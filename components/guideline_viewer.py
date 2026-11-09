"""Pratinjau dan unduh dokumen pedoman: tombol sumber di jawaban AI (lompat ke halaman
kutipan) dan halaman telusur dokumen untuk SEMUA peran (admin/dokter/perawat).

Pratinjau berupa jendela MENGAMBANG (bisa digeser, diubah ukurannya, di-zoom) yang dipasang
di halaman utama, sehingga roomchat tetap terlihat dan bisa dibandingkan dengan dokumen.
Halaman PDF dirender di server (pypdfium2) jadi gambar JPEG, bukan <embed>/<iframe>/data-URI
(dibuang Streamlit / diblokir Chrome). Unggah dan hapus tetap khusus admin (components/admin_docs.py)."""

import base64
import io
import json

import streamlit as st
import streamlit.components.v1 as components

from auth import audit_log
from auth.session import close_account_page, require_login
from modules import guideline_rag as rag

SPAN = 4        # halaman sebelum & sesudah halaman kutipan yang ikut dimuat (kecil = cepat)
SCALE = 1.4     # ketajaman render; naikkan ke 1.8 jika teks kurang tajam
JPEG_QUALITY = 70


@st.cache_data(show_spinner=False, ttl=300, max_entries=3)
def _load_file(doc_id: int):
    """File asli dari DB di-cache supaya klik berikutnya tidak mengunduh ulang blob dari database."""
    return rag.get_file(doc_id)


@st.cache_data(show_spinner=False, max_entries=48)
def _render_pages(doc_id: int, first: int, last: int, _data: bytes):
    """Render halaman first..last (1-based) jadi JPEG base64. Return (total_halaman, first, [b64...])."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(_data)
    try:
        total = len(pdf)
        first, last = max(1, first), min(last, total)
        out = []
        for p in range(first, last + 1):
            img = pdf[p - 1].render(scale=SCALE).to_pil().convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=JPEG_QUALITY)
            out.append(base64.b64encode(buf.getvalue()).decode("ascii"))
        return total, first, out
    finally:
        pdf.close()


# Kode jendela mengambang. Dijalankan di halaman induk (bukan di iframe) agar tetap hidup
# saat Streamlit me-rerun dan menghapus iframe pembawanya.
_PANEL_JS = r"""
(function(){
  var P = window.__gvPayload, d = document;
  var old = d.getElementById('gv-float'); if (old) old.remove();
  var last = P.first + P.imgs.length - 1;
  var cur = Math.min(Math.max(P.start || P.first, P.first), last);
  var zoom = 100;
  function mk(tag, css, txt){ var e = d.createElement(tag); if (css) e.style.cssText = css; if (txt) e.textContent = txt; return e; }
  var vw = window.innerWidth, vh = window.innerHeight;
  var w = Math.min(460, vw - 16), h = Math.min(Math.round(vh * 0.8), 720);
  var box = mk('div', 'position:fixed;z-index:999990;display:flex;flex-direction:column;background:#fff;color:#222;' +
    'border:1px solid rgba(0,0,0,.3);border-radius:10px;box-shadow:0 8px 30px rgba(0,0,0,.4);resize:both;overflow:hidden;' +
    'min-width:260px;min-height:220px;max-width:98vw;max-height:98vh;font:14px system-ui,sans-serif;' +
    'width:' + w + 'px;height:' + h + 'px;left:' + Math.max(8, vw - w - 16) + 'px;top:64px;');
  box.id = 'gv-float';
  var head = mk('div', 'display:flex;align-items:center;gap:6px;padding:6px 8px;background:#f3f4f6;cursor:move;' +
    'border-bottom:1px solid #d1d5db;touch-action:none;user-select:none;');
  var title = mk('div', 'flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:600;', '⠿ ' + P.title);
  title.title = P.title + (P.section ? ' · ' + P.section : '');
  function btn(t, tip, fn){
    var b = mk('button', 'border:1px solid #d1d5db;background:#fff;color:#222;border-radius:6px;padding:2px 9px;cursor:pointer;font:inherit;', t);
    b.title = tip; b.addEventListener('click', fn); return b;
  }
  var bPrev = btn('◀', 'Halaman sebelumnya', function(){ go(-1); });
  var lbl = mk('span', 'min-width:84px;text-align:center;white-space:nowrap;');
  var bNext = btn('▶', 'Halaman berikutnya', function(){ go(1); });
  var bZo = btn('−', 'Perkecil', function(){ setZoom(zoom - 20); });
  var bZi = btn('+', 'Perbesar', function(){ setZoom(zoom + 20); });
  var bX = btn('✕', 'Tutup', function(){ box.remove(); });
  [title, bPrev, lbl, bNext, bZo, bZi, bX].forEach(function(e){ head.appendChild(e); });
  var sub = mk('div', 'padding:3px 10px;font-size:12px;color:#6b7280;background:#fafafa;border-bottom:1px solid #e5e7eb;' +
    'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;', P.section || '');
  var body = mk('div', 'flex:1;overflow:auto;background:#e5e7eb;padding:6px;');
  var img = mk('img', 'display:block;margin:0 auto;background:#fff;box-shadow:0 1px 4px rgba(0,0,0,.3);');
  body.appendChild(img);
  box.appendChild(head); if (P.section) box.appendChild(sub); box.appendChild(body);
  d.body.appendChild(box);

  function setZoom(z){ zoom = Math.min(300, Math.max(40, z)); img.style.width = zoom + '%'; }
  function show(){
    img.src = 'data:image/jpeg;base64,' + P.imgs[cur - P.first];
    lbl.textContent = 'Hal. ' + cur + ' / ' + P.total;
    bPrev.disabled = cur <= P.first; bNext.disabled = cur >= last;
    bPrev.style.opacity = bPrev.disabled ? .4 : 1; bNext.style.opacity = bNext.disabled ? .4 : 1;
    bPrev.title = bPrev.disabled ? 'Batas halaman yang dimuat (hal. ' + P.first + '–' + last + '); buka ulang dari sumber lain' : 'Halaman sebelumnya';
    bNext.title = bNext.disabled ? 'Batas halaman yang dimuat (hal. ' + P.first + '–' + last + '); buka ulang dari sumber lain' : 'Halaman berikutnya';
    body.scrollTop = 0;
  }
  function go(n){ var c = cur + n; if (c >= P.first && c <= last){ cur = c; show(); } }
  setZoom(100); show();

  var drag = false, ox = 0, oy = 0;
  head.addEventListener('pointerdown', function(e){
    if (e.target.tagName === 'BUTTON') return;
    drag = true; var r = box.getBoundingClientRect(); ox = e.clientX - r.left; oy = e.clientY - r.top;
    head.setPointerCapture(e.pointerId); e.preventDefault();
  });
  head.addEventListener('pointermove', function(e){
    if (!drag) return;
    box.style.left = Math.min(Math.max(0, e.clientX - ox), window.innerWidth - 80) + 'px';
    box.style.top = Math.min(Math.max(0, e.clientY - oy), window.innerHeight - 40) + 'px';
  });
  function stop(){ drag = false; }
  head.addEventListener('pointerup', stop); head.addEventListener('pointercancel', stop);
})();
"""


def _show_floating(payload: dict) -> None:
    """Pasang/ganti jendela mengambang di halaman induk lewat iframe 0 tinggi."""
    data = json.dumps(payload).replace("</", "<\\/")
    html = (
        "<script>(function(){var w=window.parent,d=w.document;"
        f"w.__gvPayload={data};"
        "try{var f=window.frameElement;if(f&&f.parentElement)f.parentElement.style.display='none';}catch(e){}"
        f"var s=d.createElement('script');s.textContent={json.dumps(_PANEL_JS)};d.head.appendChild(s);s.remove();"
        "})();</script>"
    )
    components.html(html, height=0)


def _open_viewer(doc_id: int, title: str, page=None, section: str = "") -> None:
    file = _load_file(doc_id)
    if not file:
        st.warning(
            "File asli dokumen ini tidak tersimpan (diunggah sebelum fitur pratinjau tersedia). "
            "Minta admin mengunggah ulang agar bisa dibuka dan diunduh."
        )
        return
    audit_log.log("dokumen_lihat", None, title + (f" hal. {page}" if page else ""))
    if file["content_type"] != "application/pdf":
        st.info("Pratinjau halaman hanya tersedia untuk PDF. Unduh file untuk membaca dokumen DOCX ini.")
        return
    start = int(page) if page else 1
    try:
        total, first, imgs = _render_pages(doc_id, max(1, start - SPAN), start + SPAN, file["data"])
    except ImportError:
        st.warning("Pratinjau butuh paket pypdfium2 (py -m pip install pypdfium2).")
        return
    except Exception as e:
        st.warning(f"Pratinjau gagal dibuat ({e}). Unduh file untuk membaca.")
        return
    _show_floating({"title": title, "section": section, "start": start, "first": first,
                    "total": total, "imgs": imgs})


def render_source_button(doc_id, title: str, page=None, section: str = "", key: str = "") -> None:
    """Tombol kecil di bawah jawaban AI: buka dokumen asli, langsung ke halaman kutipan
    (verifikasi keaslian sitasi). Kutipan lama tanpa doc_id tampil sebagai teks biasa."""
    label = f"📄 {title}" + (f", hal. {page}" if page else "") + (f" ({section})" if section else "")
    if doc_id is None:
        st.caption(f"- {label}")
        return
    if st.button(label, key=key or f"src_{doc_id}_{page}_{section}"):
        _open_viewer(doc_id, title, page, section)


def render_file_download_button(doc: dict, key: str) -> None:
    """Tombol unduh file asli untuk satu baris dokumen (dipakai di halaman admin & halaman umum)."""
    file = _load_file(doc["id"])
    if not file:
        st.caption("File asli tidak tersedia")
        return
    st.download_button(
        "⬇ Unduh", data=file["data"], file_name=file["filename"], mime=file["content_type"],
        key=key, use_container_width=True,
    )


def render_guidelines_page() -> None:
    """Halaman telusur dokumen pedoman: semua peran (admin/dokter/perawat) bisa lihat & unduh.
    Mengunggah dan menghapus hanya lewat menu admin 'Kelola Dokumen'."""
    require_login()
    if st.button("← Kembali", key="docs_view_back"):
        close_account_page()
        st.rerun()
    st.title("Dokumen Pedoman")
    st.caption("Referensi yang dipakai AI saat menjawab. Pilih halaman lalu klik 👁 untuk membuka jendela "
               "pratinjau (bisa digeser), atau unduh file asli.")
    docs = rag.list_documents()
    if not docs:
        st.info("Belum ada dokumen pedoman yang diunggah.")
        return
    for d in docs:
        c1, c2, c3, c4, c5 = st.columns([3.0, 1.5, 0.8, 1.0, 1.1])
        c1.markdown(f"**{d['title']}**  \n{d['filename']}")
        c2.caption(f"{d['doc_type'] or '-'}  \n{d['pages']} halaman · diunggah @{d['uploaded_by']}")
        pg = c3.number_input("Hal.", min_value=1, max_value=max(1, int(d["pages"] or 1)), value=1,
                             key=f"pg_{d['id']}", label_visibility="collapsed")
        if c4.button("👁 Buka", key=f"view_{d['id']}", use_container_width=True):
            _open_viewer(d["id"], d["title"], pg)
        with c5:
            render_file_download_button(d, key=f"dl_browse_{d['id']}")
        st.divider()