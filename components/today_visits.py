"""Kunjungan: admin menandai pasien yang berkunjung hari ini, semua peran melihat daftarnya (satu baris per pasien).
Tombol Data/Roomchat pada baris pasien membuka kunjungan HARI INI; kunjungan dibuat
otomatis saat pertama dibuka (satu pasien satu kunjungan per hari). Tanggal lampau
(pemilih tanggal) bersifat hanya-baca. Seluruh riwayat kunjungan ada di Data Pasien."""
import json
from collections import Counter
from datetime import date, datetime, timedelta

import streamlit as st
from auth import audit_log
from auth.session import current_user

from components.nav import go_to_patient_data, open_roomchat_for_mrn
from database import (_NOW, _query, _run, _write, create_visit, list_patient_overview,
                      list_visits)
from modules.patient_profile import allergy_map

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
        f"created_at TEXT DEFAULT ({_NOW}), queue_no INTEGER, PRIMARY KEY (visit_date, mrn))",
        (),
    )])
    try:  # tabel lama belum punya nomor antrean: tambahkan kolom + isi dari urutan tambah
        _run([("SELECT queue_no FROM today_visits LIMIT 1", ())])
    except Exception:
        _write([
            ("ALTER TABLE today_visits ADD COLUMN queue_no INTEGER", ()),
            ("UPDATE today_visits SET queue_no = (SELECT COUNT(*) FROM today_visits t "
             "WHERE t.visit_date = today_visits.visit_date "
             "AND (t.created_at < today_visits.created_at "
             "OR (t.created_at = today_visits.created_at AND t.mrn <= today_visits.mrn)))", ()),
        ])
    return True


STATUS = {
    "menunggu": ("⚪", "Menunggu"),
    "diisi": ("🟡", "Sedang diisi"),
    "persetujuan": ("🟠", "Menunggu persetujuan"),
    "selesai": ("🟢", "Selesai"),
}


def _loads(text, default):
    try:
        return json.loads(text) if text else default
    except (TypeError, ValueError):
        return default


def _has(value) -> bool:
    if isinstance(value, dict):
        return any(_has(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return any(_has(v) for v in value)
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (int, float)):
        return value != 0
    return bool(value)


@st.cache_data(ttl=10, show_spinner=False)
def _statuses(day: str) -> dict:
    """mrn -> kunci status, dihitung otomatis dari data kunjungan pada tanggal itu (tanpa tombol).
    Menunggu: belum ada data. Sedang diisi: ada data klinis/penunjang/chat. Menunggu persetujuan: ada hasil AI
    (draft di formulir atau kesimpulan roomchat) yang belum disetujui. Selesai: ada hasil AI yang disetujui."""
    rows = _query("SELECT mrn, visit_no, chief_complaints, anamnesis, physical_exam FROM visits "
                  "WHERE visit_date = ? ORDER BY created_at DESC", (day,))
    visits = {}
    for mrn, vno, cc, an, pe in rows:
        visits.setdefault(mrn, (vno, cc, an, pe))        # kunjungan terbaru per pasien
    if not visits:
        return {}
    vnos = tuple(v[0] for v in visits.values())
    marks = ",".join("?" * len(vnos))
    support = {r[0] for r in _query(
        f"SELECT DISTINCT mrn FROM patient_supporting WHERE mrn IN ({marks})", vnos)}
    results = {r[0]: (r[1], r[2]) for r in _query(
        f"SELECT mrn, MAX(approved), COUNT(*) FROM anamnesis_results WHERE mrn IN ({marks}) GROUP BY mrn", vnos)}
    chats = {}
    for vno, raw in _query(
            f"SELECT medical_record_no, messages FROM consultations WHERE medical_record_no IN ({marks})", vnos):
        msgs = _loads(raw, [])
        last = msgs[-1] if msgs else {}
        chats[vno] = (any(m.get("role") == "user" for m in msgs),
                      bool(last.get("final")) and last.get("approved") is None)
    out = {}
    for mrn, (vno, cc, an, pe) in visits.items():
        approved, count = results.get(vno, (0, 0))
        user_chat, chat_draft = chats.get(vno, (False, False))
        if approved:
            out[mrn] = "selesai"
        elif count or chat_draft:
            out[mrn] = "persetujuan"
        elif (_has(_loads(cc, [])) or _has(_loads(an, {})) or _has(_loads(pe, {}))
              or vno in support or user_chat):
            out[mrn] = "diisi"
        else:
            out[mrn] = "menunggu"
    return out


@st.cache_data(ttl=15, show_spinner=False)
def _overview() -> list:
    """Daftar pasien (dicache singkat): dipakai daftar hari ini dan panel 'Atur pasien'."""
    return list_patient_overview()


@st.cache_data(ttl=15, show_spinner=False)
def _allergies() -> dict:
    return allergy_map()


@st.cache_data(ttl=15, show_spinner=False)
def today_patients(day: str) -> list:
    """Pasien yang ditandai berkunjung pada tanggal `day` (urut sesuai waktu ditambahkan)."""
    _init_table()
    order = _query(
        "SELECT mrn, queue_no FROM today_visits WHERE visit_date = ? "
        "ORDER BY queue_no, created_at, mrn", (day,))
    if not order:
        return []
    info = {p["mrn"]: p for p in _overview()}
    return [{**info[m], "queue_no": q} for m, q in order if m in info]


def _add_today(mrns: list, by: str):
    _init_table()
    day = today_str()
    # Nomor antrean = nomor berikutnya hari itu, berurutan sesuai urutan `mrns` (urutan check-in).
    _write([("INSERT OR IGNORE INTO today_visits (visit_date, mrn, added_by, queue_no) VALUES "
             "(?, ?, ?, (SELECT COALESCE(MAX(queue_no), 0) + 1 FROM today_visits WHERE visit_date = ?))",
             (day, m, by, day)) for m in mrns])
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
        return "—"


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
            options = [p for p in _overview() if p["mrn"] not in in_today]
            labels = {p["mrn"]: f"{p['name']} ({p['mrn']})" for p in options}
            with st.form("form_add_today", clear_on_submit=True):
                chosen = st.multiselect("Pilih pasien (ketik untuk mencari)", list(labels),
                                        format_func=lambda m: labels[m])
                st.caption("Nomor antrean diberikan berurutan sesuai urutan pasien dipilih (check-in).")
                if st.form_submit_button("Check-in & beri nomor antrean") and chosen:
                    _add_today(chosen, (current_user() or {}).get("username", ""))
                    st.rerun()

    if not rows:
        st.info(("Belum ada pasien yang ditandai berkunjung hari ini."
                 + (" Tambahkan lewat panel di atas." if can_edit else ""))
                if is_today else "Tidak ada pasien yang tercatat pada tanggal ini.")
        return

    _rows_list(rows, day, can_edit)


def _render_row(no, r, statuses, allergies, day, can_edit, notice, done=False):
    mrn = r["mrn"]
    icon, label = STATUS[statuses.get(mrn, "menunggu")]
    dob = _fmt_date(r.get("birth_date")) if r.get("birth_date") else "—"
    allergy = allergies.get(mrn, "")
    with st.container(border=not done):
        cols = st.columns([2.6, 6, 1.5, 1.7, 0.7] if can_edit else [2.6, 6, 1.5, 1.7])
        cols[0].markdown(f"**No. {no}** · {icon} {label}")
        info = (f"**{r['name']}** · `{mrn}` · {r.get('sex') or '—'} · lahir {dob} · "
                + (f"⚠️ Alergi: {allergy}" if allergy else "Alergi: belum diisi"))
        cols[1].markdown(f":gray[{info}]" if done else info)
        if cols[2].button("📂 Data", key=f"today_data_{mrn}", use_container_width=True):
            v = _resolve_visit(mrn, day)
            if v:
                go_to_patient_data(v["visit_no"])
                st.rerun()
            notice.warning("Tidak ada kunjungan pada tanggal ini.")
        if cols[3].button("💬 Roomchat", key=f"today_chat_{mrn}", use_container_width=True):
            v = _resolve_visit(mrn, day)
            if not v:
                notice.warning("Tidak ada kunjungan pada tanggal ini.")
            elif v.get("archived"):
                notice.warning("Roomchat kunjungan ini sudah diarsipkan.")
            else:
                open_roomchat_for_mrn(v["visit_no"])
                st.rerun()
        if can_edit and cols[4].button("🗑", key=f"today_del_{mrn}",
                                       help="Keluarkan dari daftar hari ini"):
            _remove_today(mrn)
            st.rerun()


def _rows_list(rows: list, day: str, can_edit: bool):
    """Antrean: pasien belum selesai di atas (urut datang), pasien selesai di bawah divider."""
    notice = st.empty()
    allergies = _allergies()
    statuses = _statuses(day)
    count = Counter(statuses.get(r["mrn"], "menunggu") for r in rows)
    st.caption(" · ".join(f"{STATUS[k][0]} {STATUS[k][1]}: {count[k]}" for k in STATUS if count[k]))

    numbered = [(r.get("queue_no") or n, r) for n, r in enumerate(rows, start=1)]  # nomor antrean tetap
    is_done = lambda r: statuses.get(r["mrn"]) == "selesai"
    active = [(n, r) for n, r in numbered if not is_done(r)]
    done = [(n, r) for n, r in numbered if is_done(r)]

    for n, r in active:
        _render_row(n, r, statuses, allergies, day, can_edit, notice)
    if active == [] and done:
        st.success("Semua pasien hari ini sudah selesai diperiksa.")
    if done:
        st.divider()
        st.markdown(f"##### ✅ Sudah selesai diperiksa ({len(done)})")
        for n, r in done:
            _render_row(n, r, statuses, allergies, day, can_edit, notice, done=True)


def render_today_page():
    user = current_user() or {}
    st.session_state.today_mrn = None        # halaman detail pasien dihapus; bersihkan sisa URL lama (t=)
    st.title("Kunjungan Hari Ini" if _selected_day() == today_str() else "📅 Riwayat Kunjungan")
    _page_list(user.get("role") in TODAY_EDIT_ROLES)