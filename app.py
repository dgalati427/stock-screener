"""
TEMPORARY diagnostic build. Surfaces the real startup error (which Streamlit
Cloud otherwise hides behind a generic "Error running app" page) so we can see
whether the failure is an import/dependency problem or a data problem.
Will be reverted to the real app once diagnosed.
"""

import sys
import traceback

import streamlit as st

st.set_page_config(page_title="Screener (diagnostic)", layout="wide")
st.title("Screener — diagnostic mode")
st.write(f"Python: {sys.version}")

# --- imports ---
try:
    import pandas as pd
    st.success(f"pandas {pd.__version__} imported")
except Exception:
    st.error("pandas import FAILED:")
    st.code(traceback.format_exc())

try:
    import numpy as np
    st.success(f"numpy {np.__version__} imported")
except Exception:
    st.error("numpy import FAILED:")
    st.code(traceback.format_exc())

try:
    import yfinance as yf
    st.success(f"yfinance {yf.__version__} imported")
except Exception:
    st.error("yfinance import FAILED:")
    st.code(traceback.format_exc())

# --- data load ---
try:
    import os
    DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "latest.csv")
    df = pd.read_csv(DATA_PATH)
    st.success(f"data/latest.csv loaded: {df.shape[0]} rows, {df.shape[1]} cols")
    st.write("Columns:", list(df.columns))
except Exception:
    st.error("data load FAILED:")
    st.code(traceback.format_exc())
