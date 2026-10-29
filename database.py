import base64
import json
import os
import sqlite3
import time
from contextlib import closing
from datetime import date

import requests
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Konfigurasi backend
#   - Jika TURSO_DATABASE_URL dan TURSO_AUTH_TOKEN terisi -> data disimpan di Turso (cloud)
#   - Jika tidak -> memakai file SQLite lokal (cocok untuk development)
# ---------------------------------------------------------------------------
DB_FILE = "anamnesis_local.db"
TURSO_TIMEOUT = 20          # detik
READ_CACHE_TTL = 20         # detik; cache bacaan hanya untuk mode Turso (mengurangi bolak-balik jaringan)

# Waktu tulis memakai WIB (UTC+7), sama di komputer lokal maupun server hosting (biasanya UTC)
_NOW = "datetime('now','+7 hours')"


def _get_secret(name: str) -> str:
    """Baca dari st.secrets (hosting) dulu, lalu environment/.env."""
    try:
        import streamlit as st
        value = st.secrets.get(name, "")
        if value:
            return str(value)
    except Exception:
        pass
    return os.getenv(name, "")


TURSO_URL = _get_secret("TURSO_DATABASE_URL").strip()
TURSO_TOKEN = _get_secret("TURSO_AUTH_TOKEN").strip()
USE_TURSO = bool(TURSO_URL and TURSO_TOKEN)

JSON_FIELDS = {
    "chief_complaints": list,
    "anamnesis": dict,
    "physical_exam": dict,
    "confirmed_findings": list,
}
PLAIN_FIELDS = ("name", "birth_date", "sex")
_PATIENT_COLS = (
    "mrn", "name", "birth_date", "sex", "chief_complaints", "anamnesis",
    "physical_exam", "confirmed_findings", "created_at", "updated_at",
)


# ---------------------------------------------------------------------------
# Lapisan akses data (satu antarmuka untuk dua backend)
# ---------------------------------------------------------------------------
_session = requests.Session()
_READ_CACHE = {}


def _pipeline_url(url: str) -> str:
    url = url.strip().rstrip("/")
    for prefix in ("libsql://", "wss://", "ws://"):
        if url.startswith(prefix):
            url = "https://" + url[len(prefix):]
            break
    if not url.endswith("/v2/pipeline"):
        url += "/v2/pipeline"
    return url


def _encode_arg(value) -> dict:
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "integer", "value": str(int(value))}
    if isinstance(value, int):
        return {"type": "integer", "value": str(value)}
    if isinstance(value, float):
        return {"type": "float", "value": value}
    if isinstance(value, bytes):
        return {"type": "blob", "base64": base64.b64encode(value).decode("ascii")}
    return {"type": "text", "value": str(value)}


def _decode_cell(cell):
    if not isinstance(cell, dict):
        return cell
    kind = cell.get("type")
    if kind == "null":
        return None
    if kind == "integer":
        return int(cell["value"])
    if kind == "float":
        return float(cell["value"])
    if kind == "blob":
        return base64.b64decode(cell.get("base64", ""))
    return cell.get("value")


def _turso_pipeline(statements: list) -> list:
    """Kirim beberapa pernyataan SQL dalam satu permintaan HTTP. Return: daftar hasil (list of rows)."""
    body = {"requests": []}
    for sql, params in statements:
        stmt = {"sql": sql}
        if params:
            stmt["args"] = [_encode_arg(p) for p in params]
        body["requests"].append({"type": "execute", "stmt": stmt})
    body["requests"].append({"type": "close"})

    try:
        resp = _session.post(
            _pipeline_url(TURSO_URL),
            headers={"Authorization": f"Bearer {TURSO_TOKEN}", "Content-Type": "application/json"},
            json=body,
            timeout=TURSO_TIMEOUT,
        )
    except requests.RequestException as e:
        raise RuntimeError(f"Tidak bisa terhubung ke Turso: {e}") from e

    if resp.status_code != 200:
        raise RuntimeError(f"Turso HTTP {resp.status_code}: {resp.text[:300]}")

    results = resp.json().get("results", [])
    outputs = []
    for item in results[:len(statements)]:
        if item.get("type") == "error":
            message = (item.get("error") or {}).get("message", item)
            raise RuntimeError(f"Turso SQL error: {message}")
        result = (item.get("response") or {}).get("result") or {}
        rows = [tuple(_decode_cell(c) for c in row) for row in result.get("rows", [])]
        outputs.append(rows)
    return outputs


def _sqlite_run(statements: list) -> list:
    """Jalankan pernyataan di SQLite lokal dalam satu transaksi."""
    outputs = []
    with closing(sqlite3.connect(DB_FILE)) as conn:
        with conn:
            for sql, params in statements:
                cur = conn.execute(sql, params)
                outputs.append(cur.fetchall() if cur.description else [])
    return outputs


def _run(statements: list) -> list:
    return _turso_pipeline(statements) if USE_TURSO else _sqlite_run(statements)


def _query(sql: str, params: tuple = ()) -> list:
    """Baca data. Di mode Turso hasilnya di-cache singkat dan dibersihkan setiap ada penulisan."""
    params = tuple(params)
    if not USE_TURSO:
        return _sqlite_run([(sql, params)])[0]

    key = (sql, params)
    hit = _READ_CACHE.get(key)
    if hit and time.time() - hit[0] < READ_CACHE_TTL:
        return hit[1]
    rows = _turso_pipeline([(sql, params)])[0]
    _READ_CACHE[key] = (time.time(), rows)
    return rows


def _write(statements: list):
    _run(statements)
    _READ_CACHE.clear()


# ---------------------------------------------------------------------------
# Skema & migrasi
# ---------------------------------------------------------------------------
_SCHEMA = [
    (sql, ()) for sql in (
        '''
        CREATE TABLE IF NOT EXISTS consultations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_name TEXT NOT NULL,
            medical_record_no TEXT NOT NULL,
            messages TEXT,
            quick_actions TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''',
        f'''
        CREATE TABLE IF NOT EXISTS patients (
            mrn TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            birth_date TEXT,
            sex TEXT,
            chief_complaints TEXT,
            anamnesis TEXT,
            physical_exam TEXT,
            confirmed_findings TEXT,
            created_at TIMESTAMP DEFAULT ({_NOW}),
            updated_at TIMESTAMP DEFAULT ({_NOW})
        )
        ''',
        f'''
        CREATE TABLE IF NOT EXISTS patient_supporting (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mrn TEXT NOT NULL,
            category TEXT NOT NULL,
            recorded_on TEXT,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT ({_NOW})
        )
        ''',
        f'''
        CREATE TABLE IF NOT EXISTS anamnesis_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mrn TEXT NOT NULL,
            summary TEXT NOT NULL,
            codes TEXT,
            approved INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT ({_NOW})
        )
        ''',
    )
]


def _add_column_if_missing(table: str, column: str, ddl: str):
    """Migrasi database lama: tambah kolom; abaikan jika kolom sudah ada."""
    try:
        _run([(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}", ())])
    except Exception as e:
        if "duplicate column" not in str(e).lower():
            raise


def init_db():
    _write(_SCHEMA)
    _add_column_if_missing("patients", "confirmed_findings", "TEXT")
    _add_column_if_missing("anamnesis_results", "approved", "INTEGER DEFAULT 0")
    _write([
        ("CREATE INDEX IF NOT EXISTS idx_consult_mrn ON consultations(medical_record_no)", ()),
        ("CREATE INDEX IF NOT EXISTS idx_supporting_mrn ON patient_supporting(mrn)", ()),
        ("CREATE INDEX IF NOT EXISTS idx_results_mrn ON anamnesis_results(mrn)", ()),
        # Pasien dari roomchat lama dimasukkan ke tabel patients
        (
            "INSERT OR IGNORE INTO patients (mrn, name) "
            "SELECT medical_record_no, patient_name FROM consultations",
            (),
        ),
    ])


def backend_info() -> dict:
    if USE_TURSO:
        return {"backend": "Turso", "target": _pipeline_url(TURSO_URL)}
    return {"backend": "SQLite lokal", "target": os.path.abspath(DB_FILE)}


def table_counts() -> dict:
    counts = {}
    for table in ("consultations", "patients", "patient_supporting", "anamnesis_results"):
        counts[table] = _query(f"SELECT COUNT(*) FROM {table}")[0][0]
    return counts


# ---------------------------------------------------------------------------
# Roomchat (consultations)
# ---------------------------------------------------------------------------
def save_or_update_consultation(patient_name: str, medical_record_no: str, messages: list, quick_actions: list):
    messages_json = json.dumps(messages, ensure_ascii=False)
    actions_json = json.dumps(quick_actions, ensure_ascii=False)

    _write([
        (
            "UPDATE consultations SET patient_name = ?, messages = ?, quick_actions = ? "
            "WHERE medical_record_no = ?",
            (patient_name, messages_json, actions_json, medical_record_no),
        ),
        (
            "INSERT INTO consultations (patient_name, medical_record_no, messages, quick_actions) "
            "SELECT ?, ?, ?, ? WHERE NOT EXISTS "
            "(SELECT 1 FROM consultations WHERE medical_record_no = ?)",
            (patient_name, medical_record_no, messages_json, actions_json, medical_record_no),
        ),
    ])


def get_all_consultations():
    if not USE_TURSO and not os.path.exists(DB_FILE):
        return []

    rows = _query('''
        SELECT id, patient_name, medical_record_no, messages, quick_actions, created_at
        FROM consultations
        ORDER BY created_at DESC, id DESC
    ''')

    consultations = []
    for r in rows:
        consultations.append({
            "id": r[0],
            "name": r[1],
            "mrn": r[2],
            "messages": json.loads(r[3]) if r[3] else [],
            "quick_actions": json.loads(r[4]) if r[4] else [],
            "created_at": r[5],
        })
    return consultations


def delete_consultation(mrn):
    """Hanya menghapus roomchat. Data pasien & hasil anamnesis tetap tersimpan."""
    _write([("DELETE FROM consultations WHERE medical_record_no = ?", (mrn,))])


def update_patient_name(mrn, new_name):
    _write([
        ("UPDATE consultations SET patient_name = ? WHERE medical_record_no = ?", (new_name, mrn)),
        ("INSERT OR IGNORE INTO patients (mrn, name) VALUES (?, ?)", (mrn, new_name)),
        (f"UPDATE patients SET name = ?, updated_at = {_NOW} WHERE mrn = ?", (new_name, mrn)),
    ])


# ---------------------------------------------------------------------------
# Data pasien
# ---------------------------------------------------------------------------
def _decode_patient(row) -> dict:
    data = dict(zip(_PATIENT_COLS, row))
    for field, typ in JSON_FIELDS.items():
        try:
            value = json.loads(data[field]) if data[field] else typ()
        except Exception:
            value = typ()
        data[field] = value if isinstance(value, typ) else typ()
    return data


def ensure_patient(mrn: str, name: str):
    """Buat pasien jika belum ada; jika sudah ada, perbarui namanya."""
    _write([(
        f'''
        INSERT INTO patients (mrn, name) VALUES (?, ?)
        ON CONFLICT(mrn) DO UPDATE SET name = excluded.name, updated_at = {_NOW}
        ''',
        (mrn, name),
    )])


def get_patient(mrn: str):
    rows = _query(f"SELECT {', '.join(_PATIENT_COLS)} FROM patients WHERE mrn = ?", (mrn,))
    return _decode_patient(rows[0]) if rows else None


def list_patients() -> list:
    rows = _query(f"SELECT {', '.join(_PATIENT_COLS)} FROM patients ORDER BY name COLLATE NOCASE")
    return [_decode_patient(r) for r in rows]


def update_patient(mrn: str, **fields):
    """Perbarui sebagian kolom pasien. Kolom yang diizinkan: name, birth_date, sex,
    chief_complaints, anamnesis, physical_exam, confirmed_findings."""
    allowed = set(PLAIN_FIELDS) | set(JSON_FIELDS)
    sets, values = [], []
    for key, value in fields.items():
        if key not in allowed:
            continue
        if key in JSON_FIELDS:
            value = json.dumps(value, ensure_ascii=False)
        sets.append(f"{key} = ?")
        values.append(value)
    if not sets:
        return
    sets.append(f"updated_at = {_NOW}")

    _write([
        ("INSERT OR IGNORE INTO patients (mrn, name) VALUES (?, ?)", (mrn, fields.get("name") or mrn)),
        (f"UPDATE patients SET {', '.join(sets)} WHERE mrn = ?", (*values, mrn)),
    ])


# ---------------------------------------------------------------------------
# Data penunjang
# ---------------------------------------------------------------------------
def add_supporting(mrn: str, category: str, content: str, recorded_on: str = None):
    _write([(
        "INSERT INTO patient_supporting (mrn, category, recorded_on, content) VALUES (?, ?, ?, ?)",
        (mrn, category, recorded_on, content),
    )])


def list_supporting(mrn: str) -> list:
    rows = _query(
        '''
        SELECT id, category, recorded_on, content, created_at
        FROM patient_supporting WHERE mrn = ? ORDER BY id DESC
        ''',
        (mrn,),
    )
    return [
        {"id": r[0], "category": r[1], "recorded_on": r[2], "content": r[3], "created_at": r[4]}
        for r in rows
    ]


def delete_supporting(item_id: int):
    _write([("DELETE FROM patient_supporting WHERE id = ?", (item_id,))])


# ---------------------------------------------------------------------------
# Hasil anamnesis AI
# ---------------------------------------------------------------------------
def save_anamnesis_result(mrn: str, summary: str, codes: list, approved: bool = False):
    _write([(
        "INSERT INTO anamnesis_results (mrn, summary, codes, approved) VALUES (?, ?, ?, ?)",
        (mrn, summary, json.dumps(codes or [], ensure_ascii=False), 1 if approved else 0),
    )])


def list_anamnesis_results(mrn: str, limit: int = 20) -> list:
    rows = _query(
        '''
        SELECT id, summary, codes, created_at, approved
        FROM anamnesis_results WHERE mrn = ? ORDER BY id DESC LIMIT ?
        ''',
        (mrn, limit),
    )

    results = []
    for r in rows:
        try:
            codes = json.loads(r[2]) if r[2] else []
        except Exception:
            codes = []
        results.append({
            "id": r[0], "summary": r[1], "codes": codes,
            "created_at": r[3], "approved": bool(r[4]),
        })
    return results


def approve_anamnesis(mrn: str, summary: str, codes: list) -> dict:
    """Dipanggil saat dokter menyatakan hasil AI akurat.
    - Menyimpan kesimpulan (berstatus disetujui) ke anamnesis_results.
    - Gejala ditambahkan ke keluhan utama pasien (tanpa duplikat).
    - Semua temuan ditambahkan/diperbarui di 'temuan terkonfirmasi'.
    Kode berkecocokan 'lemah' tidak disimpan ke data pasien."""
    codes = codes or []
    usable = [c for c in codes if c.get("match") != "lemah"]

    save_anamnesis_result(mrn, summary, codes, approved=True)

    patient = get_patient(mrn)
    if patient is None:
        return {"saved": 0, "complaints": 0, "skipped": len(codes)}

    complaints = list(patient["chief_complaints"])
    complaint_ids = {c.get("conceptId") for c in complaints}
    added = 0
    for c in usable:
        if c.get("kategori") == "gejala" and c["conceptId"] not in complaint_ids:
            complaints.append({"conceptId": c["conceptId"], "term": c["term"]})
            complaint_ids.add(c["conceptId"])
            added += 1

    findings = {f.get("conceptId"): f for f in patient["confirmed_findings"]}
    today = date.today().isoformat()
    for c in usable:
        findings[c["conceptId"]] = {
            "conceptId": c["conceptId"],
            "term": c["term"],
            "kategori": c.get("kategori", "lainnya"),
            "label": c.get("label", c["term"]),
            "confirmed_at": today,
        }

    update_patient(
        mrn,
        chief_complaints=complaints,
        confirmed_findings=list(findings.values()),
    )
    return {"saved": len(usable), "complaints": added, "skipped": len(codes) - len(usable)}


try:
    init_db()
except Exception as _e:  # jangan menjatuhkan aplikasi saat import; error akan muncul lagi saat query
    print(f"[db] inisialisasi database gagal ({backend_info()['backend']}): {_e}")