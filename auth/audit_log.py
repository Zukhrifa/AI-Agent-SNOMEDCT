"""Log aktivitas pengguna (append-only): siapa melakukan apa, kapan, pada pasien mana.
Satu tabel pusat `activity_logs`; ditampilkan di Kelola Akun, Data Pasien, dan panel roomchat.
Isi pesan/data klinis TIDAK disimpan di log, hanya jenis aktivitas dan ringkasan singkat."""
import streamlit as st
from database import _query, _write

ACTIONS = {
    "login": "Login", "login_gagal": "Login gagal", "logout": "Logout",
    "akun_buat": "Buat akun", "akun_reset": "Reset password", "akun_aktif": "Aktifkan akun",
    "akun_nonaktif": "Nonaktifkan akun", "password_ganti": "Ganti password",
    "pasien_buat": "Tambah pasien", "pasien_lihat": "Buka data pasien",
    "identitas_ubah": "Ubah identitas", "keluhan_tambah": "Tambah keluhan utama",
    "keluhan_hapus": "Hapus keluhan utama", "anamnesis_ubah": "Ubah anamnesis",
    "fisik_ubah": "Ubah pemeriksaan fisik", "penunjang_tambah": "Tambah data penunjang",
    "penunjang_hapus": "Hapus data penunjang", "temuan_hapus": "Hapus temuan SNOMED",
    "roomchat_buka": "Buka roomchat", "roomchat_mulai": "Mulai roomchat",
    "chat_clear": "Bersihkan chat", "sesi_hapus": "Hapus sesi chat",
    "ai_tanya": "Kirim pesan ke AI", "ai_jawab": "AI menjawab", "ai_error": "AI gagal menjawab",
    "ai_setuju": "Setujui hasil AI", "ai_tolak": "Tolak hasil AI",
}
_COLS = ("id", "user_id", "username", "full_name", "role", "action", "mrn", "detail", "created_at")
def init_table() -> None:
    from database import _NOW
    _write([
        (f"""CREATE TABLE IF NOT EXISTS activity_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER, username TEXT NOT NULL DEFAULT '', full_name TEXT NOT NULL DEFAULT '',
            role TEXT NOT NULL DEFAULT '', action TEXT NOT NULL, mrn TEXT, detail TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT ({_NOW}))""", ()),
        ("CREATE INDEX IF NOT EXISTS idx_log_mrn ON activity_logs(mrn)", ()),
        ("CREATE INDEX IF NOT EXISTS idx_log_user ON activity_logs(user_id)", ()),
    ])
def log(action: str, mrn: str = None, detail: str = "", user: dict = None) -> None:
    """Catat aktivitas. Pengguna diambil dari sesi login (atau `user` bila diberikan).
    Tidak pernah melempar error agar tidak mengganggu fitur utama."""
    user = user or st.session_state.get("auth_user")
    if not user:
        return
    try:
        _write([(
            "INSERT INTO activity_logs (user_id, username, full_name, role, action, mrn, detail) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user["id"], user["username"], user.get("full_name") or "", user["role"],
             action, mrn, (detail or "")[:300]),
        )])
    except Exception as e:
        print(f"[audit] gagal mencatat {action}: {e}")
def log_once(action: str, mrn: str = None, detail: str = "") -> None:
    """Catat sekali per sesi login untuk (aktivitas, MRN) yang sama, agar rerun tidak membanjiri log."""
    seen = st.session_state.setdefault("_audit_seen", set())
    if (action, mrn) not in seen:
        seen.add((action, mrn))
        log(action, mrn, detail)
def list_logs(mrn: str = None, user_id: int = None, limit: int = 100) -> list:
    where, params = [], []
    if mrn:
        where.append("mrn = ?"); params.append(mrn)
    if user_id:
        where.append("user_id = ?"); params.append(int(user_id))
    sql = ("SELECT " + ", ".join(_COLS) + " FROM activity_logs"
           + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY id DESC LIMIT ?")
    return [dict(zip(_COLS, r)) for r in _query(sql, (*params, int(limit)))]
def table_rows(logs: list, with_mrn: bool = True) -> list:
    """Baris siap tampil untuk st.dataframe."""
    rows = []
    for l in logs:
        row = {
            "Waktu (WIB)": l["created_at"],
            "Pengguna": f"{l['full_name'] or l['username']} (@{l['username']})",
            "Aktivitas": ACTIONS.get(l["action"], l["action"]),
        }
        if with_mrn:
            row["MRN"] = l["mrn"] or "-"
        row["Detail"] = l["detail"] or "-"
        rows.append(row)
    return rows