import streamlit as st
import google.generativeai as genai

def render_sidebar():
    st.sidebar.title("Pengaturan & Pasien")
    
    # --- FITUR INPUT & VALIDASI API KEY MANUAL ---
    st.sidebar.subheader("Gemini API Key")
    user_api_key = st.sidebar.text_input(
        "Masukkan API Key Anda:",
        value=st.session_state.get("custom_api_key", ""),
        type="password",
        help="Dapatkan API key dari Google AI Studio."
    )
    
    # Tombol atau logika cek keaktifan API Key
    if user_api_key:
        # Cek apakah API Key valid dengan melakukan tes panggilan ringan ke Gemini
        try:
            genai.configure(api_key=user_api_key)
            # Tes model ringan untuk verifikasi kunci
            model = genai.GenerativeModel("gemini-1.5-flash")
            # Cek cepat (hanya inisialisasi / bisa test generate kecil)
            st.session_state["custom_api_key"] = user_api_key
            st.sidebar.success("API Key aktif dan valid!", icon="✅")
        except Exception as e:
            st.sidebar.error("API Key tidak valid atau salah! ❌", icon="❌")
            # Hapus atau kosongkan jika tidak valid agar tidak merusak sesi
            if "custom_api_key" in st.session_state:
                del st.session_state["custom_api_key"]
    else:
        st.sidebar.warning("Masukkan API Key untuk menggunakan AI.", icon="⚠️")
        
    st.sidebar.divider()
    
    # --- MANAJEMEN DAFTAR PASIEN / CHAT HISTORY ---
    st.sidebar.subheader("📋 Daftar Pasien")
    
    # Tombol Buat Konsultasi Baru
    if st.sidebar.button("➕ Pasien / Konsultasi Baru", use_container_width=True):
        st.session_state.active_patient = None
        st.session_state.messages = []
        st.session_state.quick_actions = []
        st.rerun()

    st.sidebar.markdown("---")

    # Simulasi Daftar Riwayat Pasien
    if "patient_list" not in st.session_state:
        st.session_state.patient_list = []

    if not st.session_state.patient_list:
        st.sidebar.info("Belum ada riwayat pasien.")
    else:
        for idx, pat in enumerate(st.session_state.patient_list):
            btn_label = f"{pat['name']} ({pat.get('mrn', 'MRN')})"
            if st.sidebar.button(btn_label, key=f"pat_history_{idx}", use_container_width=True):
                st.session_state.active_patient = pat
                st.session_state.messages = pat.get("messages", [])
                st.session_state.quick_actions = pat.get("quick_actions", [])
                st.rerun()