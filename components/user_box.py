"""Kotak pengguna kecil untuk sidebar: nama, peran, tombol Profil dan Keluar."""
import streamlit as st

from auth.session import current_user, logout
from components.admin_profile import ROLE_LABEL


def render_user_box() -> None:
    user = current_user()
    if not user:
        return
    st.markdown(f"**{user['full_name'] or user['username']}**")
    st.caption(ROLE_LABEL.get(user["role"], user["role"]))
    col_profile, col_logout = st.columns(2)
    if col_profile.button("Profil", key="btn_open_profile", use_container_width=True):
        st.session_state["show_profile"] = True
        st.rerun()
    if col_logout.button("Keluar", key="btn_logout", use_container_width=True):
        logout()
        st.rerun()