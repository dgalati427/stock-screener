"""
Scheduled job: scans the full US + ASX universe and writes data/latest.csv.
Run manually, or on a schedule via .github/workflows/update-data.yml.
"""

import os
from datetime import datetime, timezone

import core

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
DATA_PATH = os.path.join(DATA_DIR, "latest.csv")


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    print("Scanning US + ASX universe...")
    df = core.scan_all(markets=["us", "asx"], workers=3,
                        progress=lambda done, total: print(f"  {done}/{total}", end="\r"))
    df["last_updated_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    df.to_csv(DATA_PATH, index=False)
    print(f"\nSaved {len(df)} tickers to {DATA_PATH}")


if __name__ == "__main__":
    main()
