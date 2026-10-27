import streamlit as st

from database import get_all_consultations, get_patient, save_or_update_consultation
from modules.ai_agent import DEFAULT_QUICK_ACTIONS


def go_to_patient_data(mrn: str = None):
    """Pindah ke halaman Data Pasien (opsional: langsung ke MRN tertentu)."""
    st.session_state.view = "patient_data"
    if mrn:
        st.session_state.data_mrn = mrn
    st.session_state.pop("data_patient_select", None)


def go_to_chat():
    st.session_state.view = "chat"


def open_consultation(pat: dict):
    """Buka roomchat dari data konsultasi yang sudah ada."""
    st.session_state.active_patient = pat
    st.session_state.messages = pat.get("messages", [])
    st.session_state.quick_actions = pat.get("quick_actions", [])
    st.session_state.pending_input = None
    st.session_state.view = "chat"


def open_roomchat_for_mrn(mrn: str):
    """Buka roomchat milik MRN; jika belum ada, buat roomchat baru dengan sapaan awal."""
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