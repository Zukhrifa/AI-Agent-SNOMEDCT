"""Data Klinis satu halaman untuk kunjungan: anamnesis (keluhan sekarang) + pemeriksaan fisik +
data penunjang dengan satu tombol 'Simpan & Analisis'. Riwayat tetap pasien (penyakit dahulu,
keluarga, alergi, obat, kebiasaan) ada di modules/patient_profile.py. Setelah disimpan, AI
menganalisis data kunjungan, hasilnya tersimpan sebagai draft dan gejala terisi ke Keluhan
Utama. Temuan SNOMED CT (diagnosis dugaan, faktor risiko) baru masuk ke Data Pasien setelah
dokter menyetujui."""
from datetime import date

import streamlit as st
from auth import audit_log
from auth.session import current_user

from database import (add_supporting, approve_anamnesis, delete_supporting, get_patient,
                      list_anamnesis_results, list_supporting, save_anamnesis_result,
                      update_patient)
from modules.ai_agent import (FINAL_REQUEST_TEXT, friendly_error, get_candidates,
                              parse_response, run_agent)
from modules.patient_context import build_patient_context


SUPPORT_CATEGORIES = ["Laboratorium", "EKG", "Ekokardiografi", "Rontgen Thorax", "Lainnya"]
APPROVE_ROLES = ("dokter", "admin")


def _filled(value) -> bool:
    if isinstance(value, dict):
        return any(_filled(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return any(_filled(v) for v in value)
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (int, float)):
        return value != 0
    return bool(value)


def _fill_complaints(vno: str, codes: list) -> int:
    """Gejala hasil analisis (kecocokan tidak lemah) -> Keluhan Utama, tanpa duplikat."""
    patient = get_patient(vno) or {}
    complaints = list(patient.get("chief_complaints") or [])
    ids = {c.get("conceptId") for c in complaints}
    added = 0
    for c in codes:
        cid = c.get("conceptId")
        if c.get("kategori") == "gejala" and c.get("match") != "lemah" and cid and cid not in ids:
            complaints.append({"conceptId": cid, "term": c.get("term", "")})
            ids.add(cid)
            added += 1
    if added:
        update_patient(vno, chief_complaints=complaints)
    return added


def _analyze(vno: str) -> tuple:
    """Jalankan agent sekali untuk kesimpulan kunjungan. Return (level, pesan)."""
    use_tools = bool(st.session_state.get("agent_pref", True))
    raw, last_text = "", ""
    try:
        with st.spinner("AI menganalisis data kunjungan..."):
            context = build_patient_context(vno)
            for event in run_agent(FINAL_REQUEST_TEXT, [], context, mrn=vno, use_tools=use_tools):
                if event["type"] == "text" and event["text"].strip():
                    last_text = event["text"].strip()
                elif event["type"] == "final":
                    raw = event["raw"]
    except Exception as e:
        return "error", f"Data tersimpan, tetapi analisis gagal: {friendly_error(e)}"
    raw = raw or last_text
    if not raw.strip():
        return "error", "Data tersimpan, tetapi respons AI kosong. Coba lagi."
    result = parse_response(raw, get_candidates(FINAL_REQUEST_TEXT, []), force_final=True)
    text, codes = (result.get("text") or "").strip(), result.get("codes") or []
    if not text:
        return "error", "Data tersimpan, tetapi respons AI kosong. Coba lagi."
    save_anamnesis_result(vno, text, codes, approved=False)
    added = _fill_complaints(vno, codes)
    audit_log.log("ai_jawab", vno, "analisis dari data klinis")
    return "success", (f"Data tersimpan dan dianalisis. {added} keluhan utama ditambahkan; "
                       "hasil AI menunggu persetujuan dokter.")


def _approval_block(vno: str) -> None:
    results = list_anamnesis_results(vno, 1)
    latest = results[0] if results else None
    if not latest or latest["approved"]:
        return
    with st.container(border=True):
        st.markdown("**Hasil AI terbaru: draft, belum disetujui dokter**")
        st.write(latest["summary"])
        for c in latest["codes"]:
            st.markdown(f"- **{c.get('term', '')}** `{c.get('conceptId', '')}`"
                        + (f" — _{c['match']}_" if c.get("match") else ""))
        if (current_user() or {}).get("role") in APPROVE_ROLES:
            if st.button("✅ Setujui & simpan temuan SNOMED CT", key=f"cf_approve_{vno}",
                         type="primary", use_container_width=True):
                info = approve_anamnesis(vno, latest["summary"], latest["codes"])
                audit_log.log("ai_setuju", vno, f"{info.get('saved', 0)} temuan SNOMED tersimpan")
                st.rerun()
        else:
            st.caption("Persetujuan dilakukan oleh dokter.")


def _supporting_list(vno: str) -> None:
    items = list_supporting(vno)
    if not items:
        return
    st.markdown("**Data penunjang tersimpan**")
    for item in items:
        when = item.get("recorded_on") or (item.get("created_at") or "")[:10]
        with st.expander(f"{item['category']} — {when}"):
            st.write(item["content"])
            if st.button("🗑 Hapus", key=f"pj_del_{item['id']}"):
                delete_supporting(item["id"])
                audit_log.log("penunjang_hapus", vno, item["category"])
                st.rerun()


def render_clinical_form(vno: str) -> None:
    patient = get_patient(vno)
    if not patient:
        return
    an = patient.get("anamnesis") or {}
    pe = patient.get("physical_exam") or {}
    n = st.session_state.get(f"cf_n_{vno}", 0)          # mengosongkan kolom penunjang setelah simpan

    flash = st.session_state.pop(f"cf_flash_{vno}", None)
    if flash:
        (st.success if flash[0] == "success" else st.error)(flash[1])

    with st.form(f"form_klinis_{vno}"):
        st.markdown("#### Anamnesis")
        st.caption("Riwayat tetap (penyakit dahulu, keluarga, alergi, obat, kebiasaan) diisi di "
                   "**Riwayat tetap pasien** pada bagian atas halaman.")
        rps = st.text_area("Riwayat penyakit sekarang", value=an.get("rps", ""), height=110)

        st.markdown("#### Pemeriksaan Fisik")
        st.caption("Tanda vital: isi 0 jika belum diukur.")
        c1, c2, c3, c4 = st.columns(4)
        td_s = c1.number_input("TD Sistolik (mmHg)", 0, 300, int(pe.get("td_sistolik") or 0), 1)
        td_d = c2.number_input("TD Diastolik (mmHg)", 0, 200, int(pe.get("td_diastolik") or 0), 1)
        nadi = c3.number_input("Nadi (x/menit)", 0, 250, int(pe.get("nadi") or 0), 1)
        rr = c4.number_input("RR (x/menit)", 0, 80, int(pe.get("rr") or 0), 1)
        c5, c6, c7, c8 = st.columns(4)
        suhu = c5.number_input("Suhu (°C)", min_value=0.0, max_value=45.0,
                               value=float(pe.get("suhu") or 0.0), step=0.1, format="%.1f")
        spo2 = c6.number_input("SpO2 (%)", 0, 100, int(pe.get("spo2") or 0), 1)
        bb = c7.number_input("Berat badan (kg)", min_value=0.0, max_value=400.0,
                             value=float(pe.get("bb") or 0.0), step=0.5, format="%.1f")
        tb = c8.number_input("Tinggi badan (cm)", min_value=0.0, max_value=250.0,
                             value=float(pe.get("tb") or 0.0), step=0.5, format="%.1f")
        pe_jantung = st.text_area("Jantung (bunyi jantung, murmur, JVP, dll.)",
                                  value=pe.get("pe_jantung", ""), height=90)
        pe_paru = st.text_area("Paru (ronki, wheezing, dll.)", value=pe.get("pe_paru", ""), height=90)
        pe_lain = st.text_area("Lain-lain (edema, akral, abdomen, dll.)",
                               value=pe.get("pe_lain", ""), height=90)

        st.markdown("#### Data Penunjang")
        st.caption("Opsional: tambahkan satu hasil baru. Yang sudah tersimpan tampil di bawah formulir.")
        d1, d2 = st.columns(2)
        category = d1.selectbox("Jenis pemeriksaan", SUPPORT_CATEGORIES)
        recorded = d2.date_input("Tanggal pemeriksaan", value=date.today(), max_value=date.today())
        pj_text = st.text_area("Hasil / interpretasi", height=100, key=f"cf_pj_{vno}_{n}",
                               placeholder="Contoh EKG: sinus rhythm, ST elevasi V1-V4 ...")

        b_analyze = st.form_submit_button("▶ Simpan & Analisis", type="primary", use_container_width=True)
        b_save = st.form_submit_button("💾 Simpan saja", use_container_width=True)

    if b_analyze or b_save:
        physical = {"td_sistolik": td_s, "td_diastolik": td_d, "nadi": nadi, "rr": rr,
                    "suhu": suhu, "spo2": spo2, "bb": bb, "tb": tb,
                    "pe_jantung": pe_jantung.strip(), "pe_paru": pe_paru.strip(),
                    "pe_lain": pe_lain.strip()}
        new_support = pj_text.strip()
        if not (rps.strip() or _filled(physical) or new_support or list_supporting(vno)):
            st.warning("Isi minimal salah satu: anamnesis, pemeriksaan fisik, atau data penunjang.")
        else:
            update_patient(vno, anamnesis={**an, "rps": rps.strip()}, physical_exam=physical)
            audit_log.log("anamnesis_ubah", vno)
            audit_log.log("fisik_ubah", vno, "tanda vital & pemeriksaan fisik")
            if new_support:
                add_supporting(vno, category, new_support, recorded.isoformat())
                audit_log.log("penunjang_tambah", vno, category)
                st.session_state[f"cf_n_{vno}"] = n + 1
            st.session_state[f"cf_flash_{vno}"] = (
                _analyze(vno) if b_analyze else ("success", "Data klinis tersimpan."))
            st.rerun()
    _supporting_list(vno)
    _approval_block(vno)