"""
NSE F&O Business Growth data fetcher.
Source: https://www.nseindia.com/market-data/business-growth-fo-segment
API: https://www.nseindia.com/api/reports?archives=[{"name":"F&O - Business Growth","type":"archives","category":"derivatives","section":"equity"}]&date=DD-MMM-YYYY&type=equity&mode=single
"""
import json
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from .base import get_session, retry_get, trading_days, save_csv, load_csv, DATA_DIR

NSE_BASE = "https://www.nseindia.com"
NSE_FO_ARCHIVE_URL = "https://www.nseindia.com/api/historicalRates-equityFOdata"

# NSE weekly expiry: Thursday
NSE_EXPIRY_WEEKDAY = 3  # Monday=0


def _build_nse_params(from_date: datetime, to_date: datetime) -> dict:
    return {
        "segment": "equity",
        "from": from_date.strftime("%d-%m-%Y"),
        "to": to_date.strftime("%d-%m-%Y"),
    }


def fetch_nse_fo_data(from_date: datetime, to_date: datetime, use_cache=True) -> pd.DataFrame:
    cache_file = f"nse_fo_{from_date.strftime('%Y%m%d')}_{to_date.strftime('%Y%m%d')}.csv"
    if use_cache:
        cached = load_csv("nse", cache_file)
        if cached is not None:
            cached["date"] = pd.to_datetime(cached["date"])
            return cached

    df = _fetch_live_nse(from_date, to_date)
    if df is None or df.empty:
        print("[NSE] Live fetch failed — using synthetic sample data.")
        df = _generate_sample_data(from_date, to_date, "NSE")
    else:
        print(f"[NSE] Fetched {len(df)} rows from live API.")

    save_csv(df, "nse", cache_file)
    return df


def _fetch_live_nse(from_date: datetime, to_date: datetime) -> pd.DataFrame | None:
    try:
        session = get_session(NSE_BASE)
        params = _build_nse_params(from_date, to_date)
        resp = retry_get(session, NSE_FO_ARCHIVE_URL, params=params)
        if resp is None:
            return None
        data = resp.json()
        # NSE returns {"data": [...]} or list directly
        if isinstance(data, dict):
            rows = data.get("data", data.get("indexCloseOnlineRecords", []))
        else:
            rows = data
        if not rows:
            return None
        df = pd.DataFrame(rows)
        return _normalize_nse(df)
    except Exception as e:
        print(f"[NSE] Fetch error: {e}")
        return None


def _normalize_nse(df: pd.DataFrame) -> pd.DataFrame:
    # NSE API column names vary — map best-effort
    col_map = {
        "date": ["date", "DATE", "tradeDate", "TIMESTAMP"],
        "turnover_cr": ["TURNOVER", "turnover", "totalTurnover", "TOTAL_TURNOVER_LAKH"],
        "contracts": ["NO_OF_CONTRACTS", "noOfContracts", "contracts", "CONTRACTS"],
        "notional_turnover": ["NOTIONAL_TURNOVER", "notionalTurnover"],
        "premium_turnover": ["PREMIUM_TURNOVER", "premiumTurnover"],
        "oi_contracts": ["OPEN_INT", "openInterest", "OI_CONTRACTS"],
        "oi_value": ["OI_VALUE", "oiValue"],
    }
    result = {}
    for target, candidates in col_map.items():
        for c in candidates:
            if c in df.columns:
                result[target] = df[c]
                break

    out = pd.DataFrame(result)
    if "date" not in out.columns:
        return pd.DataFrame()

    out["date"] = pd.to_datetime(out["date"], dayfirst=True, errors="coerce")
    out = out.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)

    for col in ["turnover_cr", "contracts", "notional_turnover", "premium_turnover", "oi_contracts", "oi_value"]:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
        else:
            out[col] = np.nan

    out["exchange"] = "NSE"
    return out


def _generate_sample_data(from_date: datetime, to_date: datetime, exchange: str) -> pd.DataFrame:
    """Generate realistic synthetic F&O data when live fetch is unavailable."""
    np.random.seed(42)
    days = trading_days(from_date, to_date)
    n = len(days)

    # Simulate realistic NSE F&O turnover with trend + noise
    base_turnover = 18000  # ~18,000 Cr/day starting point
    trend = np.linspace(0, 4000, n)  # mild uptrend
    noise = np.random.normal(0, 1200, n)
    weekly_cycle = 1800 * np.sin(np.linspace(0, 4 * np.pi, n))  # expiry week spike
    turnover = base_turnover + trend + noise + weekly_cycle
    turnover = np.maximum(turnover, 5000)

    base_contracts = 95_000_000
    contracts = (base_contracts + np.random.normal(0, 8_000_000, n) +
                 np.linspace(0, 15_000_000, n)).astype(int)
    contracts = np.maximum(contracts, 10_000_000)

    oi_base = 4_500_000
    oi = (oi_base + np.random.normal(0, 200_000, n) + np.linspace(0, 500_000, n)).astype(int)

    premium = turnover * 0.08 + np.random.normal(0, 200, n)

    df = pd.DataFrame({
        "date": days,
        "turnover_cr": np.round(turnover, 2),
        "contracts": contracts,
        "notional_turnover": np.round(turnover * 12, 2),
        "premium_turnover": np.round(np.maximum(premium, 500), 2),
        "oi_contracts": oi,
        "oi_value": np.round(oi * 0.0012, 2),
        "exchange": exchange,
    })
    return df
