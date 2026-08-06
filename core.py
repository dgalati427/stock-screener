"""
Shared data-fetching logic used by both the CLI (screener.py) and the
Streamlit app (app.py) / scheduled scan (update_data.py).
"""

import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import StringIO

import pandas as pd
import requests
import yfinance as yf

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) stock-screener/1.0"}

SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
ASX200_URL = "https://en.wikipedia.org/wiki/S%26P/ASX_200"

EXCHANGE_LABELS = {
    "NMS": "NASDAQ", "NGM": "NASDAQ", "NCM": "NASDAQ", "NAS": "NASDAQ",
    "NYQ": "NYSE", "ASE": "NYSE American", "PCX": "NYSE Arca",
    "BTS": "Cboe BZX", "BATS": "Cboe BZX",
    "ASX": "ASX",
}


def _read_html_tables(url):
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return pd.read_html(StringIO(resp.text))


def _find_table(tables, must_have_any):
    """Return the first DataFrame in `tables` whose columns include any of
    the given candidate column names."""
    for table in tables:
        cols = [str(c).strip() for c in table.columns]
        if any(name in cols for name in must_have_any):
            return table
    raise ValueError(f"Could not find a table with columns in {must_have_any}")


def get_sp500_universe():
    tables = _read_html_tables(SP500_URL)
    table = _find_table(tables, ["Symbol"])
    universe = []
    for _, row in table.iterrows():
        symbol = str(row["Symbol"]).strip().replace(".", "-")
        name = str(row.get("Security", row.get("Company", symbol))).strip()
        sector = str(row.get("GICS Sector", "")).strip()
        universe.append({
            "ticker_yf": symbol,
            "code": str(row["Symbol"]).strip(),
            "market": "US",
            "company": name,
            "sector": sector,
        })
    return universe


def get_asx200_universe():
    tables = _read_html_tables(ASX200_URL)
    table = _find_table(tables, ["Code", "ASX code", "Symbol"])
    code_col = next(c for c in table.columns if str(c).strip() in ("Code", "ASX code", "Symbol"))
    name_col = next((c for c in table.columns if "Company" in str(c)), code_col)
    sector_col = next((c for c in table.columns if "Sector" in str(c)), None)
    universe = []
    for _, row in table.iterrows():
        code = str(row[code_col]).strip()
        if not code or code.lower() == "nan":
            continue
        universe.append({
            "ticker_yf": f"{code}.AX",
            "code": code,
            "market": "ASX",
            "company": str(row.get(name_col, code)).strip(),
            "sector": str(row.get(sector_col, "")).strip() if sector_col else "",
        })
    return universe


def build_universe(markets, limit=None):
    universe = []
    if "us" in markets:
        sp500 = get_sp500_universe()
        universe += sp500[:limit] if limit else sp500
    if "asx" in markets:
        asx200 = get_asx200_universe()
        universe += asx200[:limit] if limit else asx200
    return universe


def _pct_change(current, prior):
    if prior is None or current is None:
        return None
    try:
        if prior == 0:
            return None
        return (current - prior) / abs(prior) * 100.0
    except (TypeError, ValueError):
        return None


def _first_matching_row(df, candidates):
    if df is None or df.empty:
        return None
    for name in candidates:
        if name in df.index:
            return df.loc[name]
    return None


def _clean_series(row):
    """A financial-statement row as a list of floats, newest-first, with
    non-numeric entries turned into None. yfinance orders columns newest→oldest."""
    if row is None:
        return []
    out = []
    for v in row.tolist():
        try:
            f = float(v)
            out.append(f if f == f else None)  # f != f filters NaN
        except (TypeError, ValueError):
            out.append(None)
    return out


def _cagr_pct(newest, oldest, years):
    """Compound annual growth rate as a percent. Needs positive endpoints."""
    if newest is None or oldest is None or years <= 0:
        return None
    if newest <= 0 or oldest <= 0:
        return None
    return ((newest / oldest) ** (1.0 / years) - 1.0) * 100.0


def _compute_growth_metrics(income_stmt, revenue_row, current_ni, market_cap,
                            pe_ratio, net_income_yoy_pct):
    """Analyst-style growth metrics derived from the annual income statement we
    already fetched (no extra API calls). Everything is null-safe: any piece we
    can't compute comes back as None rather than raising."""
    g = {
        "revenue_cagr_pct": None,
        "revenue_accelerating": None,
        "gross_margin_pct": None,
        "gross_margin_trend_pp": None,
        "net_margin_pct": None,
        "peg_ratio": None,
        "rule_of_40": None,
    }

    rev = _clean_series(revenue_row)
    # Multi-year revenue CAGR across all available years (newest -> oldest).
    if len(rev) >= 2 and rev[0] is not None:
        oldest_idx = next((i for i in range(len(rev) - 1, -1, -1) if rev[i] is not None), None)
        if oldest_idx is not None and oldest_idx >= 1:
            g["revenue_cagr_pct"] = _cagr_pct(rev[0], rev[oldest_idx], oldest_idx)

    # Revenue growth acceleration: is the most recent YoY faster than the one before?
    if len(rev) >= 3 and all(v is not None for v in rev[:3]):
        latest_yoy = _pct_change(rev[0], rev[1])
        prior_yoy = _pct_change(rev[1], rev[2])
        if latest_yoy is not None and prior_yoy is not None:
            g["revenue_accelerating"] = latest_yoy > prior_yoy

    latest_rev = rev[0] if rev else None

    # Gross margin (quality/scalability): Gross Profit / Revenue, falling back to
    # (Revenue - Cost of Revenue) if the gross-profit line isn't reported.
    gross_profit_row = _first_matching_row(income_stmt, ["Gross Profit", "GrossProfit"])
    gp = _clean_series(gross_profit_row)
    if (not gp or gp[0] is None):
        cost_row = _first_matching_row(
            income_stmt, ["Cost Of Revenue", "CostOfRevenue", "Cost of Revenue", "Reconciled Cost Of Revenue"]
        )
        cost = _clean_series(cost_row)
        if latest_rev and cost and cost[0] is not None:
            gp = [latest_rev - cost[0]] + gp[1:] if gp else [latest_rev - cost[0]]
    if latest_rev and gp and gp[0] is not None and latest_rev != 0:
        g["gross_margin_pct"] = gp[0] / latest_rev * 100.0
        # Margin expansion vs prior year (percentage points).
        if len(gp) >= 2 and len(rev) >= 2 and gp[1] is not None and rev[1]:
            prior_gm = gp[1] / rev[1] * 100.0
            g["gross_margin_trend_pp"] = g["gross_margin_pct"] - prior_gm

    # A gross margin of ~100% means Yahoo didn't report a cost-of-revenue line
    # (common for airports, REITs, some miners) -- it's a data gap, not a real
    # margin. Drop it so it can't spuriously pass a "high margin = quality" gate.
    if g["gross_margin_pct"] is not None and g["gross_margin_pct"] >= 99.5:
        g["gross_margin_pct"] = None
        g["gross_margin_trend_pp"] = None

    # Net margin.
    if latest_rev and current_ni is not None and latest_rev != 0:
        g["net_margin_pct"] = current_ni / latest_rev * 100.0

    # PEG: P/E relative to earnings growth (growth-at-a-reasonable-price). Only
    # meaningful when both the multiple and the growth rate are positive.
    if pe_ratio and net_income_yoy_pct and net_income_yoy_pct > 0:
        g["peg_ratio"] = pe_ratio / net_income_yoy_pct

    # Rule of 40 (popular for growth companies): revenue growth % + profit margin %.
    latest_rev_yoy = _pct_change(rev[0], rev[1]) if len(rev) >= 2 else None
    if latest_rev_yoy is not None and g["net_margin_pct"] is not None:
        g["rule_of_40"] = latest_rev_yoy + g["net_margin_pct"]

    return g


def _round_opt(x, n=1):
    return round(x, n) if x is not None else None


def fetch_metrics(entry, retries=3, sleep_between_retries=3.0):
    """Fetch 1y price return and YoY revenue/net income change for one ticker.
    Returns a dict of metrics, or None if data could not be retrieved."""
    ticker_yf = entry["ticker_yf"]
    # Stagger requests so parallel workers don't burst Yahoo Finance's rate limit.
    time.sleep(random.uniform(0.5, 1.5))
    last_error = None
    for attempt in range(retries + 1):
        try:
            t = yf.Ticker(ticker_yf)

            hist = t.history(period="1y", auto_adjust=True)
            if hist.empty or len(hist) < 2:
                return None
            start_price = float(hist["Close"].iloc[0])
            end_price = float(hist["Close"].iloc[-1])
            if start_price == 0:
                return None
            price_return_pct = (end_price - start_price) / start_price * 100.0

            income_stmt = getattr(t, "income_stmt", None)
            if income_stmt is None or income_stmt.empty:
                income_stmt = getattr(t, "financials", None)

            revenue_row = _first_matching_row(income_stmt, ["Total Revenue", "TotalRevenue"])
            net_income_row = _first_matching_row(
                income_stmt, ["Net Income", "Net Income Common Stockholders", "NetIncome"]
            )

            revenue_yoy_pct = None
            net_income_yoy_pct = None
            net_income_turned_negative = False

            if revenue_row is not None and len(revenue_row) >= 2:
                revenue_yoy_pct = _pct_change(revenue_row.iloc[0], revenue_row.iloc[1])

            current_ni = None
            if net_income_row is not None and len(net_income_row) >= 2:
                current_ni, prior_ni = net_income_row.iloc[0], net_income_row.iloc[1]
                net_income_yoy_pct = _pct_change(current_ni, prior_ni)
                if prior_ni is not None and current_ni is not None:
                    net_income_turned_negative = prior_ni > 0 and current_ni < 0

            fast_info = t.fast_info
            market_cap = fast_info["market_cap"]
            year_high = fast_info["year_high"]
            exchange_raw = fast_info["exchange"]

            pe_ratio = None
            if market_cap and current_ni and current_ni > 0:
                pe_ratio = market_cap / current_ni

            pct_from_52wk_high = None
            if year_high:
                pct_from_52wk_high = (end_price - year_high) / year_high * 100.0

            # Growth metrics are best-effort: never let them fail a whole ticker.
            try:
                growth = _compute_growth_metrics(
                    income_stmt, revenue_row, current_ni, market_cap,
                    pe_ratio, net_income_yoy_pct,
                )
            except Exception:
                growth = {
                    "revenue_cagr_pct": None, "revenue_accelerating": None,
                    "gross_margin_pct": None, "gross_margin_trend_pp": None,
                    "net_margin_pct": None, "peg_ratio": None, "rule_of_40": None,
                }

            return {
                **entry,
                "exchange": EXCHANGE_LABELS.get(exchange_raw, exchange_raw),
                "current_price": round(end_price, 2),
                "price_return_pct": round(price_return_pct, 1),
                "revenue_yoy_pct": round(revenue_yoy_pct, 1) if revenue_yoy_pct is not None else None,
                "net_income_yoy_pct": round(net_income_yoy_pct, 1) if net_income_yoy_pct is not None else None,
                "net_income_turned_negative": net_income_turned_negative,
                "market_cap": round(market_cap) if market_cap else None,
                "pe_ratio": round(pe_ratio, 1) if pe_ratio is not None else None,
                "pct_from_52wk_high": round(pct_from_52wk_high, 1) if pct_from_52wk_high is not None else None,
                "revenue_cagr_pct": _round_opt(growth["revenue_cagr_pct"]),
                "revenue_accelerating": growth["revenue_accelerating"],
                "gross_margin_pct": _round_opt(growth["gross_margin_pct"]),
                "gross_margin_trend_pp": _round_opt(growth["gross_margin_trend_pp"]),
                "net_margin_pct": _round_opt(growth["net_margin_pct"]),
                "peg_ratio": _round_opt(growth["peg_ratio"], 2),
                "rule_of_40": _round_opt(growth["rule_of_40"]),
            }
        except Exception as e:  # yfinance/network calls are flaky; retry then give up
            last_error = e
            time.sleep(sleep_between_retries)
    print(f"  [skip] {ticker_yf}: {last_error}", file=sys.stderr)
    return None


def passes_filters(metrics, drop_threshold, revenue_tolerance, income_tolerance):
    if metrics["price_return_pct"] > -drop_threshold:
        return False
    if metrics["net_income_turned_negative"]:
        return False
    if metrics["revenue_yoy_pct"] is not None and metrics["revenue_yoy_pct"] < -revenue_tolerance:
        return False
    if metrics["net_income_yoy_pct"] is not None and metrics["net_income_yoy_pct"] < -income_tolerance:
        return False
    return True


def scan_all(markets, limit=None, workers=6, progress=None):
    """Fetch metrics for every ticker in the given markets' universe.
    Returns a DataFrame with one row per ticker that was successfully
    fetched -- no pass/fail filtering applied. `progress`, if given, is
    called with (completed_count, total_count) after each ticker finishes."""
    universe = build_universe(markets, limit=limit)
    results = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fetch_metrics, entry): entry for entry in universe}
        completed = 0
        for future in as_completed(futures):
            completed += 1
            if progress:
                progress(completed, len(futures))
            metrics = future.result()
            if metrics is not None:
                results.append(metrics)

    if not results:
        return pd.DataFrame(columns=[
            "code", "market", "company", "sector", "exchange", "current_price",
            "price_return_pct", "revenue_yoy_pct", "net_income_yoy_pct",
            "net_income_turned_negative", "market_cap", "pe_ratio",
            "pct_from_52wk_high", "revenue_cagr_pct", "revenue_accelerating",
            "gross_margin_pct", "gross_margin_trend_pp", "net_margin_pct",
            "peg_ratio", "rule_of_40", "ticker_yf",
        ])

    df = pd.DataFrame(results)
    return df.sort_values("price_return_pct").reset_index(drop=True)
