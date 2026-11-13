import streamlit as st
from auth.session import close_account_page, current_user
from components.assistant_chat import go_to_assistant
from components.nav import go_to_patient_data
from components.today_visits import TODAY_VIEW_ROLES, go_to_today
from components.user_box import render_user_box


def render_sidebar():
    st.sidebar.title("Menu")
    if "patient_list" not in st.session_state:
        st.session_state.patient_list = []

    # --- DATA PASIEN: pencarian pasien, tambah pasien, dan kunjungan dilakukan di halamannya ---
    st.sidebar.subheader("🗂 Data Pasien")
    if st.sidebar.button("Data Pasien", key="sb_data_home", use_container_width=True):
        close_account_page()
        go_to_patient_data()
        st.rerun()
    st.sidebar.divider()

    # --- KUNJUNGAN: pasien yang ditandai berkunjung hari ini ---
    user = current_user()
    if user and user["role"] in TODAY_VIEW_ROLES:
        st.sidebar.subheader("📅 Kunjungan")
        if st.sidebar.button("Kunjungan Pasien", key="sb_today_home", use_container_width=True):
            close_account_page()
            go_to_today()
            st.rerun()
        st.sidebar.divider()

    # --- ASISTEN KLINIS (umum, bisa membaca data sistem); roomchat pasien dibuka dari data kunjungan ---
    st.sidebar.subheader("💬 Asisten Klinis")
    if st.sidebar.button("Tanya Asisten", key="sb_assistant", use_container_width=True):
        close_account_page()
        go_to_assistant()
        st.rerun()
    st.sidebar.divider()
    st.sidebar.subheader("Profil dan Pengaturan")
    render_user_box()