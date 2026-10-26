import streamlit as st
from components.sidebar import render_sidebar
from components.chat_ui import render_chat_interface

st.set_page_config(
    page_title="Cardiology Anamnesis System",
    page_icon="🫀",
    layout="wide"
)

# Render UI
patient_info = render_sidebar()
render_chat_interface()