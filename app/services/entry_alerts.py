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

# ===== 환경설정 =====
TOP_N = int(float(os.getenv("ENTRY_ALERT_TOP_N", "5") or 5))
PULLBACK_PCT = float(os.getenv("ENTRY_ALERT_PULLBACK_PCT", "-5.0") or -5.0)
NEAR_PCT = float(os.getenv("ENTRY_ALERT_NEAR_PCT", "1.2") or 1.2)

# 스크립트판 참고 확장값
REBOUND_MIN_PCT = float(os.getenv("ENTRY_ALERT_REBOUND_MIN_PCT", "0.8") or 0.8)
REBOUND_STRONG_PCT = float(os.getenv("ENTRY_ALERT_REBOUND_STRONG_PCT", "1.2") or 1.2)
BREAKOUT_BUFFER_PCT = float(os.getenv("ENTRY_ALERT_BREAKOUT_BUFFER_PCT", "0.6") or 0.6)
SUPPORT_TEST_BUFFER_PCT = float(os.getenv("ENTRY_ALERT_SUPPORT_TEST_BUFFER_PCT", "1.0") or 1.0)

# 추격/과열 차단
CHASE_GAP_PCT = float(os.getenv("ENTRY_ALERT_CHASE_GAP_PCT", "4.0") or 4.0)
HOT_CHANGE_PCT = float(os.getenv("ENTRY_ALERT_HOT_CHANGE_PCT", "8.0") or 8.0)
HOT_RSI = float(os.getenv("ENTRY_ALERT_HOT_RSI", "75.0") or 75.0)
HOT_VOL_RATE = float(os.getenv("ENTRY_ALERT_HOT_VOL_RATE", "250.0") or 250.0)

# 중복 알림 방지
WATCH_COOLDOWN_MIN = int(float(os.getenv("ENTRY_ALERT_WATCH_COOLDOWN_MIN", "90") or 90))
REBOUND_COOLDOWN_MIN = int(float(os.getenv("ENTRY_ALERT_REBOUND_COOLDOWN_MIN", "240") or 240))
BREAKOUT_COOLDOWN_MIN = int(float(os.getenv("ENTRY_ALERT_BREAKOUT_COOLDOWN_MIN", "360") or 360))
CHASE_COOLDOWN_MIN = int(float(os.getenv("ENTRY_ALERT_CHASE_COOLDOWN_MIN", "240") or 240))
SUPPORT_COOLDOWN_MIN = int(float(os.getenv("ENTRY_ALERT_SUPPORT_COOLDOWN_MIN", "180") or 180))


# ===== 공통 유틸 =====
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


def _minutes_since(text: str) -> float:
    raw = str(text or "").strip()
    if not raw:
        return 10**9
    try:
        dt = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S").replace(tzinfo=KST)
        return max(0.0, (datetime.now(KST) - dt).total_seconds() / 60.0)
    except Exception:
        return 10**9


# ===== 파일 저장 =====
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


# ===== 외부 데이터 =====
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


# ===== 가격 구간 계산 =====
def _normalize_price_levels(row: dict, market: str, prev_close: float) -> tuple[float, float, float]:
    suggested_buy = _safe_float(row.get("suggested_buy", 0), 0.0)
    lower = _safe_float(row.get("entry_zone_low", 0), 0.0)
    upper = _safe_float(row.get("entry_zone_high", 0), 0.0)

    if suggested_buy <= 0 and prev_close > 0:
        suggested_buy = prev_close * (1.0 + PULLBACK_PCT / 100.0)

    if suggested_buy > 0 and (lower <= 0 or upper <= 0):
        digits = 2 if _is_us_market(market) else 0
        lower = round(suggested_buy * (1.0 - NEAR_PCT / 100.0), digits)
        upper = round(suggested_buy * (1.0 + NEAR_PCT / 100.0), digits)

    return suggested_buy, lower, upper


def _alert_allowed(row: dict, key: str, cooldown_min: int) -> bool:
    prev_key = str(row.get("last_alert_key", "")).strip()
    prev_at = str(row.get("last_alert_at", "")).strip()
    if not key:
        return False
    if not prev_key or prev_key != key:
        return True
    return _minutes_since(prev_at) >= cooldown_min


# ===== 행동 문구 =====
def get_entry_action_text(signal: str, stage: str, entry_decision: str) -> str:
    sig = str(signal or "").strip().upper()
    stg = str(stage or "").strip().upper()
    decision = str(entry_decision or "").strip().upper()

    # 신형 신호
    if sig == "WATCH_ZONE":
        return "관심구간 진입, 반등 대기"
    if sig == "REBOUND_READY":
        return "반등 확인 후 1차 분할진입 검토"
    if sig == "BREAKOUT_CONFIRM":
        return "돌파 확인, 1차 분할진입 가능"
    if sig == "SUPPORT_TEST":
        return "지지 유지 여부 확인"
    if sig == "CHASE_BLOCK":
        return "신규진입 보류"

    # 구형 문구 호환
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


# ===== 리포트 후보 저장 =====
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
    tracked = tracked[:TOP_N]

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
        suggested_buy = _safe_float(r.get("proposed_entry", 0))
        lower = _safe_float(r.get("entry_zone_low", 0))
        upper = _safe_float(r.get("entry_zone_high", 0))

        if suggested_buy <= 0 and prev_close > 0:
            suggested_buy = prev_close * (1.0 + PULLBACK_PCT / 100.0)

        if suggested_buy > 0 and (lower <= 0 or upper <= 0):
            digits = 2 if market == "US" else 0
            lower = round(suggested_buy * (1.0 - NEAR_PCT / 100.0), digits)
            upper = round(suggested_buy * (1.0 + NEAR_PCT / 100.0), digits)

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
            # 추적용 확장 상태
            "low_seen_price": 0.0,
            "watch_hit_at": "",
            "low_touch_count": 0,
            "last_breakout_price": 0.0,
            "last_alert_key": "",
            "last_alert_at": "",
        }

        key = _key_of(payload)
        prev = existing_map.get(key, {})
        if prev:
            payload["low_seen_price"] = _safe_float(prev.get("low_seen_price", 0))
            payload["watch_hit_at"] = str(prev.get("watch_hit_at", "")).strip()
            payload["low_touch_count"] = _safe_int(prev.get("low_touch_count", 0))
            payload["last_breakout_price"] = _safe_float(prev.get("last_breakout_price", 0))
            payload["last_alert_key"] = str(prev.get("last_alert_key", "")).strip()
            payload["last_alert_at"] = str(prev.get("last_alert_at", "")).strip()

        existing_map[key] = payload

    merged = list(existing_map.values())
    merged.sort(key=lambda x: (x.get("market", ""), x.get("code", "")))
    _save_rows(merged)
    return merged


# ===== 텔레그램 메시지 =====
def _signal_title(signal: str, market: str) -> str:
    sig = str(signal or "").upper()
    mapping = {
        "WATCH_ZONE": f"🟡 [관심구간 진입/{market}]",
        "REBOUND_READY": f"🟢 [반등 준비/{market}]",
        "BREAKOUT_CONFIRM": f"🚀 [돌파 확인/{market}]",
        "SUPPORT_TEST": f"🔵 [지지 재테스트/{market}]",
        "CHASE_BLOCK": f"⛔ [추격주의/{market}]",
        "반등확인": f"🟢 [반등확인 매수시점/{market}]",
        "관심구간진입": f"🟡 [관심구간 진입/{market}]",
        "대기": f"⚪ [대기/{market}]",
        "WAIT": f"⚪ [대기/{market}]",
    }
    return mapping.get(sig, f"⚪ [대기/{market}]")


def build_entry_alert_telegram_message(payload: dict) -> str:
    market = _market_of(payload.get("market", "KOR"))
    fx_value = _safe_float(payload.get("fx_value", 0), 0.0)
    signal = str(payload.get("auto_signal", "") or "WAIT")

    tech_parts = [
        f"RSI {_safe_float(payload.get('rsi', 0)):.1f}",
        f"거래량비 {_safe_float(payload.get('vol_rate', 0)):.0f}%"
    ]
    acc = payload.get("accumulation_flags", [])
    if isinstance(acc, list) and acc:
        tech_parts.append("매집 " + ", ".join(str(x) for x in acc[:3]))

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
        f"기술상태: {' / '.join(tech_parts)}",
        f"사유: {payload.get('reason', '')}",
        f"행동: {payload.get('action_text', '')}",
        "주의: 최종 판단은 직접",
    ]
    return "\n".join(lines)


# ===== 신호 평가 엔진 =====
def _evaluate_signal(row: dict, quote: dict) -> tuple[str, str, str, int]:
    market = _market_of(row.get("market", "KOR"))
    code = str(row.get("code", "")).strip().upper()

    price = _safe_float(quote.get("price", 0), 0.0)
    prev_close = _safe_float(quote.get("prev_close", 0) or row.get("prev_close", 0), 0.0)
    rsi = _safe_float(row.get("rsi", 0), 0.0)
    vol_rate = _safe_float(row.get("vol_rate", 0), 0.0)
    stage = str(row.get("stage", "")).strip().upper()
    entry_decision = str(row.get("entry_decision", "")).strip().upper()

    suggested_buy, lower, upper = _normalize_price_levels(row, market, prev_close)
    if suggested_buy <= 0 or price <= 0 or prev_close <= 0:
        return "대기", "", "", 0

    change_from_prev = ((price - prev_close) / prev_close) * 100 if prev_close > 0 else 0.0
    gap_from_buy = ((price - suggested_buy) / suggested_buy) * 100 if suggested_buy > 0 else 0.0

    low_seen_old = _safe_float(row.get("low_seen_price", 0), 0.0)
    low_seen_new = min(low_seen_old, price) if low_seen_old > 0 else price
    rebound_pct = ((price - low_seen_new) / low_seen_new) * 100 if low_seen_new > 0 else 0.0

    row["low_seen_price"] = low_seen_new

    in_watch_zone = lower <= price <= upper
    if in_watch_zone:
        row["low_touch_count"] = _safe_int(row.get("low_touch_count", 0)) + 1
        if not str(row.get("watch_hit_at", "")).strip():
            row["watch_hit_at"] = _now_text()

    breakout_ref = max(_safe_float(row.get("entry_zone_high", 0), 0.0), suggested_buy)
    last_breakout_price = _safe_float(row.get("last_breakout_price", 0), 0.0)

    # 1) 추격 차단
    chase_block = (
        gap_from_buy >= CHASE_GAP_PCT
        or change_from_prev >= HOT_CHANGE_PCT
        or (rsi >= HOT_RSI and change_from_prev >= 4.0)
        or vol_rate >= HOT_VOL_RATE
    )
    if chase_block:
        row["last_breakout_price"] = max(last_breakout_price, price)
        signal = "CHASE_BLOCK"
        reason = (
            f"제안매수가 대비 +{gap_from_buy:.2f}% 괴리 / "
            f"전일 대비 {change_from_prev:.2f}% / RSI {rsi:.1f} / 거래량비 {vol_rate:.0f}%"
        )
        alert_key = f"{market}_{code}_CHASE_{int(round(price))}"
        return signal, reason, alert_key, CHASE_COOLDOWN_MIN

    # 2) 돌파 확인
    if price >= breakout_ref * (1.0 + BREAKOUT_BUFFER_PCT / 100.0):
        row["last_breakout_price"] = max(last_breakout_price, price)
        signal = "BREAKOUT_CONFIRM"
        reason = f"관심구간 상단 재돌파 확인 / 기준가 {breakout_ref:,.2f}"
        alert_key = f"{market}_{code}_BREAKOUT_{int(round(breakout_ref))}"
        return signal, reason, alert_key, BREAKOUT_COOLDOWN_MIN

    # 3) 반등 준비
    if low_seen_new <= upper and rebound_pct >= REBOUND_MIN_PCT and price >= suggested_buy:
        strength = "강한 반등" if rebound_pct >= REBOUND_STRONG_PCT else "반등 확인"
        signal = "REBOUND_READY"
        reason = f"관심구간 터치 후 저점 대비 +{rebound_pct:.2f}% {strength}"
        alert_key = f"{market}_{code}_REBOUND_{int(round(suggested_buy))}"
        return signal, reason, alert_key, REBOUND_COOLDOWN_MIN

    # 4) 관심구간 진입
    if in_watch_zone:
        signal = "WATCH_ZONE"
        reason = f"전일종가 대비 {change_from_prev:.2f}% / 제안매수가 부근 도달"
        alert_key = f"{market}_{code}_WATCH_{int(round(suggested_buy))}"
        return signal, reason, alert_key, WATCH_COOLDOWN_MIN

    # 5) 지지 재테스트
    if lower > 0 and price <= lower * (1.0 + SUPPORT_TEST_BUFFER_PCT / 100.0):
        signal = "SUPPORT_TEST"
        reason = "관심구간 하단 또는 지지권 재테스트"
        alert_key = f"{market}_{code}_SUPPORT_{int(round(lower))}"
        return signal, reason, alert_key, SUPPORT_COOLDOWN_MIN

    # 6) 기본 대기
    if stage == "BREAKOUT_READY":
        return "대기", "돌파 준비형 추적 중", "", 0
    if stage == "EARLY_ACCUMULATION" and entry_decision == "ENTRY":
        return "대기", "눌림 및 반등 대기", "", 0

    return "대기", "", "", 0


# ===== 스캔 실행 =====
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

        suggested_buy, lower, upper = _normalize_price_levels(row, market, prev_close)
        signal, reason, alert_key, cooldown = _evaluate_signal(row, quote)

        row["current_price"] = price
        row["prev_close"] = prev_close
        row["suggested_buy"] = suggested_buy
        row["entry_zone_low"] = lower
        row["entry_zone_high"] = upper
        row["auto_signal"] = signal
        row["reason"] = reason
        row["gap_pct"] = ((price - suggested_buy) / suggested_buy) * 100 if suggested_buy > 0 else 0.0
        row["fx_value"] = _get_fx_value() if market == "US" else 1.0
        row["action_text"] = get_entry_action_text(
            signal,
            str(row.get("stage", "")),
            str(row.get("entry_decision", "")),
        )

        if signal in {"WATCH_ZONE", "REBOUND_READY", "BREAKOUT_CONFIRM", "SUPPORT_TEST", "CHASE_BLOCK"}:
            if _alert_allowed(row, alert_key, cooldown):
                row["last_alert_key"] = alert_key
                row["last_alert_at"] = _now_text()
                msgs.append(build_entry_alert_telegram_message(row))

        changed = True

    if changed:
        _save_rows(rows)

    return msgs
