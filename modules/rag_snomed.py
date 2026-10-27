import os
import re

import streamlit as st
from dotenv import load_dotenv
from langchain_community.vectorstores import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

load_dotenv()

CHROMA_PATH = os.getenv("CHROMA_PATH", "./chroma_db")
LEGACY_EMBEDDING_MODEL = "all-MiniLM-L6-v2"
MARKER_FILE = os.path.join(CHROMA_PATH, "embedding_model.txt")

# Term yang hanya berisi angka / notasi ilmiah (mis. "9E+17") adalah sisa kerusakan CSV
NUMERIC_TERM_RE = re.compile(r"[\d.]+(?:e[+-]?\d+)?", re.IGNORECASE)
# ID berawalan 90000000... adalah konsep metadata SNOMED (modul, tipe, dst.), bukan konsep klinis
METADATA_ID_PREFIX = "90000000"


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


def _legacy_term(content: str) -> str:
    """Database lama menyimpan 'Terminologi Medis: X, Concept ID: Y' sebagai isi dokumen."""
    term = re.sub(r"^Terminologi Medis:\s*", "", content or "")
    term = re.sub(r",\s*Concept ID:.*$", "", term)
    return term.strip()


def is_junk(concept_id: str, term: str) -> bool:
    """True untuk entri rusak/metadata yang tidak boleh dipakai sebagai kode klinis."""
    term = (term or "").strip()
    concept_id = (concept_id or "").strip()
    if not term or not concept_id:
        return True
    if NUMERIC_TERM_RE.fullmatch(term):
        return True
    if concept_id.startswith(METADATA_ID_PREFIX):
        return True
    return False


@st.cache_data(show_spinner=False, max_entries=1024)
def search_candidates(query: str, k: int = 3) -> list:
    """Cari konsep SNOMED CT terdekat. Return: [{'conceptId': ..., 'term': ...}]"""
    query = " ".join(query.split())[:300]
    if not query:
        return []

    # Ambil lebih banyak lalu saring, supaya entri sampah tidak menghabiskan jatah k
    docs = get_cached_vectorstore().similarity_search(query, k=k * 4)

    results, seen = [], set()
    for d in docs:
        meta = d.metadata or {}
        concept_id = str(meta.get("conceptId", "")).strip()
        term = meta.get("term") or _legacy_term(d.page_content)

        if is_junk(concept_id, term) or concept_id in seen:
            continue
        seen.add(concept_id)
        results.append({"conceptId": concept_id, "term": term})
        if len(results) >= k:
            break
    return results


@st.cache_data(show_spinner=False, max_entries=2048)
def lookup_term(concept_id: str) -> str:
    """Validasi kode: kembalikan istilah jika conceptId benar-benar ada di database
    DAN bukan entri sampah/metadata. Jika tidak, kembalikan ''."""
    cid = re.sub(r"\D", "", str(concept_id))
    if not cid:
        return ""

    res = get_cached_vectorstore()._collection.get(
        where={"conceptId": cid},
        limit=1,
        include=["metadatas", "documents"],
    )
    metas = res.get("metadatas") or []
    docs = res.get("documents") or []
    if not metas and not docs:
        return ""

    meta = metas[0] if metas else {}
    term = meta.get("term") or _legacy_term(docs[0] if docs else "")
    return "" if is_junk(cid, term) else term