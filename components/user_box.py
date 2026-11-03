"""Menu akun di bawah sidebar (gaya Claude): chip nama/peran yang membuka menu Profil, Kelola akun, Keluar."""
import streamlit as st

from auth.service import ROLE_LABEL
from auth.session import current_account_page, current_user, logout, open_account_page
from components.admin_profile import render_profile_page
from components.admin_users import render_admin_users_page

_PAGES = {"profile": render_profile_page, "admin": render_admin_users_page}

# Ikon Material butuh Streamlit >= 1.37; versi lebih lama memakai emoji.
_MATERIAL = tuple(int(p) for p in st.__version__.split(".")[:2] if p.isdigit()) >= (1, 37)
_ICON = {
    "user": ":material/account_circle:" if _MATERIAL else "👤",
    "profile": ":material/person:" if _MATERIAL else "👤",
    "admin": ":material/manage_accounts:" if _MATERIAL else "⚙️",
    "logout": ":material/logout:" if _MATERIAL else "🚪",
}

_EC = ':is([data-testid="stElementContainer"],[data-testid="element-container"])'
_CSS = f"""
<style>
{_EC}:has(#um-anchor) {{display: none;}}
[data-testid="stVerticalBlock"]:has(> {_EC} #um-anchor) {{min-height: calc(100vh - 8rem);}}
{_EC}:has(#um-anchor) + {_EC} {{
  position: sticky; bottom: 0; margin-top: auto; z-index: 5; padding: .5rem 0;
  background: var(--secondary-background-color, #f0f2f6);
}}
{_EC}:has(#um-anchor) + {_EC} button {{
  border: none; background: rgba(128,128,128,.12); border-radius: 12px;
  justify-content: flex-start; text-align: left; padding: .6rem .75rem;
}}
{_EC}:has(#um-anchor) + {_EC} button:hover {{background: rgba(128,128,128,.2);}}
[data-testid="stPopoverBody"] .stButton > button {{
  border: none; background: transparent; box-shadow: none; justify-content: flex-start;
  text-align: left; padding: .45rem .6rem; border-radius: 8px;
}}
[data-testid="stPopoverBody"] .stButton > button:hover {{background: rgba(128,128,128,.14);}}
</style>
<span id="um-anchor"></span>
"""


def _item(label: str, icon_key: str, key: str) -> bool:
    return st.button(label, key=key, icon=_ICON[icon_key], use_container_width=True)


def render_user_box() -> None:
    """Panggil di AKHIR render_sidebar() agar menu berada di bagian bawah sidebar."""
    user = current_user()
    if not user:
        return
    with st.sidebar:
        st.markdown(_CSS, unsafe_allow_html=True)
        name = user["full_name"] or user["username"]
        with st.popover(f"{name} · {ROLE_LABEL.get(user['role'], user['role'])}",
                        icon=_ICON["user"], use_container_width=True):
            st.caption(f"@{user['username']}")
            st.divider()
            if _item("Profil", "profile", "menu_profile"):
                open_account_page("profile")
                st.rerun()
            if user["role"] == "admin" and _item("Kelola akun", "admin", "menu_admin"):
                open_account_page("admin")
                st.rerun()
            st.divider()
            if _item("Keluar", "logout", "menu_logout"):
                logout()
                st.rerun()


def render_account_page() -> bool:
    """True jika halaman profil/kelola akun sedang dibuka (app.py lalu memanggil st.stop())."""
    render = _PAGES.get(current_account_page())
    if not render:
        return False
    render()
    return True