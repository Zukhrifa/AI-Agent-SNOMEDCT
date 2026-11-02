import os
import re
from bisect import bisect_left
from functools import lru_cache

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from langchain_community.vectorstores import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

load_dotenv()

CHROMA_PATH = os.getenv("CHROMA_PATH", "./chroma_db")
COLLECTION_NAME = "snomed_cardio"
LEGACY_EMBEDDING_MODEL = "all-MiniLM-L6-v2"
MARKER_FILE = os.path.join(CHROMA_PATH, "embedding_model.txt")
CSV_MASTER_FILE = "snomed_cardio_umum_full.csv"

NUMERIC_TERM_RE = re.compile(r"[\d.]+(?:e[+-]?\d+)?", re.IGNORECASE)
METADATA_ID_PREFIX = "90000000"


def resolve_embedding_model() -> str:
    if os.path.exists(MARKER_FILE):
        with open(MARKER_FILE, "r", encoding="utf-8") as f:
            name = f.read().strip()
        if name:
            return name
    return LEGACY_EMBEDDING_MODEL


def _chroma_available() -> bool:
    return os.path.isdir(CHROMA_PATH) and any(os.scandir(CHROMA_PATH))


@st.cache_resource(show_spinner=False)
def get_cached_vectorstore():
    """None jika chroma_db tidak ada (mis. di Streamlit Cloud): pencarian semantik dinonaktifkan."""
    if not _chroma_available():
        print("[rag] chroma_db tidak ditemukan -> hanya pencarian teks dari CSV")
        return None
    embeddings = HuggingFaceEmbeddings(
        model_name=resolve_embedding_model(), model_kwargs={"device": "cpu"}
    )
    return Chroma(
        persist_directory=CHROMA_PATH,
        embedding_function=embeddings,
        collection_name=COLLECTION_NAME,
    )


def _find_csv() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    for p in (CSV_MASTER_FILE, os.path.join(here, CSV_MASTER_FILE), os.path.join(os.path.dirname(here), CSV_MASTER_FILE)):
        if os.path.exists(p):
            return p
    raise FileNotFoundError(f"{CSV_MASTER_FILE} tidak ditemukan (pastikan ikut di-push ke GitHub)")


def _legacy_term(content: str) -> str:
    term = re.sub(r"^Terminologi Medis:\s*", "", content or "")
    term = re.sub(r",\s*Concept ID:.*$", "", term)
    return term.strip()


def is_junk(concept_id: str, term: str) -> bool:
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


@st.cache_resource(show_spinner=False)
def get_search_index() -> dict:
    """Dibangun SEKALI dari CSV (tidak butuh ChromaDB): daftar entri + indeks terbalik token -> posisi entri (pencarian awalan via bisect)."""
    df = pd.read_csv(_find_csv(), dtype=str)
    if "active" in df.columns:
        df = df[df["active"].astype(str).str.strip() == "1"]
    df = df[["conceptId", "term"]].dropna().drop_duplicates()
    entries, seen = [], set()
    for concept_id, term in zip(df["conceptId"], df["term"]):
        concept_id = str(concept_id).strip()
        if is_junk(concept_id, term):
            continue
        norm = _norm(term)
        key = (concept_id, norm)
        if not norm or key in seen:
            continue
        seen.add(key)
        entries.append({"conceptId": concept_id, "term": term, "norm": norm})
    postings = {}
    for i, e in enumerate(entries):
        for tok in set(e["norm"].split()):
            postings.setdefault(tok, []).append(i)
    return {"entries": entries, "postings": postings, "tokens": sorted(postings)}


def get_term_index() -> list:
    return get_search_index()["entries"]


@st.cache_resource(show_spinner=False)
def warmup() -> bool:
    vs = get_cached_vectorstore()
    if vs is not None:
        vs.similarity_search("chest pain", k=1)  # muat model embedding
    try:
        get_search_index()
    except Exception as e:
        print(f"[rag] indeks teks gagal dibuat: {e}")
    return True


def _ids_for_prefix(idx: dict, prefix: str) -> set:
    tokens, postings = idx["tokens"], idx["postings"]
    ids, i = set(), bisect_left(tokens, prefix)
    while i < len(tokens) and tokens[i].startswith(prefix):
        ids.update(postings[tokens[i]])
        i += 1
    return ids


@lru_cache(maxsize=2048)
def _lexical_cached(q: str, k: int) -> tuple:
    q_tokens = q.split()
    if not q_tokens:
        return ()
    idx = get_search_index()
    entries = idx["entries"]
    matched = None
    for qt in q_tokens:
        ids = _ids_for_prefix(idx, qt)
        matched = ids if matched is None else matched & ids
        if not matched:
            return ()
    scored = []
    for i in matched:
        norm = entries[i]["norm"]
        rank = 0 if norm == q else (1 if norm.startswith(q) else 2)
        scored.append((rank, len(norm), i))
    scored.sort()
    results, seen = [], set()
    for _, _, i in scored:
        e = entries[i]
        if e["conceptId"] in seen:
            continue
        seen.add(e["conceptId"])
        results.append((e["conceptId"], e["term"]))
        if len(results) >= k:
            break
    return tuple(results)


def lexical_search(query: str, k: int = 8) -> list:
    return [{"conceptId": c, "term": t} for c, t in _lexical_cached(_norm(query), k)]


@st.cache_data(show_spinner=False, max_entries=1024)
def search_candidates(query: str, k: int = 3) -> list:
    query = " ".join(query.split())[:300]
    if not query:
        return []
    vs = get_cached_vectorstore()
    if vs is None:
        return []
    docs = vs.similarity_search(query, k=k * 3)
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
    """Teks dulu (milidetik). Pencarian semantik (embedding, lambat) hanya jika hasil teks kurang dari k."""
    try:
        lexical = lexical_search(query, k)
    except Exception as e:
        print(f"[rag] pencarian teks gagal: {e}")
        lexical = []
    if len(lexical) >= k:
        return lexical
    try:
        semantic = search_candidates(query, k)
    except Exception as e:
        print(f"[rag] pencarian semantik gagal: {e}")
        semantic = []
    results, seen = [], set()
    for hit in lexical + semantic:
        if hit["conceptId"] in seen:
            continue
        seen.add(hit["conceptId"])
        results.append(hit)
    return results[:k]


def index_stats() -> dict:
    vs = get_cached_vectorstore()
    try:
        documents = vs._collection.count() if vs is not None else 0
    except Exception:
        documents = -1
    try:
        terms = len(get_term_index())
    except Exception:
        terms = -1
    return {
        "documents": documents,
        "terms": terms,
        "model": resolve_embedding_model() if vs is not None else "(semantik nonaktif)",
        "path": os.path.abspath(CSV_MASTER_FILE),
    }