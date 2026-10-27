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


init_db()