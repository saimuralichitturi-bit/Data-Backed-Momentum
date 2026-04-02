"""Daily Thomas Scott proxy sales tracker for Myntra.

Usage:
    python track_myntra.py                  # Fetch today + show daily proxy table
    python track_myntra.py --history        # Show full daily history
    python track_myntra.py --categories     # Show category breakdown for today
    python track_myntra.py --skus           # Dump all current SKUs
    python track_myntra.py --no-cache       # Force re-fetch even if cached today

How it works (proxy methodology):
  Myntra doesn't expose sales data publicly.  We track three proxy signals:

  1. rating_count_delta  – new ratings accrued each day.
     Rated purchases are ~5–15% of actual purchases (platform average).
     A consistent multiplier makes delta a reliable relative indicator.

  2. out_of_stock_skus   – SKUs that went OOS since the prior snapshot.
     A spike = sell-through event (clearance or flash sale).

  3. avg_discount_pct    – rising discount = push for volume,
     falling discount = demand-driven pricing.

Run daily (e.g. via cron at 10:00 AM IST):
    0 10 * * 1-6 cd /home/user/Data-Backed-Momentum && python track_myntra.py >> data/myntra/tracker.log 2>&1
"""

import argparse
import sys
from datetime import datetime

import pandas as pd

from src.fetchers.myntra_fetcher import (
    compute_daily_proxy,
    fetch_thomas_scott_snapshot,
    get_category_breakdown,
)


def _fmt_table(df: pd.DataFrame) -> str:
    return df.to_string(index=False)


def main():
    parser = argparse.ArgumentParser(description="Myntra Thomas Scott proxy tracker")
    parser.add_argument("--history", action="store_true", help="Print full daily proxy history")
    parser.add_argument("--categories", action="store_true", help="Print category breakdown")
    parser.add_argument("--skus", action="store_true", help="Dump all current SKU listings")
    parser.add_argument("--no-cache", action="store_true", help="Force fresh fetch")
    args = parser.parse_args()

    use_cache = not args.no_cache
    today = datetime.today().strftime("%Y-%m-%d")

    print(f"\n{'='*65}")
    print(f"  Myntra  |  Thomas Scott  |  Proxy Sales Tracker  |  {today}")
    print(f"{'='*65}\n")

    # ── 1. Fetch today's snapshot ───────────────────────────────────────────
    print("Fetching today's snapshot from Myntra…")
    snapshot = fetch_thomas_scott_snapshot(use_cache=use_cache)

    if snapshot.empty:
        print("[ERROR] Could not fetch Myntra data. Check network / try --no-cache.")
        sys.exit(1)

    print(f"  {len(snapshot)} Thomas Scott SKUs found on Myntra today.\n")

    # ── 2. SKU dump ─────────────────────────────────────────────────────────
    if args.skus:
        cols = ["product_id", "product_name", "category", "price", "mrp",
                "discount_pct", "avg_rating", "rating_count", "in_stock"]
        display_cols = [c for c in cols if c in snapshot.columns]
        print("── All SKUs ──────────────────────────────────────────────────")
        print(_fmt_table(snapshot[display_cols]))
        print()

    # ── 3. Category breakdown ───────────────────────────────────────────────
    if args.categories or not args.history:
        cat_df = get_category_breakdown()
        if not cat_df.empty:
            print("── Category Breakdown ────────────────────────────────────────")
            print(_fmt_table(cat_df))
            print()

    # ── 4. Daily proxy history ──────────────────────────────────────────────
    proxy_df = compute_daily_proxy()

    if proxy_df.empty:
        print("No historical data yet — run again tomorrow for delta metrics.\n")
        return

    if args.history:
        print("── Daily Proxy History ───────────────────────────────────────")
        print(_fmt_table(proxy_df))
        print()
    else:
        # Show last 7 days by default
        print("── Last 7 Days Proxy Summary ─────────────────────────────────")
        recent = proxy_df.tail(7)
        print(_fmt_table(recent))
        print()

    # ── 5. Latest snapshot summary ─────────────────────────────────────────
    latest = proxy_df.iloc[-1]
    prev = proxy_df.iloc[-2] if len(proxy_df) > 1 else None

    print("── Today's Proxy Signals ─────────────────────────────────────")
    print(f"  Total SKUs listed      : {latest['total_skus']}")
    print(f"  In stock               : {latest['in_stock_skus']}")
    print(f"  Out of stock           : {latest['out_of_stock_skus']}")
    print(f"  Avg discount           : {latest['avg_discount_pct']}%")
    print(f"  Avg selling price      : ₹{latest['avg_price']}")
    print(f"  Avg rating             : {latest['avg_rating']}")
    print(f"  Total ratings (cumul.) : {latest['total_rating_count']:,}")
    print(f"  New ratings today      : {latest['rating_count_delta']:+,}  ← SALES PROXY")

    if prev is not None:
        oos_delta = int(latest["out_of_stock_skus"]) - int(prev["out_of_stock_skus"])
        disc_delta = round(float(latest["avg_discount_pct"]) - float(prev["avg_discount_pct"]), 1)
        print(f"  OOS change vs prior    : {oos_delta:+d} SKUs")
        print(f"  Discount change        : {disc_delta:+.1f}%")

    print()

    # ── 6. Save consolidated proxy CSV ─────────────────────────────────────
    out_path = "data/myntra/daily_proxy_summary.csv"
    proxy_df.to_csv(out_path, index=False)
    print(f"Daily proxy summary saved → {out_path}")
    print()


if __name__ == "__main__":
    main()
