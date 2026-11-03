"""Logika bisnis autentikasi: bootstrap admin awal, login, ubah profil, ganti password,
serta kelola akun oleh admin (buat, reset password, aktif/nonaktif)."""
import time
from auth import security, users_db
from database import _get_secret
MAX_ATTEMPTS = 5
LOCK_SECONDS = 15 * 60
GENERIC_LOGIN_ERROR = "Username atau password salah."
ROLES = ("admin", "dokter", "perawat")
ROLE_LABEL = {"admin": "Admin", "dokter": "Dokter", "perawat": "Perawat"}
_READY = False
def public_user(user: dict) -> dict:
    """Data pengguna yang aman disimpan di session (tanpa hash dan data keamanan)."""
    return {
        "id": user["id"],
        "username": user["username"],
        "full_name": user["full_name"],
        "role": user["role"],
        "is_active": bool(user["is_active"]),
        "must_change_password": bool(user["must_change_password"]),
        "has_temp_password": bool(user.get("temp_password_enc")),
        "last_login_at": user["last_login_at"],
        "created_at": user["created_at"],
    }
def _bootstrap_admin() -> str:
    """Jika belum ada pengguna sama sekali, buat admin pertama dari secrets/.env."""
    if users_db.count_users() > 0:
        return ""
    username = security.normalize_username(_get_secret("ADMIN_USERNAME"))
    password = _get_secret("ADMIN_PASSWORD")
    if not username or not password:
        return ("Admin awal belum dikonfigurasi. Isi ADMIN_USERNAME dan ADMIN_PASSWORD "
                "di secrets (Streamlit Cloud) atau file .env, lalu muat ulang halaman.")
    error = security.validate_username(username) or security.validate_password(password)
    if error:
        return f"Konfigurasi admin awal tidak valid: {error}"
    try:
        users_db.create_user(
            username=username,
            full_name=_get_secret("ADMIN_FULL_NAME").strip() or "Administrator",
            role="admin",
            password_hash=security.hash_password(password),
            must_change=True,  # wajib ganti password saat login pertama
        )
    except Exception as e:
        if users_db.count_users() == 0:  # bukan karena sesi lain sudah membuatnya
            print(f"[auth] gagal membuat admin awal: {e}")
            return "Gagal membuat admin awal."
    return ""
def ensure_ready() -> str:
    """Siapkan tabel dan admin awal. Return pesan error (kosong jika siap)."""
    global _READY
    if _READY:
        return ""
    try:
        users_db.init_table()
        error = _bootstrap_admin()
    except Exception as e:
        print(f"[auth] database pengguna tidak dapat diakses: {e}")
        return "Database pengguna tidak dapat diakses. Periksa koneksi Turso."
    if not error:
        _READY = True
    return error
def authenticate(username: str, password: str):
    """Return (user_publik, '') jika berhasil, atau (None, pesan_error)."""
    username = security.normalize_username(username)
    password = password or ""
    if not username or not password or len(password) > security.MAX_PASSWORD_LEN:
        return None, GENERIC_LOGIN_ERROR
    user = users_db.get_by_username(username)
    if not user:
        security.burn_time(password)
        return None, GENERIC_LOGIN_ERROR
    now = int(time.time())
    if user["locked_until"] > now:
        minutes = (user["locked_until"] - now + 59) // 60
        return None, f"Terlalu banyak percobaan gagal. Coba lagi dalam {minutes} menit."
    if not security.verify_password(password, user["password_hash"]):
        users_db.register_failed_attempt(user["id"], MAX_ATTEMPTS, now + LOCK_SECONDS)
        return None, GENERIC_LOGIN_ERROR
    if not user["is_active"]:
        return None, "Akun dinonaktifkan. Hubungi admin."
    if security.needs_rehash(user["password_hash"]):
        users_db.update_password(user["id"], security.hash_password(password),
                                 bool(user["must_change_password"]))
    users_db.record_login(user["id"])
    return public_user(users_db.get_by_id(user["id"])), ""
def reload_user(user_id: int):
    """Muat ulang data pengguna dari DB. None jika sudah dihapus atau dinonaktifkan."""
    user = users_db.get_by_id(user_id)
    if not user or not user["is_active"]:
        return None
    return public_user(user)
def _is_active_admin(actor_id: int) -> bool:
    actor = users_db.get_by_id(actor_id)
    return bool(actor and actor["is_active"] and actor["role"] == "admin")
def list_accounts(actor_id: int) -> list:
    """Khusus admin. Tiap akun membawa `temp_password` (teks asli, kosong jika sudah login)."""
    if not _is_active_admin(actor_id):
        return []
    result = []
    for u in users_db.list_users():
        raw = u["temp_password_enc"] or ""
        if raw.startswith("gAAAA"):  # sisa token terenkripsi versi lama: tidak terbaca, perlu Reset
            raw = ""
        result.append({**public_user(u), "temp_password": raw})
    return result
def create_account(actor_id: int, full_name: str, username: str, role: str) -> str:
    """Hanya admin. Return pesan error, atau '' jika berhasil (password tampil di tabel)."""
    if not _is_active_admin(actor_id):
        return "Hanya admin yang dapat membuat akun."
    full_name = (full_name or "").strip()
    username = security.normalize_username(username)
    if not full_name or len(full_name) > 100:
        return "Nama lengkap wajib diisi (maksimal 100 karakter)."
    error = security.validate_username(username)
    if error:
        return error
    if role not in ROLES:
        return "Peran tidak valid."
    if users_db.get_by_username(username):
        return "Username sudah dipakai."
    plain = security.generate_temp_password()
    try:
        users_db.create_user(username, full_name, role, security.hash_password(plain),
                             plain, must_change=True)
    except Exception as e:
        print(f"[auth] gagal membuat akun: {e}")
        return "Gagal membuat akun (username mungkin sudah dipakai)."
    return ""
def reset_password(actor_id: int, target_id: int) -> str:
    """Hanya admin. Ganti password lama dengan password sementara baru. Return pesan error atau ''."""
    if not _is_active_admin(actor_id):
        return "Hanya admin yang dapat mereset password."
    if not users_db.get_by_id(target_id):
        return "Akun tidak ditemukan."
    if target_id == actor_id:
        return "Untuk akun sendiri, ganti password lewat menu Profil."
    plain = security.generate_temp_password()
    users_db.set_temp_password(target_id, security.hash_password(plain), plain)
    return ""
def set_active(actor_id: int, target_id: int, active: bool) -> str:
    """Hanya admin. Aktifkan/nonaktifkan akun lain. Return pesan error atau ''."""
    if not _is_active_admin(actor_id):
        return "Hanya admin yang dapat mengubah status akun."
    if target_id == actor_id:
        return "Anda tidak dapat menonaktifkan akun sendiri."
    if not users_db.get_by_id(target_id):
        return "Akun tidak ditemukan."
    users_db.set_active(target_id, active)
    return ""
def change_password(user_id: int, current: str, new: str, confirm: str) -> str:
    """Return pesan error, atau string kosong jika berhasil."""
    user = users_db.get_by_id(user_id)
    if not user:
        return "Akun tidak ditemukan."
    now = int(time.time())
    if user["locked_until"] > now:
        return "Terlalu banyak percobaan gagal. Coba lagi beberapa menit lagi."
    if not security.verify_password(current or "", user["password_hash"]):
        users_db.register_failed_attempt(user["id"], MAX_ATTEMPTS, now + LOCK_SECONDS)
        return "Password saat ini salah."
    if new != confirm:
        return "Konfirmasi password tidak sama."
    error = security.validate_password(new)
    if error:
        return error
    if new == current:
        return "Password baru harus berbeda dari password saat ini."
    users_db.update_password(user["id"], security.hash_password(new), must_change=False)
    return ""