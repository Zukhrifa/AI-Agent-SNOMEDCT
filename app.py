import random

import streamlit as st

from components.chat_ui import render_chat_room, send_user_message
from components.sidebar import render_sidebar
from database import (
    delete_consultation,
    get_all_consultations,
    save_or_update_consultation,
    update_patient_name,
)
from modules.ai_agent import DEFAULT_QUICK_ACTIONS
from modules.rag_snomed import warmup

st.set_page_config(page_title="Medical Anamnesis System", page_icon="🩺", layout="wide")

# 1. Inisialisasi Session State
if "patient_list" not in st.session_state:
    st.session_state.patient_list = get_all_consultations()
if "active_patient" not in st.session_state:
    st.session_state.active_patient = None
if "messages" not in st.session_state:
    st.session_state.messages = []
if "quick_actions" not in st.session_state:
    st.session_state.quick_actions = []
if "pending_input" not in st.session_state:
    st.session_state.pending_input = None

# 2. Muat model pencarian SNOMED sekali di awal (bukan saat pesan pertama pasien)
try:
    with st.spinner("Memuat model pencarian SNOMED CT (hanya saat pertama kali)..."):
        warmup()
except Exception as e:
    st.warning(f"Pencarian SNOMED CT belum siap (jalankan ingest_chroma.py dulu): {e}")

# 3. Sidebar
render_sidebar()

# --- HALAMAN UTAMA ---
if st.session_state.active_patient is None:
    st.title("🩺 Medical Anamnesis System")
    st.write(
        "Silakan buat konsultasi pasien baru melalui formulir di bawah ini "
        "atau pilih dari riwayat daftar pasien di sidebar."
    )

    with st.form("new_patient_form"):
        st.subheader("Pendaftaran Pasien Baru")
        p_name = st.text_input("Nama Pasien")

        default_mrn = f"MRN-{random.randint(10000, 99999)}"
        p_mrn = st.text_input("Medical Record Number (MRN)", value=default_mrn)

        p_complaint = st.text_area("Keluhan Utama (opsional)")

        submitted = st.form_submit_button("Mulai Konsultasi")

    if submitted:
        if not p_name.strip():
            st.warning("Nama pasien harus diisi!")
        else:
            name = p_name.strip()
            mrn = p_mrn.strip() or default_mrn
            complaint = p_complaint.strip()

            greeting = (
                f"Halo, saya asisten anamnesis kardiologi. Pasien {name} siap dianamnesis. "
                "Silakan ceritakan keluhan utama pasien atau pilih pertanyaan di bawah ini."
            )
            first_messages = [] if complaint else [{"role": "assistant", "content": greeting}]
            quick_actions = list(DEFAULT_QUICK_ACTIONS)

            save_or_update_consultation(name, mrn, first_messages, quick_actions)

            st.session_state.active_patient = {
                "name": name,
                "mrn": mrn,
                "messages": first_messages,
                "quick_actions": quick_actions,
            }
            st.session_state.messages = first_messages
            st.session_state.quick_actions = quick_actions
            st.session_state.pending_input = None

            if complaint:
                # Jawaban AI akan di-stream di room chat (tanpa menunggu di halaman ini)
                send_user_message(complaint)

            st.session_state.patient_list = get_all_consultations()
            st.rerun()

else:
    # --- ROOM CHAT ANAMNESIS ---
    active = st.session_state.active_patient

    col_title, col_btn = st.columns([5, 1])
    with col_title:
        st.subheader(f"RoomChat: {active['name']}")
        st.caption(f"Medical Record Number: {active['mrn']}")

    with col_btn:
        with st.popover("⚙️ Menu", use_container_width=True):
            st.markdown("### Pengaturan Sesi")

            # Edit nama pasien
            new_name = st.text_input("Ubah Nama Pasien", value=active["name"])
            if st.button("Simpan Nama", use_container_width=True):
                if new_name.strip():
                    update_patient_name(active["mrn"], new_name.strip())
                    st.session_state.active_patient["name"] = new_name.strip()
                    st.session_state.patient_list = get_all_consultations()
                    st.rerun()

            st.divider()

            # Clear chat
            if st.button("🔄 Clear Chat", use_container_width=True):
                st.session_state.messages = []
                st.session_state.pending_input = None
                st.session_state.quick_actions = list(DEFAULT_QUICK_ACTIONS)
                active["messages"] = st.session_state.messages
                active["quick_actions"] = st.session_state.quick_actions
                save_or_update_consultation(
                    active["name"], active["mrn"], [], st.session_state.quick_actions
                )
                st.session_state.patient_list = get_all_consultations()
                st.rerun()

            st.divider()

            # Hapus sesi
            if st.button("🗑 Hapus Sesi", type="primary", use_container_width=True):
                delete_consultation(active["mrn"])
                st.session_state.active_patient = None
                st.session_state.messages = []
                st.session_state.quick_actions = []
                st.session_state.pending_input = None
                st.session_state.patient_list = get_all_consultations()
                st.rerun()

    render_chat_room()