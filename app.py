import random

import streamlit as st
from auth import audit_log
from components.context_panel import render_context_panel
from components.user_box import render_account_page   # taruh bersama import lainnya
from components.chat_ui import render_chat_room, send_user_message
from components.nav import go_to_patient_data, open_consultation, sync_url
from components.patient_data import render_patient_data_page
from components.sidebar import render_sidebar
from components.today_visits import render_today_page
from database import (
    create_visit,
    ensure_patient,
    get_all_consultations,
    list_patients,
    list_visits,
    save_or_update_consultation,
    set_visit_archived,
    update_patient_name,
)
from modules.ai_agent import DEFAULT_QUICK_ACTIONS
from modules.rag_snomed import warmup

st.set_page_config(page_title="Medical Anamnesis System", page_icon="🩺", layout="wide")
from auth.session import require_login
from components.admin_profile import render_profile_page
user = require_login()


NEW_PATIENT = "➕ Pasien baru"

# 1. Inisialisasi Session State
if "patient_list" not in st.session_state:
    st.session_state.patient_list = get_all_consultations()
if "active_patient" not in st.session_state:
    st.session_state.active_patient = None
if "messages" not in st.session_state:
    st.session_state.messages = []
if "quick_actions" not in st.session_state:
    st.session_state.quick_actions = []
if "pending_input" not in st.session_state:
    st.session_state.pending_input = None
if "view" not in st.session_state:
    st.session_state.view = "chat"
_restore_mrn = st.session_state.pop("_restore_mrn", None)  # roomchat terakhir sebelum refresh
if _restore_mrn and st.session_state.active_patient is None:
    for _c in st.session_state.patient_list:
        if _c["mrn"] == _restore_mrn:
            st.session_state.active_patient = _c
            st.session_state.messages = _c.get("messages", [])
            st.session_state.quick_actions = _c.get("quick_actions", [])
            break
if "new_mrn_default" not in st.session_state:
    st.session_state.new_mrn_default = f"MRN-{random.randint(10000, 99999)}"

# 2. Muat model pencarian SNOMED sekali di awal (bukan saat pesan pertama pasien)
try:
    with st.spinner("Memuat model pencarian SNOMED CT (hanya saat pertama kali)..."):
        warmup()
except Exception as e:
    st.warning(f"Pencarian SNOMED CT belum siap (jalankan ingest_chroma.py dulu): {e}")

# 3. Sidebar (URL disinkronkan dulu agar tombol Kembali browser berfungsi)
sync_url()
render_sidebar()
if render_account_page():
    st.stop()


def _open_visits(mrn: str) -> list:
    """Kunjungan yang roomchat-nya belum diarsipkan (terbaru dulu)."""
    return [v for v in list_visits(mrn) if not v["archived"]]


def render_new_consultation_form():
    st.title("🩺 Medical Anamnesis System")
    st.write(
        "Pilih pasien yang sudah terdaftar atau buat pasien baru. Tiap kunjungan punya data "
        "sendiri; data kunjungan sebelumnya tetap tersimpan dan terbaca."
    )

    patients = list_patients()
    all_names = {p["mrn"]: p["name"] for p in patients}
    names = all_names

    options = [NEW_PATIENT] + list(names.keys())
    selected = st.selectbox(
        "Pasien", options,
        format_func=lambda m: NEW_PATIENT if m == NEW_PATIENT else f"{names[m]} ({m})",
    )
    if selected == NEW_PATIENT:
        default_name, default_mrn, has_visit = "", st.session_state.new_mrn_default, False
    else:
        default_name, default_mrn, has_visit = names[selected], selected, bool(_open_visits(selected))

    with st.form("new_patient_form"):
        st.subheader("Pendaftaran / Konsultasi")
        p_name = st.text_input("Nama Pasien", value=default_name, key=f"form_name_{selected}")
        p_mrn = st.text_input("Medical Record Number (MRN)", value=default_mrn, key=f"form_mrn_{selected}")
        p_complaint = st.text_area("Keluhan Utama / catatan awal (opsional)", key=f"form_complaint_{selected}")
        new_visit = has_visit and st.checkbox(
            "Kunjungan baru (kunjungan lama tidak diubah; kalau tidak dicentang, lanjut kunjungan terakhir)",
            key=f"form_newvisit_{selected}",
        )
        submitted = st.form_submit_button("Mulai Konsultasi")

    if not submitted:
        return

    name, mrn, complaint = p_name.strip(), p_mrn.strip(), p_complaint.strip()
    if not name or not mrn:
        st.warning("Nama pasien dan MRN harus diisi!")
        return
    if selected == NEW_PATIENT and mrn in all_names:
        st.error(
            f"MRN {mrn} sudah terdaftar atas nama {all_names[mrn]}. "
            "Pilih pasien tersebut dari daftar, atau gunakan MRN lain."
        )
        return

    ensure_patient(mrn, name)
    if selected == NEW_PATIENT:
        audit_log.log("pasien_buat", mrn)

    visits = _open_visits(mrn)
    if new_visit or not visits:
        vno = create_visit(mrn)
        audit_log.log("kunjungan_baru", vno)
    else:
        vno = visits[0]["visit_no"]

    existing = next((c for c in st.session_state.patient_list if c["mrn"] == vno), None)
    if existing:
        existing["name"] = name
        open_consultation(existing)
    else:
        greeting = (
            f"Halo, saya asisten anamnesis kardiologi. Pasien {name} siap dianamnesis. "
            "Data kunjungan ini akan dipakai otomatis. "
            "Silakan ceritakan keluhan utama pasien atau pilih pertanyaan di bawah ini."
        )
        first_messages = [] if complaint else [{"role": "assistant", "content": greeting}]
        quick_actions = list(DEFAULT_QUICK_ACTIONS)
        save_or_update_consultation(name, vno, first_messages, quick_actions)
        audit_log.log("roomchat_mulai", vno)
        open_consultation({"name": name, "mrn": vno, "messages": first_messages,
                           "quick_actions": quick_actions})

    if complaint:
        send_user_message(complaint)

    st.session_state.patient_list = get_all_consultations()
    st.session_state.new_mrn_default = f"MRN-{random.randint(10000, 99999)}"
    st.rerun()


def render_roomchat_view():
    active = st.session_state.active_patient

    col_title, col_data, col_btn = st.columns([5, 2, 1])
    with col_title:
        st.subheader(f"RoomChat: {active['name']}")
        st.caption(f"Nomor Kunjungan: {active['mrn']}")

    with col_data:
        if st.button("🗂 Data Pasien", key="open_patient_data", use_container_width=True):
            go_to_patient_data(active["mrn"])
            st.rerun()

    with col_btn:
        with st.popover("⚙️ Menu", use_container_width=True):
            st.markdown("### Pengaturan Sesi")

            # Edit nama pasien
            new_name = st.text_input("Ubah Nama Pasien", value=active["name"])
            if st.button("Simpan Nama", use_container_width=True):
                if new_name.strip():
                    update_patient_name(active["mrn"], new_name.strip())
                    audit_log.log("identitas_ubah", active["mrn"], "nama diubah")
                    st.session_state.active_patient["name"] = new_name.strip()
                    st.session_state.patient_list = get_all_consultations()
                    st.rerun()

            st.divider()

            # Clear chat
            if st.button("🔄 Clear Chat", use_container_width=True):
                st.session_state.messages = []
                st.session_state.pending_input = None
                st.session_state.quick_actions = list(DEFAULT_QUICK_ACTIONS)
                active["messages"] = st.session_state.messages
                active["quick_actions"] = st.session_state.quick_actions
                save_or_update_consultation(
                    active["name"], active["mrn"], [], st.session_state.quick_actions
                )
                audit_log.log("chat_clear", active["mrn"])
                st.session_state.patient_list = get_all_consultations()
                st.rerun()

            st.divider()

            # Arsipkan: roomchat ini disembunyikan dari sidebar, tidak ada yang dihapus
            if st.button("📦 Arsipkan Roomchat", key="btn_arsip_pasien", use_container_width=True):
                set_visit_archived(active["mrn"], True)
                audit_log.log("pasien_arsip", active["mrn"])
                st.session_state.active_patient = None
                st.session_state.messages = []
                st.session_state.quick_actions = []
                st.session_state.pending_input = None
                st.session_state.patient_list = get_all_consultations()
                st.rerun()
            st.caption("Roomchat disembunyikan dari sidebar; data tetap ada di Data Pasien dan bisa diaktifkan kembali.")

    render_context_panel(active["mrn"])
    render_chat_room()


# --- Routing halaman ---
if st.session_state.view == "patient_data":
    render_patient_data_page()
elif st.session_state.view == "today":
    render_today_page()
elif st.session_state.active_patient is None:
    render_new_consultation_form()
else:
    render_roomchat_view()

sync_url()