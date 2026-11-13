"""Asisten Klinis untuk dokter dan perawat (seperti ChatGPT/Gemini): pertanyaan medis umum, kode SNOMED CT,
SOP/pedoman rumah sakit, dan data sistem (kunjungan/pasien, hanya baca). Pendukung kerja, bukan pengambil
keputusan klinis. Kode SNOMED hanya dari database lokal; data pasien hanya dari alat baca-saja
(modules/assistant_tools.py). Satu percakapan per akun (tabel assistant_chats); 'Percakapan baru' mengosongkannya."""
import json
from datetime import date, timedelta

import streamlit as st
from auth import audit_log
from auth.session import current_user
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from components.patient_data import _collect_search_results
from components.chat_ui import _ai_bubble, _header, _user_bubble
from components.today_visits import today_str
from components.voice_input import render_voice_button
from database import _NOW, _query, _write
from modules import assistant_tools as AT
from modules.ai_agent import MAX_HISTORY_MESSAGES, _stream_llm, friendly_error

SYSTEM_PROMPT = """Anda Asisten Klinis untuk dokter dan perawat rumah sakit di Indonesia. Berbahasa Indonesia \
(atau Inggris bila ditanya), ringkas dan jelas, seperti asisten umum.
Anda boleh: menjawab pertanyaan medis dan keperawatan umum, menjelaskan istilah, membantu dokumentasi, \
menjawab kode SNOMED CT, dan membaca data sistem lewat alat bila diminta.
Aturan:
- Anda pendukung kerja, bukan pengambil keputusan. Diagnosis, terapi, dan dosis tetap keputusan dokter/perawat: \
jangan menyatakan diagnosis pasti atau memerintahkan tindakan. Sajikan sebagai informasi dan pertimbangan, \
dan ingatkan untuk memverifikasi bila perlu.
- Kode SNOMED CT: hanya sebut kode di daftar KANDIDAT di bawah (hasil pencarian database lokal); jangan mengarang \
atau mengingat kode. Jika tidak ada yang cocok, katakan tidak ditemukan. Tulis: istilah — `kode`.
- Data pasien/kunjungan: hanya dari HASIL TOOL; jangan menebak atau mengarang. Jika tool tidak menemukan apa pun, \
katakan tidak ditemukan. Data pasien hanya untuk keperluan pelayanan; sebut nama/MRN seperlunya.
- SOP/pedoman rumah sakit: gunakan search_guidelines dan sebutkan nama dokumen dan halamannya.
Hari ini: {today}; kemarin: {yesterday} (WIB)."""

TOOLS_HINT = """

ALAT BACA-SAJA untuk data sistem:
{tools}
Bila butuh data sistem, balas HANYA satu objek JSON tanpa teks lain, contoh:
{{"tool_calls":[{{"tool":"find_visits","args":{{"date_from":"{yesterday}","date_to":"{yesterday}","keywords":["gagal jantung","heart failure"]}}}}]}}
Setelah menerima HASIL TOOL, jawab dalam bahasa biasa. Untuk pertanyaan umum atau kode SNOMED, jawab langsung tanpa alat."""


NAME = "Asisten Klinis"


class _BubbleSlot:
    """Pembungkus st.empty(): setiap tulisan tampil sebagai bubble AI yang sama dengan roomchat pasien."""

    def __init__(self, slot):
        self.slot = slot

    def markdown(self, text: str, tools=None):
        footer = ""
        if tools:
            footer = ("<div style='margin-top:8px;font-size:12px;color:#64748b;'>🔎 Data sistem dibaca: "
                      + ", ".join(AT.TOOLS[x]["label"] for x in tools if x in AT.TOOLS) + "</div>")
        self.slot.markdown(_ai_bubble(text, name=NAME, title="", footer=footer,
                                      loading=text.startswith(("⏳", "🔎"))), unsafe_allow_html=True)


    def error(self, text: str):
        self.slot.error(text)


def _show(m: dict):
    if m["role"] == "user":
        st.markdown(_user_bubble(m), unsafe_allow_html=True)
    else:
        _BubbleSlot(st.empty()).markdown(m["content"], m.get("tools"))


def go_to_assistant():
    ss = st.session_state
    ss.view = "assistant"
    ss.data_mrn = ss.data_visit = ss.today_mrn = None      # URL tidak membawa MRN


@st.cache_resource(show_spinner=False)
def _init_table() -> bool:
    _write([(
        f"CREATE TABLE IF NOT EXISTS assistant_chats ("
        f"chat_id TEXT PRIMARY KEY, username TEXT NOT NULL, title TEXT, messages TEXT, "
        f"updated_at TEXT DEFAULT ({_NOW}))",
        (),
    )])
    return True


def _user() -> str:
    return (current_user() or {}).get("username", "")


def _chat_id() -> str:
    return f"asisten:{_user()}"      # satu percakapan per akun


def _load(chat_id: str) -> list:
    rows = _query("SELECT messages FROM assistant_chats WHERE chat_id = ? AND username = ?",
                  (chat_id, _user()))
    return json.loads(rows[0][0]) if rows and rows[0][0] else []


def _save(chat_id: str, messages: list):
    title = "Asisten Klinis"
    _write([(
        "INSERT INTO assistant_chats (chat_id, username, title, messages) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(chat_id) DO UPDATE SET title = excluded.title, messages = excluded.messages, "
        f"updated_at = {_NOW} WHERE assistant_chats.username = excluded.username",
        (chat_id, _user(), title, json.dumps(messages, ensure_ascii=False)),
    )])


def _delete(chat_id: str):
    _write([("DELETE FROM assistant_chats WHERE chat_id = ? AND username = ?", (chat_id, _user()))])


def _candidates(query: str) -> list:
    try:
        results, _ = _collect_search_results(query, True)
    except Exception:
        return []
    return results[:8]


def _build_messages(history: list, candidates: list, use_tools: bool) -> list:
    cand = "\n".join(f"- {r['term']} — {r['conceptId']}" for r in candidates) \
        or "(tidak ada kandidat yang cocok)"
    today = today_str()
    yesterday = (date.fromisoformat(today) - timedelta(days=1)).isoformat()
    system = SYSTEM_PROMPT.format(today=today, yesterday=yesterday)
    if use_tools:
        system += TOOLS_HINT.format(tools=AT.tools_prompt(), yesterday=yesterday)
    system += (f"\n\nKANDIDAT KODE SNOMED CT (hasil pencarian database lokal untuk pesan terakhir; "
               f"bisa jadi tidak relevan):\n{cand}")
    window = list(history[-MAX_HISTORY_MESSAGES:])
    while window and window[0]["role"] != "user":          # Gemini mewajibkan diawali pesan user
        window.pop(0)
    messages = [SystemMessage(content=system)]
    for m in window:
        messages.append(HumanMessage(content=m["content"]) if m["role"] == "user"
                        else AIMessage(content=m["content"]))
    return messages


def _step(messages: list, slot, allow_tools: bool):
    """Satu panggilan AI. Teks biasa ditampilkan langsung; balasan JSON (permintaan alat) ditahan."""
    buf, shown = "", False
    for chunk in _stream_llm(messages, timeout=30):
        buf += chunk
        head = buf.lstrip()
        if not shown and head and not (allow_tools and head[0] in "{`"):
            shown = True
        if shown:
            slot.markdown(buf + "▌")
    calls = AT.parse_calls(buf) if allow_tools else None
    return buf, calls


def _answer(history: list, candidates: list, use_tools: bool, slot):
    """Jawab, bila perlu setelah memanggil alat data (maksimal 3 putaran). Return (teks, nama_alat)."""
    messages = _build_messages(history, candidates, use_tools)
    used = []
    for step in range(3):
        last = step == 2
        text, calls = _step(messages, slot, allow_tools=use_tools and not last)
        if not calls:
            return text, used
        slot.markdown(AT.tool_label([c.get("tool") for c in calls]))
        outputs = AT.run_calls(calls)
        used += [o["tool"] for o in outputs if o["tool"] in AT.TOOLS]
        messages += [AIMessage(content=text), HumanMessage(content=AT.format_results(outputs, last_step=step == 1))]
    return text, used


def render_assistant_page():
    _init_table()
    ss = st.session_state
    cid = _chat_id()
    if ss.get("asst_user") != _user():               # muat percakapan akun ini sekali per sesi
        ss.asst_user = _user()
        ss.asst_messages = _load(cid)

    render_voice_button()                            # tombol mikrofon di kotak pesan (seperti roomchat)
    col_title, col_new = st.columns([6, 2])
    col_title.markdown(_header(NAME, "Umum · dokter & perawat"), unsafe_allow_html=True)
    if ss.asst_messages and col_new.button("🧹 Percakapan baru", key="asst_new", use_container_width=True):
        _delete(cid)
        ss.asst_messages = []
        st.rerun()
    st.caption("Asisten umum untuk dokter dan perawat: pertanyaan medis, kode SNOMED CT, SOP rumah sakit, "
               "dan data sistem. Membantu pekerjaan Anda, keputusan klinis tetap di tangan Anda. "
               "Percakapan tersimpan di akun Anda.")
    use_tools = st.toggle("Izinkan membaca data sistem (kunjungan & pasien)", value=True, key="asst_data",
                          help="Jika aktif, data yang dibaca (termasuk nama pasien) ikut dikirim ke penyedia AI "
                               "yang dipakai. Matikan bila hanya ingin bertanya hal umum.")

    if not ss.asst_messages:
        st.info("Contoh: \"kode SNOMED untuk nyeri dada menjalar ke lengan kiri\", "
                "\"pasien kemarin yang gagal jantung siapa?\", \"riwayat kunjungan pasien Ani\", "
                "\"apa kata SOP tentang ...\", \"beda dyspnea dan orthopnea?\".")
    for m in ss.asst_messages:
        _show(m)

    prompt = (st.chat_input("Ketik atau ucapkan pertanyaan...") or "").strip()
    if not prompt:
        return
    ss.asst_messages.append({"role": "user", "content": prompt})
    _show(ss.asst_messages[-1])
    slot = _BubbleSlot(st.empty())
    slot.markdown("⏳ Menyusun jawaban...")
    try:
        answer, used = _answer(ss.asst_messages, _candidates(prompt), use_tools, slot)
    except Exception as e:
        slot.error(friendly_error(e))
        return
    used = list(dict.fromkeys(used))
    slot.markdown(answer, used)
    ss.asst_messages.append({"role": "assistant", "content": answer, **({"tools": used} if used else {})})
    _save(cid, ss.asst_messages)
    audit_log.log("asisten_tanya", "-", f"{len(prompt)} karakter" + (f"; data: {','.join(used)}" if used else ""))