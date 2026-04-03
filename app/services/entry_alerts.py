import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from app.clients.kis import get_access_token, get_domestic_current_price
from app.clients.yahoo_us import get_us_current_price
from app.services.macro import get_macro_snapshot


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
    tracked = [
        r for r in (rows or [])
        if str(r.get("entry_decision", "")).upper() == "ENTRY"
        or str(r.get("stage", "")).upper() in ("EARLY_ACCUMULATION", "BREAKOUT_READY")
    ]
    tracked.sort(key=lambda x: -_safe_int(x.get("total_score", 0)))
    tracked = tracked[:5]

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
            "prev_close": _safe_float(r.get("prev_close", 0)),
            "suggested_buy": _safe_float(r.get("proposed_entry", 0)),
            "entry_zone_low": _safe_float(r.get("entry_zone_low", 0)),
            "entry_zone_high": _safe_float(r.get("entry_zone_high", 0)),
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
        if prev:
            payload["low_seen_price"] = _safe_float(prev.get("low_seen_price", 0))
            payload["last_alert_key"] = str(prev.get("last_alert_key", "")).strip()
            payload["last_alert_at"] = str(prev.get("last_alert_at", "")).strip()
        else:
            payload["low_seen_price"] = 0.0
            payload["last_alert_key"] = ""
            payload["last_alert_at"] = ""

        existing_map[key] = payload

    merged = list(existing_map.values())
    merged.sort(key=lambda x: (x.get("market", ""), x.get("code", "")))
    _save_rows(merged)
    return merged


def build_entry_alert_telegram_message(payload: dict) -> str:
    market = _market_of(payload.get("market", "KOR"))
    fx_value = _safe_float(payload.get("fx_value", 0), 0.0)

    lines = [
        f"🟢 [반등확인 매수시점/{market}]",
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

        price = _safe_float(quote.get("price", 0), 0.0)
        prev_close = _safe_float(quote.get("prev_close", 0) or row.get("prev_close", 0), 0.0)
        if price <= 0 or prev_close <= 0:
            continue

        suggested_buy = _safe_float(row.get("suggested_buy", 0), 0.0)
        lower = _safe_float(row.get("entry_zone_low", 0), 0.0)
        upper = _safe_float(row.get("entry_zone_high", 0), 0.0)

        if suggested_buy <= 0:
            suggested_buy = prev_close * 0.95
            lower = round(suggested_buy * 0.99, 2 if market == "US" else 0)
            upper = round(suggested_buy * 1.01, 2 if market == "US" else 0)

        change_from_prev = ((price - prev_close) / prev_close) * 100 if prev_close > 0 else 0.0
        low_seen_old = _safe_float(row.get("low_seen_price", 0), 0.0)
        low_seen_new = min(low_seen_old, price) if low_seen_old > 0 else price
        rebound_pct = ((price - low_seen_new) / low_seen_new) * 100 if low_seen_new > 0 else 0.0

        signal = "대기"
        reason = ""
        alert_key = ""

        if lower <= price <= upper:
            signal = "관심구간진입"
            reason = f"전일종가 대비 {change_from_prev:.2f}% / 제안매수가 부근 도달"

        if low_seen_new <= upper and rebound_pct >= 0.8 and price >= suggested_buy:
            signal = "반등확인"
            reason = f"관심구간 터치 후 저점 대비 +{rebound_pct:.2f}% 반등"
            alert_key = f"{market}_{code}_ENTRY_{suggested_buy}"

        row["current_price"] = price
        row["prev_close"] = prev_close
        row["suggested_buy"] = suggested_buy
        row["entry_zone_low"] = lower
        row["entry_zone_high"] = upper
        row["low_seen_price"] = low_seen_new
        row["auto_signal"] = signal
        row["reason"] = reason
        row["gap_pct"] = ((price - suggested_buy) / suggested_buy) * 100 if suggested_buy > 0 else 0.0
        row["fx_value"] = _safe_float(quote.get("currency", ""), 0.0)  # placeholder safe overwrite below
        row["action_text"] = get_entry_action_text(
            signal,
            str(row.get("stage", "")),
            str(row.get("entry_decision", "")),
        )

        # 실제 FX 값은 macro snapshot 기준
        row["fx_value"] = _get_fx_value() if market == "US" else 1.0

        prev_alert_key = str(row.get("last_alert_key", "")).strip()
        if signal == "반등확인" and alert_key and alert_key != prev_alert_key:
            row["last_alert_key"] = alert_key
            row["last_alert_at"] = _now_text()
            msgs.append(build_entry_alert_telegram_message(row))

        changed = True

    if changed:
        _save_rows(rows)

    return msgs
