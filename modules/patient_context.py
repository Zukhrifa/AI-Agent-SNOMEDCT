from datetime import date, datetime

from database import get_patient, list_anamnesis_results, list_supporting

MAX_CONTEXT_CHARS = 3500
MAX_SUPPORTING_ITEMS = 8

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

    complaints = patient.get("chief_complaints") or []
    if complaints:
        lines.append(
            "Keluhan utama (istilah SNOMED CT): "
            + "; ".join(f"{c.get('term', '')} ({c.get('conceptId', '')})" for c in complaints)
        )

    anamnesis = patient.get("anamnesis") or {}
    for key, label in ANAMNESIS_LABELS:
        value = str(anamnesis.get(key, "")).strip()
        if value:
            lines.append(f"{label}: {value}")

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

    previous = list_anamnesis_results(mrn, limit=1)
    if previous:
        summary = " ".join(previous[0]["summary"].split())[:600]
        lines.append(f"Kesimpulan anamnesis AI sebelumnya ({previous[0]['created_at']}): {summary}")

    text = "\n".join(lines).strip()
    return text[:MAX_CONTEXT_CHARS]