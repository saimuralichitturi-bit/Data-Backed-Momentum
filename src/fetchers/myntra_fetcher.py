"""Myntra fetcher – scrapes Thomas Scott product listings as daily sales proxy.

Proxy metrics (no direct sales API available):
  - rating_count_delta  : new ratings since last snapshot  ≈ sales velocity
  - avg_rating          : product quality signal
  - price / mrp         : pricing dynamics
  - discount_pct        : promotional intensity
  - in_stock            : availability (stock-out = sold through)

Myntra exposes an internal search/gateway JSON API that returns product cards
with rating counts, prices, and category metadata — sufficient for daily proxy
tracking without requiring any authentication.
"""

import json
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

from .base import DATA_DIR, get_session, retry_get, save_csv, load_csv

MYNTRA_BASE = "https://www.myntra.com"
SEARCH_API = "https://www.myntra.com/gateway/v2/search/thomas%20scott"
BRAND = "Thomas Scott"
EXCHANGE = "myntra"

# Extra headers Myntra expects
MYNTRA_EXTRA_HEADERS = {
    "Referer": "https://www.myntra.com/thomas-scott",
    "Origin": "https://www.myntra.com",
    "x-location-code": "MH",
    "x-myntraweb": "Yes",
    "x-requested-with": "browser",
}


def _build_session() -> requests.Session:
    session = get_session(MYNTRA_BASE)
    session.headers.update(MYNTRA_EXTRA_HEADERS)
    # Pre-warm cookie by visiting brand page
    try:
        session.get(
            f"{MYNTRA_BASE}/thomas-scott",
            timeout=10,
            allow_redirects=True,
        )
    except Exception:
        pass
    return session


def _parse_products(raw: dict) -> list[dict]:
    """Extract product rows from Myntra search gateway response."""
    rows = []
    try:
        products = (
            raw.get("searchData", {})
               .get("results", {})
               .get("products", [])
        )
    except AttributeError:
        return rows

    for p in products:
        try:
            price_info = p.get("price", {})
            mrp = float(price_info.get("mrp", 0) or 0)
            discounted = float(price_info.get("discounted", mrp) or mrp)
            discount_pct = round((mrp - discounted) / mrp * 100, 1) if mrp > 0 else 0.0

            rows.append({
                "product_id": str(p.get("productId", "")),
                "product_name": p.get("productName", ""),
                "brand": p.get("brandName", BRAND),
                "category": p.get("category", ""),
                "sub_category": p.get("subCategory", ""),
                "mrp": mrp,
                "price": discounted,
                "discount_pct": discount_pct,
                "avg_rating": float(p.get("rating", 0) or 0),
                "rating_count": int(p.get("ratingCount", 0) or 0),
                "in_stock": not p.get("isOutOfStock", False),
            })
        except Exception:
            continue
    return rows


def _fetch_all_pages(session: requests.Session) -> list[dict]:
    """Paginate through all Thomas Scott results (50 per page)."""
    all_products = []
    page_size = 50
    offset = 0

    while True:
        params = {
            "rawQuery": "thomas scott",
            "o": offset,
            "n": page_size,
            "plaEnabled": "false",
        }
        resp = retry_get(session, SEARCH_API, params=params)
        if resp is None:
            break

        try:
            data = resp.json()
        except Exception:
            break

        products = _parse_products(data)
        if not products:
            break

        all_products.extend(products)

        # Check total count to decide whether to paginate
        try:
            total = int(
                data.get("searchData", {})
                    .get("results", {})
                    .get("totalCount", 0)
            )
        except Exception:
            total = 0

        offset += page_size
        if offset >= total or total == 0:
            break

        time.sleep(0.5)  # polite crawl delay

    return all_products


def fetch_thomas_scott_snapshot(use_cache: bool = True) -> pd.DataFrame:
    """Return a DataFrame of all current Thomas Scott listings on Myntra.

    Each call represents one daily snapshot.  Cache key is today's date so
    repeated calls on the same day return the cached result.
    """
    today_str = datetime.today().strftime("%Y%m%d")
    cache_file = f"thomas_scott_snapshot_{today_str}.csv"

    if use_cache:
        cached = load_csv(EXCHANGE, cache_file)
        if cached is not None and not cached.empty:
            return cached

    session = _build_session()
    products = _fetch_all_pages(session)

    if not products:
        # Graceful fallback: load most recent snapshot if available
        data_dir = DATA_DIR / EXCHANGE
        snapshots = sorted(data_dir.glob("thomas_scott_snapshot_*.csv")) if data_dir.exists() else []
        if snapshots:
            df = pd.read_csv(snapshots[-1])
            df["fetched_date"] = today_str
            return df
        return pd.DataFrame()

    df = pd.DataFrame(products)
    df["fetched_date"] = today_str
    df = df.drop_duplicates(subset=["product_id"])

    save_csv(df, EXCHANGE, cache_file)
    return df


def compute_daily_proxy(days: int = 30) -> pd.DataFrame:
    """Aggregate all saved snapshots into a daily proxy sales DataFrame.

    Returns one row per day with:
      - total_skus          : total Thomas Scott SKUs listed
      - in_stock_skus       : SKUs currently in stock
      - out_of_stock_skus   : SKUs sold out (high = sold through)
      - avg_rating_count    : mean rating count across all SKUs
      - total_rating_count  : sum of all ratings (cumulative proxy)
      - rating_count_delta  : new ratings vs prior day  ← SALES PROXY
      - avg_discount_pct    : average discount across SKUs
      - avg_price           : average selling price
      - avg_rating          : average product rating
    """
    data_dir = DATA_DIR / EXCHANGE
    if not data_dir.exists():
        return pd.DataFrame()

    snapshots = sorted(data_dir.glob("thomas_scott_snapshot_*.csv"))
    if not snapshots:
        return pd.DataFrame()

    daily_rows = []
    for snap_path in snapshots:
        df = pd.read_csv(snap_path)
        if df.empty:
            continue

        date_str = snap_path.stem.replace("thomas_scott_snapshot_", "")
        try:
            snap_date = datetime.strptime(date_str, "%Y%m%d").date()
        except ValueError:
            continue

        total_ratings = int(df["rating_count"].sum())
        in_stock = int(df["in_stock"].sum()) if "in_stock" in df.columns else len(df)

        daily_rows.append({
            "date": snap_date,
            "total_skus": len(df),
            "in_stock_skus": in_stock,
            "out_of_stock_skus": len(df) - in_stock,
            "total_rating_count": total_ratings,
            "avg_rating_count": round(df["rating_count"].mean(), 1),
            "avg_discount_pct": round(df["discount_pct"].mean(), 1),
            "avg_price": round(df["price"].mean(), 2),
            "avg_rating": round(df["avg_rating"].mean(), 2),
        })

    if not daily_rows:
        return pd.DataFrame()

    agg = pd.DataFrame(daily_rows).sort_values("date").reset_index(drop=True)

    # Delta = new ratings per day (primary sales proxy)
    agg["rating_count_delta"] = agg["total_rating_count"].diff().fillna(0).astype(int)

    return agg


def get_category_breakdown(snapshot_date: str | None = None) -> pd.DataFrame:
    """Return category-level summary for a given snapshot (default: today).

    Columns: category, sku_count, avg_price, avg_discount_pct,
             avg_rating, total_rating_count, in_stock_count
    """
    if snapshot_date is None:
        snapshot_date = datetime.today().strftime("%Y%m%d")

    df = load_csv(EXCHANGE, f"thomas_scott_snapshot_{snapshot_date}.csv")
    if df is None or df.empty:
        df = fetch_thomas_scott_snapshot()

    if df.empty:
        return pd.DataFrame()

    grp = (
        df.groupby("category")
          .agg(
              sku_count=("product_id", "count"),
              avg_price=("price", "mean"),
              avg_discount_pct=("discount_pct", "mean"),
              avg_rating=("avg_rating", "mean"),
              total_rating_count=("rating_count", "sum"),
              in_stock_count=("in_stock", "sum"),
          )
          .round(2)
          .reset_index()
          .sort_values("total_rating_count", ascending=False)
    )
    return grp
