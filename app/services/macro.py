from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from app.utils import request_with_retry


def _safe_float(value, default=0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def get_usdkrw_rate() -> dict:
    api_key = os.getenv("EXCHANGERATE_API_KEY", "").strip()
    if not api_key:
        return {"value": 0.0, "change_percent": 0.0, "source": "none"}

    # exchangerate.host style fallback
    urls = [
        f"https://v6.exchangerate-api.com/v6/{api_key}/latest/USD",
        f"https://open.er-api.com/v6/latest/USD",
    ]

    for url in urls:
        try:
            resp = request_with_retry("GET", url)
            data = resp.json()
            rates = data.get("conversion_rates") or data.get("rates") or {}
            krw = rates.get("KRW")
            if krw:
                return {"value": _safe_float(krw), "change_percent": 0.0, "source": "fx_api"}
        except Exception:
            continue

    return {"value": 0.0, "change_percent": 0.0, "source": "unavailable"}


def get_macro_snapshot() -> dict:
    # 현재 Python판에서는 VIX / SOX가 외부 API 없이 비어 있을 수 있으므로
    # 환율만이라도 반영하고, 나머지는 추후 확장 가능하게 구조화
    usdkrw = get_usdkrw_rate()
    return {
        "vix": {"value": 0.0, "change_percent": 0.0, "source": "not_connected"},
        "sox": {"value": 0.0, "change_percent": 0.0, "source": "not_connected"},
        "usdkrw": usdkrw,
        "captured_at": datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M:%S"),
    }


def detect_macro_regime(macro: dict) -> str:
    vix = _safe_float((macro.get("vix") or {}).get("value", 0))
    usd = _safe_float((macro.get("usdkrw") or {}).get("value", 0))

    if (vix and vix >= 25) or (usd and usd >= 1450):
        return "RISK_OFF"
    if (vix and vix < 20) and (usd and usd < 1400):
        return "RISK_ON"
    return "NEUTRAL"


def apply_macro_risk_overlay(items: list[dict], macro: dict, run_type: str) -> list[dict]:
    if not items:
        return []

    regime = detect_macro_regime(macro)
    usd = _safe_float((macro.get("usdkrw") or {}).get("value", 0))
    sox_pct = _safe_float((macro.get("sox") or {}).get("change_percent", 0))
    vix = _safe_float((macro.get("vix") or {}).get("value", 0))
    upper_run_type = str(run_type or "").upper()

    out_items = []
    for row in items:
        item = dict(row)
        flags = []
        risk_add = 0
        breakout_penalty = 0
        early_bonus = 0
        breakout_bonus = 0

        if vix >= 25:
            risk_add += 8
            breakout_penalty += 6
            flags.append("VIX고위험")
        elif vix >= 20:
            risk_add += 4
            breakout_penalty += 3
            flags.append("VIX경계")

        if usd >= 1450:
            risk_add += 8
            breakout_penalty += 3
            flags.append("환율고위험")
        elif usd >= 1400:
            risk_add += 4
            flags.append("환율경계")

        if upper_run_type == "MORNING" and sox_pct <= -2.0:
            breakout_penalty += 3
            flags.append("SOX약세")

        if regime == "RISK_ON":
            breakout_bonus += 5
            early_bonus += 2
            flags.append("전략:공격형")
        elif regime == "RISK_OFF":
            breakout_penalty += 12
            risk_add += 8
            early_bonus += 3
            flags.append("전략:방어형")
        else:
            flags.append("전략:중립형")

        item["breakout_score"] = max(0, int(item.get("breakout_score", 0)) + breakout_bonus - breakout_penalty)
        item["risk_score"] = int(item.get("risk_score", 0)) + risk_add
        item["macro_regime"] = regime
        item["macro_flags"] = flags
        item["macro_summary"] = ", ".join(flags)

        out_items.append(item)

    return out_items
