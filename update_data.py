"""
Scheduled job: scans the full US + ASX universe and writes data/latest.csv.
Run manually, or on a schedule via .github/workflows/update-data.yml.
"""

import os
import sys
from datetime import datetime, timezone

import core

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
DATA_PATH = os.path.join(DATA_DIR, "latest.csv")

# A healthy scan returns ~600+ rows. If Yahoo Finance rate-limits the run,
# far fewer tickers come back. Refuse to overwrite good data with a mostly
# empty scan -- keep the previous file so the app never sees an empty table.
MIN_ACCEPTABLE_ROWS = 200


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    print("Scanning US + ASX universe...")
    df = core.scan_all(markets=["us", "asx"], workers=3,
                        progress=lambda done, total: print(f"  {done}/{total}", end="\r"))

    if len(df) < MIN_ACCEPTABLE_ROWS:
        print(f"\nOnly {len(df)} tickers came back (< {MIN_ACCEPTABLE_ROWS}); "
              "this run was probably rate-limited. Keeping the existing "
              "data/latest.csv instead of overwriting it with a thin scan.",
              file=sys.stderr)
        # Exit non-zero so the workflow's `git commit` step finds nothing staged
        # (the file is unchanged) and simply skips -- the good data survives.
        return

    df["last_updated_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    df.to_csv(DATA_PATH, index=False)
    print(f"\nSaved {len(df)} tickers to {DATA_PATH}")


if __name__ == "__main__":
    main()
