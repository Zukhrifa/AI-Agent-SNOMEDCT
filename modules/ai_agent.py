import json
import os
import re
import time
from difflib import SequenceMatcher
import streamlit as st
from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from database import get_patient, list_supporting
from modules.agent_tools import (
    CONTROL_PREFIX,
    checklist_status,
    clean_covered,
    compute_red_flags,
    conversation_texts,
    execute_tool_calls,
    format_agent_state,
    format_tool_results,
    sources_of,
    tool_label,
    tools_prompt,
)
from modules.guideline_rag import has_documents
from modules.rag_snomed import search_candidates, search_terms
load_dotenv()
# --- Konfigurasi (bisa diubah lewat .env) ---
MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
FALLBACK_MODELS = os.getenv("GEMINI_FALLBACK_MODELS", "gemini-3.8-flash")
THINKING_BUDGET = os.getenv("GEMINI_THINKING_BUDGET", "0").strip()
THINKING_LEVEL = os.getenv("GEMINI_THINKING_LEVEL", "").strip()
MAX_OUTPUT_TOKENS = int(os.getenv("GEMINI_MAX_OUTPUT_TOKENS", "900"))
REQUEST_TIMEOUT = int(os.getenv("GEMINI_TIMEOUT", "15"))
# Agent: jumlah langkah tool tambahan per pesan. 0 = mode cepat (selalu 1 panggilan AI per pesan).
AGENT_MAX_STEPS = int(os.getenv("AGENT_MAX_STEPS", "2"))
MAX_TOOL_CALLS = 3            # jumlah tool maksimal dalam satu langkah
MAX_HISTORY_MESSAGES = 10
RETRIEVAL_MESSAGES = 3        # jumlah jawaban terakhir yang dipakai mencari istilah referensi
SNOMED_K_PER_QUERY = 3
SNOMED_MAX_CANDIDATES = 12
MAX_FINDINGS = 8
DELIMITER = "===DATA==="
# Toleran terhadap variasi penulisan model: "==DATA", "===DATA", "=== DATA ===", dst.
DELIMITER_RE = re.compile(r"={2,}\s*DATA\s*=*", re.IGNORECASE)
STATUS_JSON_RE = re.compile(r'\{\s*"status"')
PARTIAL_DELIMITER_RE = re.compile(r"=+\s*(?:D|DA|DAT)?$", re.IGNORECASE)
FINAL_REQUEST_TEXT = (
    f"{CONTROL_PREFIX} mohon berikan kesimpulan dugaan diagnosis beserta kode SNOMED CT yang ada di chromadb dan harus akurat, bukan angka asal "
    "berdasarkan informasi yang sudah terkumpul."
)
REGENERATE_REQUEST_TEXT = (
    f"{CONTROL_PREFIX} kesimpulan sebelumnya dinilai TIDAK akurat oleh dokter. "
    "Mohon buat ulang kesimpulan yang lebih sesuai dan akurat berdasarkan seluruh data yang ada "
    "(jawaban pasien, data pasien tersimpan, tanda vital, pemeriksaan fisik, dan data penunjang). "
    "Pertimbangkan diagnosis alternatif serta koreksi temuan dan kodenya. Jangan mengulang kesimpulan yang sama."
)
VALID_CATEGORIES = ("gejala", "faktor_risiko", "diagnosis")
DEFAULT_QUICK_ACTIONS = [
    "Bagaimana karakteristik nyeri dada yang dirasakan?",
    "Kapan pertama kali keluhan ini dirasakan?",
    "Apakah ada riwayat penyakit jantung sebelumnya?",
]
SYSTEM_TEMPLATE = """Anda adalah AI agent klinis untuk dokter/staf medis kardiologi dalam proses anamnesis, berbahasa Indonesia. Anda mendukung keputusan klinis, bukan pengganti dokter. Tujuan Anda: menyelesaikan anamnesis dengan cepat dan lengkap, mengenali tanda bahaya, lalu menyusun dugaan diagnosis beserta temuan SNOMED CT untuk disetujui dokter.

SUMBER FAKTA:
- Pesan dari staf medis berformat "Pertanyaan dokter: ... / Jawaban pasien: ..." atau catatan bebas.
- Yang dianggap fakta: isi "Jawaban pasien", catatan bebas, dan DATA PASIEN TERSIMPAN di bawah. "Pertanyaan dokter" BUKAN fakta. Jangan menyimpulkan gejala dari pertanyaan saja.
- Jangan menanyakan ulang informasi yang sudah ada di DATA PASIEN TERSIMPAN. Gunakan tanda vital, pemeriksaan fisik, dan data penunjang (bila ada) untuk menilai kemungkinan diagnosis.
- Jawaban negatif/ambigu ("tidak", "belum tahu") dicatat apa adanya. Jangan mengarang informasi.

DATA PASIEN TERSIMPAN:
{{DATA_PASIEN}}

STATUS AGENT (dihitung sistem, andalkan ini):
{{STATUS_AGENT}}
{{TOOLS_BLOCK}}
ALUR:
A. Jika informasi belum cukup -> status "ask": tanggapi jawaban terakhir (maksimal 3 kalimat), lalu beri 3 pertanyaan lanjutan BARU yang singkat tentang item yang BELUM digali pada checklist. Jika ada tanda bahaya KRITIS, sebutkan di awal tanggapan dan sarankan evaluasi segera, lalu tetap gali informasi yang paling menentukan.
B. Status "final" jika (1) item inti checklist (onset, quality, radiation, duration, associated, risk_factors) sudah terisi dan topik utama sudah tergali, atau (2) dokter meminta kesimpulan, atau (3) ada tanda bahaya kritis dan data sudah cukup untuk dugaan awal. Tulis kesimpulan ringkas dengan struktur:
Ringkasan gejala: ...
Dugaan diagnosis (urut dari paling mungkin, maksimal 3): ...
Dasar: ...
Tanda bahaya / saran pemeriksaan lanjutan: ...
Jika data belum memadai tetapi dokter meminta kesimpulan, sebutkan keterbatasannya. Jangan menyatakan diagnosis pasti; gunakan kata "dugaan" atau "kemungkinan".
C. Jika dokter menyatakan kesimpulan sebelumnya TIDAK akurat: buat kesimpulan BARU (status "final") yang berbeda dan lebih sesuai. Tinjau ulang semua data, pertimbangkan diagnosis alternatif, perbaiki findings. Jangan mengulang kesimpulan yang sama.

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
{"status": "ask atau final", "covered": ["onset", "quality"], "quick_actions": ["...", "...", "..."], "findings": [{"label": "nyeri dada", "term_en": "chest pain", "kategori": "gejala"}]}
Pada status "final", "quick_actions" harus []. "covered" = kunci checklist yang sudah digali (kumulatif) dari: onset, provocation, quality, radiation, severity, duration, associated, risk_factors, history, medications.
Baris pemisah harus persis "{{DELIM}}" (tiga tanda sama dengan di kiri DAN kanan) pada baris tersendiri, tidak boleh dihilangkan atau diubah."""
TOOLS_BLOCK_TEMPLATE = """
TOOL (opsional, hanya bila perlu):
{{TOOLS}}
Aturan tool: tanda bahaya, checklist, dan data pasien SUDAH tersedia di atas, jadi jangan memanggil tool untuk hal itu. Panggil tool HANYA untuk: menghitung skor risiko (calculate_heart_score) bila datanya cukup, mencari kode untuk istilah spesifik, melihat detail data lengkap, atau mencari isi SOP/pedoman (search_guidelines). Jika dokter bertanya tentang SOP, prosedur, pemeriksaan, atau tatalaksana dan tool search_guidelines tersedia, panggil tool itu lebih dulu dan jawab HANYA berdasarkan kutipan yang dikembalikan. Tulis sumbernya di teks dengan format (Sumber: nama dokumen, hal. X). Jika tidak ada kutipan yang relevan, katakan terus terang bahwa tidak ditemukan di dokumen pedoman, dan jangan mengarang isi dokumen. Maksimal {{MAX_CALLS}} tool per langkah. Untuk memanggil tool, keluarkan HANYA (tanpa teks sebelum pemisah):
{{DELIM}}
{"status": "tool", "calls": [{"tool": "nama_tool", "args": {}}]}
Sebagian besar giliran TIDAK memerlukan tool: langsung jawab (status ask atau final).
"""
TRANSLATE_PROMPT = """Anda penerjemah istilah medis untuk pencarian SNOMED CT.
Ubah masukan (bahasa Indonesia atau bahasa awam lain) menjadi 1 sampai 3 istilah medis berbahasa Inggris yang baku dan sependek mungkin, bergaya SNOMED CT.
Balas HANYA berupa array JSON berisi string, tanpa teks lain.
Contoh:
"nyeri dada seperti ditindih" -> ["chest pain", "crushing chest pain"]
"sesak napas" -> ["dyspnea", "shortness of breath"]
"tekanan darah tinggi" -> ["hypertension"]"""
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
def _build_llm(api_key: str, model: str, tuned: bool, max_tokens: int = MAX_OUTPUT_TOKENS, timeout: int = REQUEST_TIMEOUT):
    kwargs = dict(
        model=model,
        google_api_key=api_key,
        temperature=0.3,
        max_output_tokens=max_tokens,
        max_retries=0,  # sebelumnya 1: model yang error membuat user menunggu 2x timeout
        timeout=timeout,
    )
    if tuned:
        if THINKING_LEVEL:
            kwargs["thinking_level"] = THINKING_LEVEL
        elif THINKING_BUDGET.lstrip("-").isdigit():
            kwargs["thinking_budget"] = int(THINKING_BUDGET)
    return ChatGoogleGenerativeAI(**kwargs)


_TUNED_REJECTED = set()  # model yang menolak parameter thinking: jangan dicoba lagi tiap pesan


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
def build_system_prompt(candidates: dict, patient_context: str = "", agent_state: str = "",
                        tools_text: str = "") -> str:
    ref = "\n".join(f"- {term}" for term in candidates.values()) if candidates else "(tidak ada)"
    data_pasien = (patient_context or "").strip() or "(belum ada data tersimpan)"
    status_agent = (agent_state or "").strip() or "(tidak tersedia)"

    tools_block = ""
    if tools_text:
        tools_block = (
            TOOLS_BLOCK_TEMPLATE
            .replace("{{TOOLS}}", tools_text)
            .replace("{{MAX_CALLS}}", str(MAX_TOOL_CALLS))
        )

    return (
        SYSTEM_TEMPLATE
        .replace("{{TOOLS_BLOCK}}", tools_block)
        .replace("{{REFERENSI}}", ref)
        .replace("{{DELIM}}", DELIMITER)
        .replace("{{STATUS_AGENT}}", status_agent)
        .replace("{{DATA_PASIEN}}", data_pasien)
    )
def build_messages(user_input: str, chat_history: list, candidates: dict, patient_context: str = "",
                   agent_state: str = "", tools_text: str = "") -> list:
    messages = [SystemMessage(content=build_system_prompt(candidates, patient_context, agent_state, tools_text))]

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
def _stream_llm(messages: list, max_tokens: int = MAX_OUTPUT_TOKENS, timeout: int = REQUEST_TIMEOUT):
    api_key = get_api_key()
    models = _model_chain()
    errors = []
    for model in models:
        for tuned in ((False,) if model in _TUNED_REJECTED else (True, False)):
            emitted = False
            try:
                llm = _build_llm(api_key, model, tuned, max_tokens, timeout)
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
                    _TUNED_REJECTED.add(model)
                    print(f"[llm] {model}: parameter thinking ditolak, dicatat & tidak dicoba lagi")
                    continue
                short = " ".join(str(e).split())[:220]
                print(f"[llm] {model} gagal: {short}")
                errors.append(f"{model}: {short}")
                break
    raise RuntimeError("Semua model gagal -> " + " | ".join(errors))


# ---------------------------------------------------------------------------
# Pemetaan temuan -> kode SNOMED CT terdekat (dilakukan oleh kode, bukan LLM)
# ---------------------------------------------------------------------------
def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).split())
def _ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()
def match_label(query: str, term: str) -> str:
    """tepat / mirip / terdekat / lemah, berdasarkan kemiripan teks istilah."""
    r = _ratio(query, term)
    q_words, t_words = set(_norm(query).split()), set(_norm(term).split())
    if r >= 0.9:
        return "tepat"
    if r >= 0.6 or (q_words and q_words <= t_words):
        return "mirip"
    if r >= 0.4:
        return "terdekat"
    return "lemah"
def find_best_concept(term_en: str, label: str):
    """Cari konsep SNOMED terdekat untuk satu temuan. Return (konsep, label_kecocokan) atau None."""
    pool, seen = [], set()
    for query, k in ((term_en, 6), (label, 4)):
        query = (query or "").strip()
        if not query:
            continue
        try:
            hits = search_terms(query, k)
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
    # Jika tidak ada yang cukup mirip secara teks, percayakan urutan hasil pencarian
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

def _data_of(raw: str):
    """Blok JSON dari keluaran AI (atau None)."""
    _, tail, found = split_data_block(raw)
    return _load_json_object(tail) if found else None
def _as_final(result: dict, codes: list, candidates: dict) -> dict:
    result["status"] = "final"
    result["quick_actions"] = []
    result["codes"] = codes or fallback_codes(result["text"], candidates)
    return result
def parse_response(raw: str, candidates: dict = None, force_final: bool = False) -> dict:
    """Return dict: text, status ('ask'/'final'), quick_actions, codes, covered, dropped."""
    candidates = candidates or {}
    head, tail, found = split_data_block(raw)

    result = {
        "text": head.strip(),
        "status": "ask",
        "quick_actions": list(DEFAULT_QUICK_ACTIONS),
        "codes": [],
        "covered": [],
        "dropped": 0,
    }

    data = _load_json_object(tail) if found else None
    status = str(data.get("status", "ask")).strip().lower() if data else ""

    if data:
        result["covered"] = clean_covered(data.get("covered"))

    if status == "final":
        return _as_final(result, map_findings_to_codes(data.get("findings")), candidates)

    if status == "tool":
        # Batas langkah tercapai (atau mode tanpa tool) tetapi AI masih meminta tool
        if not result["text"]:
            result["text"] = (
                "Maaf, analisis belum selesai dalam batas langkah agent. "
                "Silakan kirim ulang pesan atau tekan Minta Kesimpulan Sekarang."
            )
        if force_final:
            return _as_final(result, [], candidates)
        return result

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
# ---------------------------------------------------------------------------
# AI AGENT: loop reason -> act (tool) -> observe, dengan jalur cepat
# ---------------------------------------------------------------------------
def run_agent(user_input: str, chat_history: list, patient_context: str = "",
              mrn: str = None, use_tools: bool = True):
    """Generator event untuk UI:
      {"type": "text",  "text": <teks yang boleh tampil sekarang>}
      {"type": "tool",  "label": <status>, "names": [...]}
      {"type": "final", "raw": <keluaran AI mentah>, "steps": [<jejak tool>], "elapsed": <detik>}

    JALUR CEPAT (hampir semua giliran): data pasien, tanda bahaya, dan checklist sudah dihitung
    kode dan disisipkan ke prompt, sehingga AI cukup 1 panggilan. Tool hanya dipakai bila AI
    memutuskan perlu (mis. skor HEART), dengan batas AGENT_MAX_STEPS langkah tambahan."""
    t0 = time.perf_counter()
    max_steps = AGENT_MAX_STEPS if use_tools else 0

    # Persiapan lokal (milidetik, tanpa LLM)
    candidates = get_candidates(user_input, chat_history)
    patient = get_patient(mrn) if mrn else None
    supporting = list_supporting(mrn) if mrn else []
    texts = conversation_texts(list(chat_history) + [{"role": "user", "content": user_input}])
    flags = compute_red_flags(patient, texts, supporting)
    status = checklist_status(chat_history, patient)
    agent_state = format_agent_state(flags, status)
    tools_text = tools_prompt() if max_steps > 0 else ""

    messages = build_messages(user_input, chat_history, candidates, patient_context, agent_state, tools_text)
    ctx = {"mrn": mrn, "patient": patient, "texts": texts}
    t_prep = time.perf_counter() - t0

    steps, seen_calls = [], set()

    for step in range(max_steps + 1):
        raw = ""
        first = True
        for chunk in _stream_llm(messages):
            raw += chunk
            if first:
                print(
                    f"[agent] langkah {step + 1}: persiapan={t_prep:.2f}s "
                    f"token_pertama={time.perf_counter() - t0:.2f}s"
                )
                first = False
            yield {"type": "text", "text": visible_part(raw)}

        data = _data_of(raw)
        wants_tool = bool(data) and str(data.get("status", "")).strip().lower() == "tool"

        if wants_tool and step < max_steps:
            raw_calls = data.get("calls")
            calls = [c for c in raw_calls if isinstance(c, dict)][:MAX_TOOL_CALLS] if isinstance(raw_calls, list) else []

            if calls:
                fresh, repeated = [], []
                for call in calls:
                    signature = (str(call.get("tool")), json.dumps(call.get("args") or {}, sort_keys=True, default=str))
                    (repeated if signature in seen_calls else fresh).append(call)
                    seen_calls.add(signature)

                names = [str(c.get("tool")) for c in fresh] or [str(c.get("tool")) for c in repeated]
                yield {"type": "tool", "label": tool_label(names), "names": names}

                outputs = execute_tool_calls(fresh, ctx, MAX_TOOL_CALLS)
                for call in repeated:
                    outputs.append({
                        "tool": str(call.get("tool")),
                        "args": call.get("args") if isinstance(call.get("args"), dict) else {},
                        "result": {"info": "tool ini sudah dipanggil dengan argumen yang sama; pakai hasil sebelumnya"},
                        "summary": "dilewati (duplikat)",
                        "ms": 0,
                    })

                for item in outputs:
                    trace = {
                        "tool": item["tool"],
                        "args": item["args"],
                        "summary": item["summary"],
                        "ms": item["ms"],
                    }
                    found = sources_of(item)
                    if found:
                        trace["sources"] = found
                    steps.append(trace)
                print(f"[agent] langkah {step + 1}: tool={names} " + ", ".join(f"{o['ms']}ms" for o in outputs))

                messages.append(AIMessage(content=raw))
                messages.append(HumanMessage(content=format_tool_results(outputs, last_step=(step + 1 >= max_steps))))
                continue

        # Kesimpulan tercapai ("final"): cari rekomendasi tindakan di dokumen pedoman
        # secara OTOMATIS dari kode, berdasarkan dugaan diagnosis — tidak menunggu dokter
        # bertanya, dan tidak bergantung pada penilaian AI apakah ini "pertanyaan SOP" atau bukan.
        status_val = str((data or {}).get("status", "")).strip().lower()
        already_searched = any(s["tool"] == "search_guidelines" for s in steps)
        if status_val == "final" and max_steps > 0 and not already_searched and has_documents():
            findings = (data or {}).get("findings") if isinstance(data, dict) else None
            diag_labels = [
                str(f.get("label", "")).strip()
                for f in (findings or [])
                if isinstance(f, dict) and str(f.get("kategori", "")).strip().lower() == "diagnosis"
                and str(f.get("label", "")).strip()
            ]
            query = " ".join(diag_labels[:2]).strip()
            if query:
                yield {"type": "tool", "label": tool_label(["search_guidelines"]), "names": ["search_guidelines"]}
                auto_outputs = execute_tool_calls(
                    [{"tool": "search_guidelines", "args": {"query": query}}], ctx, 1
                )
                item = auto_outputs[0]
                trace = {
                    "tool": item["tool"], "args": item["args"],
                    "summary": item["summary"], "ms": item["ms"],
                }
                found = sources_of(item)
                if found:
                    trace["sources"] = found
                steps.append(trace)
                print(f"[agent] auto-cek pedoman: query='{query}' -> {item['summary']}")

                if isinstance(item["result"], dict) and item["result"].get("results"):
                    messages.append(AIMessage(content=raw))
                    messages.append(HumanMessage(content=(
                        format_tool_results(auto_outputs, last_step=True)
                        + "\nSisipkan rekomendasi tindakan dari kutipan di atas ke dalam ringkasan jawaban akhir, "
                          "dengan sitasi (Sumber: nama dokumen, hal. X). Jika kutipan tidak relevan dengan diagnosis "
                          "ini, biarkan jawaban seperti semula tanpa menyebutnya. Tetap format JSON ===DATA=== yang sama "
                          "seperti sebelumnya (findings tidak perlu diulang menulis ulang kode)."
                    )))
                    raw2 = ""
                    for chunk in _stream_llm(messages):
                        raw2 += chunk
                        yield {"type": "text", "text": visible_part(raw2)}
                    if raw2.strip():
                        raw = raw2

        elapsed = time.perf_counter() - t0
        print(f"[agent] selesai: {step + 1} panggilan AI, {len(steps)} tool, total={elapsed:.2f}s")
        yield {"type": "final", "raw": raw, "steps": steps, "elapsed": elapsed}
        return

    # Tidak tercapai secara normal; jaga-jaga
    yield {"type": "final", "raw": raw, "steps": steps, "elapsed": time.perf_counter() - t0}

# ---------------------------------------------------------------------------
# Terjemahan istilah (Indonesia -> istilah Inggris gaya SNOMED) untuk pencarian
# ---------------------------------------------------------------------------
_TRANSLATE_CACHE = {}

# Keluhan awam yang umum: diterjemahkan lokal (instan, tanpa API).
_LOCAL_TERMS = {
    "serangan jantung": ["myocardial infarction", "heart attack"],
    "gagal jantung": ["heart failure"], "jantung koroner": ["coronary artery disease"],
    "stroke": ["stroke"], "asma": ["asthma"], "maag": ["gastritis"],
    "pusing": ["dizziness"], "pening": ["dizziness"], "vertigo": ["vertigo"],
    "sesak napas": ["dyspnea"], "sesak nafas": ["dyspnea"], "sesak": ["dyspnea"],
    "nyeri dada": ["chest pain"], "dada sakit": ["chest pain"],
    "berdebar": ["palpitations"], "jantung berdebar": ["palpitations"],
    "pingsan": ["syncope"], "hampir pingsan": ["presyncope"],
    "lemas": ["weakness"], "lemah": ["weakness"], "lelah": ["fatigue"], "capek": ["fatigue"],
    "mual": ["nausea"], "muntah": ["vomiting"], "demam": ["fever"], "batuk": ["cough"],
    "sakit kepala": ["headache"], "keringat dingin": ["cold sweat"],
    "bengkak kaki": ["leg swelling", "edema of lower limb"],
    "kaki bengkak": ["leg swelling", "edema of lower limb"],
    "tekanan darah tinggi": ["hypertension"], "darah tinggi": ["hypertension"],
    "kencing manis": ["diabetes mellitus"], "kolesterol tinggi": ["hypercholesterolemia"],
}


def translate_to_snomed_terms(query: str):
    """Return (daftar_istilah_inggris, pesan_error). Kamus lokal dulu, baru LLM (tanpa streaming, output kecil)."""
    key = " ".join((query or "").lower().split())
    if not key:
        return [], ""
    if key in _LOCAL_TERMS:
        return list(_LOCAL_TERMS[key]), ""
    if key in _TRANSLATE_CACHE:
        return list(_TRANSLATE_CACHE[key]), ""
    messages = [SystemMessage(content=TRANSLATE_PROMPT), HumanMessage(content=query.strip())]
    try:
        raw = "".join(_stream_llm(messages, max_tokens=80, timeout=15))
    except Exception as e:
        return [], friendly_error(e)[:200]
    terms = []
    try:
        cleaned = re.sub(r"```json|```", "", raw).strip()
        match = re.search(r"\[.*\]", cleaned, re.DOTALL)
        parsed = json.loads(match.group(0)) if match else []
        terms = [str(t).strip() for t in parsed if str(t).strip()][:3]
    except Exception:
        terms = []
    if not terms:
        return [], "AI tidak mengembalikan istilah yang bisa dibaca"
    _TRANSLATE_CACHE[key] = terms
    return list(terms), ""