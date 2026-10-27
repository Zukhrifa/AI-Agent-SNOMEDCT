import json
import os
import re
import time

import streamlit as st
from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from modules.rag_snomed import get_snomed_context

load_dotenv()

# --- Konfigurasi (bisa diubah lewat .env) ---
MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
FALLBACK_MODELS = os.getenv("GEMINI_FALLBACK_MODELS", "gemini-3.5-flash-lite")
THINKING_BUDGET = os.getenv("GEMINI_THINKING_BUDGET", "0").strip()
THINKING_LEVEL = os.getenv("GEMINI_THINKING_LEVEL", "").strip()
MAX_OUTPUT_TOKENS = int(os.getenv("GEMINI_MAX_OUTPUT_TOKENS", "400"))
REQUEST_TIMEOUT = int(os.getenv("GEMINI_TIMEOUT", "25"))

MAX_HISTORY_MESSAGES = 8  # batasi riwayat agar prompt tetap pendek
SNOMED_TOP_K = 3
DELIMITER = "===QUICK_ACTIONS==="

DEFAULT_QUICK_ACTIONS = [
    "Bagaimana karakteristik nyeri dada yang dirasakan?",
    "Kapan pertama kali keluhan ini dirasakan?",
    "Apakah ada riwayat penyakit jantung sebelumnya?",
]


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
    """Model utama, lalu model cadangan (tanpa duplikat)."""
    models = [MODEL_NAME] + [m.strip() for m in FALLBACK_MODELS.split(",") if m.strip()]
    chain = []
    for m in models:
        if m not in chain:
            chain.append(m)
    return chain


@st.cache_resource(show_spinner=False)
def _build_llm(api_key: str, model: str, tuned: bool):
    """Klien LLM dibuat sekali per model dan dipakai ulang."""
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


def build_system_prompt(snomed_context: str) -> str:
    return f"""Anda adalah dokter spesialis kardiologi yang memandu anamnesis klinis dalam Bahasa Indonesia.

ATURAN:
1. Tanggapi jawaban terakhir pasien secara singkat (maksimal 3 kalimat), lalu arahkan ke SATU topik baru yang belum ditanyakan. Urutan topik: karakteristik nyeri, penjalaran, durasi, faktor pemicu, gejala penyerta, riwayat penyakit, faktor risiko.
2. Jika informasi sudah cukup, berikan kesimpulan singkat beserta kode SNOMED CT dari referensi di bawah. Jangan mengarang kode.
3. Akhiri dengan tepat 3 pertanyaan lanjutan yang BARU, berbeda, singkat, dan relevan.

Referensi SNOMED CT:
{snomed_context}

FORMAT OUTPUT (wajib persis, tanpa teks lain):
[tanggapan klinis singkat]
{DELIMITER}
["pertanyaan 1", "pertanyaan 2", "pertanyaan 3"]"""


def build_messages(user_input: str, chat_history: list) -> list:
    # Query retrieval = beberapa keluhan terakhir pasien, bukan hanya satu kalimat
    recent_user_texts = [m["content"] for m in chat_history if m["role"] == "user"][-2:]
    query = " ".join(recent_user_texts + [user_input])

    try:
        snomed_context = get_snomed_context(query, SNOMED_TOP_K)
    except Exception as e:
        print(f"[rag] pencarian SNOMED gagal: {e}")
        snomed_context = ""
    if not snomed_context:
        snomed_context = "Tidak ada data spesifik."

    messages = [SystemMessage(content=build_system_prompt(snomed_context))]

    window = list(chat_history[-MAX_HISTORY_MESSAGES:])
    # Gemini mewajibkan percakapan diawali pesan user
    while window and window[0]["role"] != "user":
        window.pop(0)

    for msg in window:
        if msg["role"] == "user":
            messages.append(HumanMessage(content=msg["content"]))
        elif msg["role"] == "assistant":
            messages.append(AIMessage(content=msg["content"]))

    messages.append(HumanMessage(content=user_input))
    return messages


def _is_model_missing(e: Exception) -> bool:
    low = str(e).lower()
    return any(k in low for k in ("404", "not_found", "no longer available", "is not found"))


def _is_transient_error(e: Exception) -> bool:
    """Error di sisi server/kuota."""
    low = str(e).lower()
    keys = (
        "503", "unavailable", "high demand", "overloaded", "429", "quota",
        "resource_exhausted", "rate limit", "timeout", "timed out", "deadline",
        "500", "internal",
    )
    return any(k in low for k in keys)


def _is_config_error(e: Exception) -> bool:
    """Parameter thinking ditolak model (bukan masalah server atau nama model)."""
    if _is_transient_error(e) or _is_model_missing(e):
        return False
    low = str(e).lower()
    keys = (
        "thinking", "budget", "invalid argument", "invalid_argument",
        "unexpected keyword", "extra inputs", "validation error", "400",
    )
    return any(k in low for k in keys)


def _stream_llm(messages: list):
    """Stream token. Jika model gagal (sibuk/timeout/tidak ada), pindah ke model cadangan."""
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
                    raise  # sudah terlanjur menampilkan sebagian jawaban
                if tuned and _is_config_error(e):
                    print(f"[llm] {model}: parameter thinking ditolak, mencoba tanpa itu")
                    continue
                short = " ".join(str(e).split())[:220]
                print(f"[llm] {model} gagal: {short}")
                errors.append(f"{model}: {short}")
                break

    raise RuntimeError("Semua model gagal -> " + " | ".join(errors))


def stream_anamnesis_response(user_input: str, chat_history: list):
    """Generator potongan teks mentah dari Gemini (1 panggilan LLM berhasil saja)."""
    t0 = time.perf_counter()
    messages = build_messages(user_input, chat_history)
    t_retrieval = time.perf_counter() - t0

    first = True
    for text in _stream_llm(messages):
        if first:
            print(
                f"[timing] retrieval={t_retrieval:.2f}s | "
                f"token_pertama={time.perf_counter() - t0:.2f}s"
            )
            first = False
        yield text
    print(f"[timing] total={time.perf_counter() - t0:.2f}s")


def visible_part(raw: str) -> str:
    """Bagian teks yang boleh ditampilkan (sebelum pemisah QUICK_ACTIONS)."""
    if DELIMITER in raw:
        return raw.split(DELIMITER, 1)[0]
    # sembunyikan potongan pemisah yang belum lengkap di akhir stream
    for i in range(len(DELIMITER) - 1, 0, -1):
        if raw.endswith(DELIMITER[:i]):
            return raw[:-i]
    return raw


def parse_response(raw: str):
    text = raw.strip()
    quick_actions = list(DEFAULT_QUICK_ACTIONS)

    if DELIMITER in raw:
        head, tail = raw.split(DELIMITER, 1)
        text = head.strip()
        try:
            cleaned = re.sub(r"```json|```", "", tail).strip()
            match = re.search(r"\[.*\]", cleaned, re.DOTALL)
            parsed = json.loads(match.group(0) if match else cleaned)
            items = [str(x).strip() for x in parsed if str(x).strip()]
            if items:
                quick_actions = items[:3]
        except Exception:
            pass  # pakai quick action default

    return text, quick_actions


def friendly_error(e: Exception) -> str:
    msg = str(e)
    low = msg.lower()
    hints = []

    if any(k in low for k in ("503", "unavailable", "high demand", "overloaded")):
        hints.append(
            "Server Gemini sedang penuh (503). Ini masalah di sisi Google dan biasanya sementara."
        )
    if any(k in low for k in ("429", "quota", "resource_exhausted", "rate limit")):
        hints.append(
            "Kuota/batas permintaan Gemini gratis terlampaui. Tunggu sekitar 1 menit atau pakai API key lain."
        )
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


def generate_anamnesis_response(user_input: str, chat_history: list):
    """Versi non-streaming (kompatibilitas). UI utama memakai stream_anamnesis_response."""
    raw = ""
    try:
        for chunk in stream_anamnesis_response(user_input, chat_history):
            raw += chunk
    except Exception as e:
        if not raw:
            return f"⚠️ {friendly_error(e)}", list(DEFAULT_QUICK_ACTIONS)
    text, quick_actions = parse_response(raw)
    return text or "Respons AI kosong, silakan coba lagi.", quick_actions