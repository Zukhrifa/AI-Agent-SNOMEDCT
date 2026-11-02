import os
import pandas as pd
import chromadb

def update_snomed_vector_store():
    # 1. Hubungkan ke ChromaDB lokal yang sudah ada
    CHROMA_PATH = "chroma_db"
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    
    # Ambil atau buat koleksi yang sama
    collection = client.get_or_create_collection("snomed_cardio")
    
    # 2. Baca file CSV terbaru yang sudah mencakup klinis umum
    csv_file = "snomed_cardio_umum_full.csv"
    if not os.path.exists(csv_file):
        print(f"File {csv_file} tidak ditemukan!")
        return

    df = pd.read_csv(csv_file, dtype=str)
    df = df[['conceptId', 'term']].dropna().drop_duplicates()
    
    # 3. Ambil daftar ID yang sudah ada di dalam ChromaDB saat ini agar tidak duplikat
    existing_data = collection.get()
    existing_ids = set(existing_data['ids']) if existing_data and 'ids' in existing_data else set()
    
    documents_to_add = []
    metadatas_to_add = []
    ids_to_add = []
    
    # 4. Filter data: Hanya masukkan yang ID-nya BELUM ada di ChromaDB
    for index, row in df.iterrows():
        concept_id = str(row['conceptId'])
        term = str(row['term'])
        unique_id = f"snomed_{concept_id}_{index}"  # Buat ID unik berbasis conceptId
        
        if unique_id not in existing_ids:
            documents_to_add.append(term)
            metadatas_to_add.append({"conceptId": concept_id, "term": term})
            ids_to_add.append(unique_id)
            
    # 5. Masukkan data baru secara batch (jika ada data baru)
    if documents_to_add:
        batch_size = 5000
        for i in range(0, len(documents_to_add), batch_size):
            collection.add(
                documents=documents_to_add[i:i+batch_size],
                metadatas=metadatas_to_add[i:i+batch_size],
                ids=ids_to_add[i:i+batch_size]
            )
        print(f"Berhasil menambahkan {len(documents_to_add)} istilah baru (klinis umum) ke ChromaDB tanpa duplikasi!")
    else:
        print("Tidak ada data baru yang perlu ditambahkan. Semua sudah termuat.")

if __name__ == "__main__":
    update_snomed_vector_store()