import os
import re
import shutil

import pandas as pd
from dotenv import load_dotenv
from langchain_community.vectorstores import Chroma
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings

load_dotenv()

CSV_PATH = "snomed_cardio_subset2.csv"
CHROMA_PATH = os.getenv("CHROMA_PATH", "./chroma_db")
# Model multibahasa: pasien mengetik Indonesia, istilah SNOMED berbahasa Inggris
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "paraphrase-multilingual-MiniLM-L12-v2")
BATCH_SIZE = 500

SEMANTIC_TAG = re.compile(r"\s*\([a-z][a-z /\-]*\)\s*$")  # "(disorder)", "(finding)", dst.

print("Membaca dataset SNOMED CT...")
df = pd.read_csv(CSV_PATH, sep=";", dtype=str)
print(f"Total baris mentah: {len(df)}")

extra_cols = [c for c in df.columns if c.startswith("Unnamed")]


def recover(row):
    """Sebagian baris bergeser kolom (typeId == 'en'): conceptId ada di kolom languageCode,
    term tersebar di kolom 'Unnamed' sampai penanda 9E+17."""
    if row.get("typeId") == "en":
        parts = []
        for col in extra_cols:
            v = row.get(col)
            if pd.isna(v) or str(v).strip() == "9E+17":
                break
            parts.append(str(v).strip())
        return row.get("languageCode"), "; ".join(parts)
    return row.get("conceptId"), row.get("term")


documents = []
seen = set()
skipped = 0

for row in df.to_dict("records"):
    if row.get("active") != "1":
        skipped += 1
        continue

    concept_id, term = recover(row)
    concept_id = str(concept_id).strip() if concept_id is not None else ""
    term = str(term).strip() if term is not None and not pd.isna(term) else ""

    if not re.fullmatch(r"\d{5,18}", concept_id) or not term:
        skipped += 1
        continue

    clean = SEMANTIC_TAG.sub("", term).strip()
    key = (concept_id, clean.lower())
    if not clean or key in seen:
        skipped += 1
        continue
    seen.add(key)

    # Yang di-embed hanya istilahnya; ID konsep disimpan di metadata
    documents.append(
        Document(page_content=clean, metadata={"conceptId": concept_id, "term": clean})
    )

print(f"Dokumen unik & aktif: {len(documents)} | dilewati (nonaktif/rusak/duplikat): {skipped}")

if os.path.exists(CHROMA_PATH):
    print(f"Menghapus database lama di {CHROMA_PATH} ...")
    try:
        shutil.rmtree(CHROMA_PATH)
    except PermissionError:
        raise SystemExit("Gagal menghapus chroma_db. Hentikan aplikasi Streamlit dulu, lalu ulangi.")

print(f"Memuat model embedding: {EMBEDDING_MODEL} (pertama kali akan mengunduh model)...")
embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL, model_kwargs={"device": "cpu"})

vectorstore = Chroma(persist_directory=CHROMA_PATH, embedding_function=embeddings)

total = len(documents)
for start in range(0, total, BATCH_SIZE):
    batch = documents[start:start + BATCH_SIZE]
    vectorstore.add_documents(batch)
    print(f"  tersimpan {min(start + BATCH_SIZE, total)}/{total}")

# Catat model yang dipakai agar aplikasi selalu memakai model yang sama saat mencari
with open(os.path.join(CHROMA_PATH, "embedding_model.txt"), "w", encoding="utf-8") as f:
    f.write(EMBEDDING_MODEL)

print("Data SNOMED CT berhasil diolah dan disimpan ke ChromaDB lokal.")

print("\nUji cepat: 'nyeri dada menjalar ke lengan kiri'")
for d in vectorstore.similarity_search("nyeri dada menjalar ke lengan kiri", k=3):
    print(f"  - {d.metadata.get('term')} ({d.metadata.get('conceptId')})")