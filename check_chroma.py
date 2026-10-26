import os
from langchain_community.vectorstores import Chroma
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from dotenv import load_dotenv

load_dotenv()

# Sesuaikan path direktori chroma_db Anda jika berbeda
CHROMA_PATH = "./chroma_db"

def inspect_chromadb():
    if not os.path.exists(CHROMA_PATH):
        print(f"Folder database {CHROMA_PATH} tidak ditemukan!")
        return

    # Inisialisasi embeddings (pastikan menggunakan model yang sama saat membuat database)
    embeddings = GoogleGenerativeAIEmbeddings(model="models/embedding-001")
    
    # Load ChromaDB yang sudah ada
    vector_store = Chroma(
        persist_directory=CHROMA_PATH, 
        embedding_function=embeddings
    )
    
    # Ambil data koleksi di dalamnya
    collection = vector_store._collection
    count = collection.count()
    
    print(f"=== INFORMASI CHROMADB SNOMED CT ===")
    print(f"Total data (chunks) aktif yang tersimpan: {count}")

    # Ambil beberapa sampel data pertama untuk melihat isinya
    if count > 0:
        sample = collection.peek(limit=3)
        print("\n--- Sampel Data Teratas ---")
        for i, (doc_id, doc, meta) in enumerate(zip(sample['ids'], sample['documents'], sample['metadatas'])):
            print(f"\n[Data ke-{i+1}]")
            print(f"ID     : {doc_id}")
            print(f"Isi    : {doc}")
            print(f"Metadata (Active/Lainnya): {meta}")
    else:
        print("Database ChromaDB masih kosong.")

if __name__ == "__main__":
    inspect_chromadb()