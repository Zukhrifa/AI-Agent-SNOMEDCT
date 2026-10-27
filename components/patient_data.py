from datetime import date, datetime

import streamlit as st

from components.nav import go_to_chat, open_roomchat_for_mrn
from database import (
    add_supporting,
    delete_supporting,
    ensure_patient,
    get_all_consultations,
    get_patient,
    list_anamnesis_results,
    list_patients,
    list_supporting,
    update_patient,
    update_patient_name,
)
from modules.patient_context import calc_age
from modules.rag_snomed import search_candidates

SEX_OPTIONS = ["", "Laki-laki", "Perempuan"]
SUPPORT_CATEGORIES = ["Laboratorium", "EKG", "Ekokardiografi", "Rontgen Thorax", "Lainnya"]
CATEGORY_NAMES = {
    "gejala": "Gejala", "faktor_risiko": "Faktor risiko",
    "diagnosis": "Dugaan diagnosis", "lainnya": "Lainnya",
}


def _refresh_consultations():
    st.session_state.patient_list = get_all_consultations()


# ---------------------------------------------------------------------------
# Tab-tab
# ---------------------------------------------------------------------------
def _tab_identity(mrn: str, patient: dict):
    with st.form(f"form_identity_{mrn}"):
        name = st.text_input("Nama Pasien", value=patient["name"])
        dob = st.text_input(
            "Tanggal lahir (YYYY-MM-DD)",
            value=patient.get("birth_date") or "",
            placeholder="contoh: 1975-08-17",
        )
        sex_value = patient.get("sex") or ""
        sex = st.selectbox(
            "Jenis kelamin", SEX_OPTIONS,
            index=SEX_OPTIONS.index(sex_value) if sex_value in SEX_OPTIONS else 0,
        )
        submitted = st.form_submit_button("💾 Simpan Identitas")

    if submitted:
        dob = dob.strip()
        valid = True
        if dob:
            try:
                datetime.strptime(dob, "%Y-%m-%d")
            except ValueError:
                valid = False
                st.error("Format tanggal lahir harus YYYY-MM-DD.")
        if not name.strip():
            valid = False
            st.error("Nama tidak boleh kosong.")

        if valid:
            update_patient_name(mrn, name.strip())
            update_patient(mrn, birth_date=dob, sex=sex)
            active = st.session_state.get("active_patient")
            if active and active.get("mrn") == mrn:
                active["name"] = name.strip()
            _refresh_consultations()
            st.success("Identitas tersimpan.")


def _tab_chief_complaint(mrn: str, patient: dict):
    st.caption(
        "Keluhan utama dipilih dari istilah SNOMED CT agar terstandar. "
        "Cari istilahnya, lalu pilih dari hasil pencarian."
    )
    current = list(patient.get("chief_complaints") or [])

    if current:
        for i, item in enumerate(current):
            col_text, col_del = st.columns([11, 1])
            col_text.markdown(f"• **{item['term']}** `{item['conceptId']}`")
            if col_del.button("🗑", key=f"kc_del_{mrn}_{i}", help="Hapus"):
                current.pop(i)
                update_patient(mrn, chief_complaints=current)
                st.rerun()
    else:
        st.info("Belum ada keluhan utama.")

    query = st.text_input(
        "Cari istilah SNOMED CT",
        key=f"kc_query_{mrn}",
        placeholder="mis. nyeri dada / chest pain / sesak napas",
    )
    if query.strip():
        try:
            results = search_candidates(query.strip(), 8)
        except Exception as e:
            results = []
            st.error(f"Pencarian gagal: {e}")

        if results:
            options = {f"{r['term']}  ({r['conceptId']})": r for r in results}
            pick = st.selectbox("Hasil pencarian", list(options), key=f"kc_pick_{mrn}")
            if st.button("➕ Tambahkan sebagai keluhan utama", key=f"kc_add_{mrn}"):
                chosen = options[pick]
                if chosen["conceptId"] not in {c["conceptId"] for c in current}:
                    current.append({"conceptId": chosen["conceptId"], "term": chosen["term"]})
                    update_patient(mrn, chief_complaints=current)
                st.rerun()
        else:
            st.warning("Tidak ada hasil. Coba kata kunci lain (istilah Inggris biasanya lebih tepat).")


def _tab_anamnesis(mrn: str, patient: dict):
    data = patient.get("anamnesis") or {}
    with st.form(f"form_anamnesis_{mrn}"):
        rps = st.text_area("Riwayat penyakit sekarang", value=data.get("rps", ""), height=110)
        rpd = st.text_area("Riwayat penyakit dahulu", value=data.get("rpd", ""), height=90)
        rpk = st.text_area("Riwayat penyakit keluarga", value=data.get("rpk", ""), height=90)
        obat = st.text_area("Obat yang sedang dikonsumsi", value=data.get("obat", ""), height=80)
        alergi = st.text_input("Alergi", value=data.get("alergi", ""))
        kebiasaan = st.text_area(
            "Kebiasaan (merokok, alkohol, aktivitas fisik)",
            value=data.get("kebiasaan", ""), height=80,
        )
        submitted = st.form_submit_button("💾 Simpan Anamnesis")

    if submitted:
        update_patient(mrn, anamnesis={
            "rps": rps.strip(), "rpd": rpd.strip(), "rpk": rpk.strip(),
            "obat": obat.strip(), "alergi": alergi.strip(), "kebiasaan": kebiasaan.strip(),
        })
        st.success("Anamnesis tersimpan.")


def _tab_physical(mrn: str, patient: dict):
    pe = patient.get("physical_exam") or {}

    with st.form(f"form_pe_{mrn}"):
        st.markdown("**Tanda vital** (isi 0 jika belum diukur)")
        c1, c2, c3, c4 = st.columns(4)
        td_s = c1.number_input("TD Sistolik (mmHg)", 0, 300, int(pe.get("td_sistolik") or 0), 1)
        td_d = c2.number_input("TD Diastolik (mmHg)", 0, 200, int(pe.get("td_diastolik") or 0), 1)
        nadi = c3.number_input("Nadi (x/menit)", 0, 250, int(pe.get("nadi") or 0), 1)
        rr = c4.number_input("RR (x/menit)", 0, 80, int(pe.get("rr") or 0), 1)

        c5, c6, c7, c8 = st.columns(4)
        suhu = c5.number_input(
            "Suhu (°C)", min_value=0.0, max_value=45.0,
            value=float(pe.get("suhu") or 0.0), step=0.1, format="%.1f",
        )
        spo2 = c6.number_input("SpO2 (%)", 0, 100, int(pe.get("spo2") or 0), 1)
        bb = c7.number_input(
            "Berat badan (kg)", min_value=0.0, max_value=400.0,
            value=float(pe.get("bb") or 0.0), step=0.5, format="%.1f",
        )
        tb = c8.number_input(
            "Tinggi badan (cm)", min_value=0.0, max_value=250.0,
            value=float(pe.get("tb") or 0.0), step=0.5, format="%.1f",
        )

        st.markdown("**Temuan pemeriksaan fisik**")
        pe_jantung = st.text_area(
            "Jantung (bunyi jantung, murmur, JVP, dll.)", value=pe.get("pe_jantung", ""), height=90,
        )
        pe_paru = st.text_area("Paru (ronki, wheezing, dll.)", value=pe.get("pe_paru", ""), height=90)
        pe_lain = st.text_area(
            "Lain-lain (edema, akral, abdomen, dll.)", value=pe.get("pe_lain", ""), height=90,
        )
        submitted = st.form_submit_button("💾 Simpan Pemeriksaan Fisik")

    if submitted:
        update_patient(mrn, physical_exam={
            "td_sistolik": td_s, "td_diastolik": td_d, "nadi": nadi, "rr": rr,
            "suhu": suhu, "spo2": spo2, "bb": bb, "tb": tb,
            "pe_jantung": pe_jantung.strip(), "pe_paru": pe_paru.strip(), "pe_lain": pe_lain.strip(),
        })
        if bb and tb:
            st.success(f"Tersimpan. IMT: {bb / ((tb / 100) ** 2):.1f}")
        else:
            st.success("Pemeriksaan fisik tersimpan.")


def _tab_supporting(mrn: str):
    st.caption("Tambahkan hasil pemeriksaan penunjang. Data ini ikut dipakai AI di roomchat pasien ini.")

    with st.form(f"form_support_{mrn}", clear_on_submit=True):
        c1, c2 = st.columns(2)
        category = c1.selectbox("Jenis pemeriksaan", SUPPORT_CATEGORIES)
        recorded_on = c2.text_input("Tanggal pemeriksaan (YYYY-MM-DD)", value=date.today().isoformat())
        content = st.text_area(
            "Hasil / interpretasi", height=110,
            placeholder="Contoh EKG: sinus rhythm, ST elevasi V1-V4 ...",
        )
        submitted = st.form_submit_button("➕ Simpan Data Penunjang")

    if submitted:
        if not content.strip():
            st.warning("Isi hasil pemeriksaan terlebih dahulu.")
        else:
            add_supporting(mrn, category, content.strip(), recorded_on.strip() or None)
            st.rerun()

    items = list_supporting(mrn)
    if not items:
        st.info("Belum ada data penunjang.")
    for item in items:
        when = item.get("recorded_on") or (item.get("created_at") or "")[:10]
        with st.expander(f"{item['category']} — {when}"):
            st.write(item["content"])
            if st.button("🗑 Hapus", key=f"pj_del_{item['id']}"):
                delete_supporting(item["id"])
                st.rerun()


def _tab_results(mrn: str):
    st.caption("Kesimpulan AI tersimpan otomatis setiap kali anamnesis mencapai tahap akhir.")
    results = list_anamnesis_results(mrn)
    if not results:
        st.info("Belum ada kesimpulan anamnesis untuk pasien ini.")
        return

    for r in results:
        with st.expander(f"Kesimpulan — {r['created_at']}"):
            st.write(r["summary"])
            if r["codes"]:
                st.markdown("**Kode SNOMED CT**")
                for c in r["codes"]:
                    kategori = CATEGORY_NAMES.get(c.get("kategori", ""), "")
                    match = c.get("match", "")
                    note = f" — _{match}_" if match else ""
                    st.markdown(f"- {kategori}: **{c['term']}** `{c['conceptId']}`{note}")


# ---------------------------------------------------------------------------
# Halaman
# ---------------------------------------------------------------------------
def render_patient_data_page():
    st.title("🗂 Data Pasien")
    st.caption("Data tersimpan per MRN dan otomatis dipakai AI di roomchat pasien yang sama.")

    patients = list_patients()
    names = {p["mrn"]: p["name"] for p in patients}
    mrns = list(names.keys())

    with st.expander("➕ Tambah pasien baru", expanded=not mrns):
        with st.form("form_new_patient_data", clear_on_submit=True):
            new_name = st.text_input("Nama Pasien")
            new_mrn = st.text_input("Medical Record Number (MRN)")
            submitted = st.form_submit_button("Simpan Pasien Baru")
        if submitted:
            n, m = new_name.strip(), new_mrn.strip()
            if not n or not m:
                st.warning("Nama dan MRN wajib diisi.")
            elif m in names:
                st.error(f"MRN {m} sudah dipakai oleh {names[m]}.")
            else:
                ensure_patient(m, n)
                st.session_state.data_mrn = m
                st.session_state.pop("data_patient_select", None)
                st.rerun()

    if not mrns:
        return

    current = st.session_state.get("data_mrn")
    if current not in mrns:
        current = mrns[0]
    mrn = st.selectbox(
        "Pilih pasien", mrns, index=mrns.index(current),
        format_func=lambda m: f"{names[m]} ({m})", key="data_patient_select",
    )
    st.session_state.data_mrn = mrn

    patient = get_patient(mrn)
    if not patient:
        st.error("Data pasien tidak ditemukan.")
        return

    age = calc_age(patient.get("birth_date"))
    info = f"MRN: {mrn}"
    if age is not None:
        info += f" • {age} tahun"
    if patient.get("sex"):
        info += f" • {patient['sex']}"

    col_info, col_chat, col_back = st.columns([6, 2, 2])
    with col_info:
        st.subheader(patient["name"])
        st.caption(info)
    with col_chat:
        if st.button("💬 Buka Roomchat", key="dp_open_chat", use_container_width=True):
            open_roomchat_for_mrn(mrn)
            st.rerun()
    with col_back:
        if st.button("← Kembali", key="dp_back", use_container_width=True):
            go_to_chat()
            st.rerun()

    tabs = st.tabs([
        "Identitas", "Keluhan Utama (SNOMED)", "Anamnesis",
        "Pemeriksaan Fisik", "Data Penunjang", "Hasil Anamnesis AI",
    ])
    with tabs[0]:
        _tab_identity(mrn, patient)
    with tabs[1]:
        _tab_chief_complaint(mrn, patient)
    with tabs[2]:
        _tab_anamnesis(mrn, patient)
    with tabs[3]:
        _tab_physical(mrn, patient)
    with tabs[4]:
        _tab_supporting(mrn)
    with tabs[5]:
        _tab_results(mrn)