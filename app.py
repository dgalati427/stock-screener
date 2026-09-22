"""
Streamlit UI for the stock screener. Reads the pre-computed data/latest.csv
(refreshed on a schedule by update_data.py / GitHub Actions). Two screens:

  * Sentiment Drop -- big price falls with stable fundamentals.
  * Growth -- companies compounding revenue with quality margins, plus a
    valuation check, aimed at "get in early" and "grown but more runway".

Both are heuristics, not financial advice.
"""

import os

import pandas as pd
import streamlit as st
import yfinance as yf

DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "latest.csv")

GROWTH_COLS = {"revenue_cagr_pct", "gross_margin_pct", "rule_of_40"}
QUALITY_COLS = {"roe_pct", "operating_margin_pct", "debt_to_equity"}
TECH_COLS = {"rsi_14", "pct_vs_50dma", "pct_vs_200dma"}


def rsi_label(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "n/a"
    if v >= 70:
        return f"{v:.0f} · overbought"
    if v <= 30:
        return f"{v:.0f} · oversold"
    return f"{v:.0f} · neutral"


def trend_label(row):
    """Simple trend read from price vs the 50/200-day moving averages."""
    a, b = row.get("pct_vs_50dma"), row.get("pct_vs_200dma")
    if a is None or b is None or pd.isna(a) or pd.isna(b):
        return "n/a"
    if a > 0 and b > 0:
        return "Uptrend"
    if a < 0 and b < 0:
        return "Downtrend"
    return "Mixed"

st.set_page_config(page_title="Stock Screener", layout="wide")


@st.cache_data(ttl=600)
def load_data(data_mtime):
    # data_mtime is part of the cache key (no leading underscore) so a changed
    # data file busts the cache and a fresh CSV is read.
    return pd.read_csv(DATA_PATH)


@st.cache_data(ttl=3600)
def load_price_history(ticker_yf):
    return yf.Ticker(ticker_yf).history(period="1y", auto_adjust=True)


def _fmt(v, suffix="", pct=False, dp=1):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "n/a"
    return f"{v:.{dp}f}{'%' if pct else ''}{suffix}"


def render_drilldown(selected):
    """Company detail panel shared by both screens."""
    if selected is None:
        st.info("No candidates match the current filters. Try loosening them in the sidebar.")
        return

    st.divider()
    st.subheader(
        f"{selected['company']} ({selected['code']}.{selected['market']}, "
        f"{selected.get('exchange', 'n/a')})"
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Price", _fmt(selected.get("current_price")))
    c2.metric("12mo Return", _fmt(selected.get("price_return_pct"), pct=True))
    c3.metric("Market Cap",
              f"${selected['market_cap'] / 1e9:.1f}B" if pd.notna(selected.get("market_cap")) else "n/a")
    c4.metric("P/E", _fmt(selected.get("pe_ratio")))

    # Growth row (only meaningful once the growth columns exist in the data).
    if GROWTH_COLS.issubset(selected.index):
        g1, g2, g3, g4 = st.columns(4)
        g1.metric("Revenue CAGR", _fmt(selected.get("revenue_cagr_pct"), pct=True))
        g2.metric("Revenue YoY", _fmt(selected.get("revenue_yoy_pct"), pct=True))
        g3.metric("Gross Margin", _fmt(selected.get("gross_margin_pct"), pct=True))
        g4.metric("Rule of 40", _fmt(selected.get("rule_of_40")))

        h1, h2, h3, h4 = st.columns(4)
        h1.metric("Net Margin", _fmt(selected.get("net_margin_pct"), pct=True))
        h2.metric("Margin trend (pp)", _fmt(selected.get("gross_margin_trend_pp")))
        h3.metric("PEG", _fmt(selected.get("peg_ratio"), dp=2))
        accel = selected.get("revenue_accelerating")
        h4.metric("Rev. accelerating", "Yes" if accel is True else ("No" if accel is False else "n/a"))

    # Quality row.
    if QUALITY_COLS.issubset(selected.index):
        q1, q2, q3, q4 = st.columns(4)
        q1.metric("ROE", _fmt(selected.get("roe_pct"), pct=True))
        q2.metric("Operating Margin", _fmt(selected.get("operating_margin_pct"), pct=True))
        q3.metric("Debt / Equity", _fmt(selected.get("debt_to_equity"), dp=2))
        q4.metric("Net Margin", _fmt(selected.get("net_margin_pct"), pct=True))

    # Technical / momentum row.
    if TECH_COLS.issubset(selected.index):
        t1, t2, t3, t4 = st.columns(4)
        t1.metric("RSI (14)", rsi_label(selected.get("rsi_14")))
        t2.metric("Trend", trend_label(selected))
        t3.metric("vs 50-day MA", _fmt(selected.get("pct_vs_50dma"), pct=True))
        t4.metric("3mo Return", _fmt(selected.get("return_3mo_pct"), pct=True))

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
        "&mdash; check recent news and the full financials before drawing conclusions."
    )


def common_filters(raw_df, key):
    """Market / exchange / sector / search filters shared by both screens.
    `key` keeps widget state separate between screens."""
    st.sidebar.header("Universe")
    markets = sorted(raw_df["market"].dropna().unique())
    sel_markets = st.sidebar.multiselect("Market", markets, default=markets, key=f"{key}_mkt")

    exchanges = sorted(raw_df["exchange"].dropna().unique()) if "exchange" in raw_df.columns else []
    sel_exchanges = st.sidebar.multiselect("Exchange", exchanges, default=exchanges, key=f"{key}_exc")

    sectors = sorted(raw_df["sector"].dropna().unique())
    sel_sectors = st.sidebar.multiselect("Sector", sectors, default=sectors, key=f"{key}_sec")

    search = st.sidebar.text_input("Search company / ticker", key=f"{key}_search")

    df = raw_df.copy()
    df = df[df["market"].isin(sel_markets)]
    if exchanges:
        df = df[df["exchange"].isin(sel_exchanges)]
    df = df[df["sector"].isin(sel_sectors)]
    if search:
        needle = search.lower()
        df = df[
            df["company"].str.lower().str.contains(needle, na=False)
            | df["code"].str.lower().str.contains(needle, na=False)
        ]
    return df


# ---------------------------------------------------------------------------
# Screen 1: Sentiment Drop
# ---------------------------------------------------------------------------
def render_drop_screen(raw_df):
    st.title("📉 Sentiment Drop Screener")
    st.caption(
        "Stocks whose price has dropped significantly over 12 months while revenue "
        "and net income stayed roughly flat or improved -- a pattern more often "
        "driven by sentiment or broad market moves than by the business itself. "
        "**Heuristic, not a fact-finder. Not financial advice.**"
    )

    with st.expander("How to read this / methodology"):
        st.markdown(
            "- Flags stocks down a lot over 12 months whose revenue and net income "
            "held flat or grew -- drops that look sentiment- or headline-driven.\n"
            "- It does **not** know *why* a stock dropped (news, lawsuits, debt, "
            "cash flow). A flagged name can still be a value trap.\n"
            "- Use it as a **research queue**, not a buy list. **Not financial advice.**"
        )

    df = common_filters(raw_df, "drop")

    st.sidebar.header("Drop filters")
    drop_threshold = st.sidebar.slider("Min. price drop over 12 months (%)", 0, 90, 30, 5)
    revenue_tolerance = st.sidebar.slider("Max. allowed revenue decline YoY (%)", 0, 100, 10, 5)
    income_tolerance = st.sidebar.slider("Max. allowed net income decline YoY (%)", 0, 100, 25, 5)
    exclude_turned_unprofitable = st.sidebar.checkbox(
        "Exclude companies that swung from profit to loss", value=True
    )

    st.sidebar.header("Additional filters")
    use_mc = st.sidebar.checkbox("Filter by minimum market cap")
    min_mc_b = st.sidebar.slider("Min. market cap ($B)", 0.0, 500.0, 10.0, 1.0) if use_mc else None
    use_pe = st.sidebar.checkbox("Filter by maximum P/E ratio")
    max_pe = st.sidebar.slider("Max. P/E ratio", 1, 100, 25, 1) if use_pe else None

    df = df[df["price_return_pct"] <= -drop_threshold]
    df = df[df["revenue_yoy_pct"].isna() | (df["revenue_yoy_pct"] >= -revenue_tolerance)]
    df = df[df["net_income_yoy_pct"].isna() | (df["net_income_yoy_pct"] >= -income_tolerance)]
    if exclude_turned_unprofitable:
        df = df[~df["net_income_turned_negative"].fillna(False)]
    if use_mc:
        df = df[df["market_cap"].notna() & (df["market_cap"] >= min_mc_b * 1e9)]
    if use_pe:
        df = df[df["pe_ratio"].notna() & (df["pe_ratio"] > 0) & (df["pe_ratio"] <= max_pe)]

    df = df.sort_values("price_return_pct", na_position="last").reset_index(drop=True)

    st.subheader(f"{len(df)} candidates")
    if not df.empty:
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Candidates", len(df))
        m2.metric("Median 12mo drop", f"{df['price_return_pct'].median():.0f}%")
        m3.metric("Sectors", df["sector"].nunique())
        median_pe = df.loc[df["pe_ratio"] > 0, "pe_ratio"].median()
        m4.metric("Median P/E", f"{median_pe:.1f}" if pd.notna(median_pe) else "n/a")

    disp = df.copy()
    disp["market_cap_b"] = disp["market_cap"] / 1e9
    cols = ["code", "exchange", "company", "sector", "current_price",
            "price_return_pct", "revenue_yoy_pct", "net_income_yoy_pct",
            "market_cap_b", "pe_ratio", "pct_from_52wk_high"]
    disp = disp[cols].rename(columns={
        "code": "Ticker", "exchange": "Exchange", "company": "Company", "sector": "Sector",
        "current_price": "Price", "price_return_pct": "12mo Return %",
        "revenue_yoy_pct": "Revenue YoY %", "net_income_yoy_pct": "Net Income YoY %",
        "market_cap_b": "Market Cap ($B)", "pe_ratio": "P/E", "pct_from_52wk_high": "% From 52wk High",
    })

    event = st.dataframe(disp, use_container_width=True, hide_index=True,
                         on_select="rerun", selection_mode="single-row")
    if not df.empty:
        st.download_button("Download these candidates (CSV)",
                           data=disp.to_csv(index=False).encode("utf-8"),
                           file_name="drop_candidates.csv", mime="text/csv")
        st.caption("Tip: click any column header to sort, or a row to drill in below.")

    rows = event.selection.rows if event and event.selection else []
    selected = df.iloc[rows[0]] if rows else (df.iloc[0] if not df.empty else None)
    render_drilldown(selected)


# ---------------------------------------------------------------------------
# Screen 2: Growth
# ---------------------------------------------------------------------------
GROWTH_PRESETS = {
    "Emerging growth (smaller, fast-growing)": dict(
        min_cagr=15, min_gross=30, require_accel=True, max_mc_b=50.0, use_peg=False, max_peg=2.5,
    ),
    "Proven compounder (durable, more runway)": dict(
        min_cagr=10, min_gross=45, require_accel=False, max_mc_b=3000.0, use_peg=True, max_peg=2.5,
    ),
    "Custom": dict(
        min_cagr=10, min_gross=0, require_accel=False, max_mc_b=3000.0, use_peg=False, max_peg=3.0,
    ),
}


def growth_score(df):
    """Transparent composite for RANKING (0-100), not a rating. It blends
    percentile ranks (within the current result set) of the growth metrics,
    so it only ever compares like with like. Missing metrics score neutral."""
    def pr(col, invert=False):
        if col not in df.columns:
            return pd.Series(0.5, index=df.index)
        s = df[col]
        if invert:
            s = -s
        return s.rank(pct=True).fillna(0.5)

    score = (
        0.30 * pr("revenue_cagr_pct")
        + 0.25 * pr("rule_of_40")
        + 0.20 * pr("gross_margin_pct")
        + 0.15 * pr("revenue_yoy_pct")
        + 0.10 * pr("peg_ratio", invert=True)  # lower PEG is better
    ) * 100.0
    # Small bonus for revenue growth that is accelerating.
    if "revenue_accelerating" in df.columns:
        score = score + df["revenue_accelerating"].fillna(False).astype(float) * 5.0
    return score.clip(upper=100).round(1)


def render_growth_screen(raw_df):
    st.title("📈 Growth Screener")
    st.caption(
        "Companies compounding revenue with quality margins, screened the way a "
        "growth analyst would -- multi-year revenue CAGR, growth *acceleration*, "
        "gross margin & margin expansion, the Rule of 40, and a PEG valuation "
        "check. **Heuristic, not financial advice.**"
    )

    if not GROWTH_COLS.issubset(raw_df.columns):
        st.info(
            "📊 Growth metrics aren't in the data file yet. They populate on the "
            "next scan with the updated code -- trigger **Run workflow** in the "
            "repo's GitHub Actions, or wait for the next scheduled refresh, then "
            "reload this page."
        )
        return

    with st.expander("How growth screening works (metrics & the two presets)"):
        st.markdown(
            "**Metrics** (all from annual financials):\n"
            "- **Revenue CAGR** — compound annual revenue growth over the years "
            "available. Sustained top-line growth is the core signal.\n"
            "- **Revenue accelerating** — is the latest year's growth *faster* than "
            "the year before? A forward-looking 'more to come' hint.\n"
            "- **Gross margin & margin trend** — high, expanding margins signal "
            "pricing power and a scalable model.\n"
            "- **Rule of 40** — revenue growth % + net margin %. ≥40 is the classic "
            "'growing efficiently' bar.\n"
            "- **PEG** — P/E ÷ earnings growth. Near/under ~1–2 is 'growth at a "
            "reasonable price' — helps avoid overpaying.\n"
            "- **Growth Score** — a transparent 0–100 *ranking* blend of the above "
            "(relative to the current list). A sorting aid, **not** a rating or "
            "recommendation.\n\n"
            "**Presets:** *Emerging* leans to smaller, fast, accelerating growers "
            "(get in earlier); *Proven* leans to larger, durable, high-margin "
            "compounders at a sane price.\n\n"
            "⚠️ This universe is the **S&P 500 + ASX 200** (large/established firms), "
            "so true pre-growth micro-caps aren't here — 'Emerging' finds the "
            "*smaller, faster-growing constituents*.\n\n"
            "⚠️ **Watch the sector:** commodity/resource names (miners, energy) can "
            "post huge revenue CAGR from a *production ramp or price spike*, not "
            "durable software-style growth. Judge those differently. **Not financial advice.**"
        )

    df = common_filters(raw_df, "growth")

    st.sidebar.header("Growth preset")
    preset_name = st.sidebar.radio("Preset", list(GROWTH_PRESETS.keys()), key="growth_preset")
    p = GROWTH_PRESETS[preset_name]
    # Keying widgets by preset makes switching preset reset them to preset defaults.
    k = preset_name

    st.sidebar.header("Growth filters")
    min_cagr = st.sidebar.slider("Min. revenue CAGR (%)", 0, 60, p["min_cagr"], 1, key=f"cagr_{k}")
    min_gross = st.sidebar.slider("Min. gross margin (%)", 0, 90, p["min_gross"], 5, key=f"gross_{k}")
    require_accel = st.sidebar.checkbox("Require accelerating revenue growth",
                                        value=p["require_accel"], key=f"accel_{k}")
    min_rule40 = st.sidebar.slider("Min. Rule of 40 score", -20, 80, 0, 5, key=f"r40_{k}")
    use_peg = st.sidebar.checkbox("Cap PEG (valuation discipline)", value=p["use_peg"], key=f"usepeg_{k}")
    max_peg = st.sidebar.slider("Max. PEG", 0.5, 5.0, p["max_peg"], 0.1, key=f"peg_{k}") if use_peg else None
    max_mc_b = st.sidebar.slider("Max. market cap ($B)", 1.0, 3000.0, p["max_mc_b"], 1.0, key=f"mc_{k}")

    # Apply growth filters (rows missing a required metric are excluded from that gate).
    df = df[df["revenue_cagr_pct"].notna() & (df["revenue_cagr_pct"] >= min_cagr)]
    if min_gross > 0:
        df = df[df["gross_margin_pct"].notna() & (df["gross_margin_pct"] >= min_gross)]
    if require_accel:
        df = df[df["revenue_accelerating"] == True]  # noqa: E712
    if min_rule40 > -20:
        df = df[df["rule_of_40"].notna() & (df["rule_of_40"] >= min_rule40)]
    if use_peg and max_peg is not None:
        df = df[df["peg_ratio"].notna() & (df["peg_ratio"] > 0) & (df["peg_ratio"] <= max_peg)]
    df = df[df["market_cap"].notna() & (df["market_cap"] <= max_mc_b * 1e9)]

    df = df.reset_index(drop=True)
    if not df.empty:
        df["growth_score"] = growth_score(df)
        df = df.sort_values("growth_score", ascending=False, na_position="last").reset_index(drop=True)

    st.subheader(f"{len(df)} growth candidates — {preset_name.split(' (')[0]}")
    if not df.empty:
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Candidates", len(df))
        m2.metric("Median revenue CAGR", f"{df['revenue_cagr_pct'].median():.0f}%")
        med_gm = df["gross_margin_pct"].median()
        m3.metric("Median gross margin", f"{med_gm:.0f}%" if pd.notna(med_gm) else "n/a")
        med_peg = df.loc[df["peg_ratio"] > 0, "peg_ratio"].median() if "peg_ratio" in df else None
        m4.metric("Median PEG", f"{med_peg:.2f}" if med_peg is not None and pd.notna(med_peg) else "n/a")

    disp = df.copy()
    if not disp.empty:
        disp["market_cap_b"] = disp["market_cap"] / 1e9
        disp["accel"] = disp["revenue_accelerating"].map({True: "Yes", False: "No"}).fillna("n/a")
        cols = ["code", "exchange", "company", "sector", "current_price", "growth_score",
                "revenue_cagr_pct", "revenue_yoy_pct", "accel", "gross_margin_pct",
                "net_margin_pct", "rule_of_40", "peg_ratio", "market_cap_b",
                "pe_ratio", "price_return_pct"]
        disp = disp[cols].rename(columns={
            "code": "Ticker", "exchange": "Exchange", "company": "Company", "sector": "Sector",
            "current_price": "Price", "growth_score": "Growth Score",
            "revenue_cagr_pct": "Rev CAGR %", "revenue_yoy_pct": "Rev YoY %", "accel": "Accel?",
            "gross_margin_pct": "Gross Margin %", "net_margin_pct": "Net Margin %",
            "rule_of_40": "Rule of 40", "peg_ratio": "PEG", "market_cap_b": "Market Cap ($B)",
            "pe_ratio": "P/E", "price_return_pct": "12mo Return %",
        })

    event = st.dataframe(disp, use_container_width=True, hide_index=True,
                         on_select="rerun", selection_mode="single-row")
    if not df.empty:
        st.download_button("Download these candidates (CSV)",
                           data=disp.to_csv(index=False).encode("utf-8"),
                           file_name="growth_candidates.csv", mime="text/csv")
        st.caption("Sorted by Growth Score. Click a column header to re-sort, or a row to drill in below.")

    rows = event.selection.rows if event and event.selection else []
    selected = df.iloc[rows[0]] if rows else (df.iloc[0] if not df.empty else None)
    render_drilldown(selected)


# ---------------------------------------------------------------------------
# Screen 3: Quality (core fundamentals for durable businesses)
# ---------------------------------------------------------------------------
QUALITY_PRESETS = {
    "Durable compounder (Coca-Cola-style)": dict(
        min_roe=15, min_opmargin=15, max_de=2.0, min_cagr=3, require_profit=True,
    ),
    "Custom": dict(min_roe=0, min_opmargin=0, max_de=10.0, min_cagr=-100, require_profit=False),
}


def quality_score(df):
    """Transparent 0-100 ranking blend of the quality metrics (relative to the
    current list). A sorting aid, not a rating."""
    def pr(col, invert=False):
        if col not in df.columns:
            return pd.Series(0.5, index=df.index)
        s = -df[col] if invert else df[col]
        return s.rank(pct=True).fillna(0.5)

    return ((
        0.30 * pr("roe_pct")
        + 0.25 * pr("operating_margin_pct")
        + 0.15 * pr("gross_margin_pct")
        + 0.15 * pr("revenue_cagr_pct")
        + 0.15 * pr("debt_to_equity", invert=True)
    ) * 100.0).clip(upper=100).round(1)


def render_quality_screen(raw_df):
    st.title("🏆 Quality Screener")
    st.caption(
        "Durable, high-return businesses — the Coca-Cola / Costco type — screened "
        "on the fundamentals that signal a real moat: high **return on equity**, "
        "fat **operating margins**, low **debt**, and consistent profitable growth. "
        "**Heuristic, not financial advice.**"
    )

    if not QUALITY_COLS.issubset(raw_df.columns):
        st.info(
            "📊 Quality metrics (ROE, operating margin, debt/equity) aren't in the "
            "data file yet — they populate on the next full scan with the updated "
            "code. Reload once that's run."
        )
        return

    with st.expander("How quality screening works (metrics & preset)"):
        st.markdown(
            "- **ROE (return on equity)** — profit generated per dollar of "
            "shareholder capital. Sustained high ROE is the classic mark of a "
            "great business.\n"
            "- **Operating margin** — profit from core operations; fat, stable "
            "margins signal pricing power / a moat.\n"
            "- **Debt-to-equity** — balance-sheet strength. Lower = safer.\n"
            "- **Revenue CAGR** — durable (not necessarily explosive) growth.\n"
            "- **Quality Score** — a transparent 0–100 *ranking* blend of the "
            "above (relative to the current list). A sorting aid, not a rating.\n\n"
            "⚠️ ROE and debt/equity are shown as **n/a** for companies with "
            "negative book equity (often from heavy buybacks — e.g. some blue "
            "chips); lean on margins and growth there. **Not financial advice.**"
        )

    df = common_filters(raw_df, "quality")

    st.sidebar.header("Quality preset")
    preset_name = st.sidebar.radio("Preset", list(QUALITY_PRESETS.keys()), key="quality_preset")
    p = QUALITY_PRESETS[preset_name]
    k = preset_name

    st.sidebar.header("Quality filters")
    min_roe = st.sidebar.slider("Min. ROE (%)", 0, 50, p["min_roe"], 1, key=f"roe_{k}")
    min_opm = st.sidebar.slider("Min. operating margin (%)", 0, 50, p["min_opmargin"], 1, key=f"opm_{k}")
    max_de = st.sidebar.slider("Max. debt / equity", 0.0, 10.0, p["max_de"], 0.1, key=f"de_{k}")
    min_cagr = st.sidebar.slider("Min. revenue CAGR (%)", -20, 40, p["min_cagr"], 1, key=f"qcagr_{k}")
    require_profit = st.sidebar.checkbox("Profitable only (positive net margin)",
                                         value=p["require_profit"], key=f"prof_{k}")

    if min_roe > 0:
        df = df[df["roe_pct"].notna() & (df["roe_pct"] >= min_roe)]
    if min_opm > 0:
        df = df[df["operating_margin_pct"].notna() & (df["operating_margin_pct"] >= min_opm)]
    # Debt filter keeps rows with no reported D/E (e.g. negative-equity blue chips).
    df = df[df["debt_to_equity"].isna() | (df["debt_to_equity"] <= max_de)]
    if min_cagr > -20:
        df = df[df["revenue_cagr_pct"].notna() & (df["revenue_cagr_pct"] >= min_cagr)]
    if require_profit:
        df = df[df["net_margin_pct"].notna() & (df["net_margin_pct"] > 0)]

    df = df.reset_index(drop=True)
    if not df.empty:
        df["q_score"] = quality_score(df)
        df = df.sort_values("q_score", ascending=False, na_position="last").reset_index(drop=True)

    st.subheader(f"{len(df)} quality candidates — {preset_name.split(' (')[0]}")
    if not df.empty:
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Candidates", len(df))
        med_roe = df["roe_pct"].median()
        m2.metric("Median ROE", f"{med_roe:.0f}%" if pd.notna(med_roe) else "n/a")
        med_opm = df["operating_margin_pct"].median()
        m3.metric("Median op. margin", f"{med_opm:.0f}%" if pd.notna(med_opm) else "n/a")
        med_de = df["debt_to_equity"].median()
        m4.metric("Median debt/equity", f"{med_de:.2f}" if pd.notna(med_de) else "n/a")

    disp = df.copy()
    if not disp.empty:
        disp["market_cap_b"] = disp["market_cap"] / 1e9
        cols = ["code", "exchange", "company", "sector", "current_price", "q_score",
                "roe_pct", "operating_margin_pct", "net_margin_pct", "gross_margin_pct",
                "debt_to_equity", "revenue_cagr_pct", "market_cap_b", "pe_ratio"]
        disp = disp[cols].rename(columns={
            "code": "Ticker", "exchange": "Exchange", "company": "Company", "sector": "Sector",
            "current_price": "Price", "q_score": "Quality Score", "roe_pct": "ROE %",
            "operating_margin_pct": "Op Margin %", "net_margin_pct": "Net Margin %",
            "gross_margin_pct": "Gross Margin %", "debt_to_equity": "Debt/Equity",
            "revenue_cagr_pct": "Rev CAGR %", "market_cap_b": "Market Cap ($B)", "pe_ratio": "P/E",
        })

    event = st.dataframe(disp, use_container_width=True, hide_index=True,
                         on_select="rerun", selection_mode="single-row")
    if not df.empty:
        st.download_button("Download these candidates (CSV)",
                           data=disp.to_csv(index=False).encode("utf-8"),
                           file_name="quality_candidates.csv", mime="text/csv")
        st.caption("Sorted by Quality Score. Click a column header to re-sort, or a row to drill in below.")

    rows = event.selection.rows if event and event.selection else []
    selected = df.iloc[rows[0]] if rows else (df.iloc[0] if not df.empty else None)
    render_drilldown(selected)


# ---------------------------------------------------------------------------
# Screen 4: Momentum & signals (is it trending / oversold?)
# ---------------------------------------------------------------------------
def render_momentum_screen(raw_df):
    st.title("🚀 Momentum & Signals")
    st.caption(
        "Where is the price action? This screen reads **RSI** (overbought/oversold), "
        "and price vs the **50 & 200-day moving averages** (trend). Two modes: ride "
        "existing strength, or hunt beaten-down names for a possible bounce. "
        "**Signals, not predictions. Not financial advice.**"
    )

    if not TECH_COLS.issubset(raw_df.columns):
        st.info(
            "📊 Technical signals (RSI, moving-average trend) aren't in the data "
            "file yet — they populate on the next full scan with the updated code. "
            "Reload once that's run."
        )
        return

    with st.expander("How to read these signals"):
        st.markdown(
            "- **RSI (14)** — momentum oscillator. **>70 = overbought** (extended, "
            "may cool off), **<30 = oversold** (beaten down, may bounce).\n"
            "- **Trend** — price above both the 50- and 200-day moving averages = "
            "**uptrend**; below both = downtrend.\n"
            "- **Uptrend mode** → stocks already trending up (buy strength). This is "
            "how you'd systematically hold winners like META *while* they run — but "
            "note a high RSI means it's already extended.\n"
            "- **Oversold-bounce mode** → stocks that have sold off hard (low RSI). "
            "Higher risk: 'oversold' can stay oversold if something is genuinely "
            "wrong. Cross-check with the Quality screen.\n\n"
            "⚠️ These are **timing signals, not forecasts** — no screen predicts a "
            "move before it happens. **Not financial advice.**"
        )

    df = common_filters(raw_df, "mom")

    st.sidebar.header("Mode")
    mode = st.sidebar.radio("Momentum mode",
                            ["Uptrend (buy strength)", "Oversold bounce (buy weakness)"],
                            key="mom_mode")

    st.sidebar.header("Signal filters")
    if mode.startswith("Uptrend"):
        min_3mo = st.sidebar.slider("Min. 3-month return (%)", -20, 60, 5, 5, key="mom_3mo")
        max_rsi = st.sidebar.slider("Max. RSI (avoid over-extended)", 40, 90, 80, 5, key="mom_maxrsi")
        df = df[(df["pct_vs_50dma"].notna()) & (df["pct_vs_50dma"] > 0)]
        df = df[(df["pct_vs_200dma"].notna()) & (df["pct_vs_200dma"] > 0)]
        df = df[df["return_3mo_pct"].notna() & (df["return_3mo_pct"] >= min_3mo)]
        df = df[df["rsi_14"].isna() | (df["rsi_14"] <= max_rsi)]
        df = df.reset_index(drop=True)
        if not df.empty:
            df = df.sort_values("return_3mo_pct", ascending=False, na_position="last").reset_index(drop=True)
    else:
        max_rsi_os = st.sidebar.slider("Max. RSI (how oversold)", 10, 50, 35, 1, key="mom_osrsi")
        above_200 = st.sidebar.checkbox("Still above 200-day MA (quality dip)", value=False, key="mom_above200")
        df = df[df["rsi_14"].notna() & (df["rsi_14"] <= max_rsi_os)]
        if above_200:
            df = df[df["pct_vs_200dma"].notna() & (df["pct_vs_200dma"] > 0)]
        df = df.reset_index(drop=True)
        if not df.empty:
            df = df.sort_values("rsi_14", ascending=True, na_position="last").reset_index(drop=True)

    st.subheader(f"{len(df)} candidates — {mode.split(' (')[0]}")
    if not df.empty:
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Candidates", len(df))
        med_rsi = df["rsi_14"].median()
        m2.metric("Median RSI", f"{med_rsi:.0f}" if pd.notna(med_rsi) else "n/a")
        med_3mo = df["return_3mo_pct"].median()
        m3.metric("Median 3mo return", f"{med_3mo:.0f}%" if pd.notna(med_3mo) else "n/a")
        upt = int((df.get("pct_vs_200dma", pd.Series(dtype=float)) > 0).sum())
        m4.metric("Above 200-day MA", upt)

    disp = df.copy()
    if not disp.empty:
        disp["market_cap_b"] = disp["market_cap"] / 1e9
        disp["trend"] = disp.apply(trend_label, axis=1)
        cols = ["code", "exchange", "company", "sector", "current_price", "rsi_14", "trend",
                "pct_vs_50dma", "pct_vs_200dma", "return_3mo_pct", "price_return_pct",
                "market_cap_b", "pct_from_52wk_high"]
        disp = disp[cols].rename(columns={
            "code": "Ticker", "exchange": "Exchange", "company": "Company", "sector": "Sector",
            "current_price": "Price", "rsi_14": "RSI", "trend": "Trend",
            "pct_vs_50dma": "vs 50d MA %", "pct_vs_200dma": "vs 200d MA %",
            "return_3mo_pct": "3mo Return %", "price_return_pct": "12mo Return %",
            "market_cap_b": "Market Cap ($B)", "pct_from_52wk_high": "% From 52wk High",
        })

    event = st.dataframe(disp, use_container_width=True, hide_index=True,
                         on_select="rerun", selection_mode="single-row")
    if not df.empty:
        st.download_button("Download these candidates (CSV)",
                           data=disp.to_csv(index=False).encode("utf-8"),
                           file_name="momentum_candidates.csv", mime="text/csv")
        st.caption("Click a column header to re-sort, or a row to drill in below.")

    rows = event.selection.rows if event and event.selection else []
    selected = df.iloc[rows[0]] if rows else (df.iloc[0] if not df.empty else None)
    render_drilldown(selected)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if not os.path.exists(DATA_PATH):
    st.error("No data yet. Run `python update_data.py` to generate data/latest.csv.")
    st.stop()

raw_df = load_data(os.path.getmtime(DATA_PATH))

REQUIRED_COLS = {"market", "sector", "price_return_pct"}
if raw_df.empty or not REQUIRED_COLS.issubset(raw_df.columns):
    st.warning(
        "The latest data file is empty or missing expected columns — the most "
        "recent scheduled scan was probably rate-limited. The next scan should "
        "restore it; please check back shortly."
    )
    st.stop()

if "last_updated_utc" in raw_df.columns:
    st.sidebar.caption(f"Data updated: {raw_df['last_updated_utc'].iloc[0]}")

screen = st.sidebar.radio(
    "Screen",
    ["📉 Sentiment drop", "📈 Growth", "🏆 Quality", "🚀 Momentum"],
    key="screen",
)
st.sidebar.divider()

if screen == "📉 Sentiment drop":
    render_drop_screen(raw_df)
elif screen == "📈 Growth":
    render_growth_screen(raw_df)
elif screen == "🏆 Quality":
    render_quality_screen(raw_df)
else:
    render_momentum_screen(raw_df)
