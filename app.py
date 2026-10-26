import streamlit as st
from components.sidebar import render_sidebar
from components.new_roomchat import render_new_consultation_form
from components.chat_ui import render_chat_room

st.set_page_config(
    page_title="RoomChat - Medical AI Assistant",
    page_icon="🩺",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Fungsi untuk memuat CSS eksternal
def load_css(file_name):
    with open(file_name) as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

# Panggil file CSS eksternal
load_css("style.css")

# Inisialisasi Session State
if "active_patient" not in st.session_state:
    st.session_state.active_patient = None
if "messages" not in st.session_state:
    st.session_state.messages = []
if "quick_actions" not in st.session_state:
    st.session_state.quick_actions = []

# Header Aplikasi
st.markdown("""
    <div style="display: flex; align-items: center; padding: 8px 0; margin-bottom: 10px; border-bottom: 1px solid #e2e8f0;">
        <div style="background-color: #2563eb; color: white; padding: 6px 10px; border-radius: 8px; font-weight: bold; margin-right: 10px;">
            💬
        </div>
        <span style="font-size: 20px; font-weight: 700; color: #0f172a;">RoomChat</span>
        <span style="font-size: 13px; color: #64748b; margin-left: 10px;">Medical AI Assistant</span>
    </div>
""", unsafe_allow_html=True)

# Render Sidebar
render_sidebar()

# Logika Tampilan Utama
if st.session_state.active_patient is None:
    render_new_consultation_form()
else:
    render_chat_room()