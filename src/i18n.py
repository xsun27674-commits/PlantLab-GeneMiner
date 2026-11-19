"""Translate display labels without changing stored field names or analysis values."""

import json
from functools import lru_cache
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]


@lru_cache
def catalog(language):
    return json.loads((ROOT / "locales" / f"{language}.json").read_text(encoding="utf-8"))


def tr(message, language=None):
    if not isinstance(message, str):
        return message
    language = language or st.session_state.get("language", "zh")
    return catalog(language if language in ("zh", "en") else "zh").get(message, message)


def display_frame(frame):
    return frame.rename(columns=tr)


def translator():
    """Bind the language for widget option serialization."""
    from functools import partial

    return partial(tr, language=st.session_state.get("language", "zh"))
