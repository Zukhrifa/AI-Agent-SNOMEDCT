"""Halaman profil pengguna (admin) dan form ganti password awal."""
import streamlit as st

from auth import service
from auth.session import current_user, login_user, refresh_user

ROLE_LABEL = {"admin": "Admin", "dokter": "Dokter", "perawat": "Perawat"}


def _password_form(user: dict, key: str, button_label: str, forced: bool = False) -> None:
    with st.form(key, clear_on_submit=True):
        current = st.text_input("Password saat ini", type="password", autocomplete="current-password")
        new = st.text_input("Password baru", type="password", autocomplete="new-password",
                            help="Minimal 10 karakter, mengandung huruf dan angka.")
        confirm = st.text_input("Ulangi password baru", type="password", autocomplete="new-password")
        submitted = st.form_submit_button(button_label, type="primary", use_container_width=forced)
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
    """Dipakai saat must_change_password aktif (mis. login pertama admin)."""
    st.markdown("<style>[data-testid='stSidebar'], [data-testid='collapsedControl'] {display:none;}</style>",
                unsafe_allow_html=True)
    _, col, _ = st.columns([1, 1.15, 1])
    with col:
        st.subheader("Ganti password awal")
        st.info("Demi keamanan, ganti password sementara Anda sebelum melanjutkan.")
        _password_form(user, "force_pw_form", "Simpan dan lanjutkan", forced=True)
        if st.button("Keluar", key="force_pw_logout"):
            from auth.session import logout
            logout()
            st.rerun()


def render_admin_profile_page() -> None:
    user = current_user()
    if not user:
        return
    if st.button("← Kembali", key="profile_back"):
        st.session_state["show_profile"] = False
        st.rerun()

    st.title("Profil")
    with st.container(border=True):
        left, right = st.columns([3, 2])
        left.subheader(user["full_name"] or user["username"])
        left.caption(f"@{user['username']}")
        right.markdown(f"**Peran:** {ROLE_LABEL.get(user['role'], user['role'])}")
        right.caption(f"Login terakhir: {user['last_login_at'] or '-'} WIB")
        right.caption(f"Akun dibuat: {user['created_at'] or '-'} WIB")

    tab_data, tab_security = st.tabs(["Data diri", "Keamanan"])
    with tab_data:
        with st.form("profile_form"):
            full_name = st.text_input("Nama lengkap", value=user["full_name"])
            email = st.text_input("Email (opsional)", value=user["email"])
            st.text_input("Username", value=user["username"], disabled=True,
                          help="Username tidak dapat diubah.")
            submitted = st.form_submit_button("Simpan perubahan", type="primary")
        if submitted:
            error = service.update_profile(user["id"], full_name, email)
            if error:
                st.error(error)
            else:
                fresh = service.reload_user(user["id"])
                if fresh:
                    login_user(fresh)
                st.success("Profil diperbarui.")
                st.rerun()
    with tab_security:
        _password_form(user, "change_pw_form", "Ganti password")