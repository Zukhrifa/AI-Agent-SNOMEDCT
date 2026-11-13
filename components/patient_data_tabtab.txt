from datetime import date, datetime

import streamlit as st
from auth import audit_log

from components.nav import go_to_chat, go_to_patient_data, open_roomchat_for_mrn
from database import (
    add_supporting,
    create_visit,
    delete_supporting,
    ensure_patient,
    get_all_consultations,
    get_consultation,
    get_patient,
    get_visit,
    list_anamnesis_results,
    list_patient_overview,
    list_supporting,
    list_visits,
    patient_mrn_of,
    set_visit_archived,
    update_patient,
    update_patient_name,
)
from modules.ai_agent import translate_to_snomed_terms
from modules.patient_context import calc_age
from modules.rag_snomed import index_stats, lexical_search, search_terms

SEX_OPTIONS = ["", "Laki-laki", "Perempuan"]
SUPPORT_CATEGORIES = ["Laboratorium", "EKG", "Ekokardiografi", "Rontgen Thorax", "Lainnya"]
CATEGORY_NAMES = {
    "gejala": "Gejala", "faktor_risiko": "Faktor risiko",
    "diagnosis": "Dugaan diagnosis", "lainnya": "Lainnya",
}
MAX_SEARCH_RESULTS = 12


def _refresh_consultations():
    st.session_state.patient_list = get_all_consultations()


def _date_input(label: str, value: date, key: str):
    """Kalender pop-up; memakai format DD/MM/YYYY bila versi Streamlit mendukung."""
    kwargs = dict(
        value=value,
        min_value=date(1900, 1, 1),
        max_value=date.today(),
        key=key,
    )
    try:
        return st.date_input(label, format="DD/MM/YYYY", **kwargs)
    except TypeError:
        return st.date_input(label, **kwargs)


# ---------------------------------------------------------------------------
# Tab-tab
# ---------------------------------------------------------------------------
def _tab_identity(mrn: str, patient: dict):
    try:
        saved_dob = datetime.strptime(patient.get("birth_date") or "", "%Y-%m-%d").date()
    except ValueError:
        saved_dob = None

    with st.form(f"form_identity_{mrn}"):
        name = st.text_input("Nama Pasien", value=patient["name"])

        dob_value = _date_input("Tanggal lahir", saved_dob or date(1980, 1, 1), key=f"dob_{mrn}")
        dob_unknown = st.checkbox("Tanggal lahir belum diketahui", value=saved_dob is None, key=f"dob_unknown_{mrn}")

        sex_value = patient.get("sex") or ""
        sex = st.selectbox(
            "Jenis kelamin", SEX_OPTIONS,
            index=SEX_OPTIONS.index(sex_value) if sex_value in SEX_OPTIONS else 0,
        )
        submitted = st.form_submit_button("💾 Simpan Identitas")

    if submitted:
        if not name.strip():
            st.error("Nama tidak boleh kosong.")
            return

        dob = "" if dob_unknown else dob_value.isoformat()
        update_patient_name(mrn, name.strip())
        update_patient(mrn, birth_date=dob, sex=sex)
        audit_log.log("identitas_ubah", mrn, "identitas pasien")

        active = st.session_state.get("active_patient")
        if active and patient_mrn_of(active.get("mrn")) == mrn:
            active["name"] = name.strip()
        _refresh_consultations()
        st.success("Identitas tersimpan.")


def _collect_search_results(query: str, use_ai: bool):
    """Gabungkan hasil pencarian langsung dan hasil dari terjemahan AI. Return (hasil, catatan)."""
    notes = []
    variants = []

    # Jika query sudah punya banyak kecocokan kata (istilah Inggris), AI tidak perlu dipanggil
    looks_english = False
    try:
        looks_english = len(lexical_search(query, 5)) >= 3
    except Exception:
        pass

    if use_ai and not looks_english:
        with st.spinner("AI menerjemahkan ke istilah SNOMED CT..."):
            variants, error = translate_to_snomed_terms(query)
        if variants:
            notes.append("Istilah Inggris dari AI: " + ", ".join(variants))
        elif error:
            notes.append(f"⚠️ Terjemahan AI tidak tersedia ({error}). Memakai pencarian langsung.")

    results, seen = [], set()
    for term_query in variants + [query]:
        for hit in search_terms(term_query, 6):
            if hit["conceptId"] not in seen:
                seen.add(hit["conceptId"])
                results.append(hit)
    return results[:MAX_SEARCH_RESULTS], notes


def _tab_chief_complaint(mrn: str, patient: dict):
    st.caption(
        "Keluhan utama dipilih dari istilah SNOMED CT agar terstandar. "
        "Ketik dalam bahasa Indonesia atau Inggris, lalu pilih dari hasil pencarian."
    )
    current = list(patient.get("chief_complaints") or [])

    if current:
        for i, item in enumerate(current):
            col_text, col_del = st.columns([11, 1])
            col_text.markdown(f"• **{item['term']}** `{item['conceptId']}`")
            if col_del.button("🗑", key=f"kc_del_{mrn}_{i}", help="Hapus"):
                gone = current.pop(i)
                update_patient(mrn, chief_complaints=current)
                audit_log.log("keluhan_hapus", mrn, f"{gone['term']} {gone['conceptId']}")
                st.rerun()
    else:
        st.info("Belum ada keluhan utama.")

    use_ai = st.checkbox(
        "🌐 Terjemahkan dengan AI (Indonesia → istilah SNOMED Inggris)",
        value=True, key=f"kc_ai_{mrn}",
    )
    query = st.text_input(
        "Cari keluhan / istilah",
        key=f"kc_query_{mrn}",
        placeholder="mis. nyeri dada seperti ditindih / chest pain",
    ).strip()
    if not query:
        return

    try:
        results, notes = _collect_search_results(query, use_ai)
    except Exception as e:
        st.error(f"Pencarian gagal: {e}")
        return

    for note in notes:
        st.caption(note)

    if results:
        options = {f"{r['term']}  ({r['conceptId']})": r for r in results}
        pick = st.selectbox("Hasil pencarian SNOMED CT", list(options), key=f"kc_pick_{mrn}")
        if st.button("➕ Tambahkan sebagai keluhan utama", key=f"kc_add_{mrn}"):
            chosen = options[pick]
            if chosen["conceptId"] not in {c["conceptId"] for c in current}:
                current.append({"conceptId": chosen["conceptId"], "term": chosen["term"]})
                update_patient(mrn, chief_complaints=current)
                audit_log.log("keluhan_tambah", mrn, f"{chosen['term']} {chosen['conceptId']}")
            st.rerun()
    else:
        st.warning("Tidak ada hasil. Coba kata kunci lain.")
        try:
            stats = index_stats()
            st.caption(
                f"Diagnostik: {stats['terms']} istilah terindeks dari {stats['documents']} dokumen • "
                f"model {stats['model']} • {stats['path']}"
            )
        except Exception as e:
            st.caption(f"Diagnostik: database SNOMED tidak terbaca ({e})")


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
        audit_log.log("anamnesis_ubah", mrn)
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
        audit_log.log("fisik_ubah", mrn, "tanda vital & pemeriksaan fisik")
        if bb and tb:
            st.success(f"Tersimpan. IMT: {bb / ((tb / 100) ** 2):.1f}")
        else:
            st.success("Pemeriksaan fisik tersimpan.")


def _tab_supporting(mrn: str):
    st.caption("Tambahkan hasil pemeriksaan penunjang. Data ini ikut dipakai AI di roomchat pasien ini.")

    with st.form(f"form_support_{mrn}", clear_on_submit=True):
        c1, c2 = st.columns(2)
        category = c1.selectbox("Jenis pemeriksaan", SUPPORT_CATEGORIES)
        recorded = c2.date_input("Tanggal pemeriksaan", value=date.today(), max_value=date.today())
        content = st.text_area(
            "Hasil / interpretasi", height=110,
            placeholder="Contoh EKG: sinus rhythm, ST elevasi V1-V4 ...",
        )
        submitted = st.form_submit_button("➕ Simpan Data Penunjang")

    if submitted:
        if not content.strip():
            st.warning("Isi hasil pemeriksaan terlebih dahulu.")
        else:
            add_supporting(mrn, category, content.strip(), recorded.isoformat())
            audit_log.log("penunjang_tambah", mrn, category)
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
                audit_log.log("penunjang_hapus", mrn, item["category"])
                st.rerun()


def _tab_results(mrn: str, patient: dict):
    st.markdown("#### Temuan SNOMED CT terkonfirmasi")
    st.caption("Terisi otomatis saat dokter menekan **Ya** pada pertanyaan \"Apakah jawaban AI akurat?\" di roomchat.")

    findings = list(patient.get("confirmed_findings") or [])
    if findings:
        for i, item in enumerate(findings):
            col_text, col_del = st.columns([11, 1])
            kategori = CATEGORY_NAMES.get(item.get("kategori", ""), "")
            col_text.markdown(f"• {kategori}: **{item['term']}** `{item['conceptId']}`")
            if col_del.button("🗑", key=f"cf_del_{mrn}_{i}", help="Hapus temuan"):
                gone = findings.pop(i)
                update_patient(mrn, confirmed_findings=findings)
                audit_log.log("temuan_hapus", mrn, f"{gone['term']} {gone['conceptId']}")
                st.rerun()
    else:
        st.info("Belum ada temuan terkonfirmasi.")

    st.markdown("#### Riwayat kesimpulan anamnesis")
    results = list_anamnesis_results(mrn)
    if not results:
        st.info("Belum ada kesimpulan anamnesis untuk pasien ini.")
        return

    for r in results:
        badge = "✅ Disetujui" if r.get("approved") else "belum diverifikasi"
        with st.expander(f"Kesimpulan — {r['created_at']} • {badge}"):
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
def _tab_logs(mrn: str):
    """Fragment: riwayat aktivitas pasien, diperbarui otomatis."""
    st.caption(f"Riwayat aktivitas pengguna pada pasien ini (100 terbaru). Diperbarui otomatis tiap {audit_log.LIVE_SECONDS} detik.")
    logs = audit_log.list_logs(mrn=mrn, limit=100)
    if logs:
        st.dataframe(audit_log.table_rows(logs, with_mrn=False), use_container_width=True, hide_index=True)
    else:
        st.info("Belum ada aktivitas tercatat.")
def _tab_chat_history(mrn: str):
    """Riwayat roomchat (baca-saja), termasuk milik pasien yang diarsipkan."""
    consult = get_consultation(mrn)
    if not consult or not consult["messages"]:
        st.info("Belum ada riwayat roomchat untuk pasien ini.")
        return
    audit_log.log_once("riwayat_lihat", mrn)
    st.caption("Hanya baca. Untuk melanjutkan chat, buka roomchat (pasien aktif).")
    for m in consult["messages"]:
        with st.chat_message("user" if m.get("role") == "user" else "assistant"):
            st.markdown(str(m.get("content", "")))


def _fmt_date(iso) -> str:
    try:
        return datetime.strptime(str(iso)[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        return "—"


def _snippet(text: str, n: int = 220) -> str:
    text = " ".join(str(text or "").split())
    return (text[:n] + "…") if len(text) > n else (text or "Belum ada hasil anamnesis AI.")


SORTS = {
    "Nama": lambda r: r["name"].lower(),
    "No. RM": lambda r: r["mrn"],
}


def _page_patients():
    st.caption("Klik **Cek kunjungan** untuk melihat riwayat kunjungan pasien.")
    rows = list_patient_overview()
    names = {r["mrn"]: r["name"] for r in rows}

    c1, c2, c3 = st.columns([4, 3, 1])
    query = c1.text_input("🔍 Cari pasien (nama atau MRN)", key="data_search").strip().lower()
    order = c2.selectbox("Urutkan", list(SORTS), key="data_sort")
    c3.write("")
    if c3.button("← Kembali", key="dp_back", use_container_width=True):
        go_to_chat()
        st.rerun()

    with st.expander("➕ Tambah pasien baru", expanded=not names):
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
                audit_log.log("pasien_buat", m)
                go_to_patient_data(m)
                st.rerun()

    rows = sorted(
        (r for r in rows
         if not query or query in r["name"].lower() or query in r["mrn"].lower()),
        key=SORTS[order],
    )
    if not rows:
        st.info("Tidak ada pasien pada tampilan ini.")
        return

    widths = [3, 2, 2, 2, 2]
    with st.container(height=460, border=True, key="gtbl_box_pt"):
        with st.container(key="gtbl_h_pt"):
            for col, label in zip(st.columns(widths), ["Nama", "No. RM", "Jenis kelamin", "Tanggal lahir", ""]):
                col.caption(label)
        for r in rows:
            with st.container(key=f"gtbl_r_pt_{r['mrn']}"):
                cols = st.columns(widths)
                cols[0].write(r["name"])
                cols[1].write(r["mrn"])
                cols[2].write(r["sex"] or "—")
                cols[3].write(_fmt_date(r["birth_date"]))
                if cols[4].button("Cek kunjungan", key=f"cek_{r['mrn']}", use_container_width=True):
                    go_to_patient_data(r["mrn"])
                    st.rerun()


def _page_visits(mrn: str):
    patient = get_patient(mrn)
    if not patient:
        go_to_patient_data()
        st.rerun()
    audit_log.log_once("pasien_lihat", mrn)
    age = calc_age(patient.get("birth_date"))
    info = " • ".join(x for x in (f"MRN: {mrn}", f"{age} tahun" if age is not None else "",
                                  patient.get("sex") or "") if x)

    col_info, col_new, col_back = st.columns([6, 2, 2])
    with col_info:
        st.subheader(patient["name"])
        st.caption(info)
    with col_new:
        if st.button("➕ Kunjungan baru", key="dp_new_visit", use_container_width=True):
            vno = create_visit(mrn)
            audit_log.log("kunjungan_baru", vno)
            go_to_patient_data(vno)
            st.rerun()
    with col_back:
        if st.button("← Kembali", key="dp_back_list", use_container_width=True):
            go_to_patient_data()
            st.rerun()

    with st.expander("Identitas pasien"):
        _tab_identity(mrn, patient)

    st.markdown("#### Riwayat kunjungan")
    visits = list_visits(mrn)
    if not visits:
        st.info("Belum ada kunjungan. Tekan **Kunjungan baru**.")
    for v in visits:
        with st.container(border=True):
            c_text, c_btn = st.columns([6, 1])
            badges = [b for b in ("📦 roomchat diarsipkan" if v["archived"] else "",
                                  "✅ disetujui" if v["approved"] else ("belum diverifikasi" if v["summary"] else "")) if b]
            c_text.markdown(f"**{_fmt_date(v['visit_date'])}** · `{v['visit_no']}`" + "".join(f" · {b}" for b in badges))
            c_text.caption(_snippet(v["summary"]))
            if c_btn.button("Buka", key=f"vopen_{v['visit_no']}", use_container_width=True):
                go_to_patient_data(v["visit_no"])
                st.rerun()


def _previous_visits_block(mrn: str, vno: str):
    others = [v for v in list_visits(mrn) if v["visit_no"] != vno]
    if not others:
        return
    with st.expander(f"Kunjungan lain pasien ini ({len(others)}) — hanya baca"):
        for v in others:
            findings = (get_visit(v["visit_no"]) or {}).get("confirmed_findings") or []
            st.markdown(f"**{_fmt_date(v['visit_date'])}** · `{v['visit_no']}`")
            st.caption(_snippet(v["summary"], 400))
            if findings:
                st.markdown("Temuan SNOMED: " + "; ".join(
                    f"{f.get('term', '')} `{f.get('conceptId', '')}`" for f in findings[:10]))
            if st.button("Buka kunjungan ini", key=f"vprev_{v['visit_no']}"):
                go_to_patient_data(v["visit_no"])
                st.rerun()
            st.divider()


def _page_visit(mrn: str, vno: str):
    visit, patient = get_visit(vno), get_patient(vno)
    if not visit or not patient:
        go_to_patient_data(mrn)
        st.rerun()
    audit_log.log_once("pasien_lihat", vno)
    archived = bool(visit.get("archived"))

    col_info, col_chat, col_arc, col_back = st.columns([5, 2, 2, 2])
    with col_info:
        st.subheader(patient["name"])
        st.caption(f"Kunjungan {_fmt_date(visit['visit_date'])} • No. {vno}" + (" • Roomchat diarsipkan" if archived else ""))
    with col_chat:
        if not archived and st.button("💬 Buka Roomchat", key="dp_open_chat", use_container_width=True):
            open_roomchat_for_mrn(vno)
            st.rerun()
    with col_arc:
        if st.button("♻ Aktifkan roomchat" if archived else "📦 Arsipkan roomchat", key="dp_archive",
                     use_container_width=True):
            set_visit_archived(vno, not archived)
            audit_log.log("pasien_aktif" if archived else "pasien_arsip", vno)
            if not archived and (st.session_state.get("active_patient") or {}).get("mrn") == vno:
                st.session_state.active_patient = None
                st.session_state.messages = []
                st.session_state.quick_actions = []
                st.session_state.pending_input = None
            _refresh_consultations()
            st.rerun()
    with col_back:
        if st.button("← Kembali", key="dp_back_visits", use_container_width=True):
            go_to_patient_data(mrn)
            st.rerun()

    _previous_visits_block(mrn, vno)

    tabs = st.tabs(["Keluhan Utama (SNOMED)", "Anamnesis", "Pemeriksaan Fisik", "Data Penunjang",
                    "Hasil Anamnesis AI", "Riwayat Aktivitas", "Riwayat Roomchat"])
    with tabs[0]:
        _tab_chief_complaint(vno, patient)
    with tabs[1]:
        _tab_anamnesis(vno, patient)
    with tabs[2]:
        _tab_physical(vno, patient)
    with tabs[3]:
        _tab_supporting(vno)
    with tabs[4]:
        _tab_results(vno, patient)
    with tabs[5]:
        audit_log.live(_tab_logs)(vno)
    with tabs[6]:
        _tab_chat_history(vno)


def render_patient_data_page():
    st.title("🗂 Data Pasien")
    mrn, vno = st.session_state.get("data_mrn"), st.session_state.get("data_visit")
    if mrn and vno:
        _page_visit(mrn, vno)
    elif mrn:
        _page_visits(mrn)
    else:
        _page_patients()