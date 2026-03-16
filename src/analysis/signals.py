"""
F&O-based trading signal analysis.

Signal logic:
  - PRIMARY: Turnover 5-day MA direction vs 20-day MA
  - CONFIRMATION: OI change direction (rising OI + rising price = bullish money flow)
  - EXPIRY EFFECT: Signal strength reduced 1 day before / day of expiry

Signal levels:
  STRONG_BUY   : 5MA > 20MA && turnover rising && OI rising
  BUY          : 5MA > 20MA && (turnover rising OR OI rising)
  NEUTRAL      : 5MA ≈ 20MA (within 2%)
  SHORT        : 5MA < 20MA && (turnover falling OR OI falling)
  STRONG_SHORT : 5MA < 20MA && turnover falling && OI falling
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# Weekly expiry weekdays per exchange
# NSE Nifty 50 weekly options: Tuesday
# BSE Sensex weekly options: Tuesday (post-SEBI Oct-2024 rationalisation)
# IEX Term-Ahead contracts: Tuesday
EXPIRY_WEEKDAY = {
    "NSE": 1,   # Tuesday  (Nifty weekly options)
    "BSE": 1,   # Tuesday  (Sensex weekly options)
    "IEX": 1,   # Tuesday
}

SIGNAL_COLORS = {
    "STRONG_BUY":   "#00c853",
    "BUY":          "#69f0ae",
    "NEUTRAL":      "#ffeb3b",
    "SHORT":        "#ff6d00",
    "STRONG_SHORT": "#d50000",
}

SIGNAL_VALUES = {
    "STRONG_BUY":   2,
    "BUY":          1,
    "NEUTRAL":      0,
    "SHORT":        -1,
    "STRONG_SHORT": -2,
}


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add MA, momentum, OI change, and signal columns to a single exchange df."""
    df = df.copy().sort_values("date").reset_index(drop=True)
    exchange = df["exchange"].iloc[0] if "exchange" in df.columns else "NSE"

    # ── Moving averages on turnover
    df["ma5"]  = df["turnover_cr"].rolling(5, min_periods=1).mean()
    df["ma10"] = df["turnover_cr"].rolling(10, min_periods=1).mean()
    df["ma20"] = df["turnover_cr"].rolling(20, min_periods=1).mean()

    # ── Turnover momentum: % change vs 5 days ago
    df["turnover_mom5"] = df["turnover_cr"].pct_change(5) * 100

    # ── OI change (day-over-day contracts)
    if "oi_contracts" in df.columns:
        df["oi_change"] = df["oi_contracts"].diff()
        df["oi_pct"]    = df["oi_contracts"].pct_change() * 100
    else:
        df["oi_change"] = np.nan
        df["oi_pct"]    = np.nan

    # ── Premium turnover momentum (options activity)
    if "premium_turnover" in df.columns:
        df["premium_ma5"] = df["premium_turnover"].rolling(5, min_periods=1).mean()
        df["premium_mom5"] = df["premium_turnover"].pct_change(5) * 100
    else:
        df["premium_ma5"] = np.nan
        df["premium_mom5"] = np.nan

    # ── Expiry flag
    expiry_wd = EXPIRY_WEEKDAY.get(exchange, 3)
    df["is_expiry"]   = df["date"].dt.weekday == expiry_wd
    df["pre_expiry"]  = df["date"].apply(
        lambda d: _is_day_before_expiry(d, expiry_wd)
    )

    # ── Signal generation
    df["signal"] = df.apply(lambda row: _compute_signal(row), axis=1)
    df["signal_value"] = df["signal"].map(SIGNAL_VALUES)
    df["signal_color"] = df["signal"].map(SIGNAL_COLORS)

    return df


def _is_day_before_expiry(date: datetime, expiry_wd: int) -> bool:
    next_day = date + timedelta(days=1)
    # Skip weekends when looking for "next trading day"
    while next_day.weekday() >= 5:
        next_day += timedelta(days=1)
    return next_day.weekday() == expiry_wd


def _compute_signal(row: pd.Series) -> str:
    ma5 = row.get("ma5", np.nan)
    ma20 = row.get("ma20", np.nan)
    mom5 = row.get("turnover_mom5", np.nan)
    oi_pct = row.get("oi_pct", np.nan)
    is_expiry = row.get("is_expiry", False)
    pre_expiry = row.get("pre_expiry", False)

    if pd.isna(ma5) or pd.isna(ma20) or ma20 == 0:
        return "NEUTRAL"

    ma_spread = (ma5 - ma20) / ma20 * 100  # % spread

    # Determine trend direction from MA spread
    if ma_spread > 2:
        trend = "bullish"
    elif ma_spread < -2:
        trend = "bearish"
    else:
        trend = "neutral"

    # Turnover momentum
    if not pd.isna(mom5):
        to_rising = mom5 > 3
        to_falling = mom5 < -3
    else:
        to_rising = to_falling = False

    # OI direction
    if not pd.isna(oi_pct):
        oi_rising  = oi_pct > 1
        oi_falling = oi_pct < -1
    else:
        oi_rising = oi_falling = False

    # On expiry/pre-expiry days, reduce to one level (unwinding effect)
    expiry_dampener = is_expiry or pre_expiry

    if trend == "bullish":
        if to_rising and oi_rising and not expiry_dampener:
            return "STRONG_BUY"
        elif (to_rising or oi_rising):
            return "BUY"
        else:
            return "NEUTRAL"
    elif trend == "bearish":
        if to_falling and oi_falling and not expiry_dampener:
            return "STRONG_SHORT"
        elif (to_falling or oi_falling):
            return "SHORT"
        else:
            return "NEUTRAL"
    else:
        return "NEUTRAL"


def aggregate_signals(dfs: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """
    Combine signals across exchanges into a composite momentum score.
    Returns a df indexed by date with per-exchange signal values and composite.
    """
    signal_dfs = []
    for exchange, df in dfs.items():
        if df.empty:
            continue
        sub = df[["date", "signal_value", "turnover_cr", "ma5", "ma20"]].copy()
        sub.columns = ["date", f"{exchange}_signal", f"{exchange}_turnover",
                       f"{exchange}_ma5", f"{exchange}_ma20"]
        signal_dfs.append(sub.set_index("date"))

    if not signal_dfs:
        return pd.DataFrame()

    combined = pd.concat(signal_dfs, axis=1).sort_index()

    sig_cols = [c for c in combined.columns if c.endswith("_signal")]
    combined["composite_score"] = combined[sig_cols].mean(axis=1)
    combined["composite_signal"] = combined["composite_score"].apply(_score_to_signal)
    combined = combined.reset_index()
    return combined


def _score_to_signal(score: float) -> str:
    if pd.isna(score):
        return "NEUTRAL"
    if score >= 1.5:
        return "STRONG_BUY"
    elif score >= 0.5:
        return "BUY"
    elif score <= -1.5:
        return "STRONG_SHORT"
    elif score <= -0.5:
        return "SHORT"
    return "NEUTRAL"


def get_latest_signals(dfs: dict[str, pd.DataFrame]) -> dict:
    """Return latest signal info per exchange + composite."""
    result = {}
    for exchange, df in dfs.items():
        if df.empty:
            continue
        last = df.iloc[-1]
        result[exchange] = {
            "date": last["date"].strftime("%Y-%m-%d"),
            "signal": last["signal"],
            "turnover_cr": round(last["turnover_cr"], 2),
            "ma5": round(last["ma5"], 2),
            "ma20": round(last["ma20"], 2),
            "ma_spread_pct": round((last["ma5"] - last["ma20"]) / last["ma20"] * 100, 2)
                             if last["ma20"] > 0 else 0,
            "turnover_mom5": round(last.get("turnover_mom5", 0) or 0, 2),
        }

    composite = aggregate_signals(dfs)
    if not composite.empty:
        last = composite.iloc[-1]
        result["COMPOSITE"] = {
            "date": last["date"].strftime("%Y-%m-%d"),
            "signal": last["composite_signal"],
            "composite_score": round(last["composite_score"], 2),
        }
    return result
