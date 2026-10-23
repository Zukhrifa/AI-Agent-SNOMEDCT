import streamlit as st
import os
from dotenv import load_dotenv
from ai_agent import generate_anamnesis_response, summarize_anamnesis
from modules.database import save_consultation, get_all_consultations

# Memuat environment variables (.env)
load_dotenv()

# Konfigurasi Halaman Streamlit
st.set_page_config(
    page_title="AI Cardiology Anamnesis System",
    page_icon="🩺",
    layout="wide"
)

# Sidebar untuk Navigasi & Riwayat Sesi
st.sidebar.title("🩺 Navigasi & Rekam Medis")
menu = st.sidebar.selectbox("Pilih Menu", ["Konsultasi Baru (Anamnesis)", "Riwayat Konsultasi Pasien"])

if menu == "Konsultasi Baru (Anamnesis)":
    st.title("Sistem Anamnesis Kardiologi Berbasis AI")
    st.markdown("Asisten cerdas untuk membantu wawancara awal keluhan jantung dan pencarian terminologi medis **SNOMED CT**.")

    # Form Input Identitas Pasien
    with st.expander("📝 Identitas Pasien (Wajib diisi sebelum mulai)", expanded=True):
        col1, col2 = st.columns(2)
        with col1:
            patient_name = st.text_input("Nama Lengkap Pasien", placeholder="Contoh: Budi Santoso")
        with col2:
            medical_record_no = st.text_input("Nomor Rekam Medis (No. RM)", placeholder="Contoh: RM-2026-001")

    # Inisialisasi Riwayat Chat di Streamlit Session State
    if "messages" not in st.session_state:
        st.session_state.messages = []

    # Tampilkan Riwayat Percakapan
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    # Input Chat dari Pengguna / Dokter / Pasien
    if prompt := st.chat_input("Ceritakan keluhan atau gejala kardiovaskular yang dirasakan..."):
        if not patient_name or not medical_record_no:
            st.warning("⚠️ Mohon isi Nama Pasien dan Nomor Rekam Medis terlebih dahulu pada bagian atas!")
        else:
            # Tambahkan pesan pengguna ke UI
            st.session_state.messages.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)

            # Generate respon dari AI Agent (RAG + Gemini)
            with st.chat_message("assistant"):
                with st.spinner("Menganalisis keluhan dan terminologi SNOMED CT..."):
                    try:
                        response = generate_anamnesis_response(prompt, st.session_state.messages)
                        st.markdown(response)
                        # Simpan respon asisten ke session state
                        st.session_state.messages.append({"role": "assistant", "content": response})
                    except Exception as e:
                        st.error(f"Terjadi kesalahan pada sistem AI: {e}")

    # Tombol Ringkasan & Simpan ke Database SQLite
    if st.session_state.messages:
        st.divider()
        col_btn1, col_btn2 = st.columns([1, 4])
        with col_btn1:
            if st.button("📋 Buat Ringkasan Medis"):
                with st.spinner("Menyusun ringkasan anamnesis..."):
                    summary = summarize_anamnesis(st.session_state.messages)
                    st.subheader("Hasil Ringkasan Anamnesis")
                    st.info(summary)
                    
                    # Simpan ke Database SQLite
                    save_consultation(
                        patient_name=patient_name,
                        medical_record_no=medical_record_no,
                        summary=summary,
                        validation="Pending Review Dokter"
                    )
                    st.success("Data konsultasi berhasil disimpan ke database lokal!")

        with col_btn2:
            if st.button("🔄 Reset Sesi Konsultasi"):
                st.session_state.messages = []
                st.rerun()

elif menu == "Riwayat Konsultasi Pasien":
    st.title("📂 Arsip Riwayat Konsultasi Pasien")
    st.markdown("Daftar seluruh sesi anamnesis kardiologi yang telah tersimpan di database lokal.")
    
    records = get_all_consultations()
    if not records:
        st.info("Belum ada data riwayat konsultasi yang tersimpan.")
    else:
        for rec in records:
            rec_id, name, rm, created, status = rec
            with st.container():
                st.markdown(f"""
                * **ID Sesi:** {rec_id} | **Nama Pasien:** **{name}** (No. RM: {rm})
                * **Waktu:** {created} | **Status:** `{status}`
                """)
                st.divider()