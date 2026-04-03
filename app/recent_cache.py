# === app/utils/recent_cache.py START ===
import json
import os
from datetime import datetime, timedelta

CACHE_FILE = "recent_recommendations.json"


def _load_cache():
    if not os.path.exists(CACHE_FILE):
        return []

    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save_cache(data):
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception:
        pass


def add_recommendations(tickers: list[str]):
    data = _load_cache()
    now = datetime.now().isoformat()

    for t in tickers:
        data.append({"ticker": t, "time": now})

    _save_cache(data)


def get_recent_tickers(days: int = 3) -> set:
    data = _load_cache()
    cutoff = datetime.now() - timedelta(days=days)

    result = set()
    for row in data:
        try:
            t = datetime.fromisoformat(row["time"])
            if t >= cutoff:
                result.add(row["ticker"])
        except Exception:
            continue

    return result
# === app/utils/recent_cache.py END ===
