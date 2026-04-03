from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from email.utils import parsedate_to_datetime
import xml.etree.ElementTree as ET

from app.utils import request_with_retry


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(round(float(value)))
    except Exception:
        return int(default)


def get_us_daily_chart(symbol: str, days: int = 60) -> list[dict]:
    symbol = str(symbol or "").strip().upper()
    if not symbol:
        return []

    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {
        "range": "1y",
        "interval": "1d",
        "includePrePost": "false",
    }

    resp = request_with_retry(
        "GET",
        url,
        params=params,
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=30,
    )
    data = resp.json()
    result = (((data or {}).get("chart") or {}).get("result") or [None])[0] or {}
    timestamps = result.get("timestamp") or []
    quote = ((((result.get("indicators") or {}).get("quote")) or [None])[0]) or {}

    out: list[dict] = []
    opens = quote.get("open") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    closes = quote.get("close") or []
    volumes = quote.get("volume") or []

    for i, ts in enumerate(timestamps):
        close = _safe_float(closes[i] if i < len(closes) else 0, 0.0)
        if close <= 0:
            continue
        dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
        out.append(
            {
                "date": dt.strftime("%Y%m%d"),
                "open": _safe_float(opens[i] if i < len(opens) else 0, 0.0),
                "high": _safe_float(highs[i] if i < len(highs) else 0, 0.0),
                "low": _safe_float(lows[i] if i < len(lows) else 0, 0.0),
                "close": close,
                "volume": _safe_float(volumes[i] if i < len(volumes) else 0, 0.0),
            }
        )

    return list(reversed(out[-max(1, days):]))


def _build_quote_from_daily(symbol: str, daily: list[dict]) -> dict:
    latest = (daily or [{}])[0] or {}
    prev = (daily or [{}, {}])[1] if len(daily or []) > 1 else {}
    price = _safe_float(latest.get("close", 0), 0.0)
    prev_close = _safe_float(prev.get("close", 0), 0.0)
    change_pct = ((price - prev_close) / prev_close) * 100 if prev_close > 0 else 0.0
    return {
        "code": symbol,
        "price": price,
        "prev_close": prev_close,
        "open": _safe_float(latest.get("open", 0), 0.0),
        "high": _safe_float(latest.get("high", 0), 0.0),
        "low": _safe_float(latest.get("low", 0), 0.0),
        "volume": _safe_float(latest.get("volume", 0), 0.0),
        "change_pct": change_pct,
        "currency": "USD",
        "market_state": "",
        "long_name": symbol,
    }


def get_us_current_price(symbol: str) -> dict:
    symbol = str(symbol or "").strip().upper()
    if not symbol:
        return {}

    url = "https://query1.finance.yahoo.com/v7/finance/quote"
    try:
        resp = request_with_retry(
            "GET",
            url,
            params={"symbols": symbol},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=20,
        )
        data = resp.json()
        row = (((data or {}).get("quoteResponse") or {}).get("result") or [None])[0] or {}
        price = _safe_float(row.get("regularMarketPrice", 0), 0.0)
        if price > 0:
            return {
                "code": symbol,
                "price": price,
                "prev_close": _safe_float(row.get("regularMarketPreviousClose", 0), 0.0),
                "open": _safe_float(row.get("regularMarketOpen", 0), 0.0),
                "high": _safe_float(row.get("regularMarketDayHigh", 0), 0.0),
                "low": _safe_float(row.get("regularMarketDayLow", 0), 0.0),
                "volume": _safe_float(row.get("regularMarketVolume", 0), 0.0),
                "change_pct": _safe_float(row.get("regularMarketChangePercent", 0), 0.0),
                "currency": str(row.get("currency", "USD") or "USD").strip() or "USD",
                "market_state": str(row.get("marketState", "") or "").strip(),
                "long_name": str(row.get("longName", "") or row.get("shortName", "") or symbol).strip(),
            }
    except Exception:
        pass

    daily = get_us_daily_chart(symbol, days=5)
    return _build_quote_from_daily(symbol, daily)


def get_us_news(symbol: str, limit: int = 3) -> list[dict]:
    symbol = str(symbol or "").strip().upper()
    if not symbol:
        return []

    url = "https://feeds.finance.yahoo.com/rss/2.0/headline"
    try:
        resp = request_with_retry(
            "GET",
            url,
            params={"s": symbol, "region": "US", "lang": "en-US"},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=20,
        )
        root = ET.fromstring(resp.text or "")
    except Exception:
        return []

    channel = root.find("channel")
    items = channel.findall("item") if channel is not None else []
    out: list[dict] = []
    for item in items[: max(1, limit)]:
        pub_date_raw = (item.findtext("pubDate") or "").strip()
        pub_date = pub_date_raw
        if pub_date_raw:
            try:
                pub_date = parsedate_to_datetime(pub_date_raw).isoformat()
            except Exception:
                pass
        out.append(
            {
                "title": (item.findtext("title") or "").strip(),
                "description": (item.findtext("description") or "").strip(),
                "link": (item.findtext("link") or "").strip(),
                "pub_date": pub_date,
            }
        )
    return [x for x in out if x.get("title")]
