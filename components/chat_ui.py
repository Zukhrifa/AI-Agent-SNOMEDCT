import html
import re

import streamlit as st

from components.voice_input import render_voice_button
from database import get_all_consultations, save_anamnesis_result, save_or_update_consultation
from modules.ai_agent import (
    CONTROL_PREFIX,
    DEFAULT_QUICK_ACTIONS,
    FINAL_REQUEST_TEXT,
    friendly_error,
    get_candidates,
    parse_response,
    stream_anamnesis_response,
    strip_data_block,
    visible_part,
)
from modules.patient_context import build_patient_context

CATEGORY_LABELS = [
    ("gejala", "Gejala / Temuan"),
    ("faktor_risiko", "Faktor Risiko"),
    ("diagnosis", "Dugaan Diagnosis"),
    ("lainnya", "Lainnya"),
]

MATCH_STYLES = {
    "tepat": ("#dcfce7", "#166534", "tepat"),
    "mirip": ("#fef9c3", "#854d0e", "mirip"),
    "terdekat": ("#ffedd5", "#9a3412", "terdekat - verifikasi"),
}


def _fmt(text: str) -> str:
    """Escape HTML, dukung **tebal** dan baris baru agar aman di bubble."""
    safe = html.escape(text or "")
    safe = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", safe)
    return safe.replace("\n", "<br>")


def _user_bubble(msg: dict) -> str:
    # HTML disusun satu baris tanpa indentasi/baris kosong, agar Markdown
    # tidak menganggap sisanya sebagai blok kode.
    if msg.get("question") and msg.get("answer"):
        body = (
            "<div style='font-size:12px;opacity:0.85;margin-bottom:4px;'>"
            f"❓ {html.escape(msg['question'])}</div>{_fmt(msg['answer'])}"
        )
    else:
        body = _fmt(msg["content"])

    return (
        '<div style="display:flex;justify-content:flex-end;margin-bottom:10px;">'
        '<div style="background-color:#2b5797;color:white;padding:10px 15px;border-radius:15px;max-width:70%;">'
        f"{body}"
        "</div></div>"
    )


def _match_badge(match: str) -> str:
    if match not in MATCH_STYLES:
        return ""
    bg, fg, text = MATCH_STYLES[match]
    return (
        f"<span style='background:{bg};color:{fg};padding:1px 6px;border-radius:6px;"
        f"font-size:11px;margin-left:4px;'>{text}</span>"
    )


def _codes_html(codes) -> str:
    if not codes:
        return (
            "<div style='margin-top:10px;font-size:13px;color:#64748b;'>"
            "Tidak ada konsep SNOMED CT yang cocok di subset data kardiologi.</div>"
        )
    parts = [
        "<div style='margin-top:12px;padding-top:10px;border-top:1px dashed #e2e8f0;'>"
        "<div style='font-weight:600;color:#0f172a;margin-bottom:4px;'>Kode SNOMED CT</div>"
    ]
    for key, label in CATEGORY_LABELS:
        items = [c for c in codes if c.get("kategori") == key]
        if not items:
            continue
        parts.append(
            f"<div style='font-size:12px;font-weight:600;color:#64748b;margin-top:6px;'>{label}</div>"
        )
        for c in items:
            source = (c.get("label") or "").strip()
            arrow = ""
            if source and source.lower() != c["term"].lower():
                arrow = f"<span style='color:#64748b;'>{html.escape(source)} → </span>"
            parts.append(
                f"<div style='margin-left:8px;'>• {arrow}{html.escape(c['term'])} "
                "<span style='background:#eff6ff;color:#2563eb;padding:1px 6px;border-radius:6px;font-size:12px;'>"
                f"{html.escape(c['conceptId'])}</span>{_match_badge(c.get('match', ''))}</div>"
            )
    parts.append("</div>")
    return "".join(parts)


def _ai_bubble(text: str, codes=None, final: bool = False, loading: bool = False) -> str:
    color = "#94a3b8" if loading else "#334155"
    italic = "font-style:italic;" if loading else ""
    title = "Kesimpulan Anamnesis" if final else "Assessment"
    border = "#93c5fd" if final else "#e2e8f0"
    bg = "#f8fbff" if final else "#ffffff"

    extra = ""
    if final:
        extra += _codes_html(codes)
        extra += (
            "<div style='margin-top:10px;font-size:12px;color:#92400e;background:#fffbeb;"
            "border:1px solid #fde68a;border-radius:8px;padding:6px 10px;'>"
            "⚠️ Dukungan keputusan klinis, bukan diagnosis pasti. Kode dicari otomatis dari database "
            "SNOMED CT (kecocokan terdekat), verifikasi sebelum dipakai. Keputusan akhir ada pada dokter.</div>"
        )

    # Satu baris, tanpa indentasi dan tanpa baris kosong
    return "".join([
        '<div style="display:flex;align-items:flex-start;margin-bottom:16px;">',
        '<div style="width:32px;height:32px;background-color:#eff6ff;border-radius:50%;display:flex;'
        'align-items:center;justify-content:center;margin-right:10px;color:#2563eb;font-weight:bold;'
        'font-size:14px;flex-shrink:0;">🤖</div>',
        '<div style="flex:1;">',
        '<div style="font-size:13px;font-weight:600;color:#16a34a;margin-bottom:4px;">AI Agent</div>',
        f'<div style="background-color:{bg};border:1px solid {border};border-radius:12px;padding:16px;'
        f'max-width:85%;font-size:14px;color:{color};{italic}line-height:1.5;'
        'box-shadow:0 1px 2px rgba(0,0,0,0.02);">',
        f'<div style="font-weight:600;color:#0f172a;margin-bottom:6px;">{title}</div>',
        _fmt(text),
        extra,
        "</div></div></div>",
    ])


def _persist():
    """Simpan percakapan aktif ke SQLite dan segarkan daftar roomchat."""
    patient = st.session_state.get("active_patient")
    if not patient:
        return
    patient["messages"] = st.session_state.messages
    patient["quick_actions"] = st.session_state.get("quick_actions", [])
    save_or_update_consultation(
        patient["name"], patient["mrn"], patient["messages"], patient["quick_actions"]
    )
    st.session_state.patient_list = get_all_consultations()


def send_user_message(text: str, question: str = None):
    """Catat pesan staf medis dan tandai 'pending'. Jawaban AI di-stream di render_chat_room().
    Jika 'question' diisi, pesan disimpan sebagai pasangan pertanyaan dokter + jawaban pasien."""
    text = (text or "").strip()
    if not text:
        return

    if question:
        msg = {
            "role": "user",
            "content": f"Pertanyaan dokter: {question}\nJawaban pasien: {text}",
            "question": question,
            "answer": text,
        }
    else:
        msg = {"role": "user", "content": text}

    st.session_state.messages.append(msg)
    st.session_state.pending_input = msg["content"]
    st.session_state.quick_actions = []
    _persist()


def _process_pending(slot):
    pending = st.session_state.get("pending_input")
    if not pending:
        return

    patient = st.session_state.active_patient
    history = st.session_state.messages[:-1]
    patient_context = build_patient_context(patient["mrn"])

    slot.markdown(_ai_bubble("⏳ Menganalisis jawaban pasien...", loading=True), unsafe_allow_html=True)

    raw = ""
    error = None
    try:
        for chunk in stream_anamnesis_response(pending, history, patient_context):
            raw += chunk
            visible = visible_part(raw).strip()
            if visible:
                slot.markdown(_ai_bubble(visible), unsafe_allow_html=True)
    except Exception as e:
        error = friendly_error(e)

    st.session_state.pending_input = None

    if raw.strip():
        result = parse_response(
            raw,
            get_candidates(pending, history),
            force_final=pending.startswith(CONTROL_PREFIX),
        )
        text = result["text"] or "Maaf, respons AI kosong. Silakan kirim ulang pesan Anda."

        msg = {"role": "assistant", "content": text}
        if result["status"] == "final":
            msg["final"] = True
            msg["codes"] = result["codes"]
            # Simpan hasil ke tabel anamnesis_results agar bisa dipanggil lagi
            try:
                save_anamnesis_result(patient["mrn"], text, result["codes"])
            except Exception as e:
                print(f"[db] gagal menyimpan hasil anamnesis: {e}")

        st.session_state.messages.append(msg)
        st.session_state.quick_actions = result["quick_actions"]
    else:
        st.session_state.last_error = error or "Respons AI kosong. Silakan coba lagi."
        st.session_state.quick_actions = list(DEFAULT_QUICK_ACTIONS)

    _persist()
    st.rerun()


def render_chat_room():
    patient = st.session_state.active_patient

    if "messages" not in st.session_state:
        st.session_state.messages = patient.get("messages", [])

    # Tombol mikrofon di dalam kotak pesan (di samping tombol kirim).
    # Dipanggil paling awal agar posisinya di halaman stabil antar-rerun.
    render_voice_button()

    pending = st.session_state.get("pending_input")

    # Pertanyaan aktif hanya berlaku untuk pasien yang sedang dibuka
    if st.session_state.get("active_question_mrn") != patient["mrn"]:
        st.session_state.active_question = None
        st.session_state.active_question_mrn = patient["mrn"]
    active_q = st.session_state.get("active_question")

    messages = st.session_state.messages
    last_final = bool(messages) and messages[-1].get("role") == "assistant" and messages[-1].get("final", False)
    has_user_msg = any(m["role"] == "user" for m in messages)

    # Header Pasien
    st.markdown(f"""
    <div style="padding: 12px 0; border-bottom: 1px solid #e2e8f0; margin-bottom: 20px; display: flex; align-items: center; justify-content: space-between;">
        <div>
            <span style="font-size: 18px; font-weight: 700; color: #0f172a;">{html.escape(patient['name'])}</span>
            <span style="font-size: 13px; color: #64748b; margin-left: 10px;">{html.escape(patient['mrn'])}</span>
            <span style="background-color: #dcfce7; color: #166534; font-size: 11px; padding: 2px 8px; border-radius: 12px; margin-left: 8px; font-weight: 600;">Active</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Riwayat percakapan
    for msg in messages:
        if msg["role"] == "user":
            st.markdown(_user_bubble(msg), unsafe_allow_html=True)
        else:
            st.markdown(
                _ai_bubble(
                    strip_data_block(msg["content"]),  # membersihkan pesan lama yang bocor
                    codes=msg.get("codes"),
                    final=msg.get("final", False),
                ),
                unsafe_allow_html=True,
            )

    # Tempat jawaban AI yang sedang di-stream
    stream_slot = st.empty()

    error = st.session_state.pop("last_error", None)
    if error:
        st.error(error)

    if not pending:
        if active_q:
            # Dokter sudah memilih pertanyaan -> menunggu jawaban pasien
            col_q, col_cancel = st.columns([10, 2])
            with col_q:
                st.info(
                    f"❓ **Tanyakan ke pasien:** {active_q}\n\n"
                    "Ketik atau ucapkan **jawaban pasien** di kotak pesan di bawah (ikon 🎙 di samping tombol kirim)."
                )
            with col_cancel:
                if st.button("Batal", key="cancel_q", use_container_width=True):
                    st.session_state.active_question = None
                    st.rerun()
        else:
            # Rekomendasi pertanyaan (hilang setelah kesimpulan)
            if st.session_state.get("quick_actions"):
                st.markdown(
                    "<div style='margin-top: 10px; margin-bottom: 6px; font-weight: 600; font-size: 13px; color: #64748b;'>Suggested Clinical Actions:</div>",
                    unsafe_allow_html=True,
                )
                for idx, action_text in enumerate(st.session_state.quick_actions[:3]):
                    col_num, col_btn = st.columns([1, 11])
                    with col_num:
                        st.markdown(f"""
                        <div style="background-color: #eff6ff; color: #2563eb; font-weight: 700; width: 32px; height: 32px; border-radius: 8px; display: flex; align-items: center; justify-content: center;">
                            {idx + 1}
                        </div>
                        """, unsafe_allow_html=True)
                    with col_btn:
                        if st.button(action_text, key=f"qa_btn_{idx}", use_container_width=True):
                            st.session_state.active_question = action_text
                            st.session_state.active_question_mrn = patient["mrn"]
                            st.rerun()
                st.markdown("<div style='height: 6px;'></div>", unsafe_allow_html=True)

            if has_user_msg and not last_final:
                if st.button("📋 Minta Kesimpulan Sekarang", key="ask_final"):
                    send_user_message(FINAL_REQUEST_TEXT)
                    st.rerun()

            if last_final:
                st.caption(
                    "Anamnesis selesai dan tersimpan di Data Pasien. "
                    "Tambahkan informasi baru di kotak pesan bila ingin memperbarui kesimpulan."
                )

    # Kotak input utama (tombol mikrofon disisipkan ke dalamnya oleh render_voice_button)
    placeholder = "Ketik atau ucapkan jawaban pasien..." if active_q else "Ketik atau ucapkan keluhan / jawaban pasien..."
    user_input = st.chat_input(placeholder, disabled=bool(pending))
    if user_input:
        send_user_message(user_input, question=st.session_state.pop("active_question", None))
        st.rerun()

    # Jalankan AI paling akhir supaya input & tombol sudah tampil lebih dulu
    if pending:
        _process_pending(stream_slot)