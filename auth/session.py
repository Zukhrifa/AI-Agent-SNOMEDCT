"""Status login di st.session_state dan gerbang akses halaman."""
import time

import streamlit as st

from auth import service

_KEY = "auth_user"
_CHECKED_AT = "auth_checked_at"
RECHECK_SECONDS = 300  # akun yang dinonaktifkan admin kehilangan akses paling lambat 5 menit


def current_user():
    return st.session_state.get(_KEY)


def login_user(user: dict) -> None:
    st.session_state[_KEY] = user
    st.session_state[_CHECKED_AT] = time.time()


def refresh_user() -> None:
    user = current_user()
    if user:
        fresh = service.reload_user(user["id"])
        if fresh:
            login_user(fresh)


def logout() -> None:
    st.session_state.clear()  # bersihkan juga data pasien/chat dari sesi ini


def require_login() -> dict:
    """Panggil di awal app.py (setelah set_page_config). Menghentikan skrip jika belum login."""
    from components.admin_profile import render_force_password_change
    from components.login_page import render_login_page

    setup_error = service.ensure_ready()
    user = current_user()
    if user and not setup_error and time.time() - st.session_state.get(_CHECKED_AT, 0) > RECHECK_SECONDS:
        fresh = service.reload_user(user["id"])
        if not fresh:
            logout()
            st.rerun()
        login_user(fresh)
        user = fresh
    if not user:
        render_login_page(setup_error)
        st.stop()
    if user["must_change_password"]:
        render_force_password_change(user)
        st.stop()
    return user


def require_admin() -> dict:
    user = require_login()
    if user["role"] != "admin":
        st.error("Halaman ini hanya untuk admin.")
        st.stop()
    return user