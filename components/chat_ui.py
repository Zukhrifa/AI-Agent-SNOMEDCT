import streamlit as st
from modules.ai_agent import generate_anamnesis_response

def render_chat_interface():
    # --- 1. KELOLA SIDEBAR HANYA UNTUK RIWAYAT ROOM CHAT ---
    with st.sidebar:
        st.header("📂 Riwayat Sesi")
        
        # Inisialisasi daftar room chat di session state jika belum ada
        if "chat_rooms" not in st.session_state:
            st.session_state.chat_rooms = []
            
        # Tombol untuk membuat room chat baru
        if st.button("➕ Room Chat Baru", use_container_width=True):
            if "messages" in st.session_state and len(st.session_state.messages) > 0:
                # Simpan room lama ke riwayat
                st.session_state.chat_rooms.append(st.session_state.messages)
            # Reset sesi aktif untuk room baru
            st.session_state.messages = []
            st.session_state.quick_actions = []
            st.rerun()
            
        st.divider()
        
        # Tampilkan riwayat room chat HANYA JIKA ADA
        if len(st.session_state.chat_rooms) > 0:
            for idx, room in enumerate(st.session_state.chat_rooms):
                preview = room[0]["content"] if len(room) > 0 else f"Sesi {idx+1}"
                if st.button(f"💬 {preview[:25]}...", key=f"room_{idx}", use_container_width=True):
                    st.session_state.messages = room
                    st.session_state.quick_actions = []
                    st.rerun()
        else:
            st.info("Belum ada riwayat room chat.")

    # --- 2. TAMPILAN UTAMA KELOMPOK CHAT & MOBILE FRIENDLY ---
    st.subheader("🩺 Anamnesis Kardiologi AI")
    
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "quick_actions" not in st.session_state:
        st.session_state.quick_actions = []

    # Render Riwayat Percakapan dalam Room Aktif
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.write(message["content"])

    # --- 3. QUICK ACTIONS (RESPONSIF / MOBILE FRIENDLY) ---
    if st.session_state.quick_actions and len(st.session_state.messages) > 0:
        st.markdown("💡 **Rekomendasi Pertanyaan (Quick Actions):**")
        
        # Gunakan kolom dinamis yang ramah tampilan mobile
        selected_action = None
        for idx, action_text in enumerate(st.session_state.quick_actions[:3]):
            if st.button(action_text, key=f"qa_btn_{len(st.session_state.messages)}_{idx}", use_container_width=True):
                selected_action = action_text

        if selected_action:
            process_user_input(selected_action)
            st.rerun()

    # --- 4. KOTAK INPUT TEKS DI BAGIAN BAWAH (STANDAR CHAT) ---
    # Streamlit secara otomatis merespons tampilan mobile dengan menempatkan chat_input di bawah layar.
    user_input = st.chat_input("Ketik keluhan utama pasien di sini...")
    
    if user_input:
        process_user_input(user_input)
        st.rerun()

def process_user_input(prompt_text):
    st.session_state.messages.append({"role": "user", "content": prompt_text})
    
    with st.spinner("AI sedang menganalisis gejala & mencari kode SNOMED CT..."):
        ai_reply, next_actions = generate_anamnesis_response(
            prompt_text, 
            st.session_state.messages[:-1]
        )
        
    st.session_state.messages.append({"role": "assistant", "content": ai_reply})
    st.session_state.quick_actions = next_actions