"""Status login di st.session_state, token sesi di URL (tahan refresh browser), dan gerbang akses halaman."""
import hashlib
import json
import secrets
import time

import streamlit as st

from auth import service, users_db

_KEY = "auth_user"
_CHECKED_AT = "auth_checked_at"
_PAGE = "account_page"  # None | "profile" | "admin"
_TOKEN = "auth_token"
_SAVED = "auth_state_saved"
QP = "s"  # nama parameter URL pembawa token sesi
SESSION_SECONDS = 12 * 3600  # login bertahan 12 jam (satu shift) sampai logout
RECHECK_SECONDS = 300  # akun yang dinonaktifkan admin kehilangan akses paling lambat 5 menit


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def current_user():
    return st.session_state.get(_KEY)


def login_user(user: dict) -> None:
    st.session_state[_KEY] = user
    st.session_state[_CHECKED_AT] = time.time()
    if _TOKEN not in st.session_state:  # login baru: buat token sesi + cookie
        token = secrets.token_urlsafe(32)
        try:
            users_db.create_session(_hash(token), user["id"], int(time.time()) + SESSION_SECONDS)
        except Exception as e:
            print(f"[auth] gagal membuat sesi: {e}")
            return
        st.session_state[_TOKEN] = token
        st.query_params[QP] = token  # tetap ada di URL saat refresh


def refresh_user() -> None:
    user = current_user()
    if user:
        fresh = service.reload_user(user["id"])
        if fresh:
            login_user(fresh)


def logout() -> None:
    from auth import audit_log
    audit_log.log("logout")  # catat sebelum sesi dibersihkan
    token = st.session_state.get(_TOKEN)
    if token:
        try:
            users_db.delete_session(_hash(token))
        except Exception as e:
            print(f"[auth] gagal menghapus sesi: {e}")
    st.session_state.clear()  # bersihkan juga data pasien/chat dari sesi ini
    st.query_params.pop(QP, None)


def open_account_page(page: str) -> None:
    st.session_state[_PAGE] = page


def close_account_page() -> None:
    st.session_state[_PAGE] = None


def current_account_page():
    return st.session_state.get(_PAGE)


def _restore() -> bool:
    """Pulihkan login + halaman terakhir dari token di URL setelah refresh. True jika berhasil."""
    token = st.query_params.get(QP)
    if not token:
        return False
    row = users_db.get_session(_hash(token))
    fresh = service.reload_user(row["user_id"]) if row and row["expires_at"] >= time.time() else None
    if not fresh:
        st.query_params.pop(QP, None)  # token tidak berlaku: buang dari URL
        return False
    st.session_state[_TOKEN] = token
    try:
        s = json.loads(row["state"] or "{}")
    except ValueError:
        s = {}
    if s.get("view") in ("chat", "patient_data"):
        st.session_state.view = s["view"]
    if s.get("data_mrn"):
        st.session_state.data_mrn = s["data_mrn"]
    if s.get("page") in ("profile", "admin"):
        st.session_state[_PAGE] = s["page"]
    if s.get("mrn"):
        st.session_state["_restore_mrn"] = s["mrn"]  # dipasang app.py setelah daftar roomchat dimuat
    login_user(fresh)
    return True


def _save_state() -> None:
    """Simpan halaman terakhir ke DB, hanya saat berubah (satu tulis per navigasi)."""
    token = st.session_state.get(_TOKEN)
    if not token:
        return
    snap = json.dumps({
        "view": st.session_state.get("view"),
        "mrn": (st.session_state.get("active_patient") or {}).get("mrn"),
        "data_mrn": st.session_state.get("data_mrn"),
        "page": st.session_state.get(_PAGE),
    }, sort_keys=True)
    if snap != st.session_state.get(_SAVED):
        st.session_state[_SAVED] = snap
        try:
            users_db.save_session_state(_hash(token), snap)
        except Exception as e:
            print(f"[auth] gagal menyimpan halaman terakhir: {e}")


def require_login() -> dict:
    """Panggil di awal app.py (setelah set_page_config). Menghentikan skrip jika belum login."""
    from components.admin_profile import render_force_password_change
    from components.login_page import render_login_page

    setup_error = service.ensure_ready()
    user = current_user()
    restored = False
    if not user and not setup_error:
        restored = _restore()
        user = current_user()
    if user and not setup_error and not restored and time.time() - st.session_state.get(_CHECKED_AT, 0) > RECHECK_SECONDS:
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
    if not restored:  # saat pemulihan, tunggu app.py memasang roomchat dulu agar tidak menimpa state
        _save_state()
    return user


def require_admin() -> dict:
    user = require_login()
    if user["role"] != "admin":
        st.error("Halaman ini hanya untuk admin.")
        st.stop()
    return user