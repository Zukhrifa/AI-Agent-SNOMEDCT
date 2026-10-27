import json
import os
import sqlite3
from contextlib import closing
from datetime import date

DB_FILE = "anamnesis_local.db"

# Kolom JSON pada tabel patients dan tipe datanya
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


def _connect():
    return sqlite3.connect(DB_FILE)


def _ensure_column(conn, table: str, column: str, ddl: str):
    """Tambah kolom jika belum ada (migrasi database lama)."""
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def init_db():
    with closing(_connect()) as conn:
        with conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS consultations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    patient_name TEXT NOT NULL,
                    medical_record_no TEXT NOT NULL,
                    messages TEXT,
                    quick_actions TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS patients (
                    mrn TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    birth_date TEXT,
                    sex TEXT,
                    chief_complaints TEXT,
                    anamnesis TEXT,
                    physical_exam TEXT,
                    confirmed_findings TEXT,
                    created_at TIMESTAMP DEFAULT (datetime('now','localtime')),
                    updated_at TIMESTAMP DEFAULT (datetime('now','localtime'))
                )
            ''')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS patient_supporting (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    mrn TEXT NOT NULL,
                    category TEXT NOT NULL,
                    recorded_on TEXT,
                    content TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT (datetime('now','localtime'))
                )
            ''')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS anamnesis_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    mrn TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    codes TEXT,
                    approved INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT (datetime('now','localtime'))
                )
            ''')

            # Migrasi database lama
            _ensure_column(conn, "patients", "confirmed_findings", "TEXT")
            _ensure_column(conn, "anamnesis_results", "approved", "INTEGER DEFAULT 0")

            conn.execute("CREATE INDEX IF NOT EXISTS idx_supporting_mrn ON patient_supporting(mrn)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_results_mrn ON anamnesis_results(mrn)")

            # Pasien dari roomchat lama dimasukkan ke tabel patients
            conn.execute('''
                INSERT OR IGNORE INTO patients (mrn, name)
                SELECT medical_record_no, patient_name FROM consultations
            ''')


# ---------------------------------------------------------------------------
# Roomchat (consultations)
# ---------------------------------------------------------------------------
def save_or_update_consultation(patient_name: str, medical_record_no: str, messages: list, quick_actions: list):
    messages_json = json.dumps(messages, ensure_ascii=False)
    actions_json = json.dumps(quick_actions, ensure_ascii=False)

    with closing(_connect()) as conn:
        with conn:
            row = conn.execute(
                "SELECT id FROM consultations WHERE medical_record_no = ?",
                (medical_record_no,),
            ).fetchone()

            if row:
                conn.execute(
                    '''
                    UPDATE consultations
                    SET patient_name = ?, messages = ?, quick_actions = ?
                    WHERE medical_record_no = ?
                    ''',
                    (patient_name, messages_json, actions_json, medical_record_no),
                )
            else:
                conn.execute(
                    '''
                    INSERT INTO consultations (patient_name, medical_record_no, messages, quick_actions)
                    VALUES (?, ?, ?, ?)
                    ''',
                    (patient_name, medical_record_no, messages_json, actions_json),
                )


def get_all_consultations():
    if not os.path.exists(DB_FILE):
        return []

    with closing(_connect()) as conn:
        rows = conn.execute('''
            SELECT id, patient_name, medical_record_no, messages, quick_actions, created_at
            FROM consultations
            ORDER BY created_at DESC, id DESC
        ''').fetchall()

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
    with closing(_connect()) as conn:
        with conn:
            conn.execute("DELETE FROM consultations WHERE medical_record_no = ?", (mrn,))


def update_patient_name(mrn, new_name):
    with closing(_connect()) as conn:
        with conn:
            conn.execute(
                "UPDATE consultations SET patient_name = ? WHERE medical_record_no = ?",
                (new_name, mrn),
            )
            conn.execute("INSERT OR IGNORE INTO patients (mrn, name) VALUES (?, ?)", (mrn, new_name))
            conn.execute(
                "UPDATE patients SET name = ?, updated_at = datetime('now','localtime') WHERE mrn = ?",
                (new_name, mrn),
            )


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
    with closing(_connect()) as conn:
        with conn:
            conn.execute(
                '''
                INSERT INTO patients (mrn, name) VALUES (?, ?)
                ON CONFLICT(mrn) DO UPDATE SET
                    name = excluded.name,
                    updated_at = datetime('now','localtime')
                ''',
                (mrn, name),
            )


def get_patient(mrn: str):
    with closing(_connect()) as conn:
        row = conn.execute(
            f"SELECT {', '.join(_PATIENT_COLS)} FROM patients WHERE mrn = ?", (mrn,)
        ).fetchone()
    return _decode_patient(row) if row else None


def list_patients() -> list:
    with closing(_connect()) as conn:
        rows = conn.execute(
            f"SELECT {', '.join(_PATIENT_COLS)} FROM patients ORDER BY name COLLATE NOCASE"
        ).fetchall()
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
    sets.append("updated_at = datetime('now','localtime')")

    with closing(_connect()) as conn:
        with conn:
            conn.execute(
                "INSERT OR IGNORE INTO patients (mrn, name) VALUES (?, ?)",
                (mrn, fields.get("name") or mrn),
            )
            conn.execute(
                f"UPDATE patients SET {', '.join(sets)} WHERE mrn = ?",
                (*values, mrn),
            )


# ---------------------------------------------------------------------------
# Data penunjang
# ---------------------------------------------------------------------------
def add_supporting(mrn: str, category: str, content: str, recorded_on: str = None):
    with closing(_connect()) as conn:
        with conn:
            conn.execute(
                "INSERT INTO patient_supporting (mrn, category, recorded_on, content) VALUES (?, ?, ?, ?)",
                (mrn, category, recorded_on, content),
            )


def list_supporting(mrn: str) -> list:
    with closing(_connect()) as conn:
        rows = conn.execute(
            '''
            SELECT id, category, recorded_on, content, created_at
            FROM patient_supporting WHERE mrn = ? ORDER BY id DESC
            ''',
            (mrn,),
        ).fetchall()
    return [
        {"id": r[0], "category": r[1], "recorded_on": r[2], "content": r[3], "created_at": r[4]}
        for r in rows
    ]


def delete_supporting(item_id: int):
    with closing(_connect()) as conn:
        with conn:
            conn.execute("DELETE FROM patient_supporting WHERE id = ?", (item_id,))


# ---------------------------------------------------------------------------
# Hasil anamnesis AI
# ---------------------------------------------------------------------------
def save_anamnesis_result(mrn: str, summary: str, codes: list, approved: bool = False):
    with closing(_connect()) as conn:
        with conn:
            conn.execute(
                "INSERT INTO anamnesis_results (mrn, summary, codes, approved) VALUES (?, ?, ?, ?)",
                (mrn, summary, json.dumps(codes or [], ensure_ascii=False), 1 if approved else 0),
            )


def list_anamnesis_results(mrn: str, limit: int = 20) -> list:
    with closing(_connect()) as conn:
        rows = conn.execute(
            '''
            SELECT id, summary, codes, created_at, approved
            FROM anamnesis_results WHERE mrn = ? ORDER BY id DESC LIMIT ?
            ''',
            (mrn, limit),
        ).fetchall()

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


init_db()