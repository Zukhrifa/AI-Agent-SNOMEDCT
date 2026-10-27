import random

import streamlit as st

from components.chat_ui import render_chat_room, send_user_message
from components.nav import go_to_patient_data, open_consultation
from components.patient_data import render_patient_data_page
from components.sidebar import render_sidebar
from database import (
    delete_consultation,
    ensure_patient,
    get_all_consultations,
    list_patients,
    save_or_update_consultation,
    update_patient_name,
)
from modules.ai_agent import DEFAULT_QUICK_ACTIONS
from modules.rag_snomed import warmup

st.set_page_config(page_title="Medical Anamnesis System", page_icon="🩺", layout="wide")

NEW_PATIENT = "➕ Pasien baru"

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
if "view" not in st.session_state:
    st.session_state.view = "chat"
if "new_mrn_default" not in st.session_state:
    st.session_state.new_mrn_default = f"MRN-{random.randint(10000, 99999)}"

# 2. Muat model pencarian SNOMED sekali di awal (bukan saat pesan pertama pasien)
try:
    with st.spinner("Memuat model pencarian SNOMED CT (hanya saat pertama kali)..."):
        warmup()
except Exception as e:
    st.warning(f"Pencarian SNOMED CT belum siap (jalankan ingest_chroma.py dulu): {e}")

# 3. Sidebar
render_sidebar()


def render_new_consultation_form():
    st.title("🩺 Medical Anamnesis System")
    st.write(
        "Pilih pasien yang sudah terdaftar atau buat pasien baru. "
        "Data pasien dan hasil anamnesis sebelumnya otomatis dipanggil kembali berdasarkan MRN."
    )

    patients = list_patients()
    names = {p["mrn"]: p["name"] for p in patients}
    consult_by_mrn = {c["mrn"]: c for c in st.session_state.patient_list}

    options = [NEW_PATIENT] + list(names.keys())
    selected = st.selectbox(
        "Pasien",
        options,
        format_func=lambda m: NEW_PATIENT if m == NEW_PATIENT else f"{names[m]} ({m})",
    )

    if selected == NEW_PATIENT:
        default_name, default_mrn = "", st.session_state.new_mrn_default
    else:
        default_name, default_mrn = names[selected], selected

    fresh = False
    with st.form("new_patient_form"):
        st.subheader("Pendaftaran / Konsultasi")
        p_name = st.text_input("Nama Pasien", value=default_name, key=f"form_name_{selected}")
        p_mrn = st.text_input("Medical Record Number (MRN)", value=default_mrn, key=f"form_mrn_{selected}")
        p_complaint = st.text_area("Keluhan Utama / catatan awal (opsional)", key=f"form_complaint_{selected}")

        if selected != NEW_PATIENT and selected in consult_by_mrn:
            fresh = st.checkbox(
                "Mulai sesi baru (riwayat chat lama diganti; data pasien & hasil anamnesis tetap tersimpan)"
            )

        submitted = st.form_submit_button("Mulai Konsultasi")

    if not submitted:
        return

    name, mrn, complaint = p_name.strip(), p_mrn.strip(), p_complaint.strip()
    if not name or not mrn:
        st.warning("Nama pasien dan MRN harus diisi!")
        return
    if selected == NEW_PATIENT and mrn in names:
        st.error(
            f"MRN {mrn} sudah terdaftar atas nama {names[mrn]}. "
            "Pilih pasien tersebut dari daftar, atau gunakan MRN lain."
        )
        return

    ensure_patient(mrn, name)
    existing = consult_by_mrn.get(mrn)

    if existing and not fresh:
        # Lanjutkan roomchat yang sudah ada
        existing["name"] = name
        open_consultation(existing)
    else:
        greeting = (
            f"Halo, saya asisten anamnesis kardiologi. Pasien {name} siap dianamnesis. "
            "Data pasien yang tersimpan akan dipakai otomatis. "
            "Silakan ceritakan keluhan utama pasien atau pilih pertanyaan di bawah ini."
        )
        first_messages = [] if complaint else [{"role": "assistant", "content": greeting}]
        quick_actions = list(DEFAULT_QUICK_ACTIONS)

        save_or_update_consultation(name, mrn, first_messages, quick_actions)
        open_consultation({
            "name": name,
            "mrn": mrn,
            "messages": first_messages,
            "quick_actions": quick_actions,
        })

    if complaint:
        # Jawaban AI akan di-stream di room chat (tanpa menunggu di halaman ini)
        send_user_message(complaint)

    st.session_state.patient_list = get_all_consultations()
    st.session_state.new_mrn_default = f"MRN-{random.randint(10000, 99999)}"
    st.rerun()


def render_roomchat_view():
    active = st.session_state.active_patient

    col_title, col_data, col_btn = st.columns([5, 2, 1])
    with col_title:
        st.subheader(f"RoomChat: {active['name']}")
        st.caption(f"Medical Record Number: {active['mrn']}")

    with col_data:
        if st.button("🗂 Data Pasien", key="open_patient_data", use_container_width=True):
            go_to_patient_data(active["mrn"])
            st.rerun()

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

            # Hapus roomchat (data pasien & hasil anamnesis tetap tersimpan)
            if st.button("🗑 Hapus Sesi", type="primary", use_container_width=True):
                delete_consultation(active["mrn"])
                st.session_state.active_patient = None
                st.session_state.messages = []
                st.session_state.quick_actions = []
                st.session_state.pending_input = None
                st.session_state.patient_list = get_all_consultations()
                st.rerun()
            st.caption("Menghapus sesi hanya menghapus chat. Data pasien tetap tersimpan.")

    render_chat_room()


# --- Routing halaman ---
if st.session_state.view == "patient_data":
    render_patient_data_page()
elif st.session_state.active_patient is None:
    render_new_consultation_form()
else:
    render_roomchat_view()