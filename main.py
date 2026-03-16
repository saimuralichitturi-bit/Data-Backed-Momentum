#!/usr/bin/env python3
"""
Exchange F&O Trading Signals
=============================
Fetches daily F&O data from NSE, BSE, MCX, IEX and generates:
  - Interactive charts: daily turnover + 5-day MA + 20-day MA + weekly expiry markers
  - Buy / Short signals based on turnover trend & OI momentum
  - Composite signal across all four exchanges

Usage:
    python main.py                          # last 60 trading days
    python main.py --days 90
    python main.py --from 2025-01-01 --to 2025-03-15
    python main.py --no-cache               # force re-fetch (ignores local cache)
"""
import sys
import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path

# Ensure src is importable when running from project root
sys.path.insert(0, str(Path(__file__).parent))

from src.fetchers.nse_fetcher import fetch_nse_fo_data
from src.fetchers.bse_fetcher import fetch_bse_fo_data
from src.fetchers.mcx_fetcher import fetch_mcx_fo_data
from src.fetchers.iex_fetcher import fetch_iex_data
from src.analysis.signals import compute_indicators, aggregate_signals, get_latest_signals
from src.viz.charts import build_exchange_chart, build_signal_summary_chart, save_charts


def parse_args():
    p = argparse.ArgumentParser(description="Exchange F&O Trading Signals")
    p.add_argument("--days", type=int, default=60,
                   help="Number of trading days to look back (default: 60)")
    p.add_argument("--from", dest="from_date", type=str, default=None,
                   help="Start date YYYY-MM-DD (overrides --days)")
    p.add_argument("--to", dest="to_date", type=str, default=None,
                   help="End date YYYY-MM-DD (default: today)")
    p.add_argument("--no-cache", dest="no_cache", action="store_true",
                   help="Force re-fetch, ignore cached data")
    p.add_argument("--exchanges", nargs="+", default=["NSE", "BSE", "MCX", "IEX"],
                   choices=["NSE", "BSE", "MCX", "IEX"],
                   help="Exchanges to include (default: all)")
    return p.parse_args()


def main():
    args = parse_args()
    use_cache = not args.no_cache

    to_date = datetime.strptime(args.to_date, "%Y-%m-%d") if args.to_date else datetime.today()
    if args.from_date:
        from_date = datetime.strptime(args.from_date, "%Y-%m-%d")
    else:
        # Approx trading days: multiply calendar days by 1.4 to account for weekends
        from_date = to_date - timedelta(days=int(args.days * 1.4))

    print(f"\n{'='*60}")
    print(f"  Exchange F&O Signal Analysis")
    print(f"  Period : {from_date.strftime('%d %b %Y')} → {to_date.strftime('%d %b %Y')}")
    print(f"  Exchanges: {', '.join(args.exchanges)}")
    print(f"{'='*60}\n")

    # ── 1. Fetch raw data
    raw: dict = {}
    fetchers = {
        "NSE": lambda: fetch_nse_fo_data(from_date, to_date, use_cache),
        "BSE": lambda: fetch_bse_fo_data(from_date, to_date, use_cache),
        "MCX": lambda: fetch_mcx_fo_data(from_date, to_date, use_cache),
        "IEX": lambda: fetch_iex_data(from_date, to_date, use_cache),
    }
    for exchange in args.exchanges:
        print(f"[{exchange}] Fetching data...")
        try:
            raw[exchange] = fetchers[exchange]()
        except Exception as e:
            print(f"[{exchange}] ERROR: {e}")
            raw[exchange] = None

    # ── 2. Compute indicators & signals
    processed: dict = {}
    for exchange, df in raw.items():
        if df is None or df.empty:
            print(f"[{exchange}] No data — skipping.")
            continue
        processed[exchange] = compute_indicators(df)
        last = processed[exchange].iloc[-1]
        print(f"[{exchange}] Latest ({last['date'].strftime('%d %b')}) | "
              f"Turnover: ₹{last['turnover_cr']:,.0f} Cr | "
              f"5-MA: ₹{last['ma5']:,.0f} Cr | "
              f"Signal: {last['signal']}")

    if not processed:
        print("No data available. Exiting.")
        return

    # ── 3. Aggregate composite signal
    composite_df = aggregate_signals(processed)
    latest_signals = get_latest_signals(processed)

    print(f"\n{'─'*60}")
    print("  SIGNAL SUMMARY")
    print(f"{'─'*60}")
    for exchange, info in latest_signals.items():
        if exchange == "COMPOSITE":
            print(f"  {'COMPOSITE':8s}  →  {info['signal']:12s}  (score: {info.get('composite_score', 0):+.2f})")
        else:
            print(f"  {exchange:8s}  →  {info['signal']:12s}  "
                  f"MA spread: {info.get('ma_spread_pct', 0):+.1f}%  "
                  f"MOM5: {info.get('turnover_mom5', 0):+.1f}%")
    print(f"{'─'*60}\n")

    # ── 4. Build & save charts
    main_fig = build_exchange_chart(
        processed,
        composite_df=composite_df,
        title=(f"NSE · BSE · MCX · IEX — F&O Daily Activity & Signals  "
               f"({from_date.strftime('%d %b %Y')} – {to_date.strftime('%d %b %Y')})"),
    )
    snapshot_fig = build_signal_summary_chart(latest_signals)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    main_path, snap_path = save_charts(main_fig, snapshot_fig, tag=ts)

    # ── 5. Save signal JSON report
    report_path = Path("output") / f"signals_{ts}.json"
    report_path.parent.mkdir(exist_ok=True)
    with open(report_path, "w") as f:
        json.dump(latest_signals, f, indent=2)
    print(f"[Report] Saved signal report: {report_path.name}")

    print(f"\n[Done] Charts saved to:")
    print(f"  {main_path}")
    print(f"  {snap_path}")
    print()


if __name__ == "__main__":
    main()
