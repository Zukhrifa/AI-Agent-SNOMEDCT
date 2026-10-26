import streamlit as st

def render_sidebar():
    with st.sidebar:
        # Header Sidebar
        col_title, col_btn = st.columns([4, 1])
        with col_title:
            st.markdown("<h3 style='margin:0; padding:0; color:#1e293b;'>Chat History</h3>", unsafe_allow_html=True)
        with col_btn:
            if st.button("➕", key="btn_new_chat_sidebar", help="Start New Consultation"):
                st.session_state.active_patient = None
                st.session_state.messages = []
                st.session_state.quick_actions = []
                st.rerun()

        st.markdown("<div style='margin-bottom: 10px;'></div>", unsafe_allow_html=True)
        
        # Search Box
        st.text_input("Search patients...", key="search_query", placeholder="🔍 Search patients...")

        st.markdown("<hr style='margin: 10px 0; border-color: #e2e8f0;'>", unsafe_allow_html=True)

        # Inisialisasi daftar sesi konsultasi jika belum ada
        if "chat_history_list" not in st.session_state:
            st.session_state.chat_history_list = []

        # Tampilkan daftar riwayat roomchat
        if not st.session_state.chat_history_list:
            st.caption("Belum ada riwayat konsultasi.")
        else:
            for idx, item in enumerate(st.session_state.chat_history_list):
                patient_name = item.get("name", "Unknown Patient")
                mrn = item.get("mrn", "MRN-0000")
                time_str = item.get("time", "")
                preview = item.get("last_msg", "No messages yet")

                # Penanda jika aktif
                is_active = (st.session_state.get("active_patient") and 
                             st.session_state.active_patient.get("mrn") == mrn)
                
                bg_color = "#e0e7ff" if is_active else "#ffffff"
                border_left = "4px solid #2563eb" if is_active else "1px solid #f1f5f9"

                card_html = f"""
                <div style="background-color: {bg_color}; border-left: {border_left}; padding: 10px; border-radius: 8px; margin-bottom: 8px; cursor: pointer;">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <span style="font-weight: 600; font-size: 14px; color: #0f172a;">{patient_name}</span>
                        <span style="font-size: 11px; color: #94a3b8;">{time_str}</span>
                    </div>
                    <div style="font-size: 12px; color: #2563eb; font-weight: 500;">{mrn}</div>
                    <div style="font-size: 12px; color: #64748b; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-top: 2px;">{preview}</div>
                </div>
                """
                if st.button(f"{patient_name} ({mrn})", key=f"hist_{idx}", use_container_width=True):
                    st.session_state.active_patient = item
                    st.session_state.messages = item.get("messages", [])
                    st.session_state.quick_actions = item.get("quick_actions", [])
                    st.rerun()