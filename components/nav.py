import streamlit as st
from auth import audit_log

from database import get_all_consultations, get_patient, get_visit, save_or_update_consultation
from modules.ai_agent import DEFAULT_QUICK_ACTIONS


def go_to_patient_data(key: str = None):
    """Pindah ke Data Pasien. key kosong -> daftar pasien; key = MRN -> daftar kunjungan;
    key = nomor kunjungan -> detail kunjungan."""
    st.session_state.view = "patient_data"
    visit = get_visit(key) if key else None
    st.session_state.data_mrn = (visit["mrn"] if visit else key) or None
    st.session_state.data_visit = key if visit else None


def go_to_chat():
    st.session_state.view = "chat"


# ---------------------------------------------------------------------------
# Sinkron halaman <-> URL, agar tombol Kembali/Maju browser berfungsi di dalam aplikasi.
# Parameter URL: v=halaman, m=MRN pasien, k=nomor kunjungan, c=roomchat aktif,
# t=pasien di Kunjungan Hari Ini, p=halaman akun (profile/admin).
# ---------------------------------------------------------------------------
_KEYS = ("v", "m", "k", "c", "t", "p")


def _state() -> tuple:
    ss = st.session_state
    return (ss.get("view", "chat"), ss.get("data_mrn"), ss.get("data_visit"),
            (ss.get("active_patient") or {}).get("mrn"), ss.get("today_mrn"), ss.get("account_page"))


def _url_state() -> tuple:
    qp = st.query_params
    return (qp.get("v", "chat"), qp.get("m"), qp.get("k"), qp.get("c"), qp.get("t"), qp.get("p"))


def _apply(state: tuple):
    ss = st.session_state
    ss.view, ss.data_mrn, ss.data_visit = state[0], state[1], state[2]
    ss.today_mrn, ss.account_page = state[4], state[5]  # Kembali/Maju browser ikut memulihkan keduanya
    if state[3] != (ss.get("active_patient") or {}).get("mrn"):
        pat = next((c for c in ss.get("patient_list", []) if c["mrn"] == state[3]), None)
        ss.active_patient = pat
        ss.messages = pat.get("messages", []) if pat else []
        ss.quick_actions = pat.get("quick_actions", []) if pat else []
        ss.pending_input = None


def sync_url():
    """Panggil sebelum render halaman dan sekali lagi di akhir app.py.
    URL berubah (Kembali/Maju browser, tautan, refresh) -> halaman mengikuti URL.
    Halaman berubah (tombol di aplikasi) -> URL ditulis (menambah riwayat browser)."""
    ss = st.session_state
    url, cur, last = _url_state(), _state(), ss.get("_url_last")
    changed = url != ("chat", None, None, None, None, None) if last is None else url != last
    if changed:
        _apply(url)
        ss["_url_last"] = url
        return
    if cur != url:
        params = {k: v for k, v in zip(_KEYS, cur) if v and not (k == "v" and v == "chat")}
        if "s" in st.query_params:  # jaga token sesi agar login tetap pulih saat refresh
            params["s"] = st.query_params["s"]
        st.query_params.from_dict(params)
    ss["_url_last"] = cur


def open_consultation(pat: dict):
    """Buka roomchat dari data konsultasi yang sudah ada."""
    st.session_state.active_patient = pat
    st.session_state.messages = pat.get("messages", [])
    st.session_state.quick_actions = pat.get("quick_actions", [])
    st.session_state.pending_input = None
    st.session_state.view = "chat"
    audit_log.log_once("roomchat_buka", pat.get("mrn"))


def open_roomchat_for_mrn(mrn: str):
    """Buka roomchat milik nomor kunjungan (key); jika belum ada, buat roomchat baru dengan sapaan awal."""
    for consultation in st.session_state.get("patient_list", []):
        if consultation["mrn"] == mrn:
            open_consultation(consultation)
            return

    patient = get_patient(mrn)
    name = patient["name"] if patient else mrn
    greeting = (
        f"Halo, saya asisten anamnesis kardiologi. Pasien {name} siap dianamnesis. "
        "Data pasien yang tersimpan akan dipakai otomatis. "
        "Silakan ceritakan keluhan utama pasien atau pilih pertanyaan di bawah ini."
    )
    messages = [{"role": "assistant", "content": greeting}]
    quick_actions = list(DEFAULT_QUICK_ACTIONS)

    save_or_update_consultation(name, mrn, messages, quick_actions)
    st.session_state.patient_list = get_all_consultations()
    open_consultation({
        "name": name,
        "mrn": mrn,
        "messages": messages,
        "quick_actions": quick_actions,
    })