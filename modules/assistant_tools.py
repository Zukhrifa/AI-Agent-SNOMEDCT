"""Alat baca-saja untuk Asisten Klinis (dokter/perawat): data kunjungan & pasien di sistem, serta
pedoman/SOP. Tidak ada alat yang mengubah data. Hasil dibatasi agar ringkas dan hemat token."""
import json
import re
import time

from database import _query, list_visits

MAX_ROWS = 15


def _clip(text, n=200) -> str:
    text = " ".join(str(text or "").split())
    return text[:n] + ("…" if len(text) > n else "")


def _terms(codes_json) -> list:
    try:
        return [c.get("term", "") for c in json.loads(codes_json or "[]") if c.get("term")][:6]
    except Exception:
        return []


def _status(approved, summary) -> str:
    return "disetujui dokter" if approved else ("belum diverifikasi" if summary else "belum ada hasil AI")


def _tool_find_visits(args: dict, ctx: dict) -> dict:
    d1 = str(args.get("date_from") or args.get("date") or "").strip()[:10]
    d2 = str(args.get("date_to") or d1).strip()[:10]
    kws = args.get("keywords") or []
    kws = [kws] if isinstance(kws, str) else [str(k) for k in kws]
    kws = [k.strip().lower() for k in kws if k.strip()][:6]
    try:
        limit = max(1, min(int(args.get("limit") or MAX_ROWS), 30))
    except (TypeError, ValueError):
        limit = MAX_ROWS

    where, params = [], []
    if d1:
        where.append("v.visit_date >= ?")
        params.append(d1)
    if d2:
        where.append("v.visit_date <= ?")
        params.append(d2)
    if kws:
        one = ("(LOWER(COALESCE(v.chief_complaints,'')) LIKE ? OR LOWER(COALESCE(v.confirmed_findings,'')) LIKE ? "
               "OR LOWER(COALESCE(v.anamnesis,'')) LIKE ? OR EXISTS (SELECT 1 FROM anamnesis_results r "
               "WHERE r.mrn = v.visit_no AND (LOWER(r.summary) LIKE ? OR LOWER(COALESCE(r.codes,'')) LIKE ?)))")
        where.append("(" + " OR ".join([one] * len(kws)) + ")")
        for k in kws:
            params += [f"%{k}%"] * 5
    best = "FROM anamnesis_results r WHERE r.mrn = v.visit_no ORDER BY r.approved DESC, r.id DESC LIMIT 1"
    rows = _query(
        f"SELECT v.visit_no, v.mrn, p.name, v.visit_date, (SELECT r.summary {best}), (SELECT r.approved {best}), "
        f"(SELECT r.codes {best}) FROM visits v JOIN patients p ON p.mrn = v.mrn "
        + ("WHERE " + " AND ".join(where) + " " if where else "")
        + "ORDER BY v.visit_date DESC, v.created_at DESC LIMIT ?",
        tuple(params) + (limit,),
    )
    return {
        "jumlah": len(rows),
        "kunjungan": [
            {"nomor_kunjungan": r[0], "mrn": r[1], "nama": r[2], "tanggal": r[3],
             "status_hasil": _status(r[5], r[4]), "diagnosis_terkode": _terms(r[6]), "ringkasan": _clip(r[4])}
            for r in rows
        ],
    }


def _tool_find_patients(args: dict, ctx: dict) -> dict:
    q = str(args.get("query", "")).strip().lower()
    if not q:
        return {"error": "argumen 'query' wajib diisi (nama atau MRN)"}
    rows = _query(
        "SELECT p.mrn, p.name, p.sex, p.birth_date, (SELECT COUNT(*) FROM visits v WHERE v.mrn = p.mrn) "
        "FROM patients p WHERE LOWER(p.name) LIKE ? OR LOWER(p.mrn) LIKE ? ORDER BY p.name LIMIT ?",
        (f"%{q}%", f"%{q}%", MAX_ROWS),
    )
    return {"jumlah": len(rows), "pasien": [
        {"mrn": r[0], "nama": r[1], "jenis_kelamin": r[2], "tanggal_lahir": r[3], "jumlah_kunjungan": r[4]}
        for r in rows]}


def _tool_patient_history(args: dict, ctx: dict) -> dict:
    mrn = str(args.get("mrn", "")).strip()
    rows = _query("SELECT mrn, name, sex, birth_date FROM patients WHERE mrn = ?", (mrn,))
    if not rows:
        return {"error": f"pasien dengan MRN '{mrn}' tidak ditemukan (gunakan find_patients dulu)"}
    p = rows[0]
    return {
        "pasien": {"mrn": p[0], "nama": p[1], "jenis_kelamin": p[2], "tanggal_lahir": p[3]},
        "kunjungan": [
            {"nomor_kunjungan": v["visit_no"], "tanggal": v["visit_date"],
             "status_hasil": _status(v["approved"], v["summary"]), "ringkasan": _clip(v["summary"])}
            for v in list_visits(mrn)[:10]
        ],
    }


def _tool_search_guidelines(args: dict, ctx: dict) -> dict:
    from modules.agent_tools import TOOLS  # dimuat saat dipakai
    return TOOLS["search_guidelines"]["fn"](args, ctx)


TOOLS = {
    "find_visits": {
        "fn": _tool_find_visits,
        "args": "date_from: YYYY-MM-DD; date_to: YYYY-MM-DD; keywords: daftar kata kunci; limit: angka (opsional)",
        "desc": ("Cari kunjungan di sistem menurut rentang tanggal dan/atau kata kunci diagnosis/keluhan. "
                 "Sertakan padanan Indonesia dan Inggris pada keywords, mis. [\"gagal jantung\",\"heart failure\"]. "
                 "Semua argumen opsional."),
        "label": "mencari kunjungan",
    },
    "find_patients": {
        "fn": _tool_find_patients,
        "args": "query: nama atau MRN (sebagian)",
        "desc": "Cari pasien menurut nama atau MRN.",
        "label": "mencari pasien",
    },
    "patient_history": {
        "fn": _tool_patient_history,
        "args": "mrn: string",
        "desc": "Riwayat kunjungan satu pasien beserta ringkasan hasil anamnesis tiap kunjungan.",
        "label": "membuka riwayat pasien",
    },
    "search_guidelines": {
        "fn": _tool_search_guidelines,
        "args": "query: string (kata kunci bahasa Indonesia, 2-6 kata)",
        "desc": "Cari kutipan dari dokumen SOP/pedoman rumah sakit yang diunggah admin (memuat dokumen dan halaman).",
        "label": "mencari di dokumen pedoman",
    },
}


def tools_prompt() -> str:
    try:
        from modules.guideline_rag import has_documents
        with_docs = has_documents()
    except Exception:
        with_docs = False
    return "\n".join(f"- {n}({s['args']}): {s['desc']}" for n, s in TOOLS.items()
                     if with_docs or n != "search_guidelines")


def tool_label(names) -> str:
    return "🔎 Membaca data sistem: " + ", ".join(TOOLS[n]["label"] for n in names if n in TOOLS) + "..."


_FENCE = re.compile(r"^```(?:json)?|```$", re.MULTILINE)


def parse_calls(text: str):
    """Ambil daftar tool dari balasan AI berbentuk JSON {"tool_calls":[...]}; None bila bukan permintaan tool."""
    t = _FENCE.sub("", text or "").strip()
    if not t.startswith("{"):
        return None
    data = None
    try:
        data = json.loads(t)
    except Exception:
        m = re.search(r"\{.*\}", t, re.S)
        if m:
            try:
                data = json.loads(m.group(0))
            except Exception:
                data = None
    calls = data.get("tool_calls") if isinstance(data, dict) else None
    calls = [c for c in calls if isinstance(c, dict)] if isinstance(calls, list) else []
    return calls[:3] or None


def run_calls(calls: list) -> list:
    out = []
    for c in calls:
        name = str(c.get("tool", "")).strip()
        args = c.get("args") if isinstance(c.get("args"), dict) else {}
        spec = TOOLS.get(name)
        started = time.perf_counter()
        if not spec:
            result = {"error": f"tool '{name}' tidak tersedia", "tool_tersedia": list(TOOLS)}
        else:
            try:
                result = spec["fn"](args, {})
            except Exception as e:  # noqa: BLE001 - dilaporkan ke AI, tidak menjatuhkan aplikasi
                result = {"error": f"{type(e).__name__}: {e}"}
        out.append({"tool": name, "args": args, "result": result, "ms": int((time.perf_counter() - started) * 1000)})
    return out


def format_results(outputs: list, last_step: bool) -> str:
    lines = ["HASIL TOOL (dari sistem, bukan karangan):"]
    for o in outputs:
        lines.append(f"- {o['tool']}({json.dumps(o['args'], ensure_ascii=False)}) -> "
                     f"{json.dumps(o['result'], ensure_ascii=False)[:3500]}")
    lines.append("Jawab sekarang dalam bahasa biasa (BUKAN JSON), hanya berdasarkan hasil ini. "
                 + ("Jangan memanggil tool lagi." if last_step else "Panggil tool lagi hanya bila benar-benar perlu."))
    return "\n".join(lines)