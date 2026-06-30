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
def load_data(_data_mtime):
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

raw_df = load_data(os.path.getmtime(DATA_PATH))

if "last_updated_utc" in raw_df.columns and not raw_df.empty:
    st.caption(f"Data last updated: {raw_df['last_updated_utc'].iloc[0]}")

# --- Sidebar filters ---
st.sidebar.header("Filters")

markets = sorted(raw_df["market"].dropna().unique())
selected_markets = st.sidebar.multiselect("Market", markets, default=markets)

exchanges = sorted(raw_df["exchange"].dropna().unique()) if "exchange" in raw_df.columns else []
selected_exchanges = st.sidebar.multiselect("Exchange", exchanges, default=exchanges)

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

st.sidebar.header("Additional filters")
st.sidebar.caption("Off by default — turn on the ones you want.")

use_market_cap_filter = st.sidebar.checkbox("Filter by minimum market cap")
min_market_cap_b = None
if use_market_cap_filter:
    min_market_cap_b = st.sidebar.slider(
        "Min. market cap ($B)", min_value=0.0, max_value=500.0, value=10.0, step=1.0,
    )

use_pe_filter = st.sidebar.checkbox("Filter by maximum P/E ratio")
max_pe = None
if use_pe_filter:
    max_pe = st.sidebar.slider("Max. P/E ratio", min_value=1, max_value=100, value=25, step=1)

use_52wk_filter = st.sidebar.checkbox("Filter by distance from 52-week high")
min_below_52wk_high = None
if use_52wk_filter:
    min_below_52wk_high = st.sidebar.slider(
        "Min. % below 52-week high", min_value=0, max_value=90, value=40, step=5,
    )

# --- Apply filters ---
df = raw_df.copy()
df = df[df["market"].isin(selected_markets)]
if exchanges:
    df = df[df["exchange"].isin(selected_exchanges)]
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
if use_market_cap_filter:
    df = df[df["market_cap"].notna() & (df["market_cap"] >= min_market_cap_b * 1e9)]
if use_pe_filter:
    df = df[df["pe_ratio"].notna() & (df["pe_ratio"] > 0) & (df["pe_ratio"] <= max_pe)]
if use_52wk_filter:
    df = df[df["pct_from_52wk_high"].notna() & (df["pct_from_52wk_high"] <= -min_below_52wk_high)]

df = df.sort_values("price_return_pct")

st.subheader(f"{len(df)} candidates")

display_df = df.copy()
display_df["market_cap_b"] = display_df["market_cap"] / 1e9

display_cols = [
    "code", "exchange", "company", "sector", "current_price",
    "price_return_pct", "revenue_yoy_pct", "net_income_yoy_pct",
    "market_cap_b", "pe_ratio", "pct_from_52wk_high",
]
display_df = display_df[display_cols].rename(columns={
    "code": "Ticker",
    "exchange": "Exchange",
    "company": "Company",
    "sector": "Sector",
    "current_price": "Price",
    "price_return_pct": "12mo Return %",
    "revenue_yoy_pct": "Revenue YoY %",
    "net_income_yoy_pct": "Net Income YoY %",
    "market_cap_b": "Market Cap ($B)",
    "pe_ratio": "P/E",
    "pct_from_52wk_high": "% From 52wk High",
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
    st.subheader(f"{selected['company']} ({selected['code']}.{selected['market']}, {selected.get('exchange', 'n/a')})")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Price", f"{selected['current_price']:.2f}")
    c2.metric("12mo Return", f"{selected['price_return_pct']:.1f}%")
    c3.metric("Revenue YoY", f"{selected['revenue_yoy_pct']:.1f}%" if pd.notna(selected['revenue_yoy_pct']) else "n/a")
    c4.metric("Net Income YoY", f"{selected['net_income_yoy_pct']:.1f}%" if pd.notna(selected['net_income_yoy_pct']) else "n/a")

    c5, c6, c7 = st.columns(3)
    c5.metric("Market Cap", f"${selected['market_cap'] / 1e9:.1f}B" if pd.notna(selected.get('market_cap')) else "n/a")
    c6.metric("P/E Ratio", f"{selected['pe_ratio']:.1f}" if pd.notna(selected.get('pe_ratio')) else "n/a")
    c7.metric("% From 52wk High", f"{selected['pct_from_52wk_high']:.1f}%" if pd.notna(selected.get('pct_from_52wk_high')) else "n/a")

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
