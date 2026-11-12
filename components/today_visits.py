"""Kunjungan: admin menandai pasien yang berkunjung hari ini, semua peran melihat daftarnya.
Tombol Data/Roomchat pada baris pasien membuka kunjungan HARI INI; kunjungan dibuat
otomatis saat pertama dibuka (satu pasien satu kunjungan per hari). Tanggal lampau
(pemilih tanggal) bersifat hanya-baca. Seluruh riwayat kunjungan ada di Data Pasien."""
from datetime import date, datetime, timedelta

import streamlit as st
from auth import audit_log
from auth.session import current_user

from components.nav import go_to_patient_data, open_roomchat_for_mrn
from database import (_NOW, _query, _write, create_visit, list_patient_overview,
                      list_visits)

TODAY_VIEW_ROLES = ("admin", "dokter", "perawat")   # peran yang melihat menu Kunjungan
TODAY_EDIT_ROLES = ("admin",)                       # peran yang boleh mengatur daftar hari ini
SIDEBAR_MAX = 8                                     # tidak dipakai lagi; dibiarkan agar impor lama aman


def today_str() -> str:
    return (datetime.utcnow() + timedelta(hours=7)).date().isoformat()       # tanggal WIB


def go_to_today(mrn: str = None, keep_day: bool = False):
    """Buka halaman Kunjungan. Tanpa keep_day -> kembali ke hari ini (perilaku sidebar).
    Parameter mrn dipertahankan agar pemanggil lama tidak error (tidak dipakai lagi)."""
    st.session_state.view = "today"
    st.session_state.today_mrn = None
    if not keep_day:
        st.session_state.today_day = None


def _selected_day() -> str:
    day = st.session_state.get("today_day")
    return day if day and day <= today_str() else today_str()


@st.cache_resource(show_spinner=False)
def _init_table() -> bool:
    _write([(
        f"CREATE TABLE IF NOT EXISTS today_visits ("
        f"visit_date TEXT NOT NULL, mrn TEXT NOT NULL, added_by TEXT, "
        f"created_at TEXT DEFAULT ({_NOW}), PRIMARY KEY (visit_date, mrn))",
        (),
    )])
    return True


@st.cache_data(ttl=15, show_spinner=False)
def today_patients(day: str) -> list:
    """Pasien yang ditandai berkunjung pada tanggal `day` (urut sesuai waktu ditambahkan)."""
    _init_table()
    order = [r[0] for r in _query(
        "SELECT mrn FROM today_visits WHERE visit_date = ? ORDER BY created_at, mrn", (day,))]
    if not order:
        return []
    info = {p["mrn"]: p for p in list_patient_overview()}
    return [info[m] for m in order if m in info]


def _add_today(mrns: list, by: str):
    _init_table()
    day = today_str()
    _write([("INSERT OR IGNORE INTO today_visits (visit_date, mrn, added_by) VALUES (?, ?, ?)",
             (day, m, by)) for m in mrns])
    today_patients.clear()
    for m in mrns:
        audit_log.log("pasien_hari_ini_tambah", m)


def _remove_today(mrn: str):
    _write([("DELETE FROM today_visits WHERE visit_date = ? AND mrn = ?", (today_str(), mrn))])
    today_patients.clear()
    audit_log.log("pasien_hari_ini_hapus", mrn)


def _fmt_date(iso) -> str:
    try:
        return datetime.strptime(str(iso)[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
    except Exception:
        return iso or "-"


def _resolve_visit(mrn: str, day: str):
    """Kunjungan pasien pada tanggal `day`. Khusus hari ini: dibuat otomatis jika belum ada.
    Mengembalikan dict (minimal visit_no, archived) atau None (tanggal lampau tanpa kunjungan)."""
    visit = next((v for v in list_visits(mrn) if str(v["visit_date"])[:10] == day), None)
    if visit is None and day == today_str():
        vno = create_visit(mrn)
        audit_log.log("kunjungan_baru", vno)
        return {"visit_no": vno, "archived": False}
    return visit


def _page_list(can_edit: bool):
    today, day = today_str(), _selected_day()
    is_today = day == today
    can_edit = can_edit and is_today          # daftar hari lalu hanya-baca

    c_pick, c_now, _ = st.columns([3, 2, 5])
    picked = c_pick.date_input("Tanggal", value=date.fromisoformat(day),
                               max_value=date.fromisoformat(today),
                               format="DD/MM/YYYY").isoformat()
    if picked != day:
        st.session_state.today_day = None if picked == today else picked
        st.rerun()
    if not is_today and c_now.button("↩ Hari ini", key="today_reset", use_container_width=True):
        st.session_state.today_day = None
        st.rerun()

    rows = today_patients(day)
    if is_today:
        st.caption(f"Pasien yang berkunjung hari ini ({_fmt_date(day)}). Klik **Data** atau "
                   "**Roomchat** untuk mengisi kunjungan hari ini; kunjungan dibuat otomatis.")
    else:
        st.caption(f"Riwayat pasien yang berkunjung pada {_fmt_date(day)} (hanya-baca).")

    if can_edit:
        with st.expander("➕ Atur pasien hari ini", expanded=not rows):
            in_today = {p["mrn"] for p in rows}
            options = [p for p in list_patient_overview() if p["mrn"] not in in_today]
            labels = {p["mrn"]: f"{p['name']} ({p['mrn']})" for p in options}
            with st.form("form_add_today", clear_on_submit=True):
                chosen = st.multiselect("Pilih pasien (ketik untuk mencari)", list(labels),
                                        format_func=lambda m: labels[m])
                if st.form_submit_button("Tambahkan ke hari ini") and chosen:
                    _add_today(chosen, (current_user() or {}).get("username", ""))
                    st.rerun()

    if not rows:
        st.info(("Belum ada pasien yang ditandai berkunjung hari ini."
                 + (" Tambahkan lewat panel di atas." if can_edit else ""))
                if is_today else "Tidak ada pasien yang tercatat pada tanggal ini.")
        return

    notice = st.empty()
    widths = [3, 2, 2, 2, 2, 2, 1] if can_edit else [3, 2, 2, 2, 2, 2]
    heads = ["Nama", "No. RM", "Jenis kelamin", "Tanggal lahir", "", ""] + ([""] if can_edit else [])
    with st.container(border=True):
        for col, label in zip(st.columns(widths), heads):
            col.caption(label)
        for r in rows:
            mrn = r["mrn"]
            cols = st.columns(widths)
            cols[0].write(r["name"])
            cols[1].write(mrn)
            cols[2].write(r.get("sex") or "—")
            cols[3].write(_fmt_date(r.get("birth_date")))
            if cols[4].button("📂 Data", key=f"today_data_{mrn}", use_container_width=True):
                v = _resolve_visit(mrn, day)
                if v:
                    go_to_patient_data(v["visit_no"])
                    st.rerun()
                notice.warning("Tidak ada kunjungan pada tanggal ini.")
            if cols[5].button("💬 Roomchat", key=f"today_chat_{mrn}", use_container_width=True):
                v = _resolve_visit(mrn, day)
                if not v:
                    notice.warning("Tidak ada kunjungan pada tanggal ini.")
                elif v.get("archived"):
                    notice.warning("Roomchat kunjungan ini sudah diarsipkan.")
                else:
                    open_roomchat_for_mrn(v["visit_no"])
                    st.rerun()
            if can_edit and cols[6].button("🗑", key=f"today_del_{mrn}",
                                           help="Keluarkan dari daftar hari ini"):
                _remove_today(mrn)
                st.rerun()


def render_today_page():
    user = current_user() or {}
    st.session_state.today_mrn = None        # halaman detail pasien dihapus; bersihkan sisa URL lama (t=)
    st.title("📅 Kunjungan Hari Ini" if _selected_day() == today_str() else "📅 Riwayat Kunjungan")
    _page_list(user.get("role") in TODAY_EDIT_ROLES)