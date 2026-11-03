"""Panel konteks pasien di sisi kanan roomchat: ringkasan data pasien + log aktivitas pasien ini."""
import html
import streamlit as st
from auth import audit_log
from database import get_patient, list_supporting
from modules.patient_context import calc_age
_CSS = """<style>
.block-container{padding-right:21rem !important}
[data-testid="stBottom"]{padding-right:20rem}
.rp{position:fixed;top:3.75rem;right:0;width:20rem;height:calc(100vh - 3.75rem);overflow-y:auto;
padding:1rem 1.1rem 2rem;background:var(--secondary-background-color,#f6f7f9);
border-left:1px solid rgba(128,128,128,.25);z-index:99;font-size:13px;line-height:1.45}
.rp h4{margin:0 0 .6rem;font-size:13px;font-weight:600;opacity:.75}
.rp .nm{font-size:17px;font-weight:700}.rp .sub{opacity:.65;font-size:12px}
.rp .lb{margin:.9rem 0 .2rem;font-size:10.5px;letter-spacing:.04em;text-transform:uppercase;opacity:.55}
.rp hr{border:none;border-top:1px solid rgba(128,128,128,.25);margin:.9rem 0 0}
.rp .lg{padding:.3rem 0;border-bottom:1px dashed rgba(128,128,128,.2)}
.rp .lg small{opacity:.6;display:block}
.rp .nt{margin-top:1rem;font-size:11px;opacity:.55}
@media (max-width:1100px){.rp{display:none}.block-container{padding-right:1rem !important}
[data-testid="stBottom"]{padding-right:0}}
</style>"""
def _e(v) -> str:
    return html.escape(str(v))
def _sec(label: str, body: str) -> str:
    return f'<div class="lb">{label}</div><div>{body or "-"}</div>'
def _vitals(pe: dict) -> str:
    parts = []
    if pe.get("td_sistolik") and pe.get("td_diastolik"):
        parts.append(f"TD {pe['td_sistolik']}/{pe['td_diastolik']} mmHg")
    for key, fmt in (("nadi", "Nadi {} x/mnt"), ("spo2", "SpO2 {}%"), ("suhu", "Suhu {} °C"),
                     ("bb", "BB {} kg"), ("tb", "TB {} cm")):
        if pe.get(key):
            parts.append(fmt.format(pe[key]))
    return "<br>".join(_e(p) for p in parts)
def render_context_panel(mrn: str) -> None:
    p = get_patient(mrn)
    if not p:
        return
    age = calc_age(p.get("birth_date"))
    sub = " · ".join(x for x in (f"{age} tahun" if age is not None else "", p.get("sex") or "") if x)
    an = p.get("anamnesis") or {}
    complaints = "<br>".join(f"• {_e(c['term'])} <small>{_e(c['conceptId'])}</small>"
                             for c in p.get("chief_complaints") or [])
    support = "<br>".join(f"• {_e(s['category'])} · {_e(s.get('recorded_on') or (s['created_at'] or '')[:10])}"
                          for s in list_supporting(mrn)[:3])
    logs = "".join(
        f'<div class="lg">{_e(audit_log.ACTIONS.get(l["action"], l["action"]))}'
        f'<small>{_e(l["full_name"] or l["username"])} · {_e(l["created_at"][5:16].replace("-", "/", 1))}'
        f'{" · " + _e(l["detail"]) if l["detail"] else ""}</small></div>'
        for l in audit_log.list_logs(mrn=mrn, limit=8)
    ) or "<div>Belum ada aktivitas.</div>"
    body = "".join([
        "<h4>Konteks pasien</h4>",
        f'<div class="nm">{_e(p["name"])}</div><div class="sub">{_e(mrn)}</div>',
        f'<div class="sub">{_e(sub)}</div>' if sub else "",
        "<hr>",
        _sec("Keluhan utama", complaints),
        _sec("Tanda vital", _vitals(p.get("physical_exam") or {})),
        _sec("Obat dikonsumsi", _e(an.get("obat", "")).replace("\n", "<br>")),
        _sec("Alergi", _e(an.get("alergi", ""))),
        _sec("Data penunjang terbaru", support),
        _sec("Temuan SNOMED terkonfirmasi", str(len(p.get("confirmed_findings") or [])) or "0"),
        "<hr>",
        f'<div class="lb">Log aktivitas pasien ini</div>{logs}',
        '<div class="nt">Hanya referensi. Verifikasi seluruh informasi dengan rekam medis sebelum dipakai secara klinis.</div>',
    ])
    st.markdown(_CSS + f'<div class="rp">{body}</div>', unsafe_allow_html=True)