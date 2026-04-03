from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from app.clients.kis import get_access_token, get_domestic_current_price
from app.clients.yahoo_us import get_us_current_price
from app.services.macro import get_macro_snapshot


ENTRY_ALERTS_FILE = os.getenv("ENTRY_ALERTS_FILE", "entry_alerts.json").strip() or "entry_alerts.json"
KST = timezone(timedelta(hours=9))


DEFAULTS = {
    "TOP_N": 5,
    "PULLBACK_PCT": -5.0,
    "NEAR_PCT": 1.2,
    "WATCH_COOLDOWN_MIN": 90,
    "REBOUND_COOLDOWN_MIN": 240,
    "BREAKOUT_COOLDOWN_MIN": 360,
    "CHASE_COOLDOWN_MIN": 240,
    "REBOUND_MIN_PCT": 0.8,
    "REBOUND_STRONG_PCT": 1.2,
    "BREAKOUT_BUFFER_PCT": 0.6,
    "CHASE_GAP_PCT": 4.0,
    "HOT_CHANGE_PCT": 8.0,
    "HOT_RSI": 75.0,
    "HOT_VOL_RATE": 250.0,
    "GOOD_VOL_RATE_MIN": 110.0,
    "GOOD_VOL_RATE_MAX": 230.0,
    "STOP_BUFFER_PCT": 4.0,
}


def _now_text() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(round(float(value)))
    except Exception:
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _env_float(name: str, default: float) -> float:
    return _safe_float(os.getenv(name, "").strip() or default, default)


def _env_int(name: str, default: int) -> int:
    return _safe_int(os.getenv(name, "").strip() or default, default)


def _cfg(name: str) -> float:
    env_name = f"ENTRY_ALERT_{name}"
    default = DEFAULTS[name]
    if isinstance(default, int):
        return float(_env_int(env_name, int(default)))
    return float(_env_float(env_name, float(default)))


def _market_of(value: Any) -> str:
    return str(value or "KOR").upper().strip() or "KOR"


def _is_us_market(value: Any) -> bool:
    return _market_of(value) == "US"


def _format_price(value: Any, market: str = "KOR") -> str:
    num = _safe_float(value, 0.0)
    if num <= 0:
        return "-"
    if _is_us_market(market):
        return f"${num:,.2f}"
    return f"{int(round(num)):,}원"


def _format_price_with_krw(value: Any, market: str = "KOR", fx_value: Any = 0.0) -> str:
    num = _safe_float(value, 0.0)
    if num <= 0:
        return "-"

    if not _is_us_market(market):
        return _format_price(num, market)

    fx = _safe_float(fx_value, 0.0)
    if fx > 0:
        krw = int(round(num * fx))
        return f"${num:,.2f} (약 {krw:,}원)"
    return f"${num:,.2f}"


def _load_rows() -> list[dict]:
    if not os.path.exists(ENTRY_ALERTS_FILE):
        return []
    try:
        with open(ENTRY_ALERTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []


def _save_rows(rows: list[dict]) -> None:
    try:
        with open(ENTRY_ALERTS_FILE, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("entry alerts save failed:", str(e))


def _key_of(row: dict) -> str:
    market = _market_of(row.get("market", "KOR"))
    code = str(row.get("code", "")).strip().upper()
    return f"{market}:{code}"


def _get_fx_value() -> float:
    try:
        macro = get_macro_snapshot()
        return _safe_float((macro.get("usdkrw") or {}).get("value", 0), 0.0)
    except Exception:
        return 0.0


def _get_quote_by_market(market: str, code: str, token: str | None = None) -> dict:
    market = _market_of(market)
    code = str(code or "").strip().upper()

    if market == "US":
        return get_us_current_price(code)

    if not token:
        token = get_access_token()
    return get_domestic_current_price(code=code, token=token)


def _minutes_since(text: str) -> float:
    raw = str(text or "").strip()
    if not raw:
        return 10**9
    try:
        dt = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S").replace(tzinfo=KST)
        return max(0.0, (datetime.now(KST) - dt).total_seconds() / 60.0)
    except Exception:
        return 10**9


def _normalize_price_levels(row: dict, market: str, prev_close: float) -> tuple[float, float, float]:
    suggested_buy = _safe_float(row.get("suggested_buy", 0), 0.0)
    lower = _safe_float(row.get("entry_zone_low", 0), 0.0)
    upper = _safe_float(row.get("entry_zone_high", 0), 0.0)

    if suggested_buy <= 0 and prev_close > 0:
        suggested_buy = prev_close * (1.0 + _cfg("PULLBACK_PCT") / 100.0)

    if suggested_buy > 0 and (lower <= 0 or upper <= 0):
        band = _cfg("NEAR_PCT") / 100.0
        digits = 2 if _is_us_market(market) else 0
        lower = round(suggested_buy * (1.0 - band), digits)
        upper = round(suggested_buy * (1.0 + band), digits)

    return suggested_buy, lower, upper


def _proximity_pct(price: float, anchor: float) -> float:
    if price <= 0 or anchor <= 0:
        return 0.0
    return ((price - anchor) / anchor) * 100.0


def _alert_allowed(row: dict, key: str, cooldown_min: float) -> bool:
    prev_key = str(row.get("last_alert_key", "")).strip()
    prev_at = str(row.get("last_alert_at", "")).strip()
    if not prev_key or prev_key != key:
        return True
    return _minutes_since(prev_at) >= cooldown_min


def get_entry_action_text(signal: str, stage: str, entry_decision: str) -> str:
    sig = str(signal or "").strip().upper()
    stg = str(stage or "").strip().upper()
    decision = str(entry_decision or "").strip().upper()

    if sig == "BREAKOUT_CONFIRM":
        return "1차 분할진입 가능"
    if sig == "REBOUND_READY":
        return "반등 확인 후 1차 접근"
    if sig == "WATCH_ZONE":
        return "관심구간 진입, 반등 대기"
    if sig == "SUPPORT_TEST":
        return "지지 유지 여부 확인"
    if sig == "CHASE_BLOCK":
        return "추격 금지"
    if decision == "PASS":
        return "신규진입 보류"
    if stg == "BREAKOUT_READY":
        return "전고 돌파 재확인 후 접근"
    if stg == "EARLY_ACCUMULATION":
        return "눌림 유지 시 분할 접근"
    if stg == "MOMENTUM_BUY":
        return "추격보다 눌림 재진입 대기"
    return "조건 재확인 후 판단"


def sync_report_entry_alerts(rows: list[dict], run_type: str, run_id: str) -> list[dict]:
    tracked = [
        r for r in (rows or [])
        if str(r.get("entry_decision", "")).upper() == "ENTRY"
        or str(r.get("stage", "")).upper() in ("EARLY_ACCUMULATION", "BREAKOUT_READY")
        or str(r.get("final_stage", "")).upper() in ("EARLY_ACCUMULATION", "BREAKOUT_READY")
    ]
    tracked.sort(
        key=lambda x: (
            0 if str(x.get("entry_decision", "")).upper() == "ENTRY" else 1,
            -_safe_int(x.get("entry_score", 0)),
            -_safe_int(x.get("quality_score", 0)),
            -_safe_int(x.get("total_score", 0)),
        )
    )
    tracked = tracked[: int(_cfg("TOP_N"))]

    if not tracked:
        return []

    existing = _load_rows()
    existing_map = {_key_of(row): row for row in existing}
    fx_value = _get_fx_value()

    for r in tracked:
        market = _market_of(r.get("market", "KOR"))
        code = str(r.get("code", "")).strip().upper()
        if not code:
            continue

        prev_close = _safe_float(r.get("prev_close", 0), 0.0)
        suggested_buy, lower, upper = _normalize_price_levels(r, market, prev_close)

        payload = {
            "market": market,
            "code": code,
            "name": str(r.get("name", code)).strip() or code,
            "run_type": str(run_type or "").upper().strip(),
            "run_id": str(run_id or "").strip(),
            "saved_at": _now_text(),
            "currency": str(r.get("currency", "USD" if market == "US" else "KRW")).strip() or ("USD" if market == "US" else "KRW"),
            "fx_value": fx_value if market == "US" else 1.0,
            "stage": str(r.get("final_stage", r.get("stage", ""))).strip(),
            "base_stage": str(r.get("stage", "")).strip(),
            "entry_decision": str(r.get("entry_decision", "")).strip(),
            "entry_reason": str(r.get("entry_reason", "")).strip(),
            "total_score": _safe_int(r.get("total_score", 0)),
            "entry_score": _safe_int(r.get("entry_score", 0)),
            "quality_score": _safe_int(r.get("quality_score", 0)),
            "current_price": _safe_float(r.get("price", 0)),
            "prev_close": prev_close,
            "suggested_buy": suggested_buy,
            "entry_zone_low": lower,
            "entry_zone_high": upper,
            "stop_loss": _safe_float(r.get("stop_loss", 0)),
            "target1": _safe_float(r.get("target1", 0)),
            "target2": _safe_float(r.get("target2", 0)),
            "gap_pct": 0.0,
            "rsi": _safe_float(r.get("rsi", 0)),
            "vol_rate": _safe_float(r.get("vol_rate", 0)),
            "news_bias": str((r.get("news_signal") or {}).get("bias", "")),
            "news_keywords": str((r.get("news_signal") or {}).get("keyword_summary", "")),
            "news_summary": str(r.get("news_summary", "")),
            "accumulation_flags": list(r.get("accumulation_flags", []) or []),
            "candidate_source": str(r.get("candidate_source", "")),
            "memo": str(r.get("entry_reason", "")),
            "reason": "",
            "auto_signal": "WAIT",
            "action_text": get_entry_action_text("", str(r.get("final_stage", r.get("stage", ""))), str(r.get("entry_decision", ""))),
        }

        prev = existing_map.get(_key_of(payload), {})
        payload["low_seen_price"] = _safe_float(prev.get("low_seen_price", 0))
        payload["low_touch_count"] = _safe_int(prev.get("low_touch_count", 0))
        payload["watch_hit_at"] = str(prev.get("watch_hit_at", "")).strip()
        payload["last_alert_key"] = str(prev.get("last_alert_key", "")).strip()
        payload["last_alert_at"] = str(prev.get("last_alert_at", "")).strip()
        payload["last_breakout_price"] = _safe_float(prev.get("last_breakout_price", 0))
        payload["breakout_ref_price"] = _safe_float(prev.get("breakout_ref_price", 0))

        existing_map[_key_of(payload)] = payload

    merged = list(existing_map.values())
    merged.sort(key=lambda x: (x.get("market", ""), x.get("code", "")))
    _save_rows(merged)
    return merged


def _signal_title(signal: str, market: str) -> str:
    mapping = {
        "WATCH_ZONE": f"🟡 [관심구간 진입/{market}]",
        "REBOUND_READY": f"🟢 [반등 준비/{market}]",
        "BREAKOUT_CONFIRM": f"🚀 [돌파 확인/{market}]",
        "SUPPORT_TEST": f"🔵 [지지 확인/{market}]",
        "CHASE_BLOCK": f"⛔ [추격주의/{market}]",
        "WAIT": f"⚪ [대기/{market}]",
    }
    return mapping.get(str(signal or "").upper(), f"⚪ [대기/{market}]")


def build_entry_alert_telegram_message(payload: dict) -> str:
    market = _market_of(payload.get("market", "KOR"))
    fx_value = _safe_float(payload.get("fx_value", 0), 0.0)
    signal = str(payload.get("auto_signal", "WAIT")).upper()

    tech_line = f"RSI {_safe_float(payload.get('rsi', 0)):.1f} / 거래량비 {_safe_float(payload.get('vol_rate', 0)):.0f}%"
    if payload.get("accumulation_flags"):
        acc = payload.get("accumulation_flags") or []
        if isinstance(acc, list):
            tech_line += " / 매집 " + ", ".join(acc[:3])
        else:
            tech_line += f" / 매집 {acc}"

    lines = [
        _signal_title(signal, market),
        f"종목: {payload.get('name', '')} ({payload.get('code', '')})",
        f"현재가: {_format_price_with_krw(payload.get('current_price', 0), market, fx_value)}",
        f"전일종가: {_format_price_with_krw(payload.get('prev_close', 0), market, fx_value)}",
        f"제안매수가: {_format_price_with_krw(payload.get('suggested_buy', 0), market, fx_value)}",
        f"관심구간: {_format_price(payload.get('entry_zone_low', 0), market)} ~ {_format_price(payload.get('entry_zone_high', 0), market)}",
        f"괴리율: {_safe_float(payload.get('gap_pct', 0)):.2f}%",
        "",
        f"단계: {payload.get('stage', '')}",
        f"리포트판정: {payload.get('entry_decision', '')}",
        f"총점: {_safe_int(payload.get('total_score', 0))} / 진입점수: {_safe_int(payload.get('entry_score', 0))} / 품질점수: {_safe_int(payload.get('quality_score', 0))}",
        "",
        f"뉴스판정: {payload.get('news_bias', '')}",
        f"뉴스핵심: {payload.get('news_keywords', '')}",
        f"뉴스요약: {payload.get('news_summary', '')}",
        "",
        f"기술상태: {tech_line}",
        f"사유: {payload.get('reason', '')}",
        f"행동: {payload.get('action_text', '')}",
        "주의: 최종 판단은 직접",
    ]
    return "\n".join(lines)


def _build_signal_state(row: dict, quote: dict) -> dict:
    market = _market_of(row.get("market", "KOR"))
    price = _safe_float(quote.get("price", 0), 0.0)
    prev_close = _safe_float(quote.get("prev_close", 0) or row.get("prev_close", 0), 0.0)
    stage = str(row.get("stage", "")).upper()
    entry_decision = str(row.get("entry_decision", "")).upper()
    rsi = _safe_float(row.get("rsi", 0), 0.0)
    vol_rate = _safe_float(row.get("vol_rate", 0), 0.0)

    suggested_buy, lower, upper = _normalize_price_levels(row, market, prev_close)
    breakout_ref = _safe_float(row.get("breakout_ref_price", 0), 0.0)
    if breakout_ref <= 0:
        breakout_ref = upper if upper > 0 else suggested_buy

    gap_from_prev = ((price - prev_close) / prev_close) * 100 if prev_close > 0 else 0.0
    gap_from_buy = ((price - suggested_buy) / suggested_buy) * 100 if suggested_buy > 0 else 0.0

    low_seen_old = _safe_float(row.get("low_seen_price", 0), 0.0)
    low_seen_new = min(low_seen_old, price) if low_seen_old > 0 else price
    rebound_pct = ((price - low_seen_new) / low_seen_new) * 100 if low_seen_new > 0 else 0.0
    low_touch_count = _safe_int(row.get("low_touch_count", 0))

    in_watch_zone = lower > 0 and upper > 0 and lower <= price <= upper
    support_test = lower > 0 and price > 0 and price <= lower * 1.01
    breakout_confirm = breakout_ref > 0 and price >= breakout_ref * (1.0 + _cfg("BREAKOUT_BUFFER_PCT") / 100.0)
    chase_block = (
        gap_from_buy >= _cfg("CHASE_GAP_PCT")
        or gap_from_prev >= _cfg("HOT_CHANGE_PCT")
        or (rsi >= _cfg("HOT_RSI") and gap_from_prev >= 4.0)
        or vol_rate >= _cfg("HOT_VOL_RATE")
    )

    signal = "WAIT"
    reason = "조건 대기"
    alert_key = ""
    cooldown = 0.0

    if chase_block:
        signal = "CHASE_BLOCK"
        reason = (
            f"제안매수가 대비 +{gap_from_buy:.2f}% 괴리 / "
            f"전일 대비 {gap_from_prev:.2f}% / RSI {rsi:.1f} / 거래량비 {vol_rate:.0f}%"
        )
        alert_key = f"{market}_{row.get('code','')}_CHASE_{int(round(price)) if price > 0 else 0}"
        cooldown = _cfg("CHASE_COOLDOWN_MIN")
    elif breakout_confirm and not chase_block:
        signal = "BREAKOUT_CONFIRM"
        reason = f"관심구간 재상향 후 기준가 {breakout_ref:,.2f} 돌파 확인"
        alert_key = f"{market}_{row.get('code','')}_BREAKOUT_{int(round(breakout_ref)) if breakout_ref > 0 else 0}"
        cooldown = _cfg("BREAKOUT_COOLDOWN_MIN")
    elif low_seen_new <= upper and rebound_pct >= _cfg("REBOUND_MIN_PCT") and price >= suggested_buy and not chase_block:
        signal = "REBOUND_READY"
        strength = "강한 반등" if rebound_pct >= _cfg("REBOUND_STRONG_PCT") else "반등 확인"
        reason = f"관심구간 터치 후 저점 대비 +{rebound_pct:.2f}% {strength}"
        alert_key = f"{market}_{row.get('code','')}_REBOUND_{int(round(suggested_buy)) if suggested_buy > 0 else 0}"
        cooldown = _cfg("REBOUND_COOLDOWN_MIN")
    elif in_watch_zone:
        signal = "WATCH_ZONE"
        reason = f"제안매수가 부근 도달 / 전일 대비 {gap_from_prev:.2f}%"
        alert_key = f"{market}_{row.get('code','')}_WATCH_{int(round(suggested_buy)) if suggested_buy > 0 else 0}"
        cooldown = _cfg("WATCH_COOLDOWN_MIN")
    elif support_test:
        signal = "SUPPORT_TEST"
        reason = "관심구간 하단 또는 지지권 재테스트"
        alert_key = f"{market}_{row.get('code','')}_SUPPORT_{int(round(lower)) if lower > 0 else 0}"
        cooldown = _cfg("WATCH_COOLDOWN_MIN")

    if in_watch_zone:
        low_touch_count += 1
        if not str(row.get("watch_hit_at", "")).strip():
            row["watch_hit_at"] = _now_text()

    action_text = get_entry_action_text(signal, stage, entry_decision)
    if signal == "REBOUND_READY" and stage == "EARLY_ACCUMULATION" and entry_decision == "ENTRY":
        action_text = "1차 분할진입 검토"
    elif signal == "BREAKOUT_CONFIRM" and stage == "BREAKOUT_READY":
        action_text = "돌파 확인, 1차 분할진입 가능"
    elif signal == "CHASE_BLOCK":
        action_text = "신규진입 보류"

    return {
        "price": price,
        "prev_close": prev_close,
        "suggested_buy": suggested_buy,
        "lower": lower,
        "upper": upper,
        "gap_from_prev": gap_from_prev,
        "gap_from_buy": gap_from_buy,
        "low_seen_new": low_seen_new,
        "rebound_pct": rebound_pct,
        "low_touch_count": low_touch_count,
        "breakout_ref": breakout_ref,
        "signal": signal,
        "reason": reason,
        "alert_key": alert_key,
        "cooldown": cooldown,
        "action_text": action_text,
        "fx_value": _get_fx_value() if market == "US" else 1.0,
    }


def scan_entry_alert_signals() -> list[str]:
    rows = _load_rows()
    if not rows:
        return []

    needs_kor_token = any(_market_of(x.get("market", "KOR")) == "KOR" for x in rows)
    token = get_access_token() if needs_kor_token else None

    msgs: list[str] = []
    changed = False

    for row in rows:
        market = _market_of(row.get("market", "KOR"))
        code = str(row.get("code", "")).strip().upper()
        if not code:
            continue

        try:
            quote = _get_quote_by_market(market=market, code=code, token=token)
        except Exception as e:
            print(f"scan entry alert skipped {market} {code}: {e}")
            continue

        state = _build_signal_state(row, quote)
        price = state["price"]
        prev_close = state["prev_close"]
        if price <= 0 or prev_close <= 0:
            continue

        row["current_price"] = price
        row["prev_close"] = prev_close
        row["suggested_buy"] = state["suggested_buy"]
        row["entry_zone_low"] = state["lower"]
        row["entry_zone_high"] = state["upper"]
        row["low_seen_price"] = state["low_seen_new"]
        row["low_touch_count"] = state["low_touch_count"]
        row["breakout_ref_price"] = state["breakout_ref"]
        row["auto_signal"] = state["signal"]
        row["reason"] = state["reason"]
        row["gap_pct"] = state["gap_from_buy"]
        row["fx_value"] = state["fx_value"]
        row["action_text"] = state["action_text"]

        alert_key = state["alert_key"]
        signal = state["signal"]
        if signal in {"WATCH_ZONE", "REBOUND_READY", "BREAKOUT_CONFIRM", "CHASE_BLOCK"} and alert_key:
            if _alert_allowed(row, alert_key, state["cooldown"]):
                row["last_alert_key"] = alert_key
                row["last_alert_at"] = _now_text()
                msgs.append(build_entry_alert_telegram_message(row))

        changed = True

    if changed:
        _save_rows(rows)

    return msgs
