import streamlit as st
from datetime import datetime

def render_new_consultation_form():
    st.subheader("Form Konsultasi / Pasien Baru")
    
    with st.form("new_patient_form"):
        patient_name = st.text_input("Nama Pasien")
        patient_mrn = st.text_input("Nomor Rekam Medis (MRN)", value=f"MRN-{datetime.now().strftime('%H%M%S')}")
        initial_complaint = st.text_area("Keluhan Utama / Anamnesis Awal")
        
        submitted = st.form_submit_button("Mulai Konsultasi & Chat")
        
        if submitted:
            if patient_name.strip() == "":
                st.warning("Nama pasien harus diisi!")
            else:
                # Buat objek pasien baru
                new_patient = {
                    "name": patient_name,
                    "mrn": patient_mrn,
                    "messages": [],
                    "quick_actions": [
                        "Bagaimana karakteristik nyeri dada yang dirasakan?",
                        "Kapan pertama kali keluhan ini dirasakan?",
                        "Apakah ada riwayat penyakit jantung sebelumnya?"
                    ]
                }
                
                # Jika ada input keluhan awal, langsung masukkan ke riwayat pesan
                if initial_complaint.strip() != "":
                    new_patient["messages"].append({"role": "user", "content": initial_complaint})
                    # Berikan respons awal AI atau biarkan kosong untuk diproses agent
                    new_patient["messages"].append({
                        "role": "assistant", 
                        "content": f"Halo, saya mencatat keluhan utama pasien {patient_name}: '{initial_complaint}'. Mari kita lanjutkan anamnesis terstruktur."
                    })

                # Inisialisasi patient_list jika belum ada di session state
                if "patient_list" not in st.session_state:
                    st.session_state.patient_list = []
                
                # Masukkan pasien baru ke dalam daftar riwayat sidebar
                st.session_state.patient_list.append(new_patient)
                
                # Set sebagai pasien aktif
                st.session_state.active_patient = new_patient
                st.session_state.messages = new_patient["messages"]
                st.session_state.quick_actions = new_patient["quick_actions"]
                
                st.success("Konsultasi berhasil dibuat!")
                st.rerun()