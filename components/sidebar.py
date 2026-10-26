import streamlit as st

def render_sidebar():
    with st.sidebar:
        st.title("🏥 Navigasi KP")
        st.caption("AI-Driven Cardiology Anamnesis")
        
        st.divider()
        st.subheader("📋 Identitas Pasien")
        patient_name = st.text_input("Nama Pasien", value="lutfi")
        patient_rm = st.text_input("No. RM", value="RM-2026-1")
        
        st.divider()
        if st.button("🔄 Reset Sesi Konsultasi", use_container_width=True):
            st.session_state.messages = []
            st.session_state.quick_actions = [
                "Nyeri dada terasa seperti ditindih beban berat",
                "Nyeri menjalar ke lengan kiri dan leher",
                "Nyeri muncul saat beraktivitas fisik"
            ]
            st.rerun()
            
        return {"name": patient_name, "rm": patient_rm}