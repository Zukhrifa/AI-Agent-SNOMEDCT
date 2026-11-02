"""Akses tabel `users` di Turso (atau SQLite lokal), memakai lapisan akses dari database.py."""
from database import _NOW, _run, _write

_COLS = (
    "id", "username", "full_name", "email", "role", "password_hash", "is_active",
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
            email TEXT NOT NULL DEFAULT '',
            role TEXT NOT NULL DEFAULT 'perawat' CHECK (role IN ('admin','dokter','perawat')),
            password_hash TEXT NOT NULL,
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


def count_users() -> int:
    return int(_run([("SELECT COUNT(*) FROM users", ())])[0][0][0])


# Pembacaan memakai _run (bukan _query) agar tidak terkena cache: status akun harus selalu terbaru.
def get_by_username(username: str):
    return _row(_run([(_SELECT + "WHERE username = ?", (username,))])[0])


def get_by_id(user_id: int):
    return _row(_run([(_SELECT + "WHERE id = ?", (int(user_id),))])[0])


def create_user(username, full_name, email, role, password_hash, must_change=False) -> None:
    _write([(
        "INSERT INTO users (username, full_name, email, role, password_hash, must_change_password) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (username, full_name, email, role, password_hash, int(must_change)),
    )])


def update_profile(user_id: int, full_name: str, email: str) -> None:
    _write([(
        f"UPDATE users SET full_name = ?, email = ?, updated_at = {_NOW} WHERE id = ?",
        (full_name, email, int(user_id)),
    )])


def update_password(user_id: int, password_hash: str, must_change: bool = False) -> None:
    _write([(
        f"UPDATE users SET password_hash = ?, must_change_password = ?, failed_attempts = 0, "
        f"locked_until = 0, updated_at = {_NOW} WHERE id = ?",
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
    _write([(
        f"UPDATE users SET failed_attempts = 0, locked_until = 0, last_login_at = {_NOW} WHERE id = ?",
        (int(user_id),),
    )])