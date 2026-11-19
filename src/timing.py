"""Optional timings and bounded, per-session last-result reuse."""

import logging
import os
from contextlib import contextmanager
from time import perf_counter

import streamlit as st

LOGGER = logging.getLogger("plantlab.timing")


@contextmanager
def elapsed(stage):
    start = perf_counter()
    try:
        yield
    finally:
        if os.getenv("GENEMINER_PROFILE") == "1":
            LOGGER.warning("%s %.2f ms", stage, (perf_counter() - start) * 1000)


def session_result(stage, fingerprint, operation, *args):
    key = f"_timed_{stage}"
    cached = st.session_state.get(key)
    if cached is not None and cached[0] == fingerprint:
        with elapsed(f"{stage}.reuse"):
            return cached[1]
    with elapsed(stage):
        result = operation(*args)
    st.session_state[key] = (fingerprint, result)
    return result
