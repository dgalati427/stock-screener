"""
Streamlit UI for the stock screener. Reads the pre-computed data/latest.csv
(refreshed on a schedule by update_data.py / GitHub Actions) and lets users
filter the table and drill into a single company for a live price chart.
"""

import os

import pandas as pd
import streamlit as st
import yfinance as yf

DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "latest.csv")

st.set_page_config(page_title="Sentiment Drop Screener", layout="wide")


@st.cache_data(ttl=600)
def load_data():
    df = pd.read_csv(DATA_PATH)
    return df


@st.cache_data(ttl=3600)
def load_price_history(ticker_yf):
    hist = yf.Ticker(ticker_yf).history(period="1y", auto_adjust=True)
    return hist


st.title("Sentiment Drop Screener")
st.caption(
    "Stocks across the S&P 500 and S&P/ASX 200 whose price has dropped "
    "significantly over 12 months while revenue and net income have stayed "
    "roughly flat or improved -- a pattern more often driven by sentiment, "
    "media controversy, or broad market moves than by an actual change in "
    "the business. **This is a heuristic, not a fact-finder. Not financial advice.**"
)

if not os.path.exists(DATA_PATH):
    st.error(
        "No data yet. Run `python update_data.py` locally to generate "
        "data/latest.csv, commit it, and push."
    )
    st.stop()

raw_df = load_data()

if "last_updated_utc" in raw_df.columns and not raw_df.empty:
    st.caption(f"Data last updated: {raw_df['last_updated_utc'].iloc[0]}")

# --- Sidebar filters ---
st.sidebar.header("Filters")

markets = sorted(raw_df["market"].dropna().unique())
selected_markets = st.sidebar.multiselect("Market", markets, default=markets)

sectors = sorted(raw_df["sector"].dropna().unique())
selected_sectors = st.sidebar.multiselect("Sector", sectors, default=sectors)

search = st.sidebar.text_input("Search company / ticker")

drop_threshold = st.sidebar.slider(
    "Min. price drop over 12 months (%)", min_value=0, max_value=90, value=30, step=5,
)
revenue_tolerance = st.sidebar.slider(
    "Max. allowed revenue decline YoY (%)", min_value=0, max_value=100, value=10, step=5,
)
income_tolerance = st.sidebar.slider(
    "Max. allowed net income decline YoY (%)", min_value=0, max_value=100, value=25, step=5,
)
exclude_turned_unprofitable = st.sidebar.checkbox(
    "Exclude companies that swung from profit to loss", value=True,
)

# --- Apply filters ---
df = raw_df.copy()
df = df[df["market"].isin(selected_markets)]
df = df[df["sector"].isin(selected_sectors)]
if search:
    needle = search.lower()
    df = df[
        df["company"].str.lower().str.contains(needle, na=False)
        | df["code"].str.lower().str.contains(needle, na=False)
    ]
df = df[df["price_return_pct"] <= -drop_threshold]
df = df[df["revenue_yoy_pct"].isna() | (df["revenue_yoy_pct"] >= -revenue_tolerance)]
df = df[df["net_income_yoy_pct"].isna() | (df["net_income_yoy_pct"] >= -income_tolerance)]
if exclude_turned_unprofitable:
    df = df[~df["net_income_turned_negative"].fillna(False)]

df = df.sort_values("price_return_pct")

st.subheader(f"{len(df)} candidates")

display_cols = [
    "code", "market", "company", "sector", "current_price",
    "price_return_pct", "revenue_yoy_pct", "net_income_yoy_pct",
]
display_df = df[display_cols].rename(columns={
    "code": "Ticker",
    "market": "Market",
    "company": "Company",
    "sector": "Sector",
    "current_price": "Price",
    "price_return_pct": "12mo Return %",
    "revenue_yoy_pct": "Revenue YoY %",
    "net_income_yoy_pct": "Net Income YoY %",
})

event = st.dataframe(
    display_df,
    use_container_width=True,
    hide_index=True,
    on_select="rerun",
    selection_mode="single-row",
)

# --- Drill-down panel ---
selected_rows = event.selection.rows if event and event.selection else []
if selected_rows:
    selected = df.iloc[selected_rows[0]]
elif not df.empty:
    selected = df.iloc[0]
else:
    selected = None

if selected is not None:
    st.divider()
    st.subheader(f"{selected['company']} ({selected['code']}.{selected['market']})")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Price", f"{selected['current_price']:.2f}")
    c2.metric("12mo Return", f"{selected['price_return_pct']:.1f}%")
    c3.metric("Revenue YoY", f"{selected['revenue_yoy_pct']:.1f}%" if pd.notna(selected['revenue_yoy_pct']) else "n/a")
    c4.metric("Net Income YoY", f"{selected['net_income_yoy_pct']:.1f}%" if pd.notna(selected['net_income_yoy_pct']) else "n/a")

    with st.spinner("Loading live price history..."):
        try:
            hist = load_price_history(selected["ticker_yf"])
            if not hist.empty:
                st.line_chart(hist["Close"])
            else:
                st.info("No price history available for this ticker right now.")
        except Exception as e:
            st.warning(f"Couldn't load live chart: {e}")

    st.markdown(
        f"[View on Yahoo Finance](https://finance.yahoo.com/quote/{selected['ticker_yf']}) "
        "&mdash; check recent news before drawing any conclusions."
    )
else:
    st.info("No candidates match the current filters. Try loosening them in the sidebar.")
