"""Roomchat melayang (floating) di halaman kunjungan: tombol 💬 di pojok kanan bawah membuka panel
roomchat kunjungan yang sedang dibuka, sementara data kunjungan tetap terlihat dan bisa dibandingkan.
Memakai ulang fungsi di chat_ui.py (bubble, persetujuan, agent), jadi chat_ui.py tidak perlu diubah.
Panel adalah fragment: kirim pesan hanya memuat ulang panel, bukan seluruh halaman data."""
import streamlit as st
import streamlit.components.v1 as components

from components import chat_ui as C
from components.nav import open_roomchat_for_mrn
from modules.ai_agent import FINAL_REQUEST_TEXT

USE_FRAGMENT = True     # jika muncul error terkait chat_input di dalam fragment, ubah menjadi False
MAX_SHOWN = 8           # jumlah pesan terakhir yang ditampilkan di panel

_fragment = (getattr(st, "fragment", None) if USE_FRAGMENT else None) or (lambda fn: fn)

_CSS = """<style>
.st-key-chat_fab { position: fixed; right: 24px; bottom: 24px; z-index: 1000; width: 56px; }
.st-key-chat_fab button { border-radius: 50%; width: 56px; height: 56px; font-size: 24px;
  box-shadow: 0 4px 14px rgba(0,0,0,.25); }
.st-key-chat_panel { position: fixed; right: 24px; bottom: 90px; z-index: 1000;
  width: min(440px, calc(100vw - 32px)); max-height: 78vh; overflow-y: auto; background: #ffffff;
  border: 1px solid #d9dee7; border-radius: 14px; padding: 8px 14px 14px;
  box-shadow: 0 10px 34px rgba(0,0,0,.22); }
</style>"""


def _rerun_panel():
    """Muat ulang hanya panel (Streamlit baru); jika tidak didukung, seluruh halaman."""
    try:
        st.rerun(scope="fragment")
    except Exception:
        st.rerun()


def _activate(vno: str):
    """Pastikan state roomchat (active_patient, messages, dst.) milik kunjungan ini, tanpa pindah halaman."""
    ss = st.session_state
    active = ss.get("active_patient")
    if active and active.get("mrn") == vno and "messages" in ss:
        return
    prev_view = ss.get("view")
    open_roomchat_for_mrn(vno)          # membuat roomchat bila belum ada; ia mengubah view ke "chat"
    ss.view = prev_view                 # kembalikan: tetap di halaman data


def _scroll_down():
    components.html(
        "<script>const p=window.parent.document.querySelector('.st-key-chat_panel');"
        "if(p){setTimeout(()=>{p.scrollTop=p.scrollHeight;},60);}</script>", height=0)


def _chat_body():
    ss = st.session_state
    patient = ss.active_patient

    C.render_voice_button()
    toggle = getattr(st, "toggle", None) or st.checkbox
    ss.agent_pref = bool(toggle("⚡ Mode agent (tool)", value=ss.get("agent_pref", True),
                                key="agent_toggle_float",
                                help="Nonaktif: mode cepat, 1 panggilan AI per pesan."))

    pending = ss.get("pending_input")
    if ss.get("active_question_mrn") != patient["mrn"]:
        ss.active_question = None
        ss.active_question_mrn = patient["mrn"]
    active_q = ss.get("active_question")

    messages = ss.messages
    last_msg = messages[-1] if messages else {}
    last_final = last_msg.get("role") == "assistant" and bool(last_msg.get("final", False))
    last_approved = last_msg.get("approved") if last_final else None
    has_user_msg = any(m["role"] == "user" for m in messages)

    shown = messages[-MAX_SHOWN:]
    if len(messages) > len(shown):
        st.caption(f"Menampilkan {len(shown)} pesan terakhir. Riwayat lengkap ada di tab Riwayat Roomchat.")
    for msg in shown:
        if msg["role"] == "user":
            st.markdown(C._user_bubble(msg), unsafe_allow_html=True)
        else:
            st.markdown(
                C._ai_bubble(C.strip_data_block(msg["content"]), codes=msg.get("codes"),
                             final=msg.get("final", False), approved=msg.get("approved"),
                             approval=msg.get("approval")),
                unsafe_allow_html=True)
            C._render_meta(msg)

    stream_slot = st.empty()
    error = ss.pop("last_error", None)
    if error:
        st.error(error)

    if has_user_msg:
        flags, status = C._agent_snapshot(patient["mrn"], messages)
        C._render_red_flags(flags)
        C._render_progress(status)

    if not pending:
        if last_final and last_approved is None:
            C._render_feedback(patient)         # persetujuan: memuat ulang seluruh halaman agar data kiri terbarui
        elif last_final and last_approved is True:
            st.caption("Anamnesis selesai dan tersimpan di Data Pasien. Tambahkan informasi baru "
                       "di kotak pesan bila ingin memperbarui kesimpulan.")
        elif active_q:
            st.info(f"❓ **Tanyakan ke pasien:** {active_q}\n\nKetik atau ucapkan **jawaban pasien** di bawah.")
            if st.button("Batal", key="fcancel_q"):
                ss.active_question = None
                _rerun_panel()
        else:
            for idx, text in enumerate((ss.get("quick_actions") or [])[:3]):
                if st.button(text, key=f"fqa_{idx}", use_container_width=True):
                    ss.active_question = text
                    ss.active_question_mrn = patient["mrn"]
                    _rerun_panel()
            if has_user_msg and not last_final:
                if st.button("📋 Minta Kesimpulan Sekarang", key="fask_final"):
                    C.send_user_message(FINAL_REQUEST_TEXT)
                    _rerun_panel()

    placeholder = ("Ketik atau ucapkan jawaban pasien..." if active_q
                   else "Ketik atau ucapkan keluhan / jawaban pasien...")
    user_input = st.chat_input(placeholder, disabled=bool(pending))
    if user_input:
        C.send_user_message(user_input, question=ss.pop("active_question", None))
        _rerun_panel()

    if pending:
        C._process_pending(stream_slot)


@_fragment
def _panel(vno: str, name: str, date_text: str):
    _activate(vno)
    with st.container(key="chat_panel"):
        st.markdown(C._header(name, f"Kunjungan {date_text} · {vno}", badge=""), unsafe_allow_html=True)
        _chat_body()
        _scroll_down()


def render_floating_chat(vno: str, name: str, date_text: str, archived: bool = False):
    """Panggil di akhir halaman kunjungan. Panel hanya terbuka untuk kunjungan yang sedang dilihat."""
    if archived:
        return
    st.markdown(_CSS, unsafe_allow_html=True)
    is_open = st.session_state.get("fchat_for") == vno
    with st.container(key="chat_fab"):
        if st.button("✕" if is_open else "💬", key="chat_fab_btn", help="Roomchat kunjungan ini"):
            st.session_state["fchat_for"] = None if is_open else vno
            st.rerun()
    if is_open:
        _panel(vno, name, date_text)