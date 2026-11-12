"""Halaman profil (nama, peran, ganti password sendiri) dan form ganti password awal."""
import streamlit as st

from auth import service
from auth.session import close_account_page, current_user, logout, refresh_user
from modules.ai_agent import MODEL_NAME, PROVIDERS, get_user_llm, test_user_llm


def _password_form(user: dict, key: str, forced: bool = False) -> None:
    with st.form(key, clear_on_submit=True):
        current = st.text_input("Password saat ini", type="password", autocomplete="current-password")
        new = st.text_input("Password baru", type="password", autocomplete="new-password",
                            help="Minimal 10 karakter, mengandung huruf dan angka.")
        confirm = st.text_input("Ulangi password baru", type="password", autocomplete="new-password")
        submitted = st.form_submit_button("Simpan dan lanjutkan" if forced else "Ganti password",
                                          type="primary", use_container_width=forced)
    if not submitted:
        return
    error = service.change_password(user["id"], current, new, confirm)
    if error:
        st.error(error)
        return
    refresh_user()
    st.success("Password berhasil diganti.")
    if forced:
        st.rerun()


def render_force_password_change(user: dict) -> None:
    """Dipakai saat must_change_password aktif (login pertama, atau akun baru buatan admin)."""
    st.markdown("<style>[data-testid='stSidebar'], [data-testid='collapsedControl'] {display:none;}</style>",
                unsafe_allow_html=True)
    _, col, _ = st.columns([1, 1.15, 1])
    with col:
        st.subheader("Ganti password awal")
        st.info("Demi keamanan, ganti password sementara Anda sebelum melanjutkan.")
        _password_form(user, "force_pw_form", forced=True)
        if st.button("Keluar", key="force_pw_logout"):
            logout()
            st.rerun()


def _llm_section() -> None:
    """AI bawaan sistem untuk semua pengguna; API key pribadi (Gemini/OpenAI/Claude) hanya berlaku
    untuk akun ini dan hanya di memori sesi (tidak ditulis ke database)."""
    st.subheader("🔑 Penyedia AI & API Key")
    cfg = get_user_llm()
    if cfg:
        st.success(f"Memakai {PROVIDERS[cfg['provider']]['label']} · {cfg['model']} dengan API key pribadi "
                   f"Anda (hanya untuk sesi ini).", icon="✅")
    else:
        st.info(f"Memakai AI bawaan sistem (Gemini {MODEL_NAME}). Isi API key di bawah jika ingin memakai "
                "akun AI Anda sendiri.", icon="ℹ️")
    with st.expander("Gunakan API key pribadi (opsional)"):
        provider = st.selectbox("Penyedia", list(PROVIDERS), format_func=lambda p: PROVIDERS[p]["label"],
                                key="llm_provider")
        with st.form("llm_form", clear_on_submit=True):
            model = st.text_input("Nama model", value=PROVIDERS[provider]["default_model"],
                                  key=f"llm_model_{provider}")
            api_key = st.text_input("API Key", type="password")
            submitted = st.form_submit_button("Uji & pakai", type="primary")
        st.caption("API key hanya disimpan di memori sesi ini: tidak ditulis ke database dan hilang saat logout "
                   "atau halaman dimuat ulang. Isi percakapan (termasuk data pasien) dikirim ke penyedia yang "
                   "Anda pilih, sesuaikan dengan kebijakan data rumah sakit.")
        if submitted:
            new_cfg = {"provider": provider, "model": model.strip(), "api_key": api_key.strip()}
            if not new_cfg["model"] or len(new_cfg["api_key"]) < 20 or any(c.isspace() for c in new_cfg["api_key"]):
                st.error("Nama model dan API key (tanpa spasi) wajib diisi dengan benar.")
            else:
                with st.spinner("Menguji koneksi..."):
                    error = test_user_llm(new_cfg)
                if error:
                    st.error(f"Gagal terhubung: {error}")
                else:
                    st.session_state["user_llm"] = new_cfg
                    st.rerun()
        if cfg and st.button("Kembali ke AI sistem", key="llm_reset"):
            st.session_state.pop("user_llm", None)
            st.rerun()


def render_profile_page() -> None:
    user = current_user()
    if not user:
        return
    if st.button("← Kembali", key="profile_back"):
        close_account_page()
        st.rerun()
    st.title("Profil")
    with st.container(border=True):
        st.subheader(user["full_name"] or user["username"])
        st.markdown(f"**Peran:** {service.ROLE_LABEL.get(user['role'], user['role'])}")
        st.caption(f"Username: {user['username']}  •  Login terakhir: {user['last_login_at'] or '-'} WIB")
    _llm_section()
    st.subheader("Ganti password")
    _password_form(user, "change_pw_form")