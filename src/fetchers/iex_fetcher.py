"""
IEX (Indian Energy Exchange) market data fetcher.
Source: https://www.iexindia.com/marketdata/
IEX trades electricity contracts (Day-Ahead, Term-Ahead, Real-Time, Renewable Energy).
Weekly expiry: Tuesday
"""
import pandas as pd
import numpy as np
from datetime import datetime
from .base import get_session, retry_get, trading_days, save_csv, load_csv

IEX_BASE = "https://www.iexindia.com"
IEX_MARKET_API = "https://www.iexindia.com/api/MarketData/GetMarketDashboardData"
IEX_HISTORICAL_API = "https://www.iexindia.com/api/MarketData/GetHistoricalData"

# IEX weekly expiry: Tuesday (Term-Ahead contracts)
IEX_EXPIRY_WEEKDAY = 1  # Tuesday


def fetch_iex_data(from_date: datetime, to_date: datetime, use_cache=True) -> pd.DataFrame:
    cache_file = f"iex_{from_date.strftime('%Y%m%d')}_{to_date.strftime('%Y%m%d')}.csv"
    if use_cache:
        cached = load_csv("iex", cache_file)
        if cached is not None:
            cached["date"] = pd.to_datetime(cached["date"])
            return cached

    df = _fetch_live_iex(from_date, to_date)
    if df is None or df.empty:
        print("[IEX] Live fetch failed — using synthetic sample data.")
        df = _generate_sample_data(from_date, to_date)
    else:
        print(f"[IEX] Fetched {len(df)} rows from live API.")

    save_csv(df, "iex", cache_file)
    return df


def _fetch_live_iex(from_date: datetime, to_date: datetime) -> pd.DataFrame | None:
    try:
        session = get_session(IEX_BASE)
        session.headers.update({
            "Referer": "https://www.iexindia.com/marketdata/",
            "X-Requested-With": "XMLHttpRequest",
        })
        params = {
            "fromDate": from_date.strftime("%d/%m/%Y"),
            "toDate": to_date.strftime("%d/%m/%Y"),
            "marketType": "DAM",  # Day-Ahead Market
        }
        resp = retry_get(session, IEX_HISTORICAL_API, params=params)
        if resp is None:
            return None
        data = resp.json()
        rows = data if isinstance(data, list) else data.get("data", data.get("Data", []))
        if not rows:
            return None
        df = pd.DataFrame(rows)
        return _normalize_iex(df)
    except Exception as e:
        print(f"[IEX] Fetch error: {e}")
        return None


def _normalize_iex(df: pd.DataFrame) -> pd.DataFrame:
    col_map = {
        "date": ["Date", "DATE", "TradeDate"],
        "turnover_cr": ["TradedValue", "TotalValue", "Value", "Turnover"],
        "contracts": ["NoOfContracts", "Contracts", "Volume"],
        "oi_contracts": ["OI", "OpenInterest"],
        "volume_mwh": ["Volume_MWh", "VolumeMWh", "EnergyVolume", "TradedVolume"],
        "price_rs_kwh": ["MCPRs", "MCP", "PriceRsKwh", "ClearingPrice"],
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

    for col in ["turnover_cr", "contracts", "oi_contracts", "volume_mwh", "price_rs_kwh"]:
        if col not in out.columns:
            out[col] = np.nan
        else:
            out[col] = pd.to_numeric(out[col], errors="coerce")

    out["notional_turnover"] = out.get("turnover_cr", pd.Series(dtype=float))
    out["premium_turnover"] = np.nan
    out["oi_value"] = np.nan
    out["exchange"] = "IEX"
    return out


def _generate_sample_data(from_date: datetime, to_date: datetime) -> pd.DataFrame:
    np.random.seed(45)
    days = trading_days(from_date, to_date)
    n = len(days)

    # IEX Day-Ahead Market volumes: ~150 MU/day, turnover ~600-800 Cr
    base_volume_mwh = 150_000  # MWh
    volume_trend = np.linspace(0, 20_000, n)
    volume_noise = np.random.normal(0, 12_000, n)
    volume_mwh = base_volume_mwh + volume_trend + volume_noise
    volume_mwh = np.maximum(volume_mwh, 50_000)

    # IEX clearing price Rs/kWh ~ 3.5-5.5
    base_price = 4.2
    price_noise = np.random.normal(0, 0.4, n)
    price = base_price + price_noise
    price = np.clip(price, 2.5, 8.0)

    # Turnover = Volume(MWh) * Price(Rs/kWh) / 10_000_000 to get Cr
    turnover = volume_mwh * price / 10_000_000 * 100  # rough conversion to Cr
    turnover = np.maximum(turnover, 100)

    contracts = (volume_mwh / 100).astype(int)  # 1 contract ~ 100 MWh

    df = pd.DataFrame({
        "date": days,
        "turnover_cr": np.round(turnover, 2),
        "contracts": contracts,
        "notional_turnover": np.round(turnover, 2),
        "premium_turnover": np.nan,
        "oi_contracts": np.nan,
        "oi_value": np.nan,
        "volume_mwh": np.round(volume_mwh, 0),
        "price_rs_kwh": np.round(price, 2),
        "exchange": "IEX",
    })
    return df
