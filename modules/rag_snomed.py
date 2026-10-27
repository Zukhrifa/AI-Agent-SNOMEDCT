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


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).split())


# ---------------------------------------------------------------------------
# Indeks teks (pencarian kata, tidak bergantung pada indeks vektor)
# ---------------------------------------------------------------------------
@st.cache_resource(show_spinner=False)
def get_term_index() -> list:
    """Daftar seluruh istilah (sudah bersih dari sampah) untuk pencarian teks."""
    collection = get_cached_vectorstore()._collection
    data = collection.get(include=["documents", "metadatas"])

    entries, seen = [], set()
    for doc, meta in zip(data.get("documents") or [], data.get("metadatas") or []):
        meta = meta or {}
        concept_id = str(meta.get("conceptId", "")).strip()
        term = meta.get("term") or _legacy_term(doc)
        if is_junk(concept_id, term):
            continue
        norm = _norm(term)
        key = (concept_id, norm)
        if not norm or key in seen:
            continue
        seen.add(key)
        entries.append({"conceptId": concept_id, "term": term, "norm": norm, "tokens": norm.split()})
    return entries


@st.cache_resource(show_spinner=False)
def warmup() -> bool:
    """Panggil saat aplikasi dibuka agar pesan pertama pasien tidak menanggung load model."""
    get_cached_vectorstore().similarity_search("chest pain", k=1)
    try:
        get_term_index()
    except Exception as e:
        print(f"[rag] indeks teks gagal dibuat: {e}")
    return True


def lexical_search(query: str, k: int = 8) -> list:
    """Cari istilah yang memuat semua kata query (kata boleh baru awalan). Case-insensitive."""
    q = _norm(query)
    q_tokens = q.split()
    if not q_tokens:
        return []

    scored = []
    for entry in get_term_index():
        norm = entry["norm"]
        if not all(qt in norm for qt in q_tokens):
            continue
        tokens = entry["tokens"]
        if not all(any(t.startswith(qt) for t in tokens) for qt in q_tokens):
            continue
        rank = 0 if norm == q else (1 if norm.startswith(q) else 2)
        scored.append((rank, len(norm), entry))

    scored.sort(key=lambda item: (item[0], item[1]))

    results, seen = [], set()
    for _, _, entry in scored:
        if entry["conceptId"] in seen:
            continue
        seen.add(entry["conceptId"])
        results.append({"conceptId": entry["conceptId"], "term": entry["term"]})
        if len(results) >= k:
            break
    return results


# ---------------------------------------------------------------------------
# Pencarian semantik (vektor)
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner=False, max_entries=1024)
def search_candidates(query: str, k: int = 3) -> list:
    """Cari konsep SNOMED CT terdekat secara semantik. Return: [{'conceptId': ..., 'term': ...}]"""
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


def search_terms(query: str, k: int = 8) -> list:
    """Pencarian hybrid: kecocokan kata lebih dulu, lalu hasil semantik. Tanpa duplikat konsep."""
    results, seen = [], set()

    try:
        lexical = lexical_search(query, k)
    except Exception as e:
        print(f"[rag] pencarian teks gagal: {e}")
        lexical = []

    try:
        semantic = search_candidates(query, k)
    except Exception as e:
        print(f"[rag] pencarian semantik gagal: {e}")
        semantic = []

    for hit in lexical + semantic:
        if hit["conceptId"] in seen:
            continue
        seen.add(hit["conceptId"])
        results.append(hit)
    return results[:k]


def index_stats() -> dict:
    """Info ringkas untuk diagnostik jika pencarian kosong."""
    vectorstore = get_cached_vectorstore()
    try:
        documents = vectorstore._collection.count()
    except Exception:
        documents = -1
    try:
        terms = len(get_term_index())
    except Exception:
        terms = -1
    return {
        "documents": documents,
        "terms": terms,
        "model": resolve_embedding_model(),
        "path": os.path.abspath(CHROMA_PATH),
    }