import os

import streamlit as st

from components.nav import go_to_patient_data, open_consultation
from database import list_patients


def render_sidebar():
    st.sidebar.title("Pengaturan & Pasien")

    if "patient_list" not in st.session_state:
        st.session_state.patient_list = []

    # Ambil API key secara aman tanpa error jika secrets.toml tidak ada
    env_api_key = ""
    try:
        env_api_key = st.secrets.get("GEMINI_API_KEY", "")
    except Exception:
        pass

    if not env_api_key:
        env_api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY", "")

    st.sidebar.subheader("🔑 Gemini API Key")
    if env_api_key:
        st.sidebar.success("API Key terdeteksi otomatis dari sistem", icon="✅")
        with st.sidebar.expander("Ganti API Key secara manual (Opsional)"):
            user_api_key = st.text_input(
                "Custom API Key:",
                value=st.session_state.get("custom_api_key", ""),
                type="password",
            )
            if user_api_key:
                st.session_state["custom_api_key"] = user_api_key
    else:
        user_api_key = st.sidebar.text_input(
            "Masukkan API Key Anda:",
            value=st.session_state.get("custom_api_key", ""),
            type="password",
            help="Dapatkan API key dari Google AI Studio.",
        )
        if user_api_key:
            st.session_state["custom_api_key"] = user_api_key
            st.sidebar.success("API Key manual disimpan!", icon="✅")
        else:
            st.sidebar.warning("API Key belum diatur di .env maupun sidebar.", icon="⚠️")

    st.sidebar.divider()

    # --- DATA PASIEN (halaman data per MRN) ---
    st.sidebar.subheader("🗂 Data Pasien")
    patients = list_patients()
    viewing_data = st.session_state.get("view") == "patient_data"
    current_mrn = st.session_state.get("data_mrn")

    with st.sidebar.expander("Buka data pasien", expanded=viewing_data):
        if st.button("➕ Tambah / Kelola Data Pasien", key="sb_data_home", use_container_width=True):
            go_to_patient_data()
            st.rerun()
        if not patients:
            st.info("Belum ada data pasien.")
        for p in patients:
            marker = "▶ " if (viewing_data and p["mrn"] == current_mrn) else "📄 "
            if st.button(f"{marker}{p['name']} ({p['mrn']})", key=f"sb_data_{p['mrn']}", use_container_width=True):
                go_to_patient_data(p["mrn"])
                st.rerun()

    st.sidebar.divider()

    # --- ROOMCHAT ---
    st.sidebar.subheader("💬 Roomchat")

    if st.sidebar.button("➕ Pasien / Konsultasi Baru", use_container_width=True):
        # Reset state untuk chat baru, tapi JANGAN hapus data pasien / patient_list
        st.session_state.active_patient = None
        st.session_state.messages = []
        st.session_state.quick_actions = []
        st.session_state.pending_input = None
        st.session_state.view = "chat"
        st.rerun()

    st.sidebar.markdown("---")
    st.sidebar.subheader("📋 Riwayat Roomchat")

    if not st.session_state.patient_list:
        st.sidebar.info("Belum ada riwayat roomchat tersimpan.")
    else:
        for idx, pat in enumerate(st.session_state.patient_list):
            btn_label = f"👤 {pat['name']} ({pat.get('mrn', 'MRN')})"
            if st.sidebar.button(btn_label, key=f"history_pat_{idx}", use_container_width=True):
                open_consultation(pat)
                st.rerun()