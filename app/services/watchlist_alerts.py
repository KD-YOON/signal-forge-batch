
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from app.clients.kis import get_access_token, get_domestic_current_price
from app.clients.yahoo_us import get_us_current_price
from app.services.macro import get_macro_snapshot


WATCHLIST_ALERTS_FILE = os.getenv("WATCHLIST_ALERTS_FILE", "watchlist_alerts.json").strip() or "watchlist_alerts.json"
KST = timezone(timedelta(hours=9))

WATCH_COOLDOWN_MIN = int(float(os.getenv("WATCHLIST_ALERT_COOLDOWN_MIN", "180") or 180))
BREAKOUT_BUFFER_PCT = float(os.getenv("WATCHLIST_BREAKOUT_BUFFER_PCT", "0.5") or 0.5)
PULLBACK_BUFFER_PCT = float(os.getenv("WATCHLIST_PULLBACK_BUFFER_PCT", "1.5") or 1.5)
SUPPORT_BUFFER_PCT = float(os.getenv("WATCHLIST_SUPPORT_BUFFER_PCT", "1.0") or 1.0)
CHASE_GAP_PCT = float(os.getenv("WATCHLIST_CHASE_GAP_PCT", "4.0") or 4.0)
HOT_CHANGE_PCT = float(os.getenv("WATCHLIST_HOT_CHANGE_PCT", "8.0") or 8.0)
HOT_RSI = float(os.getenv("WATCHLIST_HOT_RSI", "75.0") or 75.0)
HOT_VOL_RATE = float(os.getenv("WATCHLIST_HOT_VOL_RATE", "250.0") or 250.0)


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


def _normalize_code(code: str, market: str = "KOR") -> str:
    market = _market_of(market)
    if market == "US":
        raw = str(code or "").strip().upper()
        return "".join(ch for ch in raw if ch.isalnum())
    raw = "".join(ch for ch in str(code or "") if ch.isdigit())
    return raw.zfill(6) if raw else ""


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


def _minutes_since(text: str) -> float:
    raw = str(text or "").strip()
    if not raw:
        return 10**9
    try:
        dt = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S").replace(tzinfo=KST)
        return max(0.0, (datetime.now(KST) - dt).total_seconds() / 60.0)
    except Exception:
        return 10**9


def _load_json_file(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []


def _save_json_file(path: str, rows: list[dict]) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("watchlist alerts save failed:", str(e))


def _get_fx_value() -> float:
    try:
        macro = get_macro_snapshot()
        return _safe_float((macro.get("usdkrw") or {}).get("value", 0), 0.0)
    except Exception:
        return 0.0


def _get_quote_by_market(market: str, code: str, token: str | None = None) -> dict:
    market = _market_of(market)
    code = _normalize_code(code, market)
    if market == "US":
        return get_us_current_price(code)
    if not token:
        token = get_access_token()
    return get_domestic_current_price(code=code, token=token)


def _alert_allowed(row: dict, key: str, cooldown_min: int) -> bool:
    prev_key = str(row.get("last_alert_key", "")).strip()
    prev_at = str(row.get("last_alert_at", "")).strip()
    if not key:
        return False
    if not prev_key or prev_key != key:
        return True
    return _minutes_since(prev_at) >= cooldown_min


def _signal_title(signal: str, market: str) -> str:
    mapping = {
        "BREAKOUT_WAIT": f"🚀 [WATCHLIST 돌파대기/{market}]",
        "PULLBACK_WAIT": f"🟡 [WATCHLIST 눌림대기/{market}]",
        "SUPPORT_CHECK": f"🔵 [WATCHLIST 지지확인/{market}]",
        "CHASE_BLOCK": f"⛔ [WATCHLIST 추격주의/{market}]",
        "WAIT": f"⚪ [WATCHLIST 대기/{market}]",
    }
    return mapping.get(str(signal or "").upper(), f"⚪ [WATCHLIST 대기/{market}]")


def get_watchlist_action_text(signal: str, strategy: str = "") -> str:
    sig = str(signal or "").strip().upper()
    strat = str(strategy or "").strip().upper()

    if sig == "BREAKOUT_WAIT":
        return "전고 돌파 재확인 후 접근"
    if sig == "PULLBACK_WAIT":
        return "눌림 유지 후 반등 확인"
    if sig == "SUPPORT_CHECK":
        return "지지 유지 여부 확인"
    if sig == "CHASE_BLOCK":
        return "신규진입 보류"

    if strat == "BREAKOUT":
        return "돌파 조건 대기"
    if strat == "PULLBACK":
        return "눌림 조건 대기"
    return "조건 재확인 후 판단"


def _parse_watchlist_rows() -> list[dict]:
    raw = os.getenv("WATCHLIST_JSON", "").strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except Exception:
        return []

    if not isinstance(data, list):
        return []

    out: list[dict] = []
    for idx, row in enumerate(data, start=1):
        if not isinstance(row, dict):
            continue
        market = _market_of(row.get("market", "KOR"))
        code = _normalize_code(row.get("code", ""), market)
        if not code:
            continue
        use_yn = str(row.get("use", row.get("useYn", "Y"))).strip().upper()
        if use_yn != "Y":
            continue

        out.append(
            {
                "market": market,
                "code": code,
                "name": str(row.get("name", code)).strip() or code,
                "strategy": str(row.get("strategy", row.get("entry_strategy", ""))).strip().upper(),
                "trigger_text": str(row.get("trigger", row.get("entry_trigger", ""))).strip(),
                "memo": str(row.get("memo", "")).strip(),
                "rank": idx,
            }
        )
    return out


def sync_watchlist_alerts() -> list[dict]:
    watchlist_rows = _parse_watchlist_rows()
    if not watchlist_rows:
        return []

    existing = _load_json_file(WATCHLIST_ALERTS_FILE)
    existing_map = {f"{_market_of(x.get('market'))}:{str(x.get('code', '')).strip().upper()}": x for x in existing}
    fx_value = _get_fx_value()

    for item in watchlist_rows:
        market = _market_of(item.get("market", "KOR"))
        code = _normalize_code(item.get("code", ""), market)
        key = f"{market}:{code}"

        prev = existing_map.get(key, {})
        payload = {
            "market": market,
            "code": code,
            "name": str(item.get("name", code)).strip() or code,
            "strategy": str(item.get("strategy", "")).strip().upper(),
            "trigger_text": str(item.get("trigger_text", "")).strip(),
            "memo": str(item.get("memo", "")).strip(),
            "saved_at": _now_text(),
            "fx_value": fx_value if market == "US" else 1.0,
            "current_price": _safe_float(prev.get("current_price", 0)),
            "prev_close": _safe_float(prev.get("prev_close", 0)),
            "anchor_price": _safe_float(prev.get("anchor_price", 0)),
            "gap_pct": _safe_float(prev.get("gap_pct", 0)),
            "rsi": _safe_float(prev.get("rsi", 0)),
            "vol_rate": _safe_float(prev.get("vol_rate", 0)),
            "auto_signal": str(prev.get("auto_signal", "WAIT")),
            "reason": str(prev.get("reason", "")),
            "action_text": str(prev.get("action_text", get_watchlist_action_text("", item.get("strategy", "")))),
            "last_alert_key": str(prev.get("last_alert_key", "")),
            "last_alert_at": str(prev.get("last_alert_at", "")),
        }
        existing_map[key] = payload

    merged = list(existing_map.values())
    merged.sort(key=lambda x: (x.get("market", ""), x.get("code", "")))
    _save_json_file(WATCHLIST_ALERTS_FILE, merged)
    return merged


def build_watchlist_alert_telegram_message(payload: dict) -> str:
    market = _market_of(payload.get("market", "KOR"))
    fx_value = _safe_float(payload.get("fx_value", 0), 0.0)
    signal = str(payload.get("auto_signal", "WAIT")).upper()

    lines = [
        _signal_title(signal, market),
        f"종목: {payload.get('name', '')} ({payload.get('code', '')})",
        f"현재가: {_format_price_with_krw(payload.get('current_price', 0), market, fx_value)}",
        f"전일종가: {_format_price_with_krw(payload.get('prev_close', 0), market, fx_value)}",
        f"기준가: {_format_price(payload.get('anchor_price', 0), market)}",
        f"괴리율: {_safe_float(payload.get('gap_pct', 0)):.2f}%",
        "",
        f"전략: {payload.get('strategy', '')}",
        f"트리거: {payload.get('trigger_text', '')}",
        f"기술상태: RSI {_safe_float(payload.get('rsi', 0)):.1f} / 거래량비 {_safe_float(payload.get('vol_rate', 0)):.0f}%",
        f"사유: {payload.get('reason', '')}",
        f"행동: {payload.get('action_text', '')}",
    ]
    memo = str(payload.get("memo", "")).strip()
    if memo:
        lines.append(f"메모: {memo}")
    lines.append("주의: 최종 판단은 직접")
    return "\n".join(lines)


def _evaluate_watch_signal(row: dict, quote: dict) -> tuple[str, float, float, str, str]:
    strategy = str(row.get("strategy", "")).strip().upper()

    price = _safe_float(quote.get("price", 0), 0.0)
    prev_close = _safe_float(quote.get("prev_close", 0), 0.0)
    rsi = _safe_float(row.get("rsi", 0), 0.0)
    vol_rate = _safe_float(row.get("vol_rate", 0), 0.0)

    if price <= 0:
        return "WAIT", 0.0, 0.0, "", ""

    anchor_price = prev_close if prev_close > 0 else price
    gap_pct = ((price - anchor_price) / anchor_price) * 100 if anchor_price > 0 else 0.0

    chase = (
        abs(gap_pct) >= CHASE_GAP_PCT
        or _safe_float(quote.get("change_pct", 0), 0.0) >= HOT_CHANGE_PCT
        or rsi >= HOT_RSI
        or vol_rate >= HOT_VOL_RATE
    )
    if chase and gap_pct > 0:
        return "CHASE_BLOCK", anchor_price, gap_pct, "급등/과열 구간으로 추격 주의", get_watchlist_action_text("CHASE_BLOCK", strategy)

    if strategy == "BREAKOUT":
        if anchor_price > 0 and price >= anchor_price * (1.0 + BREAKOUT_BUFFER_PCT / 100.0):
            return "BREAKOUT_WAIT", anchor_price, gap_pct, "기준가 상향 돌파 확인", get_watchlist_action_text("BREAKOUT_WAIT", strategy)
        return "WAIT", anchor_price, gap_pct, "돌파 조건 대기", get_watchlist_action_text("", strategy)

    if strategy == "PULLBACK":
        if anchor_price > 0 and price <= anchor_price * (1.0 + PULLBACK_BUFFER_PCT / 100.0):
            return "PULLBACK_WAIT", anchor_price, gap_pct, "기준가 부근 눌림 구간 진입", get_watchlist_action_text("PULLBACK_WAIT", strategy)
        return "WAIT", anchor_price, gap_pct, "눌림 조건 대기", get_watchlist_action_text("", strategy)

    if anchor_price > 0 and price <= anchor_price * (1.0 + SUPPORT_BUFFER_PCT / 100.0):
        return "SUPPORT_CHECK", anchor_price, gap_pct, "지지권 재테스트 구간", get_watchlist_action_text("SUPPORT_CHECK", strategy)

    return "WAIT", anchor_price, gap_pct, "조건 대기", get_watchlist_action_text("", strategy)


def scan_watchlist_alert_signals() -> list[str]:
    rows = sync_watchlist_alerts()
    if not rows:
        return []

    needs_kor_token = any(_market_of(x.get("market", "KOR")) == "KOR" for x in rows)
    token = get_access_token() if needs_kor_token else None

    msgs: list[str] = []
    changed = False

    for row in rows:
        market = _market_of(row.get("market", "KOR"))
        code = _normalize_code(row.get("code", ""), market)
        if not code:
            continue

        try:
            quote = _get_quote_by_market(market=market, code=code, token=token)
        except Exception as e:
            print(f"watchlist scan skipped {market} {code}: {e}")
            continue

        row["current_price"] = _safe_float(quote.get("price", 0))
        row["prev_close"] = _safe_float(quote.get("prev_close", 0))
        row["fx_value"] = _get_fx_value() if market == "US" else 1.0

        signal, anchor_price, gap_pct, reason, action_text = _evaluate_watch_signal(row, quote)
        row["anchor_price"] = anchor_price
        row["gap_pct"] = gap_pct
        row["reason"] = reason
        row["action_text"] = action_text
        row["auto_signal"] = signal
        row["rsi"] = _safe_float(row.get("rsi", 0))
        row["vol_rate"] = _safe_float(row.get("vol_rate", 0))

        if signal in {"BREAKOUT_WAIT", "PULLBACK_WAIT", "SUPPORT_CHECK", "CHASE_BLOCK"}:
            alert_key = f"{market}_{code}_{signal}_{int(round(anchor_price)) if anchor_price > 0 else 0}"
            if _alert_allowed(row, alert_key, WATCH_COOLDOWN_MIN):
                row["last_alert_key"] = alert_key
                row["last_alert_at"] = _now_text()
                msgs.append(build_watchlist_alert_telegram_message(row))

        changed = True

    if changed:
        _save_json_file(WATCHLIST_ALERTS_FILE, rows)

    return msgs
