"""Hash password dan validasi input. Hanya memakai pustaka standar Python (tanpa dependensi baru)."""
import base64
import hashlib
import hmac
import os
import re
from functools import lru_cache

ALGO = "pbkdf2_sha256"
ITERATIONS = 600_000
SALT_BYTES = 16
MIN_PASSWORD_LEN = 10
MAX_PASSWORD_LEN = 128

_USERNAME_RE = re.compile(r"^[a-z0-9._-]{3,32}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _derive(password: str, salt: bytes, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)


def hash_password(password: str) -> str:
    salt = os.urandom(SALT_BYTES)
    digest = _derive(password, salt, ITERATIONS)
    return "$".join((
        ALGO, str(ITERATIONS),
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(digest).decode("ascii"),
    ))


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt_b64, hash_b64 = (stored or "").split("$")
        if algo != ALGO:
            return False
        actual = _derive(password, base64.b64decode(salt_b64), int(iters))
        expected = base64.b64decode(hash_b64)
    except Exception:
        return False
    return hmac.compare_digest(actual, expected)


def needs_rehash(stored: str) -> bool:
    try:
        return int(stored.split("$")[1]) < ITERATIONS
    except Exception:
        return True


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    return hash_password("dummy-password-for-timing")


def burn_time(password: str) -> None:
    """Dipanggil saat username tidak ada, agar waktu respons sama dengan username yang ada."""
    verify_password(password, _dummy_hash())


def normalize_username(username: str) -> str:
    return (username or "").strip().lower()


def validate_username(username: str) -> str:
    if not _USERNAME_RE.fullmatch(username or ""):
        return "Username 3-32 karakter: huruf kecil, angka, titik, garis bawah, atau strip."
    return ""


def validate_email(email: str) -> str:
    email = (email or "").strip()
    if email and not _EMAIL_RE.fullmatch(email):
        return "Format email tidak valid."
    return ""


def validate_password(password: str) -> str:
    password = password or ""
    if len(password) < MIN_PASSWORD_LEN:
        return f"Password minimal {MIN_PASSWORD_LEN} karakter."
    if len(password) > MAX_PASSWORD_LEN:
        return f"Password maksimal {MAX_PASSWORD_LEN} karakter."
    if not (re.search(r"[A-Za-z]", password) and re.search(r"\d", password)):
        return "Password harus mengandung huruf dan angka."
    return ""