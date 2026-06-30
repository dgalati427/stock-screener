# Stock Screener — "Sentiment Drop" Finder

Screens the S&P 500 (US) and S&P/ASX 200 (Australia) for stocks where the
price has fallen significantly over the last 12 months, but revenue and net
income (latest annual report vs. the year before) haven't deteriorated by
much. The idea: a big price drop with stable financials is more likely to be
driven by sentiment, media controversy, or broad market moves than by an
actual change in the business.

**This is a heuristic, not a fact-finder.** The script has no idea *why* a
stock dropped — it only compares price vs. financial-statement trends.
Always read the news on anything it flags before drawing conclusions. Not
financial advice.

## Web app

Live at: https://stock-screener-kfjsu665yee3yhbtwwfdfx.streamlit.app/

`app.py` is a Streamlit UI on top of the same data: a filterable, sortable
table plus a drill-down panel (live price chart + key stats) for any
selected company. It reads `data/latest.csv`, which is regenerated every 4
hours by `.github/workflows/update-data.yml` (GitHub Actions runs
`update_data.py` and commits the result, which auto-redeploys the app).

To run it locally:

```
pip install -r requirements.txt
streamlit run app.py
```

Besides the core filters (market, sector, price drop %, revenue/earnings
tolerance), the sidebar has an **Additional filters** section, off by
default, for standard metrics: minimum market cap, maximum P/E ratio, and
minimum % below the 52-week high.

## CLI

```
pip install -r requirements.txt
python screener.py
```

Runs the full S&P 500 + ASX 200 screen with default thresholds (price down
30%+ over 12 months, revenue down no more than 10% YoY, net income down no
more than 25% YoY) and writes `results_<timestamp>.csv`.

### Useful options

```
python screener.py --markets us         # US only
python screener.py --markets asx        # ASX only
python screener.py --drop-threshold 40  # require a 40%+ decline
python screener.py --limit 20           # quick test run, 20 tickers per market
python screener.py --output myfile.csv
```

Run `python screener.py --help` for all options.

## How the filter works

For each ticker:
1. Pull 1-year daily price history → compute % return.
2. Pull the latest two annual income statements → compute YoY % change in
   revenue and net income.
3. Flag the stock if:
   - Price is down at least `--drop-threshold`% (default 30%), **and**
   - Revenue is not down more than `--revenue-tolerance`% YoY (default 10%), **and**
   - Net income is not down more than `--income-tolerance`% YoY (default 25%)
     and did not flip from profitable to a loss.

Each ticker also carries market cap, trailing P/E (market cap / latest
annual net income), exchange (NASDAQ / NYSE / ASX), and % below its
52-week high — used as optional filters in the web app, and included as
extra columns in the CLI's CSV output.

## Notes / limitations

- Ticker universes are scraped live from Wikipedia's S&P 500 and S&P/ASX 200
  pages, so they reflect current index membership, not a fixed snapshot. The
  S&P 500 isn't exchange-specific — it already includes both NASDAQ and NYSE
  listings (e.g. AAPL on NASDAQ, JPM on NYSE).
- Data comes from Yahoo Finance via `yfinance`. It's free but occasionally
  flaky/rate-limited — failed tickers are skipped and logged to stderr, not
  treated as fatal.
- Annual financials can lag (some companies report infrequently), and YoY
  swings can be noisy for cyclical or one-off items — treat the numeric
  tolerances as a coarse filter, not a precise valuation signal.
- This only screens for the *pattern* (price down, fundamentals stable). It
  cannot distinguish "media controversy" from other causes (e.g. a sector-wide
  sell-off, a one-off legal settlement, a leadership change) — that judgment
  is on you.
