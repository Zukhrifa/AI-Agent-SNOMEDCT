"""RAG dokumen pedoman/SOP: ekstraksi per halaman, potong jadi kutipan, simpan di database
(Turso/SQLite), dan cari kutipan paling relevan beserta nama dokumen, halaman, dan bagian.

- Unggah/hapus HANYA admin (dicek ulang di sini, bukan hanya di tampilan).
- Disimpan di database yang sama dengan data lain, jadi tetap ada setelah Streamlit reboot.
- Pencarian memakai BM25 (kata kunci) tanpa model embedding: tidak menambah memori/RAM server.
  Kata kunci dirumuskan oleh AI lewat tool `search_guidelines`.
"""
import hashlib
import io
import math
import re
from collections import Counter

import streamlit as st

from database import _NOW, _query, _run, _write

MAX_FILE_MB = 15
CONTENT_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
MAX_PAGES = 400
CHUNK_CHARS = 900          # panjang target satu kutipan
MIN_CHUNK_CHARS = 40
MIN_PAGE_CHARS = 25        # halaman dengan teks lebih sedikit dianggap kosong (mis. gambar)
EXCERPT_CHARS = 650        # panjang kutipan yang dikirim ke AI
BATCH = 40                 # jumlah INSERT per permintaan ke database
INDEX_TTL = 300            # detik; indeks dimuat ulang otomatis (admin lain mengunggah/menghapus)
BM25_K1, BM25_B = 1.5, 0.75

DOC_TYPES = ("SOP rumah sakit", "Pedoman nasional (PNPK)", "Panduan organisasi profesi", "Lainnya")

_READY = False


# ---------------------------------------------------------------------------
# Tabel
# ---------------------------------------------------------------------------
def _ensure_table() -> None:
    global _READY
    if _READY:
        return
    _write([
        (f"""CREATE TABLE IF NOT EXISTS guideline_docs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            doc_type TEXT NOT NULL DEFAULT '',
            filename TEXT NOT NULL DEFAULT '',
            file_hash TEXT NOT NULL UNIQUE,
            pages INTEGER NOT NULL DEFAULT 0,
            chunk_count INTEGER NOT NULL DEFAULT 0,
            uploaded_by TEXT NOT NULL DEFAULT '',
            content_type TEXT NOT NULL DEFAULT '',
            file_data BLOB,
            created_at TEXT NOT NULL DEFAULT ({_NOW}))""", ()),
        ("""CREATE TABLE IF NOT EXISTS guideline_chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id INTEGER NOT NULL,
            page INTEGER,
            section TEXT NOT NULL DEFAULT '',
            content TEXT NOT NULL)""", ()),
        ("CREATE INDEX IF NOT EXISTS idx_gchunk_doc ON guideline_chunks(doc_id)", ()),
    ])
    try:  # migrasi tabel lama yang belum punya kolom file asli
        _run([("SELECT file_data FROM guideline_docs LIMIT 1", ())])
    except Exception:
        _write([("ALTER TABLE guideline_docs ADD COLUMN content_type TEXT NOT NULL DEFAULT ''", ()),
                ("ALTER TABLE guideline_docs ADD COLUMN file_data BLOB", ())])
    _READY = True


def _require_admin(user: dict) -> None:
    if not user or user.get("role") != "admin":
        raise PermissionError("Hanya admin yang boleh mengelola dokumen pedoman.")


# ---------------------------------------------------------------------------
# Ekstraksi teks
# ---------------------------------------------------------------------------
def _pdf_pages(data: bytes) -> list:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:
            raise ValueError("PDF dikunci dengan password. Buka kuncinya dulu lalu unggah ulang.")
    if len(reader.pages) > MAX_PAGES:
        raise ValueError(f"PDF terlalu panjang ({len(reader.pages)} halaman; batas {MAX_PAGES}).")
    pages = []
    for i, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        pages.append((i, text))
    return pages


def _docx_pages(data: bytes) -> list:
    """DOCX tidak punya nomor halaman tetap, jadi seluruh isi dianggap satu 'halaman' (None)."""
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = docx.Document(io.BytesIO(data))
    lines = []
    for el in doc.element.body.iterchildren():
        if el.tag.endswith("}p"):
            para = Paragraph(el, doc)
            style = (para.style.name if para.style is not None else "").lower()
            is_head = style.startswith(("heading", "judul", "title")) and para.text.strip()
            lines.append((_HEAD_MARK + para.text.strip()) if is_head else para.text)
        elif el.tag.endswith("}tbl"):
            for row in Table(el, doc).rows:
                cells = []
                for cell in row.cells:
                    t = " ".join(cell.text.split())
                    if t and t not in cells:
                        cells.append(t)
                if cells:
                    lines.append(" | ".join(cells))
    return [(None, "\n".join(lines))]


def extract_pages(data: bytes, filename: str) -> list:
    """Return [(nomor_halaman atau None, teks)]."""
    name = (filename or "").lower()
    if name.endswith(".pdf"):
        return _pdf_pages(data)
    if name.endswith(".docx"):
        return _docx_pages(data)
    raise ValueError("Format belum didukung (hanya PDF dan DOCX).")


# ---------------------------------------------------------------------------
# Memotong teks jadi kutipan (tiap kutipan tidak melewati batas halaman)
# ---------------------------------------------------------------------------
_HEAD_MARK = "\u00a7 "  # penanda judul dari gaya Heading di DOCX
_HEADING_RE = re.compile(
    r"^(?:(?:bab|bagian)\s*[ivxlc\d]+\b.*|\d{1,2}(?:\.\d{1,2}){0,3}[.)]?\s+\S.*|\d{1,2}(?:\.\d{1,2})+[.)]?\s*[a-z].*)$",
    re.IGNORECASE,
)
_BAB_RE = re.compile(r"^(?:bab|bagian)\s*[ivxlc\d]+\b", re.IGNORECASE)
_TOC_RE = re.compile(r"\.{4,}|\s\.{2,}\s*\d+$")  # baris daftar isi: titik-titik + nomor halaman
_LIST_RE = re.compile(r"^(?:tabel|gambar|table|figure)\b.{0,40}?\d+[.:]?\s", re.IGNORECASE)
_NOISE_HEAD = ("daftar isi", "daftar tabel", "daftar gambar", "daftar bacaan", "daftar pustaka")


def _is_toc_page(text: str) -> bool:
    """Halaman daftar isi/tabel/gambar/pustaka: padat kata kunci tapi tanpa isi, jadi tidak diindeks."""
    lines = [" ".join(l.split()) for l in (text or "").split("\n") if l.strip()]
    if not lines:
        return False
    if any(k in " ".join(lines[:3]).lower() for k in _NOISE_HEAD):
        return True
    toc = sum(1 for l in lines if _TOC_RE.search(l) or _LIST_RE.match(l))
    return toc >= 5 and toc / len(lines) >= 0.3


def _is_heading(line: str) -> bool:
    s = line.strip()
    if s.startswith(_HEAD_MARK):
        return True
    if not (3 <= len(s) <= 90) or _TOC_RE.search(s):
        return False
    if _HEADING_RE.match(s):
        if len(s) > 70 or s.endswith((";", ",")):
            return False
        # "Bab 5." boleh berakhir titik; judul bernomor biasa yang berakhir titik kemungkinan kalimat
        return bool(_BAB_RE.match(s)) or not s.endswith(".")
    letters = [c for c in s if c.isalpha()]
    return len(letters) >= 4 and s.upper() == s and len(s.split()) <= 10


def chunk_pages(pages: list) -> list:
    """Return [{'page', 'section', 'content'}]. 'section' = judul bagian terakhir yang terdeteksi."""
    chunks, section = [], ""
    for page_no, text in pages:
        if _is_toc_page(text):
            continue
        cur, cur_len, cur_section = [], 0, section

        def flush():
            nonlocal cur, cur_len, cur_section
            body = " ".join(cur).strip()
            if len(body) >= MIN_CHUNK_CHARS:
                chunks.append({"page": page_no, "section": cur_section, "content": body})
            cur, cur_len, cur_section = [], 0, section

        for raw in (text or "").replace("\r", "").split("\n"):
            line = " ".join(raw.split())
            if not line:
                continue
            if _is_heading(line):
                line = line.removeprefix(_HEAD_MARK.strip()).strip()
                flush()
                section = line
                cur_section = section
            if not cur:
                cur_section = section
            cur.append(line)
            cur_len += len(line) + 1
            if cur_len >= CHUNK_CHARS:
                flush()
        flush()
    return chunks


# ---------------------------------------------------------------------------
# Pencarian BM25
# ---------------------------------------------------------------------------
_STOP = set(
    "yang dan di ke dari pada untuk dengan atau adalah ini itu dalam akan dapat juga oleh sebagai "
    "karena tidak ada bila jika serta tersebut para sudah telah harus agar bagi saat setelah sebelum "
    "the of and to in is for a an".split()
)


def tokenize(text: str) -> list:
    tokens = []
    for t in re.findall(r"[a-z0-9]+", (text or "").lower()):
        if len(t) < 2 or t in _STOP:
            continue
        if len(t) > 5 and t.endswith(("nya", "lah", "kah")):
            t = t[:-3]
        tokens.append(t)
    return tokens


@st.cache_resource(ttl=INDEX_TTL, show_spinner=False)
def _get_index() -> dict:
    _ensure_table()
    rows = _query(
        "SELECT c.id, c.doc_id, d.title, c.page, c.section, c.content "
        "FROM guideline_chunks c JOIN guideline_docs d ON d.id = c.doc_id"
    )
    chunks, tfs, lengths, df = [], [], [], Counter()
    for cid, doc_id, title, page, section, content in rows:
        tokens = tokenize(f"{section} {content}")
        tf = Counter(tokens)
        df.update(tf.keys())
        chunks.append({"id": cid, "doc_id": doc_id, "title": title, "page": page,
                       "section": section or "", "content": content})
        tfs.append(tf)
        lengths.append(len(tokens) or 1)
    avg = (sum(lengths) / len(lengths)) if lengths else 1.0
    return {"chunks": chunks, "tf": tfs, "len": lengths, "df": df, "avg": avg}


def search(query: str, k: int = 4) -> list:
    """Kutipan paling relevan: [{'title','page','section','excerpt','score'}]. [] bila tidak ada."""
    idx = _get_index()
    terms = set(tokenize(query))
    n_docs = len(idx["chunks"])
    if not terms or not n_docs:
        return []
    scored = []
    for i, (tf, dl) in enumerate(zip(idx["tf"], idx["len"])):
        score = 0.0
        for t in terms:
            f = tf.get(t)
            if not f:
                continue
            n = idx["df"][t]
            idf = math.log(1 + (n_docs - n + 0.5) / (n + 0.5))
            score += idf * f * (BM25_K1 + 1) / (f + BM25_K1 * (1 - BM25_B + BM25_B * dl / idx["avg"]))
        if score > 0:
            scored.append((score, i))
    scored.sort(reverse=True)
    results = []
    for score, i in scored[:k]:
        c = idx["chunks"][i]
        results.append({
            "doc_id": c["doc_id"], "title": c["title"], "page": c["page"], "section": c["section"],
            "excerpt": c["content"][:EXCERPT_CHARS], "score": round(score, 2),
        })
    return results


def has_documents() -> bool:
    """Dipakai agent: tool pedoman hanya ditawarkan ke AI bila sudah ada dokumen."""
    try:
        _ensure_table()
        return _query("SELECT COUNT(*) FROM guideline_docs")[0][0] > 0
    except Exception as e:
        print(f"[pedoman] gagal membaca tabel dokumen: {e}")
        return False


# ---------------------------------------------------------------------------
# Kelola dokumen (khusus admin)
# ---------------------------------------------------------------------------
def list_documents() -> list:
    _ensure_table()
    cols = ("id", "title", "doc_type", "filename", "pages", "chunk_count", "uploaded_by", "created_at")
    rows = _query(f"SELECT {', '.join(cols)} FROM guideline_docs ORDER BY id DESC")
    return [dict(zip(cols, r)) for r in rows]


def add_document(user: dict, data: bytes, filename: str, title: str, doc_type: str = "") -> dict:
    """Proses & simpan satu dokumen. Return {'doc_id','pages','chunks','empty_pages','has_pages'}.
    Melempar ValueError (pesan siap tampil) bila dokumen tidak bisa dipakai."""
    _require_admin(user)
    _ensure_table()
    title = " ".join((title or "").split()) or (filename or "Dokumen")
    if not data:
        raise ValueError("File kosong.")
    if len(data) > MAX_FILE_MB * 1024 * 1024:
        raise ValueError(f"File terlalu besar (batas {MAX_FILE_MB} MB).")

    file_hash = hashlib.sha256(data).hexdigest()
    dup = _query("SELECT title FROM guideline_docs WHERE file_hash = ?", (file_hash,))
    if dup:
        raise ValueError(f"File yang sama sudah diunggah sebagai '{dup[0][0]}'.")

    pages = extract_pages(data, filename)
    with_text = [p for p in pages if len((p[1] or "").strip()) >= MIN_PAGE_CHARS]
    if not with_text or len(with_text) < 0.3 * len(pages):
        raise ValueError(
            "Teks hampir tidak terbaca. PDF kemungkinan hasil scan (gambar) dan butuh OCR dulu. "
            "Gunakan PDF yang teksnya bisa diseleksi atau versi DOCX."
        )
    chunks = chunk_pages(pages)
    if not chunks:
        raise ValueError("Tidak ada teks yang bisa dipotong menjadi kutipan.")

    ext = (filename or "").rsplit(".", 1)[-1].lower()
    _write([(
        "INSERT INTO guideline_docs "
        "(title, doc_type, filename, file_hash, pages, chunk_count, uploaded_by, content_type, file_data) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (title, doc_type or "", filename or "", file_hash, len(pages), len(chunks),
         user.get("username", ""), CONTENT_TYPES.get(ext, "application/octet-stream"), data),
    )])
    doc_id = _query("SELECT id FROM guideline_docs WHERE file_hash = ?", (file_hash,))[0][0]
    try:
        for i in range(0, len(chunks), BATCH):
            _write([
                ("INSERT INTO guideline_chunks (doc_id, page, section, content) VALUES (?, ?, ?, ?)",
                 (doc_id, c["page"], c["section"], c["content"]))
                for c in chunks[i:i + BATCH]
            ])
    except Exception:
        _write([("DELETE FROM guideline_chunks WHERE doc_id = ?", (doc_id,)),
                ("DELETE FROM guideline_docs WHERE id = ?", (doc_id,))])
        _get_index.clear()
        raise
    _get_index.clear()
    return {
        "doc_id": doc_id,
        "pages": len(pages),
        "chunks": len(chunks),
        "empty_pages": len(pages) - len(with_text),
        "has_pages": pages[0][0] is not None,
    }


def delete_document(user: dict, doc_id: int) -> None:
    _require_admin(user)
    _ensure_table()
    _write([
        ("DELETE FROM guideline_chunks WHERE doc_id = ?", (int(doc_id),)),
        ("DELETE FROM guideline_docs WHERE id = ?", (int(doc_id),)),
    ])
    _get_index.clear()


def get_file(doc_id: int):
    """Return {'filename','content_type','data'} file asli, atau None jika tidak ada
    (dokumen lama yang diunggah sebelum fitur ini ada)."""
    _ensure_table()
    row = _query(
        "SELECT filename, content_type, file_data FROM guideline_docs WHERE id = ?", (int(doc_id),)
    )
    if not row or row[0][2] is None:
        return None
    filename, content_type, data = row[0]
    return {"filename": filename, "content_type": content_type or "application/octet-stream", "data": data}