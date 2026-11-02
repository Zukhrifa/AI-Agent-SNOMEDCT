import hashlib
import os

import pandas as pd
from langchain_community.vectorstores import Chroma
from langchain_huggingface import HuggingFaceEmbeddings


def update_snomed_vector_store():
    CHROMA_PATH = "chroma_db"
    CSV_MASTER_FILE = "snomed_cardio_umum_full.csv"

    if not os.path.exists(CSV_MASTER_FILE):
        print(f"File {CSV_MASTER_FILE} tidak ditemukan!")
        return

    df = pd.read_csv(CSV_MASTER_FILE, dtype=str)
    if "active" in df.columns:
        df = df[df["active"].astype(str).str.strip() == "1"]
    df = df[["conceptId", "term"]].dropna().drop_duplicates()

    embeddings = HuggingFaceEmbeddings(
        model_name="all-MiniLM-L6-v2", model_kwargs={"device": "cpu"}
    )
    vectorstore = Chroma(
        persist_directory=CHROMA_PATH,
        embedding_function=embeddings,
        collection_name="snomed_cardio",
    )

    texts = df["term"].tolist()
    cids = df["conceptId"].tolist()
    metadatas = [{"conceptId": str(c), "term": str(t)} for c, t in zip(cids, texts)]
    # ID tetap -> menjalankan ulang TIDAK menggandakan data (upsert)
    ids = [f"{c}_{hashlib.md5(t.encode()).hexdigest()[:10]}" for c, t in zip(cids, texts)]

    total = len(texts)
    for i in range(0, total, 5000):
        e = min(i + 5000, total)
        vectorstore.add_texts(texts=texts[i:e], metadatas=metadatas[i:e], ids=ids[i:e])
        print(f"Progress: {e}/{total}")
    print(f"SELESAI. Jumlah dokumen di koleksi: {vectorstore._collection.count()} (harus = {total})")


if __name__ == "__main__":
    update_snomed_vector_store()