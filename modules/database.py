import sqlite3
import os

DB_FILE = "anamnesis_local.db"

def init_db():
    """
    Menginisialisasi database SQLite dan membuat tabel yang diperlukan 
    jika belum tersedia.
    """
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Tabel untuk menyimpan data sesi pasien dan hasil anamnesis
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS consultations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_name TEXT NOT NULL,
            medical_record_no TEXT NOT NULL,
            anamnesis_summary TEXT,
            doctor_validation TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()

def save_consultation(patient_name: str, medical_record_no: str, summary: str, validation: str = "Pending"):
    """
    Menyimpan sesi konsultasi anamnesis baru ke database.
    """
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO consultations (patient_name, medical_record_no, anamnesis_summary, doctor_validation)
        VALUES (?, ?, ?, ?)
    ''', (patient_name, medical_record_no, summary, validation))
    
    conn.commit()
    conn.close()

def get_all_consultations():
    """
    Mengambil seluruh riwayat konsultasi pasien untuk ditampilkan di sidebar Streamlit.
    """
    if not os.path.exists(DB_FILE):
        return []
        
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT id, patient_name, medical_record_no, created_at, doctor_validation 
        FROM consultations 
        ORDER BY created_at DESC
    ''')
    rows = cursor.fetchall()
    conn.close()
    return rows

# Inisialisasi otomatis saat modul dipanggil
init_db()