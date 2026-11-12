import streamlit as st
from components.nav import go_to_patient_data
from auth.session import close_account_page, current_user
from components.today_visits import SIDEBAR_MAX, TODAY_VIEW_ROLES, go_to_today, today_patients, today_str
from components.user_box import render_user_box


def render_sidebar():
    st.sidebar.title("Menu")
    if "patient_list" not in st.session_state:
        st.session_state.patient_list = []
    # --- DATA PASIEN: satu tombol; pencarian pasien dilakukan di halamannya ---
    st.sidebar.subheader("🗂 Data Pasien")
    viewing_data = st.session_state.get("view") == "patient_data"
    if st.sidebar.button("Data Pasien", key="sb_data_home", use_container_width=True,
                         type="secondary" if viewing_data else "secondary"):
        close_account_page()
        go_to_patient_data()
        st.rerun()
    st.sidebar.divider()
    # --- KUNJUNGAN HARI INI: pasien yang ditandai admin berkunjung hari ini ---
    user = current_user()
    if user and user["role"] in TODAY_VIEW_ROLES:
        st.sidebar.subheader("📅 Kunjungan")
        if st.sidebar.button("Kunjungan Pasien", key="sb_today_home", use_container_width=True):
            close_account_page()
            go_to_today()
            st.rerun()
        #todays = today_patients(today_str())
        #if not todays:
            #st.sidebar.caption("Belum ada pasien hari ini.")
        #for p in todays[:SIDEBAR_MAX]:
            #if st.sidebar.button(f"👤 {p['name']} ({p['mrn']})", key=f"sb_today_{p['mrn']}", use_container_width=True):
                #close_account_page()
                #go_to_today(p["mrn"])
                #st.rerun()
        #if len(todays) > SIDEBAR_MAX:
            #st.sidebar.caption(f"+{len(todays) - SIDEBAR_MAX} pasien lainnya di halaman Kunjungan Hari Ini")
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
        close_account_page()
        st.rerun()
    st.sidebar.divider()
    st.sidebar.subheader("Profil dan Pengaturan")
    render_user_box()