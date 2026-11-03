"""Akses tabel `users` di Turso (atau SQLite lokal), memakai lapisan akses dari database.py.
Kolom `temp_password_enc` kini menyimpan password sementara APA ADANYA (teks asli),
dihapus saat pengguna berhasil login atau mengganti password."""
import time
from database import _NOW, _run, _write
_COLS = (
    "id", "username", "full_name", "role", "password_hash", "temp_password_enc", "is_active",
    "must_change_password", "failed_attempts", "locked_until", "last_login_at", "created_at",
)
_SELECT = "SELECT " + ", ".join(_COLS) + " FROM users "
def _row(rows: list):
    return dict(zip(_COLS, rows[0])) if rows else None
def init_table() -> None:
    _write([(
        f"""CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            full_name TEXT NOT NULL DEFAULT '',
            role TEXT NOT NULL DEFAULT 'perawat' CHECK (role IN ('admin','dokter','perawat')),
            password_hash TEXT NOT NULL,
            temp_password_enc TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            must_change_password INTEGER NOT NULL DEFAULT 0,
            failed_attempts INTEGER NOT NULL DEFAULT 0,
            locked_until INTEGER NOT NULL DEFAULT 0,
            last_login_at TEXT,
            created_at TEXT NOT NULL DEFAULT ({_NOW}),
            updated_at TEXT NOT NULL DEFAULT ({_NOW})
        )""",
        (),
    )])
    try:  # migrasi tabel lama yang belum punya kolom ini
        _run([("SELECT temp_password_enc FROM users LIMIT 1", ())])
    except Exception:
        _write([("ALTER TABLE users ADD COLUMN temp_password_enc TEXT", ())])
    _write([(
        f"""CREATE TABLE IF NOT EXISTS auth_sessions (
            token_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            state TEXT NOT NULL DEFAULT '',
            expires_at INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT ({_NOW})
        )""",
        (),
    )])
def count_users() -> int:
    return int(_run([("SELECT COUNT(*) FROM users", ())])[0][0][0])
# Pembacaan memakai _run (bukan _query) agar tidak terkena cache: status akun harus selalu terbaru.
def get_by_username(username: str):
    return _row(_run([(_SELECT + "WHERE username = ?", (username,))])[0])
def get_by_id(user_id: int):
    return _row(_run([(_SELECT + "WHERE id = ?", (int(user_id),))])[0])
def list_users() -> list:
    rows = _run([(_SELECT + "ORDER BY id", ())])[0]
    return [dict(zip(_COLS, r)) for r in rows]
def create_user(username, full_name, role, password_hash, temp_plain=None, must_change=False) -> None:
    _write([(
        "INSERT INTO users (username, full_name, role, password_hash, temp_password_enc, must_change_password) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (username, full_name, role, password_hash, temp_plain, int(must_change)),
    )])
def set_temp_password(user_id: int, password_hash: str, temp_plain) -> None:
    """Reset oleh admin: ganti password lama, simpan teks aslinya, wajib ganti saat login."""
    _write([(
        f"UPDATE users SET password_hash = ?, temp_password_enc = ?, must_change_password = 1, "
        f"failed_attempts = 0, locked_until = 0, updated_at = {_NOW} WHERE id = ?",
        (password_hash, temp_plain, int(user_id)),
    )])
def set_active(user_id: int, active: bool) -> None:
    _write([(
        f"UPDATE users SET is_active = ?, updated_at = {_NOW} WHERE id = ?",
        (int(active), int(user_id)),
    )])
def update_password(user_id: int, password_hash: str, must_change: bool = False) -> None:
    """Password diganti pengguna sendiri: salinan password sementara ikut dihapus."""
    _write([(
        f"UPDATE users SET password_hash = ?, temp_password_enc = NULL, must_change_password = ?, "
        f"failed_attempts = 0, locked_until = 0, updated_at = {_NOW} WHERE id = ?",
        (password_hash, int(must_change), int(user_id)),
    )])
def register_failed_attempt(user_id: int, max_attempts: int, locked_until: int) -> None:
    """Tambah hitungan gagal; bila mencapai batas, kunci akun lalu reset hitungan."""
    _write([(
        "UPDATE users SET "
        "locked_until = CASE WHEN failed_attempts + 1 >= ? THEN ? ELSE locked_until END, "
        "failed_attempts = CASE WHEN failed_attempts + 1 >= ? THEN 0 ELSE failed_attempts + 1 END "
        "WHERE id = ?",
        (max_attempts, locked_until, max_attempts, int(user_id)),
    )])
def record_login(user_id: int) -> None:
    """Login berhasil: password sementara dianggap sudah dipakai, salinannya dihapus."""
    _write([(
        f"UPDATE users SET failed_attempts = 0, locked_until = 0, temp_password_enc = NULL, "
        f"last_login_at = {_NOW} WHERE id = ?",
        (int(user_id),),
    )])
# --- Sesi login (tahan refresh browser): hanya hash token yang disimpan ---
def create_session(token_hash: str, user_id: int, expires_at: int) -> None:
    _write([
        ("DELETE FROM auth_sessions WHERE expires_at < ?", (int(time.time()),)),
        ("INSERT INTO auth_sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
         (token_hash, int(user_id), int(expires_at))),
    ])
def get_session(token_hash: str):
    rows = _run([("SELECT user_id, state, expires_at FROM auth_sessions WHERE token_hash = ?", (token_hash,))])[0]
    return dict(zip(("user_id", "state", "expires_at"), rows[0])) if rows else None
def save_session_state(token_hash: str, state: str) -> None:
    _write([("UPDATE auth_sessions SET state = ? WHERE token_hash = ?", (state, token_hash))])
def delete_session(token_hash: str) -> None:
    _write([("DELETE FROM auth_sessions WHERE token_hash = ?", (token_hash,))])
def delete_user_sessions(user_id: int) -> None:
    _write([("DELETE FROM auth_sessions WHERE user_id = ?", (int(user_id),))])