import streamlit as st
from auth import audit_log
from components.assistant_chat import render_assistant_page
from components.context_panel import render_context_panel
from components.user_box import render_account_page   # taruh bersama import lainnya
from components.chat_ui import render_chat_room
from components.nav import go_to_patient_data, sync_url
from components.patient_data import render_patient_data_page
from components.sidebar import render_sidebar
from components.today_visits import render_today_page
from database import (
    get_all_consultations,
    save_or_update_consultation,
    set_visit_archived,
    update_patient_name,
)
from modules.ai_agent import DEFAULT_QUICK_ACTIONS
from modules.rag_snomed import warmup

st.set_page_config(page_title="Medical Anamnesis System", page_icon="🩺", layout="wide")
from auth.session import require_login
from components.admin_profile import render_profile_page
user = require_login()


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
_restore_mrn = st.session_state.pop("_restore_mrn", None)  # roomchat terakhir sebelum refresh
if _restore_mrn and st.session_state.active_patient is None:
    for _c in st.session_state.patient_list:
        if _c["mrn"] == _restore_mrn:
            st.session_state.active_patient = _c
            st.session_state.messages = _c.get("messages", [])
            st.session_state.quick_actions = _c.get("quick_actions", [])
            break

# 2. Muat model pencarian SNOMED sekali di awal (bukan saat pesan pertama pasien)
try:
    with st.spinner("Memuat model pencarian SNOMED CT (hanya saat pertama kali)..."):
        warmup()
except Exception as e:
    st.warning(f"Pencarian SNOMED CT belum siap (jalankan ingest_chroma.py dulu): {e}")

# 3. Sidebar (URL disinkronkan dulu agar tombol Kembali browser berfungsi)
sync_url()
render_sidebar()
if render_account_page():
    st.stop()


def render_roomchat_view():
    active = st.session_state.active_patient

    col_title, col_data, col_btn = st.columns([5, 2, 1])
    with col_title:
        st.subheader(f"RoomChat: {active['name']}")
        st.caption(f"Nomor Kunjungan: {active['mrn']}")

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
                    audit_log.log("identitas_ubah", active["mrn"], "nama diubah")
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
                audit_log.log("chat_clear", active["mrn"])
                st.session_state.patient_list = get_all_consultations()
                st.rerun()

            st.divider()

            # Arsipkan: roomchat ini disembunyikan dari sidebar, tidak ada yang dihapus
            if st.button("📦 Arsipkan Roomchat", key="btn_arsip_pasien", use_container_width=True):
                set_visit_archived(active["mrn"], True)
                audit_log.log("pasien_arsip", active["mrn"])
                st.session_state.active_patient = None
                st.session_state.messages = []
                st.session_state.quick_actions = []
                st.session_state.pending_input = None
                st.session_state.patient_list = get_all_consultations()
                st.rerun()
            st.caption("Roomchat disembunyikan dari sidebar; data tetap ada di Data Pasien dan bisa diaktifkan kembali.")

    render_context_panel(active["mrn"])
    render_chat_room()


# --- Routing halaman ---
if st.session_state.view == "patient_data":
    render_patient_data_page()
elif st.session_state.view == "today":
    render_today_page()
elif st.session_state.view == "assistant":
    render_assistant_page()
elif st.session_state.active_patient is None:
    render_today_page()          # halaman awal setelah login: Kunjungan Hari Ini
else:
    render_roomchat_view()

sync_url()