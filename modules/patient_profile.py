"""Riwayat tetap pasien (jarang berubah): penyakit dahulu, keluarga, alergi, obat rutin, kebiasaan.
Disimpan per pasien (tabel patient_profile), bukan per kunjungan. Riwayat penyakit sekarang
tetap milik kunjungan. Pasien yang belum punya profil terisi sementara dari kunjungan terakhirnya."""
import json

from database import _NOW, _query, _write, patient_mrn_of

FIELDS = [
    ("rpd", "Riwayat penyakit dahulu"),
    ("rpk", "Riwayat penyakit keluarga"),
    ("alergi", "Alergi"),
    ("obat", "Obat rutin"),
    ("kebiasaan", "Kebiasaan (merokok, alkohol, aktivitas fisik)"),
]
_KEYS = tuple(k for k, _ in FIELDS)
_READY = False


def _init():
    global _READY
    if _READY:
        return
    _write([(
        "CREATE TABLE IF NOT EXISTS patient_profile ("
        "mrn TEXT PRIMARY KEY, data TEXT NOT NULL DEFAULT '{}', "
        f"updated_by TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL DEFAULT ({_NOW}))", (),
    )])
    _READY = True


def _clean(data) -> dict:
    data = data if isinstance(data, dict) else {}
    return {k: str(data.get(k) or "").strip() for k in _KEYS}


def _load(raw) -> dict:
    try:
        return _clean(json.loads(raw or "{}"))
    except ValueError:
        return _clean({})


def has_data(profile: dict) -> bool:
    return any(profile.get(k) for k in _KEYS)


def get_profile(key: str) -> dict:
    """key = MRN atau nomor kunjungan. Return isian + saved/updated_by/updated_at."""
    _init()
    mrn = patient_mrn_of(key)
    meta = {"saved": False, "updated_by": "", "updated_at": ""}
    rows = _query("SELECT data, updated_by, updated_at FROM patient_profile WHERE mrn = ?", (mrn,))
    if rows:
        return {**_load(rows[0][0]), "saved": True, "updated_by": rows[0][1], "updated_at": rows[0][2]}
    # Belum pernah disimpan: pakai isian kunjungan terbaru (data lama) bila ada.
    for (raw,) in _query("SELECT anamnesis FROM visits WHERE mrn = ? ORDER BY visit_date DESC, created_at DESC", (mrn,)):
        old = _load(raw)
        if has_data(old):
            return {**old, **meta}
    return {**_clean({}), **meta}


def save_profile(key: str, data: dict, updated_by: str = "") -> None:
    _init()
    mrn = patient_mrn_of(key)
    _write([
        ("INSERT OR IGNORE INTO patient_profile (mrn, data) VALUES (?, '{}')", (mrn,)),
        (f"UPDATE patient_profile SET data = ?, updated_by = ?, updated_at = {_NOW} WHERE mrn = ?",
         (json.dumps(_clean(data), ensure_ascii=False), updated_by, mrn)),
    ])


def allergy_map() -> dict:
    """{mrn: alergi} untuk profil yang sudah disimpan (dipakai daftar pasien)."""
    _init()
    return {r[0]: _load(r[1])["alergi"] for r in _query("SELECT mrn, data FROM patient_profile")}