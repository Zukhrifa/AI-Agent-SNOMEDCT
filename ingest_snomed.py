import pandas as pd
from langchain_community.vectorstores import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.documents import Document
import os

print("Membaca dataset SNOMED CT...")
# 1. Baca dataset CSV subset kardiologi dengan pemisah titik koma (;)
df = pd.read_csv("snomed_cardio_subset2.csv", sep=";")

print(f"Total baris data ditemukan: {len(df)}")

# 2. Ubah baris CSV menjadi objek Document LangChain
documents = []
for index, row in df.iterrows():
    term = row.get('term', '')
    concept_id = row.get('conceptId', '')
    
    if pd.notna(term):
        text_content = f"Terminologi Medis: {term}, Concept ID: {concept_id}"
        
        metadata = {
            "id": str(row.get("id", "")),
            "conceptId": str(concept_id),
            "effectiveTime": str(row.get("effectiveTime", "")),
            "active": int(row.get("active", 1)),
            "languageCode": str(row.get("languageCode", "en")),
            "typeId": str(row.get("typeId", ""))
        }
        documents.append(Document(page_content=text_content, metadata=metadata))

print("Membuat embeddings menggunakan HuggingFace dan menyimpan ke ChromaDB...")

# 3. Menggunakan model HuggingFace lokal (tidak perlu API Key Google untuk embedding)
embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")

# 4. Simpan ke ChromaDB lokal di folder './chroma_db'
vectorstore = Chroma.from_documents(
    documents=documents,
    embedding=embeddings,
    persist_directory="./chroma_db"
)

print("Data SNOMED CT berhasil diolah dan disimpan ke ChromaDB lokal.")