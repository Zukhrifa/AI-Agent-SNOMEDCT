"""Halaman admin: unggah dan kelola dokumen SOP/pedoman yang dipakai AI sebagai referensi (RAG).
Hanya admin: require_admin() menghentikan halaman untuk peran lain, dan modul guideline_rag
memeriksa peran lagi saat menyimpan/menghapus."""
import streamlit as st

from auth import audit_log
from auth.session import close_account_page, require_admin
from modules import guideline_rag as rag

_dialog = getattr(st, "dialog", None) or st.experimental_dialog  # st.dialog butuh Streamlit >= 1.37
_W = [3.2, 2.0, 0.9, 1.0, 2.2, 0.7]
_HEAD = ["Dokumen", "Jenis", "Halaman", "Kutipan", "Diunggah", "Hapus"]


@_dialog("Konfirmasi hapus")
def _confirm_delete(admin: dict, doc: dict) -> None:
    st.warning(f"Hapus **{doc['title']}** ({doc['pages']} halaman)? AI tidak bisa lagi mengutip dokumen ini.")
    c1, c2 = st.columns(2)
    if c1.button("Batal", use_container_width=True):
        st.rerun()
    if c2.button("Ya, hapus", type="primary", use_container_width=True):
        try:
            rag.delete_document(admin, doc["id"])
        except Exception as e:
            st.error(f"Gagal menghapus: {e}")
            return
        audit_log.log("dokumen_hapus", None, doc["title"])
        st.rerun()


def _upload_section(admin: dict) -> None:
    st.subheader("Unggah dokumen")
    st.caption(
        "Format: PDF (disarankan, ada nomor halaman) atau DOCX. PDF hasil scan/gambar belum bisa dibaca. "
        "Jangan unggah dokumen yang berisi data pasien."
    )
    done = st.session_state.pop("doc_upload_done", None)
    if done:
        st.success(done["message"])
        for warning in done["warnings"]:
            st.warning(warning)

    n = st.session_state.get("doc_upload_n", 0)
    file = st.file_uploader("File SOP / pedoman", type=["pdf", "docx"], key=f"doc_file_{n}")
    default_title = file.name.rsplit(".", 1)[0] if file else ""
    title = st.text_input("Judul dokumen", value=default_title, key=f"doc_title_{n}_{default_title}")
    doc_type = st.selectbox("Jenis dokumen", rag.DOC_TYPES, key=f"doc_type_{n}")

    if st.button("Proses & simpan", type="primary", disabled=file is None, key="doc_save"):
        try:
            with st.spinner("Membaca dokumen dan membuat kutipan..."):
                info = rag.add_document(admin, file.getvalue(), file.name, title, doc_type)
        except ValueError as e:
            st.error(str(e))
            return
        except Exception as e:
            st.error(f"Gagal menyimpan dokumen: {e}")
            return
        audit_log.log("dokumen_unggah", None, f"{title} ({info['pages']} hal, {info['chunks']} kutipan)")
        warnings = []
        if info["empty_pages"]:
            warnings.append(f"{info['empty_pages']} halaman tidak punya teks terbaca (mungkin gambar) dan dilewati.")
        if not info["has_pages"]:
            warnings.append(
                "DOCX tidak punya nomor halaman tetap, jadi sumber hanya menyebut nama dokumen dan bagian. "
                "Unggah versi PDF bila ingin sitasi halaman."
            )
        st.session_state["doc_upload_done"] = {
            "message": f"Tersimpan: {title} ({info['pages']} halaman, {info['chunks']} kutipan).",
            "warnings": warnings,
        }
        st.session_state["doc_upload_n"] = n + 1  # kosongkan kotak unggah
        st.rerun()


def _list_section(admin: dict) -> None:
    st.subheader("Dokumen tersimpan")
    docs = rag.list_documents()
    if not docs:
        st.info("Belum ada dokumen. AI baru memakai fitur pedoman setelah ada dokumen yang diunggah.")
        return
    cols = st.columns(_W)
    for c, head in zip(cols, _HEAD):
        c.markdown(f"**{head}**")
    for d in docs:
        c = st.columns(_W)
        c[0].markdown(f"**{d['title']}**  \n{d['filename']}")
        c[1].write(d["doc_type"] or "-")
        c[2].write(d["pages"])
        c[3].write(d["chunk_count"])
        c[4].write(f"{d['uploaded_by']}  \n{d['created_at']}")
        if c[5].button("🗑", key=f"doc_del_{d['id']}", help="Hapus dokumen"):
            _confirm_delete(admin, d)


def _test_section() -> None:
    st.subheader("Uji pencarian")
    st.caption("Cek kutipan apa yang akan ditemukan AI. Pakai kata kunci seperti yang tertulis di dokumen.")
    query = st.text_input("Kata kunci", key="doc_test_query", placeholder="mis. nyeri dada EKG 10 menit")
    if not query.strip():
        return
    results = rag.search(query, 4)
    if not results:
        st.info("Tidak ada kutipan yang cocok.")
        return
    for r in results:
        label = f"{r['title']} - hal. {r['page'] if r['page'] else '-'}"
        if r["section"]:
            label += f" - {r['section']}"
        with st.expander(f"{label} (skor {r['score']})"):
            st.write(r["excerpt"])


def render_admin_docs_page() -> None:
    admin = require_admin()
    if st.button("← Kembali", key="docs_back"):
        close_account_page()
        st.rerun()
    st.title("Dokumen Pedoman (RAG)")
    st.write(
        "Dokumen yang diunggah di sini menjadi referensi faktual AI. Saat dokter menanyakan prosedur atau "
        "pemeriksaan, AI mencari kutipan lalu menyebut nama dokumen, halaman, dan bagiannya."
    )
    _upload_section(admin)
    _list_section(admin)
    _test_section()