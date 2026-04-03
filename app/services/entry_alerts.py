import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from app.clients.kis import get_access_token, get_domestic_current_price


ENTRY_ALERTS_FILE = "entry_alerts.json"
KST = timezone(timedelta(hours=9))


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
    market = str(row.get("market", "KOR")).upper().strip()
    code = str(row.get("code", "")).strip().upper()
    return f"{market}:{code}"


def get_entry_action_text(signal: str, stage: str, entry_decision: str) -> str:
    sig = str(signal or "").strip()
    stg = str(stage or "").strip().upper()
    decision = str(entry_decision or "").strip().upper()

    if sig == "반등확인":
        return "1차 분할진입 검토"
    if sig == "관심구간진입":
        return "반등 확인 전 대기"
    if sig == "추격주의":
        return "신규진입 보류"
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
    tracked = (
        [r for r in (rows or []) if str(r.get("entry_decision", "")).upper() == "ENTRY"
         or str(r.get("stage", "")).upper() in ("EARLY_ACCUMULATION", "BREAKOUT_READY")]
    )
    tracked.sort(key=lambda x: -_safe_int(x.get("total_score", 0)))
    tracked = tracked[:5]

    if not tracked:
        return []

    existing = _load_rows()
    existing_map = {_key_of(row): row for row in existing}

    for r in tracked:
        market = str(r.get("market", "KOR")).upper().strip()
        if market != "KOR":
            continue

        code = str(r.get("code", "")).strip()
        if not code:
            continue

        prev_close = _safe_int(r.get("prev_close", 0))
        proposed_entry = _safe_int(r.get("proposed_entry", 0))
        lower = _safe_int(r.get("entry_zone_low", 0))
        upper = _safe_int(r.get("entry_zone_high", 0))

        payload = {
            "registered_at": _now_text(),
            "run_id": run_id,
            "run_type": run_type,
            "market": "KOR",
            "code": code,
            "name": str(r.get("name", "")).strip(),
            "stage": str(r.get("stage", "")).strip(),
            "entry_decision": str(r.get("entry_decision", "")).strip(),
            "total_score": _safe_int(r.get("total_score", 0)),
            "entry_score": _safe_int(r.get("entry_score", 0)),
            "quality_score": _safe_int(r.get("quality_score", 0)),
            "current_price": _safe_int(r.get("price", 0)),
            "prev_close": prev_close,
            "suggested_buy": proposed_entry,
            "entry_zone_low": lower,
            "entry_zone_high": upper,
            "auto_signal": "",
            "low_seen_price": 0,
            "last_alert_key": "",
            "last_alert_at": "",
            "news_bias": str((r.get("news_signal") or {}).get("bias", "")),
            "news_keywords": str((r.get("news_signal") or {}).get("keyword_summary", "")),
            "news_summary": str(r.get("news_summary", "")),
            "rsi": _safe_float(r.get("rsi", 0)),
            "vol_rate": _safe_float(r.get("vol_rate", 0)),
            "accumulation_flags": list(r.get("accumulation_flags", []) or []),
            "candidate_source": str(r.get("candidate_source", "")),
            "memo": str(r.get("entry_reason", "")),
            "action_text": get_entry_action_text(
                "",
                str(r.get("stage", "")),
                str(r.get("entry_decision", "")),
            ),
        }

        key = _key_of(payload)
        prev = existing_map.get(key, {})
        if prev:
            payload["low_seen_price"] = _safe_int(prev.get("low_seen_price", 0))
            payload["last_alert_key"] = str(prev.get("last_alert_key", "")).strip()
            payload["last_alert_at"] = str(prev.get("last_alert_at", "")).strip()

        existing_map[key] = payload

    merged = list(existing_map.values())
    merged.sort(key=lambda x: (x.get("market", ""), x.get("code", "")))
    _save_rows(merged)
    return merged


def build_entry_alert_telegram_message(payload: dict) -> str:
    market = str(payload.get("market", "KOR")).upper()
    lines = [
        f"🟢 [반등확인 매수시점/{market}]",
        f"종목: {payload.get('name', '')} ({payload.get('code', '')})",
        f"현재가: {_safe_int(payload.get('current_price', 0)):,}원",
        f"전일종가: {_safe_int(payload.get('prev_close', 0)):,}원",
        f"제안매수가: {_safe_int(payload.get('suggested_buy', 0)):,}원",
        f"관심구간: {_safe_int(payload.get('entry_zone_low', 0)):,} ~ {_safe_int(payload.get('entry_zone_high', 0)):,}원",
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
        f"기술상태: RSI {_safe_float(payload.get('rsi', 0)):.1f} / 거래량비 {_safe_float(payload.get('vol_rate', 0)):.0f}%",
        f"사유: {payload.get('reason', '')}",
        f"행동: {payload.get('action_text', '')}",
        "주의: 최종 판단은 직접",
    ]
    return "\n".join(lines)


def scan_entry_alert_signals() -> list[str]:
    rows = _load_rows()
    if not rows:
        return []

    token = get_access_token()
    msgs: list[str] = []
    changed = False

    for row in rows:
        market = str(row.get("market", "KOR")).upper().strip()
        code = str(row.get("code", "")).strip()
        if market != "KOR" or not code:
            continue

        try:
            quote = get_domestic_current_price(code=code, token=token)
        except Exception as e:
            print(f"scan entry alert skipped {code}: {e}")
            continue

        price = _safe_int(quote.get("price", 0))
        prev_close = _safe_int(quote.get("prev_close", 0) or row.get("prev_close", 0))
        if price <= 0 or prev_close <= 0:
            continue

        suggested_buy = _safe_int(row.get("suggested_buy", 0))
        lower = _safe_int(row.get("entry_zone_low", 0))
        upper = _safe_int(row.get("entry_zone_high", 0))

        if suggested_buy <= 0:
            suggested_buy = _safe_int(prev_close * 0.95)
            lower = _safe_int(round(suggested_buy * 0.99))
            upper = _safe_int(round(suggested_buy * 1.01))

        change_from_prev = ((price - prev_close) / prev_close) * 100 if prev_close > 0 else 0.0
        low_seen_old = _safe_int(row.get("low_seen_price", 0))
        low_seen_new = min(low_seen_old, price) if low_seen_old > 0 else price
        rebound_pct = ((price - low_seen_new) / low_seen_new) * 100 if low_seen_new > 0 else 0.0

        signal = "대기"
        reason = ""
        alert_key = ""

        if lower <= price <= upper:
            signal = "관심구간진입"
            reason = f"전일종가 대비 {_safe_float(change_from_prev):.2f}% / 제안매수가 부근 도달"

        if low_seen_new <= upper and rebound_pct >= 0.8 and price >= suggested_buy:
            signal = "반등확인"
            reason = f"관심구간 터치 후 저점 대비 +{_safe_float(rebound_pct):.2f}% 반등"
            alert_key = f"{market}_{code}_ENTRY_{suggested_buy}"

        row["current_price"] = price
        row["prev_close"] = prev_close
        row["suggested_buy"] = suggested_buy
        row["entry_zone_low"] = lower
        row["entry_zone_high"] = upper
        row["low_seen_price"] = low_seen_new
        row["auto_signal"] = signal
        row["action_text"] = get_entry_action_text(
            signal,
            str(row.get("stage", "")),
            str(row.get("entry_decision", "")),
        )

        if signal == "반등확인":
            prev_key = str(row.get("last_alert_key", "")).strip()
            if prev_key != alert_key:
                row["last_alert_key"] = alert_key
                row["last_alert_at"] = _now_text()
                row["gap_pct"] = round(change_from_prev, 2)
                row["reason"] = reason
                msgs.append(build_entry_alert_telegram_message(row))

        changed = True

    if changed:
        _save_rows(rows)

    return msgs
