import os
import time

from dotenv import load_dotenv
from langchain_community.vectorstores import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

load_dotenv()

CHROMA_PATH = os.getenv("CHROMA_PATH", "./chroma_db")
MARKER_FILE = os.path.join(CHROMA_PATH, "embedding_model.txt")


def get_model_name() -> str:
    if os.path.exists(MARKER_FILE):
        with open(MARKER_FILE, "r", encoding="utf-8") as f:
            name = f.read().strip()
        if name:
            return name
    return "all-MiniLM-L6-v2"  # database lama


def inspect_chromadb():
    if not os.path.exists(CHROMA_PATH):
        print(f"Folder database {CHROMA_PATH} tidak ditemukan!")
        return

    model_name = get_model_name()
    print(f"Model embedding: {model_name}")

    t = time.perf_counter()
    embeddings = HuggingFaceEmbeddings(model_name=model_name, model_kwargs={"device": "cpu"})
    vector_store = Chroma(persist_directory=CHROMA_PATH, embedding_function=embeddings)
    print(f"Muat model + koneksi: {time.perf_counter() - t:.2f}s (hanya sekali per proses)")

    collection = vector_store._collection
    count = collection.count()

    print("=== INFORMASI CHROMADB SNOMED CT ===")
    print(f"Total data aktif yang tersimpan: {count}")

    if count > 0:
        sample = collection.peek(limit=3)
        print("\n--- Sampel Data Teratas ---")
        for i, (doc_id, doc, meta) in enumerate(
            zip(sample["ids"], sample["documents"], sample["metadatas"])
        ):
            print(f"\n[Data ke-{i + 1}]")
            print(f"ID       : {doc_id}")
            print(f"Isi      : {doc}")
            print(f"Metadata : {meta}")

        print("\n--- Uji kecepatan pencarian ---")
        for query in ("nyeri dada menjalar ke lengan kiri", "sesak napas saat aktivitas"):
            t = time.perf_counter()
            results = vector_store.similarity_search(query, k=3)
            print(f"\nQuery: {query}  ({(time.perf_counter() - t) * 1000:.0f} ms)")
            for d in results:
                print(f"  - {d.metadata.get('term', d.page_content)} ({d.metadata.get('conceptId', '-')})")
    else:
        print("Database ChromaDB masih kosong.")


if __name__ == "__main__":
    inspect_chromadb()