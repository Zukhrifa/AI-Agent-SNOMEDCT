"""Tool, status, dan aturan deterministik untuk AI agent anamnesis.

Semua yang ada di sini dihitung oleh KODE (milidetik, tanpa panggilan LLM):
- tanda bahaya (red flags) dari tanda vital, data penunjang, dan kata kunci percakapan
- checklist kelengkapan anamnesis
- skor risiko HEART
- tool yang boleh dipanggil oleh AI (search_snomed, get_patient_record, check_red_flags, calculate_heart_score, search_guidelines)

PENTING: ambang batas dan aturan klinis di file ini adalah contoh umum untuk keperluan
pembelajaran. Tinjau dan sesuaikan bersama dokter/pembimbing sebelum dipakai di luar demo.
"""
import json
import re
import time

from database import get_patient, list_anamnesis_results, list_supporting
from modules.patient_context import calc_age, format_vitals
from modules.guideline_rag import has_documents, search as search_guideline_chunks
from modules.rag_snomed import search_terms

CONTROL_PREFIX = "Permintaan dokter:"

# ---------------------------------------------------------------------------
# Checklist anamnesis (status agent: apa yang sudah / belum digali)
# ---------------------------------------------------------------------------
CHECKLIST = [
    ("onset", "kapan mulai"),
    ("provocation", "pemicu & peredam"),
    ("quality", "karakter nyeri"),
    ("radiation", "penjalaran"),
    ("severity", "tingkat keparahan"),
    ("duration", "durasi / pola"),
    ("associated", "gejala penyerta"),
    ("risk_factors", "faktor risiko"),
    ("history", "riwayat penyakit jantung / penyakit dahulu"),
    ("medications", "obat & alergi"),
]
CHECKLIST_KEYS = [key for key, _ in CHECKLIST]
CHECKLIST_LABELS = dict(CHECKLIST)


def clean_covered(items) -> list:
    """Saring daftar 'covered' dari AI: hanya kunci checklist yang valid, tanpa duplikat."""
    if not isinstance(items, list):
        return []
    result = []
    for item in items:
        key = str(item).strip().lower()
        if key in CHECKLIST_LABELS and key not in result:
            result.append(key)
    return result


def covered_from_messages(messages) -> set:
    covered = set()
    for msg in messages or []:
        if msg.get("role") == "assistant":
            covered.update(clean_covered(msg.get("covered")))
    return covered


def covered_from_patient(patient) -> set:
    """Item checklist yang otomatis terisi dari data pasien tersimpan."""
    covered = set()
    if not patient:
        return covered
    anamnesis = patient.get("anamnesis") or {}

    def filled(key):
        return bool(str(anamnesis.get(key, "")).strip())

    if filled("obat") or filled("alergi"):
        covered.add("medications")
    if filled("rpd"):
        covered.add("history")
    if filled("kebiasaan") or filled("rpk"):
        covered.add("risk_factors")
    return covered


def checklist_status(messages, patient=None) -> dict:
    covered = covered_from_messages(messages) | covered_from_patient(patient)
    return {
        "covered": [k for k in CHECKLIST_KEYS if k in covered],
        "missing": [k for k in CHECKLIST_KEYS if k not in covered],
        "done": len([k for k in CHECKLIST_KEYS if k in covered]),
        "total": len(CHECKLIST_KEYS),
    }


# ---------------------------------------------------------------------------
# Tanda bahaya (red flags)
# ---------------------------------------------------------------------------
# (kunci_vital, operator, ambang, level, label, satuan) - urutkan 'critical' sebelum 'warn'
VITAL_RULES = [
    ("td_sistolik", ">=", 180, "critical", "Tekanan darah sistolik sangat tinggi", "mmHg"),
    ("td_sistolik", "<=", 90, "critical", "Hipotensi (sistolik rendah)", "mmHg"),
    ("td_diastolik", ">=", 120, "critical", "Tekanan darah diastolik sangat tinggi", "mmHg"),
    ("spo2", "<", 90, "critical", "Hipoksemia berat (SpO2 rendah)", "%"),
    ("spo2", "<", 94, "warn", "Saturasi oksigen rendah", "%"),
    ("nadi", ">", 120, "warn", "Takikardia", "x/menit"),
    ("nadi", "<", 50, "warn", "Bradikardia", "x/menit"),
    ("rr", ">", 24, "warn", "Takipnea (napas cepat)", "x/menit"),
    ("suhu", ">=", 38.5, "warn", "Demam tinggi", "°C"),
]

# (pola regex, level, pesan) - dicocokkan pada ucapan pasien (huruf kecil)
TEXT_RULES = [
    (r"pingsan|sinkop|tidak\s+sadar(kan diri)?", "critical", "Pingsan/sinkop dilaporkan"),
    (r"sesak(\s+(napas|nafas))?\s+(yang\s+)?(berat|hebat|mendadak)", "critical", "Sesak napas berat/mendadak dilaporkan"),
    (r"keringat\s+dingin", "warn", "Keringat dingin (kemungkinan diaforesis)"),
    (
        r"nyeri\s+(dada\s+)?(yang\s+)?(hebat|sangat\s+berat)|ditindih|tertindih|ditimpa|diremas|ditekan\s+benda",
        "warn",
        "Karakter nyeri dada khas iskemik (seperti ditindih/diremas)",
    ),
    (r"menjalar\s+ke\s+(lengan|rahang|leher|bahu|punggung)", "warn", "Nyeri menjalar ke lengan/rahang/leher/punggung"),
]

# Dicocokkan pada teks data penunjang
SUPPORT_RULES = [
    (r"st[\s\-]*(elevasi|elevation)|stemi", "critical", "Data penunjang menyebut ST elevasi / STEMI"),
    (r"troponin[^.\n]{0,40}(meningkat|positif|tinggi|elevated)", "warn", "Data penunjang menyebut troponin meningkat"),
]

_NEGATION = re.compile(r"\b(tidak|tak|tanpa|bukan|belum|disangkal|negatif|no)\b")


def _is_negated(text: str, match) -> bool:
    window = text[max(0, match.start() - 25):match.end()]
    return bool(_NEGATION.search(window))


def _num(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _vital_flags(exam: dict) -> list:
    flags, seen = [], set()
    for key, op, threshold, level, label, unit in VITAL_RULES:
        value = _num(exam.get(key))
        if not value:  # 0 = belum diukur
            continue
        hit = {
            ">": value > threshold, ">=": value >= threshold,
            "<": value < threshold, "<=": value <= threshold,
        }[op]
        direction = "high" if op in (">", ">=") else "low"
        if hit and (key, direction) not in seen:
            seen.add((key, direction))
            flags.append({"level": level, "message": f"{label} ({value:g} {unit})", "source": "vital"})
    return flags


def _pattern_flags(texts, rules, source) -> list:
    flags, seen = [], set()
    for text in texts:
        low = str(text).lower()
        for pattern, level, message in rules:
            match = re.search(pattern, low)
            if match and message not in seen and not _is_negated(low, match):
                seen.add(message)
                flags.append({"level": level, "message": message, "source": source})
    return flags


def _duration_flag(texts) -> list:
    for text in texts:
        low = str(text).lower()
        if "nyeri" not in low and "sakit" not in low:
            continue
        for match in re.finditer(r"(\d+)\s*(menit|jam)", low):
            number, unit = int(match.group(1)), match.group(2)
            if (unit == "jam" and number >= 1) or (unit == "menit" and number >= 20):
                if not _is_negated(low, match):
                    return [{
                        "level": "warn",
                        "message": "Keluhan nyeri berdurasi ≥20 menit dilaporkan (periksa apakah masih berlangsung)",
                        "source": "percakapan",
                    }]
    return []


def compute_red_flags(patient, texts, supporting=None) -> list:
    """Return daftar {'level', 'message', 'source'}; 'critical' di urutan pertama."""
    flags = []
    exam = (patient or {}).get("physical_exam") or {}
    flags += _vital_flags(exam)
    flags += _pattern_flags(texts or [], TEXT_RULES, "percakapan")
    flags += _duration_flag(texts or [])
    support_texts = [str(item.get("content", "")) for item in (supporting or [])]
    flags += _pattern_flags(support_texts, SUPPORT_RULES, "penunjang")
    flags.sort(key=lambda f: 0 if f["level"] == "critical" else 1)
    return flags


def conversation_texts(messages) -> list:
    """Ucapan pasien dari riwayat pesan (tanpa pertanyaan dokter dan tanpa pesan kontrol)."""
    texts = []
    for msg in messages or []:
        if msg.get("role") != "user":
            continue
        content = str(msg.get("answer") or msg.get("content") or "")
        if content.startswith(CONTROL_PREFIX):
            continue
        if not msg.get("answer") and "Jawaban pasien:" in content:
            content = content.split("Jawaban pasien:", 1)[1]
        content = content.strip()
        if content:
            texts.append(content)
    return texts


def red_flags_for_mrn(mrn: str, messages) -> list:
    """Dipakai UI: tanda bahaya terkini untuk satu pasien + percakapannya."""
    patient = get_patient(mrn)
    return compute_red_flags(patient, conversation_texts(messages), list_supporting(mrn))


def format_agent_state(flags, status) -> str:
    """Teks 'STATUS AGENT' untuk prompt: tanda bahaya + checklist (dihitung kode, bukan LLM)."""
    lines = []
    if flags:
        lines.append("Tanda bahaya terdeteksi (aturan sistem; sebutkan dan prioritaskan dalam jawaban):")
        for flag in flags:
            tag = "KRITIS" if flag["level"] == "critical" else "PERHATIAN"
            lines.append(f"- [{tag}] {flag['message']}")
    else:
        lines.append("Tanda bahaya: tidak ada yang terdeteksi dari data yang tersedia.")

    missing = ", ".join(f"{k} ({CHECKLIST_LABELS[k]})" for k in status["missing"]) or "-"
    lines.append(f"Checklist anamnesis terisi {status['done']}/{status['total']}.")
    lines.append("Sudah digali: " + (", ".join(status["covered"]) or "-"))
    lines.append("Belum digali: " + missing)
    lines.append(
        "Pilih pertanyaan berikutnya dari yang BELUM digali. Pada \"covered\" tulis semua kunci yang "
        "sudah digali (kumulatif, termasuk dari jawaban terbaru)."
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Skor HEART (stratifikasi risiko nyeri dada akut)
# ---------------------------------------------------------------------------
def _score_history(value):
    text = str(value or "").strip().lower()
    if not text:
        return None
    if re.search(r"high|tinggi|sangat|^2$", text):
        return 2
    if re.search(r"moderate|sedang|^1$", text):
        return 1
    if re.search(r"low|slight|ringan|rendah|^0$", text):
        return 0
    return None


def _score_ecg(value):
    text = str(value or "").strip().lower()
    if not text:
        return None
    if re.search(r"st[\s_\-]*(dev|elev|depr)|deviasi|elevasi|depresi|iskemik|ischem|^2$", text):
        return 2
    if re.search(r"non[\s\-_]*specific|tidak\s+spesifik|non[\s\-_]*spesifik|lbbb|lvh|paced|digoxin|repolari|^1$", text):
        return 1
    if re.search(r"normal|^0$", text):
        return 0
    return None


def _score_age(age):
    try:
        years = float(age)
    except (TypeError, ValueError):
        return None
    if years < 0:
        return None
    if years < 45:
        return 0
    if years < 65:
        return 1
    return 2


def _truthy(value):
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in ("true", "ya", "yes", "1", "ada")


def _score_risk(count, atherosclerotic):
    if _truthy(atherosclerotic):
        return 2
    try:
        number = int(float(count))
    except (TypeError, ValueError):
        return None
    if number < 0:
        return None
    if number == 0:
        return 0
    return 1 if number <= 2 else 2


def _score_troponin(value):
    text = str(value or "").strip().lower()
    if not text:
        return None
    if re.search(r">\s*3|lebih\s+dari\s+3|high|tinggi|^2$", text):
        return 2
    if re.search(r"1\s*[\-–_]\s*3|ringan|mild|slight|^1$", text):
        return 1
    if re.search(r"normal|negatif|negative|tidak\s+meningkat|<=|^0$", text):
        return 0
    return None


def _heart_category(total: int) -> str:
    if total <= 3:
        return "rendah (0-3)"
    if total <= 6:
        return "sedang (4-6)"
    return "tinggi (7-10)"


def heart_score(history=None, ecg=None, age=None, risk_factor_count=None,
                atherosclerotic_disease=None, troponin=None) -> dict:
    """Hitung skor HEART. Komponen yang tidak diketahui TIDAK ditebak: hasilnya berupa kisaran."""
    components = {
        "history": _score_history(history),
        "ecg": _score_ecg(ecg),
        "age": _score_age(age),
        "risk_factors": _score_risk(risk_factor_count, atherosclerotic_disease),
        "troponin": _score_troponin(troponin),
    }
    known_total = sum(v for v in components.values() if v is not None)
    missing = [k for k, v in components.items() if v is None]
    max_total = known_total + 2 * len(missing)

    low_cat, high_cat = _heart_category(known_total), _heart_category(max_total)
    if not missing:
        category, complete = low_cat, True
    else:
        category = low_cat if low_cat == high_cat else "belum dapat ditentukan"
        complete = False

    return {
        "score": known_total,
        "range": [known_total, max_total],
        "category": category,
        "complete": complete,
        "components": components,
        "missing": missing,
        "note": (
            "Skor pendukung keputusan, bukan diagnosis. Komponen yang kosong tidak ditebak; "
            "lengkapi (mis. EKG, troponin) lalu hitung ulang. Verifikasi oleh dokter."
        ),
    }


# ---------------------------------------------------------------------------
# Tool yang boleh dipanggil AI
# ---------------------------------------------------------------------------
def _tool_search_snomed(args: dict, ctx: dict) -> dict:
    term = str(args.get("term", "")).strip()
    if not term:
        return {"error": "argumen 'term' wajib diisi"}
    return {"results": search_terms(term, 5)}


def _tool_get_patient_record(args: dict, ctx: dict) -> dict:
    mrn = ctx.get("mrn")
    patient = ctx.get("patient") or (get_patient(mrn) if mrn else None)
    if not patient:
        return {"error": "data pasien tidak ditemukan"}

    section = str(args.get("section", "all")).strip().lower() or "all"
    exam = patient.get("physical_exam") or {}
    full = {
        "identity": {
            "name": patient.get("name"),
            "age": calc_age(patient.get("birth_date")),
            "sex": patient.get("sex"),
        },
        "chief_complaints": patient.get("chief_complaints") or [],
        "anamnesis": patient.get("anamnesis") or {},
        "vitals": format_vitals(exam) or "belum ada data",
        "exam": {k: exam.get(k, "") for k in ("pe_jantung", "pe_paru", "pe_lain") if exam.get(k)},
        "supporting": [
            {"kategori": s["category"], "tanggal": s.get("recorded_on"), "isi": str(s["content"])[:400]}
            for s in list_supporting(mrn)[:8]
        ],
        "confirmed": patient.get("confirmed_findings") or [],
        "previous": [
            {"tanggal": r["created_at"], "disetujui": r["approved"], "ringkasan": r["summary"][:500]}
            for r in list_anamnesis_results(mrn, 2)
        ],
    }
    if section == "all":
        return full
    if section in full:
        return {section: full[section]}
    return {"error": f"section '{section}' tidak dikenal", "section_tersedia": ["all"] + list(full)}


def _tool_check_red_flags(args: dict, ctx: dict) -> dict:
    mrn = ctx.get("mrn")
    patient = ctx.get("patient") or (get_patient(mrn) if mrn else None)
    flags = compute_red_flags(patient, ctx.get("texts") or [], list_supporting(mrn) if mrn else [])
    return {"red_flags": flags, "jumlah": len(flags)}


def _tool_heart_score(args: dict, ctx: dict) -> dict:
    age = args.get("age")
    if age in (None, ""):
        patient = ctx.get("patient")
        age = calc_age((patient or {}).get("birth_date")) if patient else None
    return heart_score(
        history=args.get("history"),
        ecg=args.get("ecg"),
        age=age,
        risk_factor_count=args.get("risk_factor_count"),
        atherosclerotic_disease=args.get("atherosclerotic_disease"),
        troponin=args.get("troponin"),
    )


def _tool_search_guidelines(args: dict, ctx: dict) -> dict:
    query = str(args.get("query", "")).strip()
    if not query:
        return {"error": "argumen 'query' wajib diisi"}
    hits = search_guideline_chunks(query, 3)
    if not hits:
        return {
            "results": [],
            "info": "tidak ada kutipan yang relevan di dokumen pedoman. Katakan terus terang dan jangan mengarang; "
                    "boleh coba sekali lagi dengan kata kunci lain.",
        }
    return {"results": [
        {"dokumen": h["title"], "halaman": h["page"], "bagian": h["section"], "kutipan": h["excerpt"]}
        for h in hits
    ]}


TOOLS = {
    "search_snomed": {
        "fn": _tool_search_snomed,
        "args": "term: string",
        "desc": "Cari konsep SNOMED CT terdekat untuk satu istilah (Indonesia/Inggris); maksimal 5 hasil.",
        "label": "mencari kode SNOMED",
    },
    "get_patient_record": {
        "fn": _tool_get_patient_record,
        "args": "section: all|identity|chief_complaints|anamnesis|vitals|exam|supporting|confirmed|previous (opsional)",
        "desc": "Ambil detail data pasien tersimpan (lebih lengkap daripada ringkasan di atas).",
        "label": "membuka data pasien",
    },
    "check_red_flags": {
        "fn": _tool_check_red_flags,
        "args": "(tanpa argumen)",
        "desc": "Hitung ulang tanda bahaya dari tanda vital, data penunjang, dan percakapan.",
        "label": "memeriksa tanda bahaya",
    },
    "search_guidelines": {
        "fn": _tool_search_guidelines,
        "args": "query: string (kata kunci bahasa Indonesia seperti di dokumen, 2-6 kata)",
        "desc": (
            "Cari kutipan faktual dari dokumen SOP/pedoman yang diunggah admin; hasilnya memuat nama dokumen, "
            "halaman, dan bagian. Pakai saat dokter bertanya soal prosedur, pemeriksaan, tatalaksana, atau kriteria."
        ),
        "label": "mencari di dokumen pedoman",
    },
    "calculate_heart_score": {
        "fn": _tool_heart_score,
        "args": (
            "history: low|moderate|high; ecg: normal|nonspecific|st_deviation; "
            "age: angka (opsional, otomatis dari data pasien); risk_factor_count: angka; "
            "atherosclerotic_disease: true|false; troponin: normal|1-3x|>3x"
        ),
        "desc": (
            "Hitung skor HEART (risiko nyeri dada akut) oleh sistem. Isi HANYA argumen yang diketahui dari fakta; "
            "yang tidak diketahui jangan diisi (tidak ditebak)."
        ),
        "label": "menghitung skor HEART",
    },
}


def tools_prompt() -> str:
    show_guidelines = has_documents()  # tool pedoman hanya ditawarkan bila sudah ada dokumen
    return "\n".join(
        f"- {name}({spec['args']}): {spec['desc']}"
        for name, spec in TOOLS.items()
        if show_guidelines or name != "search_guidelines"
    )


def tool_label(names) -> str:
    labels = [TOOLS[n]["label"] for n in names if n in TOOLS] or ["menjalankan tool"]
    return "🔧 Agent sedang " + ", ".join(labels) + "..."


def _summarize(name: str, result: dict) -> str:
    if isinstance(result, dict) and "error" in result:
        return "error: " + str(result["error"])[:120]
    if name == "calculate_heart_score" and isinstance(result, dict) and "score" in result:
        suffix = "" if result.get("complete") else f" (sementara, kisaran {result['range'][0]}-{result['range'][1]})"
        return f"skor {result['score']}{suffix}: {result['category']}"
    if name == "check_red_flags" and isinstance(result, dict):
        return f"{result.get('jumlah', 0)} tanda bahaya"
    if name == "search_guidelines" and isinstance(result, dict):
        return f"{len(result.get('results', []))} kutipan pedoman"
    if name == "search_snomed" and isinstance(result, dict):
        return f"{len(result.get('results', []))} konsep ditemukan"
    return json.dumps(result, ensure_ascii=False)[:140]


def execute_tool_calls(calls, ctx, max_calls: int = 3) -> list:
    """Jalankan tool yang diminta AI. Tidak pernah melempar error: kegagalan dikembalikan sebagai hasil."""
    outputs = []
    for call in (calls or [])[:max_calls]:
        name = str(call.get("tool", "")).strip()
        args = call.get("args") if isinstance(call.get("args"), dict) else {}
        spec = TOOLS.get(name)

        started = time.perf_counter()
        if not spec:
            result = {"error": f"tool '{name}' tidak tersedia", "tool_tersedia": list(TOOLS)}
        else:
            try:
                result = spec["fn"](args, ctx)
            except Exception as e:  # noqa: BLE001 - kegagalan tool dilaporkan ke AI, bukan menjatuhkan aplikasi
                result = {"error": f"{type(e).__name__}: {e}"}
        elapsed_ms = int((time.perf_counter() - started) * 1000)

        outputs.append({
            "tool": name,
            "args": args,
            "result": result,
            "summary": _summarize(name, result),
            "ms": elapsed_ms,
        })
    return outputs


RESULT_LIMIT = {"search_guidelines": 3500}  # batas karakter hasil tool yang dikirim ke AI (default 1500)


def sources_of(item: dict) -> list:
    """Sumber pedoman dari hasil tool (untuk ditampilkan di UI di bawah jawaban)."""
    if item.get("tool") != "search_guidelines" or not isinstance(item.get("result"), dict):
        return []
    return [
        {"dokumen": r.get("dokumen"), "halaman": r.get("halaman"), "bagian": r.get("bagian")}
        for r in item["result"].get("results", [])
    ]


def format_tool_results(outputs, last_step: bool = False) -> str:
    lines = ["HASIL TOOL (dari sistem, bukan dari pasien):"]
    for item in outputs:
        args_text = json.dumps(item["args"], ensure_ascii=False)
        result_text = json.dumps(item["result"], ensure_ascii=False)[:RESULT_LIMIT.get(item["tool"], 1500)]
        lines.append(f"- {item['tool']}({args_text}) -> {result_text}")
    lines.append(
        "Gunakan hasil ini untuk memberi jawaban akhir (status ask atau final) dalam format yang sama."
    )
    if last_step:
        lines.append("Ini langkah terakhir: JANGAN memanggil tool lagi.")
    else:
        lines.append("Jangan memanggil tool yang sama dengan argumen yang sama lagi.")
    return "\n".join(lines)