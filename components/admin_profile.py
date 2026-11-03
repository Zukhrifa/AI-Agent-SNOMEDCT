"""Halaman profil (nama, peran, ganti password sendiri) dan form ganti password awal."""
import streamlit as st

from auth import service
from auth.session import close_account_page, current_user, logout, refresh_user


def _password_form(user: dict, key: str, forced: bool = False) -> None:
    with st.form(key, clear_on_submit=True):
        current = st.text_input("Password saat ini", type="password", autocomplete="current-password")
        new = st.text_input("Password baru", type="password", autocomplete="new-password",
                            help="Minimal 10 karakter, mengandung huruf dan angka.")
        confirm = st.text_input("Ulangi password baru", type="password", autocomplete="new-password")
        submitted = st.form_submit_button("Simpan dan lanjutkan" if forced else "Ganti password",
                                          type="primary", use_container_width=forced)
    if not submitted:
        return
    error = service.change_password(user["id"], current, new, confirm)
    if error:
        st.error(error)
        return
    refresh_user()
    st.success("Password berhasil diganti.")
    if forced:
        st.rerun()


def render_force_password_change(user: dict) -> None:
    """Dipakai saat must_change_password aktif (login pertama, atau akun baru buatan admin)."""
    st.markdown("<style>[data-testid='stSidebar'], [data-testid='collapsedControl'] {display:none;}</style>",
                unsafe_allow_html=True)
    _, col, _ = st.columns([1, 1.15, 1])
    with col:
        st.subheader("Ganti password awal")
        st.info("Demi keamanan, ganti password sementara Anda sebelum melanjutkan.")
        _password_form(user, "force_pw_form", forced=True)
        if st.button("Keluar", key="force_pw_logout"):
            logout()
            st.rerun()


def render_profile_page() -> None:
    user = current_user()
    if not user:
        return
    if st.button("← Kembali", key="profile_back"):
        close_account_page()
        st.rerun()
    st.title("Profil")
    with st.container(border=True):
        st.subheader(user["full_name"] or user["username"])
        st.markdown(f"**Peran:** {service.ROLE_LABEL.get(user['role'], user['role'])}")
        st.caption(f"Username: {user['username']}  •  Login terakhir: {user['last_login_at'] or '-'} WIB")
    st.subheader("Ganti password")
    _password_form(user, "change_pw_form")