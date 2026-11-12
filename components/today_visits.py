"""Kunjungan hari ini: admin menandai pasien yang berkunjung hari ini, semua peran melihat daftarnya.
Klik pasien -> riwayat kunjungannya beserta roomchat tiap kunjungan (sama seperti di Data Pasien)."""
from datetime import datetime, timedelta

import streamlit as st
from auth import audit_log
from auth.session import current_user

from components.nav import go_to_patient_data, open_roomchat_for_mrn
from database import _NOW, _query, _write, create_visit, get_patient, list_patient_overview, list_visits

TODAY_VIEW_ROLES = ("admin", "dokter", "perawat")  # peran yang melihat menu Kunjungan Hari Ini
TODAY_EDIT_ROLES = ("admin",)                      # peran yang boleh mengatur daftar pasien hari ini
SIDEBAR_MAX = 8                                    # jumlah pasien hari ini yang tampil di sidebar


def today_str() -> str:
    return (datetime.utcnow() + timedelta(hours=7)).date().isoformat()  # tanggal WIB


def go_to_today(mrn: str = None):
    st.session_state.view = "today"
    st.session_state.today_mrn = mrn


@st.cache_resource(show_spinner=False)
def _init_table() -> bool:
    _write([(
        f"CREATE TABLE IF NOT EXISTS today_visits ("
        f"visit_date TEXT NOT NULL, mrn TEXT NOT NULL, added_by TEXT, "
        f"created_at TEXT DEFAULT ({_NOW}), PRIMARY KEY (visit_date, mrn))",
        (),
    )])
    return True


@st.cache_data(ttl=15, show_spinner=False)
def today_patients(day: str) -> list:
    """Pasien yang ditandai berkunjung pada tanggal `day` (urut sesuai waktu ditambahkan)."""
    _init_table()
    order = [r[0] for r in _query(
        "SELECT mrn FROM today_visits WHERE visit_date = ? ORDER BY created_at, mrn", (day,))]
    if not order:
        return []
    info = {p["mrn"]: p for p in list_patient_overview()}
    return [info[m] for m in order if m in info]


def _add_today(mrns: list, by: str):
    _init_table()
    day = today_str()
    _write([("INSERT OR IGNORE INTO today_visits (visit_date, mrn, added_by) VALUES (?, ?, ?)", (day, m, by))
            for m in mrns])
    today_patients.clear()
    for m in mrns:
        audit_log.log("pasien_hari_ini_tambah", m)


def _remove_today(mrn: str):
    _write([("DELETE FROM today_visits WHERE visit_date = ? AND mrn = ?", (today_str(), mrn))])
    today_patients.clear()
    audit_log.log("pasien_hari_ini_hapus", mrn)


def _fmt_date(iso) -> str:
    try:
        return datetime.strptime(str(iso)[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
    except Exception:
        return iso or "-"


def _snippet(text: str, n: int = 220) -> str:
    text = " ".join((text or "").split())
    return (text[:n] + "…") if len(text) > n else (text or "Belum ada hasil anamnesis AI.")


def _page_list(can_edit: bool):
    day = today_str()
    rows = today_patients(day)
    st.caption(f"Pasien yang berkunjung hari ini ({_fmt_date(day)}). Klik **Lihat kunjungan** untuk melihat "
               "riwayat kunjungan dan roomchat pasien.")

    if can_edit:
        with st.expander("➕ Atur pasien hari ini", expanded=not rows):
            in_today = {p["mrn"] for p in rows}
            options = [p for p in list_patient_overview() if p["mrn"] not in in_today]
            labels = {p["mrn"]: f"{p['name']} ({p['mrn']})" for p in options}
            with st.form("form_add_today", clear_on_submit=True):
                chosen = st.multiselect("Pilih pasien (ketik untuk mencari)", list(labels),
                                        format_func=lambda m: labels[m])
                if st.form_submit_button("Tambahkan ke hari ini") and chosen:
                    _add_today(chosen, (current_user() or {}).get("username", ""))
                    st.rerun()

    if not rows:
        st.info("Belum ada pasien yang ditandai berkunjung hari ini." + (" Tambahkan lewat panel di atas." if can_edit else ""))
        return

    widths = [3, 2, 2, 2, 2, 1] if can_edit else [3, 2, 2, 2, 2]
    heads = ["Nama", "No. RM", "Jenis kelamin", "Tanggal lahir", ""] + ([""] if can_edit else [])
    with st.container(border=True):
        for col, label in zip(st.columns(widths), heads):
            col.caption(label)
        for r in rows:
            cols = st.columns(widths)
            cols[0].write(r["name"])
            cols[1].write(r["mrn"])
            cols[2].write(r.get("sex") or "—")
            cols[3].write(_fmt_date(r.get("birth_date")))
            if cols[4].button("Lihat kunjungan", key=f"today_open_{r['mrn']}", use_container_width=True):
                go_to_today(r["mrn"])
                st.rerun()
            if can_edit and cols[5].button("🗑", key=f"today_del_{r['mrn']}", help="Keluarkan dari daftar hari ini"):
                _remove_today(r["mrn"])
                st.rerun()


def _page_patient(mrn: str):
    patient = get_patient(mrn)
    if not patient:
        go_to_today()
        st.rerun()
    audit_log.log_once("pasien_lihat", mrn)
    day = today_str()

    col_info, col_new, col_data, col_back = st.columns([4, 2, 2, 2])
    with col_info:
        st.subheader(patient["name"])
        st.caption(f"MRN: {mrn}" + (f" • {patient['sex']}" if patient.get("sex") else ""))
    with col_new:
        if st.button("➕ Kunjungan baru", key="today_new_visit", use_container_width=True):
            vno = create_visit(mrn)
            audit_log.log("kunjungan_baru", vno)
            st.rerun()
    with col_data:
        if st.button("🗂 Data pasien", key="today_data", use_container_width=True):
            go_to_patient_data(mrn)
            st.rerun()
    with col_back:
        if st.button("← Hari ini", key="today_back", use_container_width=True):
            go_to_today()
            st.rerun()

    st.markdown("#### Riwayat kunjungan")
    visits = list_visits(mrn)
    if not visits:
        st.info("Belum ada kunjungan. Tekan **Kunjungan baru**.")
    for v in visits:
        with st.container(border=True):
            c_text, c_data, c_chat = st.columns([6, 1.6, 2])
            badges = [b for b in (
                "hari ini" if str(v["visit_date"])[:10] == day else "",
                "📦 roomchat diarsipkan" if v["archived"] else "",
                "✅ disetujui" if v["approved"] else ("belum diverifikasi" if v["summary"] else ""),
            ) if b]
            c_text.markdown(f"**{_fmt_date(v['visit_date'])}** · `{v['visit_no']}`" + "".join(f" · {b}" for b in badges))
            c_text.caption(_snippet(v["summary"]))
            if c_data.button("📂 Data", key=f"today_vdata_{v['visit_no']}", use_container_width=True):
                go_to_patient_data(v["visit_no"])
                st.rerun()
            if v["archived"]:
                c_chat.caption("📦 diarsipkan")
            elif c_chat.button("💬 Roomchat", key=f"today_vchat_{v['visit_no']}", use_container_width=True):
                open_roomchat_for_mrn(v["visit_no"])
                st.rerun()


def render_today_page():
    user = current_user() or {}
    st.title("📅 Kunjungan Hari Ini")
    mrn = st.session_state.get("today_mrn")
    if mrn:
        _page_patient(mrn)
    else:
        _page_list(user.get("role") in TODAY_EDIT_ROLES)