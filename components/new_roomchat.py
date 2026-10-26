import streamlit as st

def render_new_consultation_form():
    st.markdown("""
        <div style="text-align: center; margin-top: 40px; margin-bottom: 20px;">
            <div style="width: 60px; height: 60px; background-color: #eff6ff; border-radius: 16px; display: inline-flex; align-items: center; justify-content: center; margin-bottom: 16px;">
                <span style="font-size: 28px; color: #2563eb;">👤</span>
            </div>
            <h2 style="color: #0f172a; font-weight: 700; margin-bottom: 4px;">Mulai Roomchat</h2>
            <p style="color: #64748b; font-size: 14px;">Masukkan detail nama pasien dan mulai pencarian rekomendasi pertanyaan anamnesis.</p>
        </div>
    """, unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        with st.form("new_consultation_form"):
            patient_name = st.text_input("Nama Pasien", placeholder="e.g. Sarah J")
            mrn = st.text_input("nomor Rekam Medis", placeholder="e.g. MRN-2024-00847")
            
            submit = st.form_submit_button("+ Mulai Percakapan", use_container_width=True)
            
            if submit:
                if not patient_name or not mrn:
                    st.error("Mohon isi Nama Pasien dan Nomor Rekam Medis.")
                else:
                    new_patient = {
                        "name": patient_name,
                        "mrn": mrn,
                        "time": "Just now",
                        "last_msg": "Analisis dimulai",
                        "messages": [],
                        "quick_actions": []
                    }
                    st.session_state.active_patient = new_patient
                    if "chat_history_list" not in st.session_state:
                        st.session_state.chat_history_list = []
                    st.session_state.chat_history_list.insert(0, new_patient)
                    st.session_state.messages = []
                    st.session_state.quick_actions = []
                    st.rerun()