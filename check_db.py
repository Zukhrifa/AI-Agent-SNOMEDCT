import database as db

info = db.backend_info()
print(f"Backend : {info['backend']}")
print(f"Target  : {info['target']}")

try:
    counts = db.table_counts()
except Exception as e:
    raise SystemExit(f"GAGAL membaca database: {e}")

print("Jumlah baris per tabel:")
for table, count in counts.items():
    print(f"  {table:20s} {count}")
print("Koneksi database OK.")