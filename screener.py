"""
CLI: finds US (S&P 500) and/or ASX (S&P/ASX 200) stocks whose price has
fallen significantly over the last 12 months while revenue and net income
(year-over-year, from the latest annual financials) have stayed roughly flat
or improved.

This is a heuristic for "the drop looks sentiment/controversy-driven rather
than fundamentals-driven" -- it does NOT know about news, lawsuits, or PR
controversies. It only checks: big price drop + stable-or-growing financials.
Always read the news on any flagged company before drawing conclusions.

Not financial advice.
"""

import argparse
from datetime import datetime

from tqdm import tqdm

import core


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--markets", default="us,asx",
                    help="Comma-separated markets to screen: us, asx (default: us,asx)")
    p.add_argument("--drop-threshold", type=float, default=30.0,
                    help="Flag stocks whose price is down at least this percent over 12 months (default: 30)")
    p.add_argument("--revenue-tolerance", type=float, default=10.0,
                    help="Allow trailing-year revenue to be down up to this percent YoY and still pass (default: 10)")
    p.add_argument("--income-tolerance", type=float, default=25.0,
                    help="Allow trailing-year net income to be down up to this percent YoY and still pass (default: 25)")
    p.add_argument("--limit", type=int, default=None,
                    help="Only screen the first N tickers per market (useful for a quick test run)")
    p.add_argument("--workers", type=int, default=6,
                    help="Number of parallel download threads (default: 6; keep modest to avoid rate limiting)")
    p.add_argument("--output", default=None,
                    help="Output CSV path (default: results_<timestamp>.csv)")
    return p.parse_args()


def run_screen(args):
    markets = [m.strip().lower() for m in args.markets.split(",") if m.strip()]

    print("Fetching ticker universe from Wikipedia...")
    universe = core.build_universe(markets, limit=args.limit)
    print(f"Screening {len(universe)} tickers across {markets} "
          f"(this can take a while due to rate limiting)...")

    bar = tqdm(total=len(universe))

    def on_progress(done, total):
        bar.n = done
        bar.refresh()

    df = core.scan_all(markets, limit=args.limit, workers=args.workers, progress=on_progress)
    bar.close()

    mask = df.apply(
        lambda row: core.passes_filters(row, args.drop_threshold, args.revenue_tolerance, args.income_tolerance),
        axis=1,
    )
    df = df[mask]

    if df.empty:
        print("No candidates matched the filters.")
        return

    columns = [
        "code", "market", "company", "sector", "current_price",
        "price_return_pct", "revenue_yoy_pct", "net_income_yoy_pct",
    ]
    df = df[columns]

    output_path = args.output or f"results_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    df.to_csv(output_path, index=False)
    print(f"\n{len(df)} candidates written to {output_path}\n")
    print(df.to_string(index=False))
    print("\nReminder: this only screens price vs. revenue/earnings trends. "
          "It does not know WHY a stock dropped -- check the news on each "
          "flagged company yourself before drawing conclusions. Not financial advice.")


if __name__ == "__main__":
    run_screen(parse_args())
