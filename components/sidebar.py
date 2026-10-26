import streamlit as st
import os

def render_sidebar():
    st.sidebar.title("Pengaturan & Pasien")
    
    # Ambil API key secara aman tanpa membuat error jika file secrets.toml tidak ada di lokal
    env_api_key = ""
    try:
        env_api_key = st.secrets.get("GEMINI_API_KEY", "")
    except Exception:
        pass
    
    # Jika tidak ada di secrets, ambil dari environment variable (.env)
    if not env_api_key:
        env_api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY", "")

    st.sidebar.subheader(" Gemini API Key")
    if env_api_key:
        st.sidebar.success("API Key terdeteksi otomatis dari sistem ", icon="✅")
        with st.sidebar.expander("Ganti API Key secara manual (Opsional)"):
            user_api_key = st.text_input(
                "Custom API Key:",
                value=st.session_state.get("custom_api_key", ""),
                type="password"
            )
            if user_api_key:
                st.session_state["custom_api_key"] = user_api_key
    else:
        user_api_key = st.sidebar.text_input(
            "Masukkan API Key Anda:",
            value=st.session_state.get("custom_api_key", ""),
            type="password",
            help="Dapatkan API key dari Google AI Studio."
        )
        if user_api_key:
            st.session_state["custom_api_key"] = user_api_key
            st.sidebar.success("API Key manual disimpan!", icon="✅")
        else:
            st.sidebar.warning("API Key belum diatur di .env maupun sidebar.", icon="⚠️")
        
    st.sidebar.divider()
    
    # --- MANAJEMEN DAFTAR PASIEN / CHAT HISTORY ---
    st.sidebar.subheader("📋 Daftar Pasien")
    
    # Tombol Buat Konsultasi Baru
    if st.sidebar.button("➕ Pasien / Konsultasi Baru", use_container_width=True):
        # Reset state untuk chat baru, tapi JANGAN hapus patient_list!
        st.session_state.active_patient = None
        st.session_state.messages = []
        st.session_state.quick_actions = []
        st.rerun()

    st.sidebar.markdown("---")
    st.sidebar.subheader("📋 Riwayat Daftar Pasien")

    # Menampilkan daftar riwayat pasien yang pernah dibuat
    if not st.session_state.patient_list:
        st.sidebar.info("Belum ada riwayat pasien tersimpan.")
    else:
        for idx, pat in enumerate(st.session_state.patient_list):
            # Tombol untuk membuka kembali roomchat pasien lama
            btn_label = f"👤 {pat['name']} ({pat.get('mrn', 'MRN')})"
            if st.sidebar.button(btn_label, key=f"history_pat_{idx}", use_container_width=True):
                # Muat ulang data pasien yang dipilih ke layar utama
                st.session_state.active_patient = pat
                st.session_state.messages = pat.get("messages", [])
                st.session_state.quick_actions = pat.get("quick_actions", [])
                st.rerun()

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