"""Halaman admin: buat akun, lalu kelola semua akun dari satu tabel
(lihat password sementara, reset password, aktifkan/nonaktifkan)."""
import streamlit as st
from auth import audit_log, service
from auth.session import close_account_page, require_admin
_dialog = getattr(st, "dialog", None) or st.experimental_dialog  # st.dialog butuh Streamlit >= 1.37
_W = [2.3, 1.1, 1.7, 2.1, 1.8, 0.7, 0.7]
_HEAD = ["Nama", "Peran", "Status", "Password sementara", "Login terakhir (WIB)", "Reset", "Aktif"]
def _status(a: dict) -> str:
    if not a["is_active"]:
        return "⛔ Nonaktif"
    return "🕓 Menunggu login pertama" if a["has_temp_password"] else "✅ Aktif"
@_dialog("Konfirmasi")
def _confirm(admin_id: int, target: dict, action: str) -> None:
    name = f"**{target['full_name']}** (@{target['username']})"
    if action == "reset":
        st.warning(f"Reset password {name}? Password lama dihapus dan diganti password sementara baru.")
    elif target["is_active"]:
        st.warning(f"Nonaktifkan akun {name}? Pengguna tidak bisa login lagi sampai diaktifkan kembali.")
    else:
        st.info(f"Aktifkan kembali akun {name}?")
    c1, c2 = st.columns(2)
    if c1.button("Batal", use_container_width=True):
        st.rerun()
    if c2.button("Ya, lanjutkan", type="primary", use_container_width=True):
        error = (service.reset_password(admin_id, target["id"]) if action == "reset"
                 else service.set_active(admin_id, target["id"], not target["is_active"]))
        if error:
            st.error(error)
        else:
            st.rerun()
def _log_view(accounts: list) -> None:
    """Fragment: filter dan tabel log, diperbarui otomatis tanpa memuat ulang halaman."""
    f1, f2 = st.columns([3, 1])
    names = {a["id"]: f"{a['full_name']} (@{a['username']})" for a in accounts}
    who = f1.selectbox("Pengguna", [None] + list(names), key="log_user",
                       format_func=lambda i: "Semua pengguna" if i is None else names[i])
    limit = f2.selectbox("Tampilkan", [50, 100, 300], index=1, key="log_limit")
    logs = audit_log.list_logs(user_id=who, limit=limit)
    if logs:
        st.dataframe(audit_log.table_rows(logs), use_container_width=True, hide_index=True)
    else:
        st.info("Belum ada aktivitas tercatat.")
    st.caption(f"Diperbarui otomatis tiap {audit_log.LIVE_SECONDS} detik.")
def render_admin_users_page() -> None:
    admin = require_admin()
    if st.button("← Kembali", key="admin_back"):
        close_account_page()
        st.rerun()
    st.title("Kelola Akun")
    st.subheader("Buat akun baru")
    with st.form("create_account_form", clear_on_submit=True):
        full_name = st.text_input("Nama lengkap")
        username = st.text_input("Username (untuk login)",
                                 help="Huruf kecil, angka, titik, garis bawah, atau strip.")
        role = st.selectbox("Peran", service.ROLES, format_func=service.ROLE_LABEL.get, index=1)
        submitted = st.form_submit_button("Buat akun", type="primary")
    if submitted:
        error = service.create_account(admin["id"], full_name, username, role)
        if error:
            st.error(error)
        else:
            st.success("Akun dibuat. Password sementara tampil di tabel di bawah.")
    st.subheader("Daftar akun")
    st.caption("🔑 Reset password · ⛔/✅ Nonaktifkan/Aktifkan. Password sementara hilang otomatis "
               "setelah pengguna berhasil login.")
    accounts = service.list_accounts(admin["id"])
    cols = st.columns(_W)
    for c, title in zip(cols, _HEAD):
        c.markdown(f"**{title}**")
    for a in accounts:
        me = a["id"] == admin["id"]
        c = st.columns(_W)
        c[0].markdown(f"**{a['full_name']}**{' (Anda)' if me else ''}  \n@{a['username']}")
        c[1].write(service.ROLE_LABEL.get(a["role"], a["role"]))
        c[2].write(_status(a))
        if a["temp_password"]:
            c[3].code(a["temp_password"], language=None)
        else:
            c[3].write("-")
        c[4].write(a["last_login_at"] or "-")
        if c[5].button("🔑", key=f"rst_{a['id']}", disabled=me, help="Reset password"):
            _confirm(admin["id"], a, "reset")
        if c[6].button("⛔" if a["is_active"] else "✅", key=f"act_{a['id']}", disabled=me,
                       help="Nonaktifkan akun" if a["is_active"] else "Aktifkan akun"):
            _confirm(admin["id"], a, "toggle")
    st.subheader("Log aktivitas")
    audit_log.live(_log_view)(accounts)