"""XLENT-logo og felles branding for alle sider."""
from __future__ import annotations

from pathlib import Path

import streamlit as st

_LOGO = Path(__file__).parent.parent / "assets" / "logo_light.svg"


def show_logo() -> None:
    """Vis XLENT-logoen øverst til venstre (og i sidebaren). Kalles først på hver side."""
    if _LOGO.is_file():
        st.logo(str(_LOGO), size="large", link="https://www.xlent.no")
