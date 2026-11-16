import json
from datetime import date, datetime

from database import _query, get_patient, get_visit, list_anamnesis_results, list_supporting
from modules.patient_profile import get_profile


MAX_CONTEXT_CHARS = 4500
MAX_SUPPORTING_ITEMS = 8
MAX_PREVIOUS_VISITS = 2
PREVIOUS_SUMMARY_CHARS = 350
PREVIOUS_NOTE_CHARS = 250


# "rps" milik kunjungan; sisanya riwayat tetap milik pasien (modules/patient_profile.py).
ANAMNESIS_LABELS = [
    ("rps", "Riwayat penyakit sekarang"),
    ("rpd", "Riwayat penyakit dahulu"),
    ("rpk", "Riwayat keluarga"),
    ("obat", "Obat yang dikonsumsi"),
    ("alergi", "Alergi"),
    ("kebiasaan", "Kebiasaan (merokok/alkohol/aktivitas)"),
]


EXAM_LABELS = [
    ("pe_jantung", "Pemeriksaan jantung"),
    ("pe_paru", "Pemeriksaan paru"),
    ("pe_lain", "Pemeriksaan lain"),
]


def calc_age(birth_date):
    """Usia (tahun) dari 'YYYY-MM-DD'. None jika tidak valid."""
    try:
        born = datetime.strptime(str(birth_date), "%Y-%m-%d").date()
    except Exception:
        return None
    today = date.today()
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


def _num(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number


def format_vitals(pe: dict) -> str:
    parts = []
    sistol, diastol = _num(pe.get("td_sistolik")), _num(pe.get("td_diastolik"))
    if sistol and diastol:
        parts.append(f"TD {sistol:.0f}/{diastol:.0f} mmHg")
    if _num(pe.get("nadi")):
        parts.append(f"nadi {_num(pe.get('nadi')):.0f} x/menit")
    if _num(pe.get("rr")):
        parts.append(f"RR {_num(pe.get('rr')):.0f} x/menit")
    if _num(pe.get("suhu")):
        parts.append(f"suhu {_num(pe.get('suhu')):.1f} °C")
    if _num(pe.get("spo2")):
        parts.append(f"SpO2 {_num(pe.get('spo2')):.0f}%")
    bb, tb = _num(pe.get("bb")), _num(pe.get("tb"))
    if bb:
        parts.append(f"BB {bb:g} kg")
    if tb:
        parts.append(f"TB {tb:g} cm")
    if bb and tb:
        parts.append(f"IMT {bb / ((tb / 100) ** 2):.1f}")
    return ", ".join(parts)


def _fmt(iso) -> str:
    try:
        return datetime.strptime(str(iso)[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
    except Exception:
        return str(iso)[:10]


def _previous_visit_lines(vno: str) -> list:
    """Kunjungan SEBELUM kunjungan ini: tanggal, keluhan/RPS yang dicatat, dan kesimpulan yang
    sudah disetujui dokter. Hanya pembanding; AI diminta menyebut tanggalnya bila relevan."""
    visit = get_visit(vno)
    if not visit:
        return []
    rows = _query(
        "SELECT v.visit_no, v.visit_date, v.anamnesis, r.summary, r.codes FROM visits v "
        "LEFT JOIN anamnesis_results r ON r.mrn = v.visit_no AND r.approved = 1 "
        "WHERE v.mrn = ? AND v.visit_no != ? AND v.created_at <= ? "
        "ORDER BY v.created_at DESC, r.id DESC",
        (visit["mrn"], vno, visit["created_at"]),
    )
    out, seen = [], set()
    for v_no, v_date, an_raw, summary, codes in rows:
        if v_no in seen:
            continue
        seen.add(v_no)
        try:
            an = json.loads(an_raw or "{}")
        except Exception:
            an = {}
        parts = []
        note = " ".join(f"{an.get('keluhan_utama', '')} {an.get('rps', '')}".split())[:PREVIOUS_NOTE_CHARS]
        if note:
            parts.append(f"keluhan/RPS: {note}")
        if summary:
            parts.append("kesimpulan disetujui: " + " ".join(str(summary).split())[:PREVIOUS_SUMMARY_CHARS])
            try:
                terms = ", ".join(c.get("term", "") for c in json.loads(codes or "[]") if c.get("term"))[:200]
            except Exception:
                terms = ""
            if terms:
                parts.append(f"temuan: {terms}")
        if parts:
            out.append(f"- Kunjungan {_fmt(v_date)}: " + "; ".join(parts))
        if len(out) >= MAX_PREVIOUS_VISITS:
            break
    if not out:
        return []
    return ["RIWAYAT KUNJUNGAN SEBELUMNYA (pembanding; keluhan hari ini tetap dari data kunjungan ini). "
            "Bila relevan dengan keluhan hari ini (mis. rawat inap, serangan jantung, tindakan), "
            "sebut tanggal kunjungannya di kesimpulan, mis. \"pada kunjungan 10/11/2026 tercatat ...\":"] + out


def build_patient_context(mrn: str) -> str:
    """Ringkasan data pasien tersimpan (untuk konteks AI). '' jika belum ada data."""
    patient = get_patient(mrn)
    if not patient:
        return ""

    lines = []

    identity = []
    age = calc_age(patient.get("birth_date"))
    if age is not None:
        identity.append(f"usia {age} tahun")
    if patient.get("sex"):
        identity.append(f"jenis kelamin {patient['sex']}")
    if identity:
        lines.append("Identitas: " + ", ".join(identity))

    manual = str((patient.get("anamnesis") or {}).get("keluhan_utama", "")).strip()
    if manual:
        lines.append(f"Keluhan utama (ditulis perawat): {manual}")

    complaints = patient.get("chief_complaints") or []
    if complaints:
        lines.append(
            "Keluhan utama (istilah SNOMED CT): "
            + "; ".join(f"{c.get('term', '')} ({c.get('conceptId', '')})" for c in complaints)
        )

    visit_anamnesis = patient.get("anamnesis") or {}
    profile = get_profile(mrn)
    for key, label in ANAMNESIS_LABELS:
        value = str((visit_anamnesis if key == "rps" else profile).get(key, "")).strip()
        if value:
            lines.append(f"{label}: {value}")
    if not profile["alergi"]:
        lines.append("Alergi: belum diisi (jangan menganggap pasien tidak punya alergi)")

    exam = patient.get("physical_exam") or {}
    vitals = format_vitals(exam)
    if vitals:
        lines.append(f"Tanda vital: {vitals}")
    for key, label in EXAM_LABELS:
        value = str(exam.get(key, "")).strip()
        if value:
            lines.append(f"{label}: {value}")

    supporting = list_supporting(mrn)[:MAX_SUPPORTING_ITEMS]
    if supporting:
        lines.append("Data penunjang:")
        for item in supporting:
            when = item.get("recorded_on") or (item.get("created_at") or "")[:10]
            content = " ".join(str(item["content"]).split())[:300]
            lines.append(f"- [{item['category']}, {when}] {content}")

    findings = patient.get("confirmed_findings") or []
    if findings:
        lines.append(
            "Temuan terkonfirmasi dokter (SNOMED CT): "
            + "; ".join(
                f"{f.get('kategori', '')}: {f.get('term', '')} ({f.get('conceptId', '')})"
                for f in findings[:15]
            )
        )

    previous = [r for r in list_anamnesis_results(mrn, limit=3) if r.get("approved")][:1]
    if previous:
        summary = " ".join(previous[0]["summary"].split())[:600]
        lines.append(f"Kesimpulan anamnesis yang disetujui sebelumnya ({previous[0]['created_at']}): {summary}")

    lines.extend(_previous_visit_lines(mrn))

    text = "\n".join(lines).strip()
    return text[:MAX_CONTEXT_CHARS]