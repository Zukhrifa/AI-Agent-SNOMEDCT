import json
import os
import re
import time
from difflib import SequenceMatcher

import streamlit as st
from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from modules.rag_snomed import search_candidates

load_dotenv()

# --- Konfigurasi (bisa diubah lewat .env) ---
MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
FALLBACK_MODELS = os.getenv("GEMINI_FALLBACK_MODELS", "gemini-3.8-flash")
THINKING_BUDGET = os.getenv("GEMINI_THINKING_BUDGET", "0").strip()
THINKING_LEVEL = os.getenv("GEMINI_THINKING_LEVEL", "").strip()
MAX_OUTPUT_TOKENS = int(os.getenv("GEMINI_MAX_OUTPUT_TOKENS", "900"))
REQUEST_TIMEOUT = int(os.getenv("GEMINI_TIMEOUT", "25"))

MAX_HISTORY_MESSAGES = 10
RETRIEVAL_MESSAGES = 6        # jumlah jawaban terakhir yang dipakai mencari istilah referensi
SNOMED_K_PER_QUERY = 3
SNOMED_MAX_CANDIDATES = 12
MAX_FINDINGS = 8

DELIMITER = "===DATA==="
# Toleran terhadap variasi penulisan model: "==DATA", "===DATA", "=== DATA ===", dst.
DELIMITER_RE = re.compile(r"={2,}\s*DATA\s*=*", re.IGNORECASE)
STATUS_JSON_RE = re.compile(r'\{\s*"status"')
PARTIAL_DELIMITER_RE = re.compile(r"=+\s*(?:D|DA|DAT)?$", re.IGNORECASE)

CONTROL_PREFIX = "Permintaan dokter:"
FINAL_REQUEST_TEXT = (
    f"{CONTROL_PREFIX} mohon berikan kesimpulan dugaan diagnosis beserta kode SNOMED CT "
    "berdasarkan informasi yang sudah terkumpul."
)
VALID_CATEGORIES = ("gejala", "faktor_risiko", "diagnosis")

DEFAULT_QUICK_ACTIONS = [
    "Bagaimana karakteristik nyeri dada yang dirasakan?",
    "Kapan pertama kali keluhan ini dirasakan?",
    "Apakah ada riwayat penyakit jantung sebelumnya?",
]

SYSTEM_TEMPLATE = """Anda adalah asisten klinis (AI agent) untuk dokter/staf medis kardiologi dalam proses anamnesis, berbahasa Indonesia. Anda mendukung keputusan klinis, bukan pengganti dokter.

SUMBER FAKTA:
- Pesan dari staf medis berformat "Pertanyaan dokter: ... / Jawaban pasien: ..." atau catatan bebas.
- Yang dianggap fakta: isi "Jawaban pasien", catatan bebas, dan DATA PASIEN TERSIMPAN di bawah. "Pertanyaan dokter" BUKAN fakta. Jangan menyimpulkan gejala dari pertanyaan saja.
- Jangan menanyakan ulang informasi yang sudah ada di DATA PASIEN TERSIMPAN. Gunakan tanda vital, pemeriksaan fisik, dan data penunjang (bila ada) untuk menilai kemungkinan diagnosis.
- Jawaban negatif/ambigu ("tidak", "belum tahu") dicatat apa adanya. Jangan mengarang informasi.

DATA PASIEN TERSIMPAN:
{{DATA_PASIEN}}

ALUR:
A. Jika informasi belum cukup -> status "ask": tanggapi jawaban terakhir (maksimal 3 kalimat), lalu beri 3 pertanyaan lanjutan BARU yang singkat tentang topik yang belum digali (karakteristik nyeri, penjalaran, durasi, pemicu/peredam, gejala penyerta, riwayat penyakit, obat, faktor risiko: merokok, hipertensi, diabetes, kolesterol, riwayat keluarga).
B. Status "final" jika (1) minimal 4 jawaban pasien yang konkret (atau data tersimpan yang setara) sudah terkumpul dan topik utama sudah tergali, atau (2) dokter meminta kesimpulan. Tulis kesimpulan ringkas dengan struktur:
Ringkasan gejala: ...
Dugaan diagnosis (urut dari paling mungkin, maksimal 3): ...
Dasar: ...
Tanda bahaya / saran pemeriksaan lanjutan: ...
Jika data belum memadai tetapi dokter meminta kesimpulan, sebutkan keterbatasannya. Jangan menyatakan diagnosis pasti; gunakan kata "dugaan" atau "kemungkinan".

TEMUAN UNTUK KODE SNOMED CT:
- Anda TIDAK menulis kode angka. Sebutkan konsep klinisnya di "findings"; sistem akan mencari kode SNOMED CT terdekat dari database.
- Setiap temuan: "label" (istilah Indonesia), "term_en" (istilah medis Inggris baku, sependek mungkin, mis. "chest pain", "hypertension", "angina pectoris"), "kategori": "gejala" atau "faktor_risiko" atau "diagnosis".
- Status "ask": findings harus [].
- Status "final": WAJIB isi findings: minimal 1 gejala dan 1-3 dugaan diagnosis, ditambah faktor risiko bila ada. Walau tidak pasti, tetap tulis dugaan yang paling mendekati (di teks tandai sebagai dugaan). Jangan mengosongkan findings.

Istilah SNOMED CT dari database yang terkait percakapan (hanya referensi penulisan term_en; pakai bila relevan):
{{REFERENSI}}

FORMAT OUTPUT (wajib persis, tanpa teks lain):
[teks tanggapan atau kesimpulan]
{{DELIM}}
{"status": "ask atau final", "quick_actions": ["...", "...", "..."], "findings": [{"label": "nyeri dada", "term_en": "chest pain", "kategori": "gejala"}]}
Pada status "final", "quick_actions" harus [].
Baris pemisah harus persis "{{DELIM}}" (tiga tanda sama dengan di kiri DAN kanan) pada baris tersendiri, tidak boleh dihilangkan atau diubah."""


def get_api_key() -> str:
    api_key = st.session_state.get("custom_api_key", "")

    if not api_key:
        try:
            api_key = st.secrets.get("GEMINI_API_KEY", "")
        except Exception:
            api_key = ""

    if not api_key:
        api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY", "")

    if not api_key:
        raise ValueError(
            "API Key belum ditemukan! Mohon masukkan API Key di menu Pengaturan sidebar."
        )
    return api_key


def _model_chain() -> list:
    models = [MODEL_NAME] + [m.strip() for m in FALLBACK_MODELS.split(",") if m.strip()]
    chain = []
    for m in models:
        if m not in chain:
            chain.append(m)
    return chain


@st.cache_resource(show_spinner=False)
def _build_llm(api_key: str, model: str, tuned: bool):
    kwargs = dict(
        model=model,
        google_api_key=api_key,
        temperature=0.3,
        max_output_tokens=MAX_OUTPUT_TOKENS,
        max_retries=1,
        timeout=REQUEST_TIMEOUT,
    )
    if tuned:
        if THINKING_LEVEL:
            kwargs["thinking_level"] = THINKING_LEVEL
        elif THINKING_BUDGET.lstrip("-").isdigit():
            kwargs["thinking_budget"] = int(THINKING_BUDGET)
    return ChatGoogleGenerativeAI(**kwargs)


def extract_text_from_response(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for part in content:
            if isinstance(part, str):
                out.append(part)
            elif isinstance(part, dict):
                if part.get("type") in ("thinking", "reasoning"):
                    continue
                out.append(part.get("text", ""))
            elif hasattr(part, "text"):
                out.append(part.text)
        return "".join(out)
    return str(content)


# ---------------------------------------------------------------------------
# Memisahkan teks jawaban dari blok data JSON (toleran terhadap variasi model)
# ---------------------------------------------------------------------------
def split_data_block(raw: str):
    """Return (teks, blok_data, ditemukan). Mengenali pemisah yang tidak persis,
    dan sebagai cadangan mengenali blok JSON {"status": ...} tanpa pemisah."""
    raw = raw or ""
    m = DELIMITER_RE.search(raw)
    if m:
        return raw[:m.start()], raw[m.end():], True
    m = STATUS_JSON_RE.search(raw)
    if m:
        return raw[:m.start()], raw[m.start():], True
    return raw, "", False


def strip_data_block(text: str) -> str:
    """Bersihkan pesan lama yang terlanjur tersimpan bersama blok data."""
    return split_data_block(text)[0].strip()


def visible_part(raw: str) -> str:
    """Bagian teks yang boleh ditampilkan saat streaming."""
    head, _, found = split_data_block(raw)
    if found:
        return head
    m = PARTIAL_DELIMITER_RE.search(raw)
    if m:
        return raw[:m.start()]
    return raw


# ---------------------------------------------------------------------------
# Istilah referensi SNOMED untuk prompt (dari ucapan pasien)
# ---------------------------------------------------------------------------
def _clean_query(text: str) -> str:
    return " ".join(re.sub(r"(Pertanyaan dokter|Jawaban pasien):", " ", text).split())


def get_candidates(user_input: str, chat_history: list) -> dict:
    """Return {conceptId: term}. Hasil pencarian di-cache, jadi aman dipanggil ulang."""
    texts = [m["content"] for m in chat_history if m["role"] == "user"] + [user_input]
    texts = [t for t in texts if not t.startswith(CONTROL_PREFIX)]

    candidates = {}
    for text in reversed(texts[-RETRIEVAL_MESSAGES:]):
        query = _clean_query(text)
        if not query:
            continue
        try:
            hits = search_candidates(query, SNOMED_K_PER_QUERY)
        except Exception as e:
            print(f"[rag] pencarian SNOMED gagal: {e}")
            continue
        for hit in hits:
            candidates.setdefault(hit["conceptId"], hit["term"])
            if len(candidates) >= SNOMED_MAX_CANDIDATES:
                return candidates
    return candidates


def codes_to_text(codes) -> str:
    """Teks kode untuk konteks LLM pada pesan kesimpulan sebelumnya."""
    if not codes:
        return ""
    lines = [f"- {c.get('kategori', '')}: {c['term']} ({c['conceptId']})" for c in codes]
    return "\n\nKode SNOMED CT:\n" + "\n".join(lines)


def build_system_prompt(candidates: dict, patient_context: str = "") -> str:
    if candidates:
        ref = "\n".join(f"- {term}" for term in candidates.values())
    else:
        ref = "(tidak ada)"
    data_pasien = (patient_context or "").strip() or "(belum ada data tersimpan)"
    return (
        SYSTEM_TEMPLATE
        .replace("{{REFERENSI}}", ref)
        .replace("{{DELIM}}", DELIMITER)
        .replace("{{DATA_PASIEN}}", data_pasien)
    )


def build_messages(user_input: str, chat_history: list, candidates: dict, patient_context: str = "") -> list:
    messages = [SystemMessage(content=build_system_prompt(candidates, patient_context))]

    window = list(chat_history[-MAX_HISTORY_MESSAGES:])
    # Gemini mewajibkan percakapan diawali pesan user
    while window and window[0]["role"] != "user":
        window.pop(0)

    for msg in window:
        if msg["role"] == "user":
            messages.append(HumanMessage(content=msg["content"]))
        elif msg["role"] == "assistant":
            content = strip_data_block(msg["content"]) + codes_to_text(msg.get("codes"))
            messages.append(AIMessage(content=content))

    messages.append(HumanMessage(content=user_input))
    return messages


# ---------------------------------------------------------------------------
# Panggilan LLM (streaming + fallback model)
# ---------------------------------------------------------------------------
def _is_model_missing(e: Exception) -> bool:
    low = str(e).lower()
    return any(k in low for k in ("404", "not_found", "no longer available", "is not found"))


def _is_transient_error(e: Exception) -> bool:
    low = str(e).lower()
    keys = (
        "503", "unavailable", "high demand", "overloaded", "429", "quota",
        "resource_exhausted", "rate limit", "timeout", "timed out", "deadline",
        "500", "internal",
    )
    return any(k in low for k in keys)


def _is_config_error(e: Exception) -> bool:
    if _is_transient_error(e) or _is_model_missing(e):
        return False
    low = str(e).lower()
    keys = (
        "thinking", "budget", "invalid argument", "invalid_argument",
        "unexpected keyword", "extra inputs", "validation error", "400",
    )
    return any(k in low for k in keys)


def _stream_llm(messages: list):
    api_key = get_api_key()
    models = _model_chain()
    errors = []

    for model in models:
        for tuned in (True, False):
            emitted = False
            try:
                llm = _build_llm(api_key, model, tuned)
                for chunk in llm.stream(messages):
                    text = extract_text_from_response(chunk.content)
                    if text:
                        emitted = True
                        yield text
                if model != models[0]:
                    print(f"[llm] dijawab oleh model cadangan: {model}")
                return
            except Exception as e:
                if emitted:
                    raise
                if tuned and _is_config_error(e):
                    print(f"[llm] {model}: parameter thinking ditolak, mencoba tanpa itu")
                    continue
                short = " ".join(str(e).split())[:220]
                print(f"[llm] {model} gagal: {short}")
                errors.append(f"{model}: {short}")
                break

    raise RuntimeError("Semua model gagal -> " + " | ".join(errors))


def stream_anamnesis_response(user_input: str, chat_history: list, patient_context: str = ""):
    """Generator potongan teks mentah dari Gemini (satu panggilan LLM per pesan)."""
    t0 = time.perf_counter()
    candidates = get_candidates(user_input, chat_history)
    messages = build_messages(user_input, chat_history, candidates, patient_context)
    t_retrieval = time.perf_counter() - t0

    first = True
    for text in _stream_llm(messages):
        if first:
            print(
                f"[timing] retrieval={t_retrieval:.2f}s ({len(candidates)} istilah) | "
                f"token_pertama={time.perf_counter() - t0:.2f}s"
            )
            first = False
        yield text
    print(f"[timing] total={time.perf_counter() - t0:.2f}s")


# ---------------------------------------------------------------------------
# Pemetaan temuan -> kode SNOMED CT terdekat (dilakukan oleh kode, bukan LLM)
# ---------------------------------------------------------------------------
def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).split())


def _ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def match_label(query: str, term: str) -> str:
    """tepat / mirip / terdekat, berdasarkan kemiripan teks istilah."""
    r = _ratio(query, term)
    q_words, t_words = set(_norm(query).split()), set(_norm(term).split())
    if r >= 0.9:
        return "tepat"
    if r >= 0.6 or (q_words and q_words <= t_words):
        return "mirip"
    return "terdekat"


def find_best_concept(term_en: str, label: str):
    """Cari konsep SNOMED terdekat untuk satu temuan. Return (konsep, label_kecocokan) atau None."""
    pool, seen = [], set()
    for query, k in ((term_en, 5), (label, 3)):
        query = (query or "").strip()
        if not query:
            continue
        try:
            hits = search_candidates(query, k)
        except Exception as e:
            print(f"[rag] pencarian '{query}' gagal: {e}")
            hits = []
        for hit in hits:
            if hit["conceptId"] not in seen:
                seen.add(hit["conceptId"])
                pool.append(hit)

    if not pool:
        return None

    ref = term_en or label
    best = max(pool, key=lambda h: _ratio(ref, h["term"]))
    # Jika tidak ada yang cukup mirip secara teks, percayakan urutan kemiripan vektor
    if _ratio(ref, best["term"]) < 0.5:
        best = pool[0]
    return best, match_label(ref, best["term"])


def map_findings_to_codes(findings) -> list:
    codes, seen = [], set()
    if not isinstance(findings, list):
        return codes

    for item in findings[:MAX_FINDINGS]:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label", "")).strip()
        term_en = str(item.get("term_en", "")).strip()
        if not (label or term_en):
            continue

        found = find_best_concept(term_en, label)
        if not found:
            continue
        hit, match = found
        if hit["conceptId"] in seen:
            continue
        seen.add(hit["conceptId"])

        kategori = str(item.get("kategori", "")).strip().lower()
        if kategori not in VALID_CATEGORIES:
            kategori = "lainnya"
        codes.append({
            "conceptId": hit["conceptId"],
            "term": hit["term"],
            "kategori": kategori,
            "label": label or term_en,
            "match": match,
        })
    return codes


def fallback_codes(text: str, candidates: dict) -> list:
    """Jaring pengaman: jika AI tidak memberi temuan, pakai konsep terdekat dari percakapan."""
    hits = [{"conceptId": cid, "term": term} for cid, term in list(candidates.items())[:3]]
    if not hits and text:
        try:
            hits = search_candidates(" ".join(text.split())[:200], 3)
        except Exception:
            hits = []
    return [
        {
            "conceptId": h["conceptId"],
            "term": h["term"],
            "kategori": "lainnya",
            "label": h["term"],
            "match": "terdekat",
        }
        for h in hits
    ]


# ---------------------------------------------------------------------------
# Parsing hasil
# ---------------------------------------------------------------------------
def _load_json_object(text: str):
    cleaned = re.sub(r"```json|```", "", text).strip()
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _as_final(result: dict, codes: list, candidates: dict) -> dict:
    result["status"] = "final"
    result["quick_actions"] = []
    result["codes"] = codes or fallback_codes(result["text"], candidates)
    return result


def parse_response(raw: str, candidates: dict = None, force_final: bool = False) -> dict:
    """Return dict: text, status ('ask'/'final'), quick_actions, codes, dropped."""
    candidates = candidates or {}
    head, tail, found = split_data_block(raw)

    result = {
        "text": head.strip(),
        "status": "ask",
        "quick_actions": list(DEFAULT_QUICK_ACTIONS),
        "codes": [],
        "dropped": 0,
    }

    data = _load_json_object(tail) if found else None

    if data and str(data.get("status", "ask")).strip().lower() == "final":
        return _as_final(result, map_findings_to_codes(data.get("findings")), candidates)

    if data:
        items = data.get("quick_actions")
        if isinstance(items, list):
            cleaned = [str(x).strip() for x in items if str(x).strip()]
            if cleaned:
                result["quick_actions"] = cleaned[:3]
        return result

    # JSON tidak terbaca, tetapi dokter meminta kesimpulan: tetap beri kode terdekat
    if force_final:
        return _as_final(result, [], candidates)
    return result


def friendly_error(e: Exception) -> str:
    msg = str(e)
    low = msg.lower()
    hints = []

    if any(k in low for k in ("503", "unavailable", "high demand", "overloaded")):
        hints.append("Server Gemini sedang penuh (503). Ini masalah di sisi Google dan biasanya sementara.")
    if any(k in low for k in ("429", "quota", "resource_exhausted", "rate limit")):
        hints.append("Kuota/batas permintaan Gemini gratis terlampaui. Tunggu sekitar 1 menit atau pakai API key lain.")
    if _is_model_missing(e):
        hints.append(
            "Ada nama model yang sudah tidak tersedia (404). Jalankan list_models.py, lalu perbarui "
            "GEMINI_MODEL / GEMINI_FALLBACK_MODELS di .env."
        )
    if any(k in low for k in ("api key", "api_key", "permission", "403", "401")):
        hints.append("API Key bermasalah atau tidak punya akses.")
    if any(k in low for k in ("timeout", "timed out", "deadline")):
        hints.append("Gemini tidak merespons tepat waktu.")

    if hints:
        return " ".join(hints) + " Coba kirim ulang pesan Anda."
    return f"Terjadi kesalahan saat memanggil LLM: {msg}"