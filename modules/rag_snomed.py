import os

import streamlit as st
from dotenv import load_dotenv
from langchain_community.vectorstores import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

load_dotenv()

CHROMA_PATH = os.getenv("CHROMA_PATH", "./chroma_db")
LEGACY_EMBEDDING_MODEL = "all-MiniLM-L6-v2"
MARKER_FILE = os.path.join(CHROMA_PATH, "embedding_model.txt")


def resolve_embedding_model() -> str:
    """Pakai model yang sama persis dengan saat ingest (dicatat oleh ingest_chroma.py).
    Jika tidak ada catatan (database lama), pakai model lama."""
    if os.path.exists(MARKER_FILE):
        with open(MARKER_FILE, "r", encoding="utf-8") as f:
            name = f.read().strip()
        if name:
            return name
    return LEGACY_EMBEDDING_MODEL


@st.cache_resource(show_spinner=False)
def get_cached_vectorstore():
    """Model embedding + koneksi ChromaDB dimuat SEKALI per proses server."""
    embeddings = HuggingFaceEmbeddings(
        model_name=resolve_embedding_model(),
        model_kwargs={"device": "cpu"},
    )
    return Chroma(persist_directory=CHROMA_PATH, embedding_function=embeddings)


@st.cache_resource(show_spinner=False)
def warmup() -> bool:
    """Panggil saat aplikasi dibuka agar pesan pertama pasien tidak menanggung load model."""
    get_cached_vectorstore().similarity_search("chest pain", k=1)
    return True


def _format_doc(doc) -> str:
    meta = doc.metadata or {}
    term = meta.get("term")
    concept_id = meta.get("conceptId")
    if term and concept_id:
        return f"- {term} (SNOMED CT ID: {concept_id})"
    return f"- {doc.page_content}"  # format database lama


@st.cache_data(show_spinner=False, max_entries=512)
def get_snomed_context(query: str, k: int = 3) -> str:
    """Cari istilah SNOMED CT terdekat. Hasil di-cache untuk query yang sama."""
    query = " ".join(query.split())[:300]
    if not query:
        return ""
    docs = get_cached_vectorstore().similarity_search(query, k=k)
    return "\n".join(_format_doc(d) for d in docs)