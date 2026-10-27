import json
import os
import sqlite3
from contextlib import closing

DB_FILE = "anamnesis_local.db"

def _connect():
    return sqlite3.connect(DB_FILE)

def init_db():
    with closing(_connect()) as conn:
        with conn:
            # Tabel konsultasi chat yang sudah ada dari Claude[cite: 45]
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
            
            # TABEL BARU: Profil Klinis & Pemeriksaan Fisik terikat ke No RM (MRN)
            conn.execute('''
                CREATE TABLE IF NOT EXISTS patient_profiles (
                    medical_record_no TEXT PRIMARY KEY,
                    patient_name TEXT NOT NULL,
                    gender TEXT DEFAULT '',
                    age TEXT DEFAULT '',
                    blood_pressure TEXT DEFAULT '',
                    pulse TEXT DEFAULT '',
                    temperature TEXT DEFAULT '',
                    respiration TEXT DEFAULT '',
                    weight TEXT DEFAULT '',
                    height TEXT DEFAULT '',
                    ekg_notes TEXT DEFAULT '',
                    allergies TEXT DEFAULT '',
                    pain_scale TEXT DEFAULT '',
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

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

# --- FUNGSI BARU UNTUK PROFIL KLINIS & PEMERIKSAAN FISIK ---
def save_patient_profile(mrn, name, gender, age, bp, pulse, temp, resp, weight, height, ekg, allergies, pain):
    with closing(_connect()) as conn:
        with conn:
            conn.execute('''
                INSERT INTO patient_profiles 
                (medical_record_no, patient_name, gender, age, blood_pressure, pulse, temperature, respiration, weight, height, ekg_notes, allergies, pain_scale, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(medical_record_no) DO UPDATE SET
                    patient_name = excluded.patient_name,
                    gender = excluded.gender,
                    age = excluded.age,
                    blood_pressure = excluded.blood_pressure,
                    pulse = excluded.pulse,
                    temperature = excluded.temperature,
                    respiration = excluded.respiration,
                    weight = excluded.weight,
                    height = excluded.height,
                    ekg_notes = excluded.ekg_notes,
                    allergies = excluded.allergies,
                    pain_scale = excluded.pain_scale,
                    updated_at = CURRENT_TIMESTAMP
            ''', (mrn, name, gender, age, bp, pulse, temp, resp, weight, height, ekg, allergies, pain))

def get_patient_profile(mrn):
    if not os.path.exists(DB_FILE):
        return None
    with closing(_connect()) as conn:
        row = conn.execute('''
            SELECT gender, age, blood_pressure, pulse, temperature, respiration, weight, height, ekg_notes, allergies, pain_scale
            FROM patient_profiles WHERE medical_record_no = ?
        ''', (mrn,)).fetchone()
        if row:
            return {
                "gender": row[0], "age": row[1], "blood_pressure": row[2],
                "pulse": row[3], "temperature": row[4], "respiration": row[5],
                "weight": row[6], "height": row[7], "ekg_notes": row[8],
                "allergies": row[9], "pain_scale": row[10]
            }
    return None

init_db()