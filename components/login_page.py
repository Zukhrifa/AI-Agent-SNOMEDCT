"""Tampilan halaman login."""
import streamlit as st

from auth.service import authenticate
from auth.session import login_user

_CSS = """
<style>
[data-testid="stSidebar"], [data-testid="collapsedControl"], [data-testid="stSidebarCollapsedControl"] {display: none;}
.block-container {padding-top: 5rem; max-width: 1100px;}
.login-brand {text-align: center; margin-bottom: 1.5rem;}
.login-brand .logo {font-size: 2.8rem; line-height: 1;}
.login-brand h1 {font-size: 1.6rem; margin: .5rem 0 .15rem; padding: 0;}
.login-brand p {color: #6b7280; font-size: .92rem; margin: 0;}
[data-testid="stForm"] {border-radius: 14px; padding: 1.5rem 1.5rem 1.25rem;}
</style>
"""

_BRAND = """
<div class="login-brand">
  <div class="logo">🩺</div>
  <h1>Medical Anamnesis System</h1>
  <p>Masuk untuk melanjutkan</p>
</div>
"""


def render_login_page(setup_error: str = "") -> None:
    st.markdown(_CSS, unsafe_allow_html=True)
    _, col, _ = st.columns([1, 1.15, 1])
    with col:
        st.markdown(_BRAND, unsafe_allow_html=True)
        if setup_error:
            st.error(setup_error)
            return
        with st.form("login_form", clear_on_submit=False):
            username = st.text_input("Username", placeholder="mis. admin", autocomplete="username")
            password = st.text_input("Password", type="password", placeholder="Password Anda",
                                     autocomplete="current-password")
            submitted = st.form_submit_button("Masuk", type="primary", use_container_width=True)
        st.caption("Belum punya akun? Hubungi admin untuk dibuatkan akun.")
        if submitted:
            with st.spinner("Memeriksa..."):
                user, error = authenticate(username, password)
            if user:
                login_user(user)
                st.rerun()
            st.error(error)