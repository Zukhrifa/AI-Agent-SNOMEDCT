import streamlit as st
import random
from database import get_all_consultations, save_or_update_consultation
from modules.ai_agent import generate_anamnesis_response
from components.sidebar import render_sidebar
from components.chat_ui import render_chat_room

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

# 2. Panggil Sidebar Modular
render_sidebar()

# --- HALAMAN UTAMA ---
if st.session_state.active_patient is None:
    st.title("🩺 Medical Anamnesis System")
    st.write("Silakan buat konsultasi pasien baru melalui formulir di bawah ini atau pilih dari riwayat daftar pasien di sidebar.")
    
    # Form Pendaftaran Pasien Baru
    with st.form("new_patient_form"):
        st.subheader("Pendaftaran Pasien Baru")
        p_name = st.text_input("Nama Pasien")
        
        # Generate nomor MRN acak otomatis yang valid
        default_mrn = f"MRN-{random.randint(10000, 99999)}"
        p_mrn = st.text_input("Medical Record Number (MRN)", value=default_mrn)
        
        submitted = st.form_submit_button("Mulai Konsultasi")
        
        if submitted and p_name:
            keluhan_awal = "Pasien datang dengan keluhan medis awal."
            
            try:
                with st.spinner("Menghubungkan ke AI & Memindai SNOMED CT..."):
                    ai_reply, dynamic_quick_actions = generate_anamnesis_response(
                        f"Keluhan utama pasien {p_name}: {keluhan_awal}", []
                    )
                
                full_messages = [
                    {"role": "user", "content": f"Keluhan awal: {keluhan_awal}"},
                    {"role": "assistant", "content": ai_reply}
                ]
                
                new_patient_data = {
                    "name": p_name,
                    "mrn": p_mrn,
                    "messages": full_messages,
                    "quick_actions": dynamic_quick_actions
                }
                
                # Simpan ke SQLite database
                save_or_update_consultation(p_name, p_mrn, full_messages, dynamic_quick_actions)
                
                # Perbarui session state dan masuk ke room chat
                st.session_state.patient_list = get_all_consultations()
                st.session_state.active_patient = new_patient_data
                st.session_state.messages = full_messages
                st.session_state.quick_actions = dynamic_quick_actions
                st.rerun()
                
            except Exception as e:
                st.error(f"Gagal memulai konsultasi. Periksa koneksi atau API Key Anda. Error: {str(e)}")
            
else:
    # --- ROOM CHAT ANAMNESIS ---
    # Memanggil komponen modular asli (chat_ui.py) tanpa argumen agar tidak terjadi TypeError
    render_chat_room()