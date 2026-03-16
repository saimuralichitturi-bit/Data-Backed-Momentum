"""Base fetcher with shared session and retry logic."""
import time
import requests
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
import json

DATA_DIR = Path(__file__).parent.parent.parent / "data"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}


def get_session(base_url: str) -> requests.Session:
    session = requests.Session()
    session.headers.update(HEADERS)
    try:
        session.get(base_url, timeout=10)
    except Exception:
        pass
    return session


def retry_get(session: requests.Session, url: str, params=None, retries=3, delay=2) -> requests.Response | None:
    for attempt in range(retries):
        try:
            resp = session.get(url, params=params, timeout=15)
            if resp.status_code == 200:
                return resp
        except Exception:
            pass
        if attempt < retries - 1:
            time.sleep(delay * (2 ** attempt))
    return None


def trading_days(start: datetime, end: datetime) -> list[datetime]:
    """Return list of weekdays between start and end (inclusive)."""
    days = []
    cur = start
    while cur <= end:
        if cur.weekday() < 5:  # Mon-Fri
            days.append(cur)
        cur += timedelta(days=1)
    return days


def cache_path(exchange: str, filename: str) -> Path:
    p = DATA_DIR / exchange / filename
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def save_csv(df: pd.DataFrame, exchange: str, filename: str):
    df.to_csv(cache_path(exchange, filename), index=False)


def load_csv(exchange: str, filename: str) -> pd.DataFrame | None:
    p = cache_path(exchange, filename)
    if p.exists():
        return pd.read_csv(p)
    return None
