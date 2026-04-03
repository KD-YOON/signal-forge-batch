from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from app.clients.kis import get_access_token, get_domestic_current_price
from app.clients.yahoo_us import get_us_current_price
from app.services.macro import get_macro_snapshot


ENTRY_ALERTS_FILE = "entry_alerts.json"
KST = timezone(timedelta(hours=9))

# 덮어쓰기형 병합본: 기존 인터페이스 유지 + 4단계 신호 확장
ENTRY_ALERT_TOP_N = int(os.getenv("ENTRY_ALERT_TOP_N", "5") or "5")
ENTRY_ALERT_PULLBACK_PCT = float(os.getenv("ENTRY_ALERT_PULLBACK_PCT", "-5.0") or "-5.0")
ENTRY_ALERT_NEAR_PCT = float(os.getenv("ENTRY_ALERT_NEAR_PCT", "1.2") or "1.2")
ENTRY_ALERT_REBOUND_MIN_PCT = float(os.getenv("ENTRY_ALERT_REBOUND_MIN_PCT", "0.8") or "0.8")
ENTRY_ALERT_REBOUND_STRONG_PCT = float(os.getenv("ENTRY_ALERT_REBOUND_STRONG_PCT", "1.2") or "1.2")
ENTRY_ALERT_BREAKOUT_BUFFER_PCT = float(os.getenv("ENTRY_ALERT_BREAKOUT_BUFFER_PCT", "0.6") or "0.6")
ENTRY_ALERT_CHASE_GAP_PCT = float(os.getenv("ENTRY_ALERT_CHASE_GAP_PCT", "4.0") or "4.0")
ENTRY_ALERT_HOT_CHANGE_PCT = float(os.getenv("ENTRY_ALERT_HOT_CHANGE_PCT", "8.0") or "8.0")
ENTRY_ALERT_HOT_RSI = float(os.getenv("ENTRY_ALERT_HOT_RSI", "75") or "75")
ENTRY_ALERT_HOT_VOL_RATE = float(os.getenv("ENTRY_ALERT_HOT_VOL_RATE", "250") or "250")
ENTRY_ALERT_WATCH_COOLDOWN_MIN = int(os.getenv("ENTRY_ALERT_WATCH_COOLDOWN_MIN", "90") or "90")
ENTRY_ALERT_REBOUND_COOLDOWN_MIN = int(os.getenv("ENTRY_ALERT_REBOUND_COOLDOWN_MIN", "240") or "240")
ENTRY_ALERT_BREAKOUT_COOLDOWN_MIN = int(os.getenv("ENTRY_ALERT_BREAKOUT_COOLDOWN_MIN", "360") or "360")
ENTRY_ALERT_CHASE_COOLDOWN_MIN = int(os.getenv("ENTRY_ALERT_CHASE_COOLDOWN_MIN", "240") or "240")


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
        return float(default)


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


def _round_price(value: float, market: str) -> float:
    if value <= 0:
        return 0.0
    return round(value, 2 if _is_us_market(market) else 0)


def _ensure_price_band(row: dict, market: str, prev_close: float) -> tuple[float, float, float]:
    suggested_buy = _safe_float(row.get("suggested_buy", 0), 0.0)
    lower = _safe_float(row.get("entry_zone_low", 0), 0.0)
    upper = _safe_float(row.get("entry_zone_high", 0), 0.0)

    if suggested_buy <= 0 and prev_close > 0:
        suggested_buy = prev_close * (1 + ENTRY_ALERT_PULLBACK_PCT / 100.0)

    if suggested_buy > 0 and (lower <= 0 or upper <= 0):
        lower = _round_price(suggested_buy * (1 - ENTRY_ALERT_NEAR_PCT / 100.0), market)
        upper = _round_price(suggested_buy * (1 + ENTRY_ALERT_NEAR_PCT / 100.0), market)

    return suggested_buy, lower, upper


def _signal_title(signal: str, market: str) -> str:
    mapping = {
        "WATCH_ZONE": f"🟡 [관심구간 진입/{market}]",
        "REBOUND_READY": f"🟢 [반등 준비/{market}]",
        "BREAKOUT_CONFIRM": f"🚀 [돌파 확인/{market}]",
        "SUPPORT_TEST": f"🔵 [지지 확인/{market}]",
        "CHASE_BLOCK": f"⛔ [추격주의/{market}]",
        "관심구간진입": f"🟡 [관심구간 진입/{market}]",
        "반등확인": f"🟢 [반등확인 매수시점/{market}]",
        "추격주의": f"⛔ [추격주의/{market}]",
        "대기": f"⚪ [대기/{market}]",
    }
    return mapping.get(str(signal or "").upper(), f"⚪ [대기/{market}]")


def get_entry_action_text(signal: str, stage: str, entry_decision: str) -> str:
    sig = str(signal or "").strip().upper()
    stg = str(stage or "").strip().upper()
    decision = str(entry_decision or "").strip().upper()

    if sig in {"반등확인", "REBOUND_READY"}:
        return "1차 분할진입 검토"
    if sig in {"관심구간진입", "WATCH_ZONE"}:
        return "반등 확인 전 대기"
    if sig == "BREAKOUT_CONFIRM":
        return "돌파 확인, 1차 분할진입 가능"
    if sig in {"추격주의", "CHASE_BLOCK"}:
        return "신규진입 보류"
    if sig == "SUPPORT_TEST":
        return "지지 유지 여부 확인"
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
    tracked = tracked[:ENTRY_ALERT_TOP_N]

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

        prev_close = _safe_float(r.get("prev_close", 0))
        suggested_buy, lower, upper = _ensure_price_band(
            {
                "suggested_buy": r.get("proposed_entry", r.get("suggested_buy", 0)),
                "entry_zone_low": r.get("entry_zone_low", 0),
                "entry_zone_high": r.get("entry_zone_high", 0),
            },
            market,
            prev_close,
        )

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
            "auto_signal": "",
            "action_text": get_entry_action_text(
                "",
                str(r.get("final_stage", r.get("stage", ""))),
                str(r.get("entry_decision", "")),
            ),
        }

        key = _key_of(payload)
        prev = existing_map.get(key, {})
        payload["low_seen_price"] = _safe_float(prev.get("low_seen_price", 0))
        payload["last_alert_key"] = str(prev.get("last_alert_key", "")).strip()
        payload["last_alert_at"] = str(prev.get("last_alert_at", "")).strip()
        payload["watch_hit_at"] = str(prev.get("watch_hit_at", "")).strip()
        payload["low_touch_count"] = _safe_int(prev.get("low_touch_count", 0))
        payload["breakout_ref_price"] = _safe_float(prev.get("breakout_ref_price", 0))
        existing_map[key] = payload

    merged = list(existing_map.values())
    merged.sort(key=lambda x: (x.get("market", ""), x.get("code", "")))
    _save_rows(merged)
    return merged


def build_entry_alert_telegram_message(payload: dict) -> str:
    market = _market_of(payload.get("market", "KOR"))
    fx_value = _safe_float(payload.get("fx_value", 0), 0.0)
    signal = str(payload.get("auto_signal", "대기"))

    tech_line = f"RSI {_safe_float(payload.get('rsi', 0)):.1f} / 거래량비 {_safe_float(payload.get('vol_rate', 0)):.0f}%"
    acc = payload.get("accumulation_flags") or []
    if isinstance(acc, list) and acc:
        tech_line += " / 매집 " + ", ".join([str(x) for x in acc[:3]])

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
    code = str(row.get("code", "")).strip().upper()
    price = _safe_float(quote.get("price", 0), 0.0)
    prev_close = _safe_float(quote.get("prev_close", 0) or row.get("prev_close", 0), 0.0)
    stage = str(row.get("stage", "")).upper()
    entry_decision = str(row.get("entry_decision", "")).upper()
    rsi = _safe_float(row.get("rsi", 0), 0.0)
    vol_rate = _safe_float(row.get("vol_rate", 0), 0.0)

    suggested_buy, lower, upper = _ensure_price_band(row, market, prev_close)
    breakout_ref = _safe_float(row.get("breakout_ref_price", 0), 0.0)
    if breakout_ref <= 0:
        breakout_ref = upper if upper > 0 else suggested_buy

    change_from_prev = ((price - prev_close) / prev_close) * 100 if prev_close > 0 else 0.0
    gap_pct = ((price - suggested_buy) / suggested_buy) * 100 if suggested_buy > 0 else 0.0
    low_seen_old = _safe_float(row.get("low_seen_price", 0), 0.0)
    low_seen_new = min(low_seen_old, price) if low_seen_old > 0 else price
    rebound_pct = ((price - low_seen_new) / low_seen_new) * 100 if low_seen_new > 0 else 0.0

    signal = "대기"
    reason = ""
    alert_key = ""
    cooldown_min = 0

    in_watch_zone = lower > 0 and upper > 0 and lower <= price <= upper
    support_test = lower > 0 and price > 0 and price <= lower * 1.01
    breakout_confirm = breakout_ref > 0 and price >= breakout_ref * (1 + ENTRY_ALERT_BREAKOUT_BUFFER_PCT / 100.0)
    chase_block = (
        gap_pct >= ENTRY_ALERT_CHASE_GAP_PCT
        or change_from_prev >= ENTRY_ALERT_HOT_CHANGE_PCT
        or (rsi >= ENTRY_ALERT_HOT_RSI and change_from_prev >= 4.0)
        or vol_rate >= ENTRY_ALERT_HOT_VOL_RATE
    )

    if chase_block:
        signal = "CHASE_BLOCK"
        reason = f"제안매수가 대비 +{gap_pct:.2f}% 괴리 / 전일 대비 {change_from_prev:.2f}% / RSI {rsi:.1f} / 거래량비 {vol_rate:.0f}%"
        alert_key = f"{market}_{code}_CHASE_{int(round(price)) if price > 0 else 0}"
        cooldown_min = ENTRY_ALERT_CHASE_COOLDOWN_MIN
    elif breakout_confirm and not chase_block:
        signal = "BREAKOUT_CONFIRM"
        reason = f"관심구간 상향 이탈 후 기준가 {breakout_ref:,.2f} 돌파 확인"
        alert_key = f"{market}_{code}_BREAKOUT_{int(round(breakout_ref)) if breakout_ref > 0 else 0}"
        cooldown_min = ENTRY_ALERT_BREAKOUT_COOLDOWN_MIN
    elif low_seen_new <= upper and rebound_pct >= ENTRY_ALERT_REBOUND_MIN_PCT and price >= suggested_buy and not chase_block:
        signal = "REBOUND_READY"
        strength = "강한 반등" if rebound_pct >= ENTRY_ALERT_REBOUND_STRONG_PCT else "반등 확인"
        reason = f"관심구간 터치 후 저점 대비 +{rebound_pct:.2f}% {strength}"
        alert_key = f"{market}_{code}_REBOUND_{int(round(suggested_buy)) if suggested_buy > 0 else 0}"
        cooldown_min = ENTRY_ALERT_REBOUND_COOLDOWN_MIN
    elif in_watch_zone:
        signal = "WATCH_ZONE"
        reason = f"전일종가 대비 {change_from_prev:.2f}% / 제안매수가 부근 도달"
        alert_key = f"{market}_{code}_WATCH_{int(round(suggested_buy)) if suggested_buy > 0 else 0}"
        cooldown_min = ENTRY_ALERT_WATCH_COOLDOWN_MIN
    elif support_test:
        signal = "SUPPORT_TEST"
        reason = "관심구간 하단 또는 지지권 재테스트"
        alert_key = f"{market}_{code}_SUPPORT_{int(round(lower)) if lower > 0 else 0}"
        cooldown_min = ENTRY_ALERT_WATCH_COOLDOWN_MIN
    elif change_from_prev >= ENTRY_ALERT_HOT_CHANGE_PCT:
        signal = "추격주의"
        reason = f"전일 대비 {change_from_prev:.2f}% 급등으로 추격 위험"
        alert_key = f"{market}_{code}_HOT_{int(round(price)) if price > 0 else 0}"
        cooldown_min = ENTRY_ALERT_CHASE_COOLDOWN_MIN

    action_text = get_entry_action_text(signal, stage, entry_decision)
    return {
        "signal": signal,
        "reason": reason,
        "alert_key": alert_key,
        "cooldown_min": cooldown_min,
        "price": price,
        "prev_close": prev_close,
        "suggested_buy": suggested_buy,
        "lower": lower,
        "upper": upper,
        "low_seen_new": low_seen_new,
        "rebound_pct": rebound_pct,
        "gap_pct": gap_pct,
        "action_text": action_text,
        "breakout_ref": breakout_ref,
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
        price = _safe_float(state["price"], 0.0)
        prev_close = _safe_float(state["prev_close"], 0.0)
        if price <= 0 or prev_close <= 0:
            continue

        row["current_price"] = price
        row["prev_close"] = prev_close
        row["suggested_buy"] = state["suggested_buy"]
        row["entry_zone_low"] = state["lower"]
        row["entry_zone_high"] = state["upper"]
        row["low_seen_price"] = state["low_seen_new"]
        row["breakout_ref_price"] = state["breakout_ref"]
        row["auto_signal"] = state["signal"]
        row["reason"] = state["reason"]
        row["gap_pct"] = state["gap_pct"]
        row["fx_value"] = _get_fx_value() if market == "US" else 1.0
        row["action_text"] = state["action_text"]

        alert_key = str(state["alert_key"] or "")
        signal = str(state["signal"] or "")
        prev_alert_key = str(row.get("last_alert_key", "")).strip()
        last_alert_at = str(row.get("last_alert_at", "")).strip()
        allow_alert = False

        if signal in {"WATCH_ZONE", "REBOUND_READY", "BREAKOUT_CONFIRM", "CHASE_BLOCK", "반등확인", "관심구간진입", "추격주의"} and alert_key:
            if prev_alert_key != alert_key:
                allow_alert = True
            elif _minutes_since(last_alert_at) >= float(state["cooldown_min"] or 0):
                allow_alert = True

        if allow_alert:
            row["last_alert_key"] = alert_key
            row["last_alert_at"] = _now_text()
            msgs.append(build_entry_alert_telegram_message(row))

        changed = True

    if changed:
        _save_rows(rows)

    return msgs
