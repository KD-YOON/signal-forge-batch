import os
from datetime import datetime, timedelta, timezone
from typing import Any

from app.clients.gemini import review_candidates_with_gemini, summarize_news
from app.clients.kis import (
    enrich_with_indicators,
    get_access_token,
    get_domestic_current_price,
    get_domestic_daily_chart,
)
from app.clients.naver import get_news as get_kor_news
from app.clients.yahoo_us import (
    get_us_current_price,
    get_us_daily_chart,
    get_us_news,
)
from app.services.candidates import get_combined_candidates
from app.services.macro import apply_macro_risk_overlay, get_macro_snapshot
from app.services.signals import (
    analyze_stage_signals,
    compute_weighted_stage_score,
    decide_stage_label,
)
from app.recent_cache import get_recent_tickers, add_recommendations


POSITIVE_NEWS_KEYWORDS = [
    "수주", "계약", "공급", "양산", "실적 개선", "실적개선", "흑자전환",
    "가이던스 상향", "증설", "인수", "합병", "파트너십", "정책 수혜",
    "데이터센터", "ai", "반도체", "전기차", "국책", "대규모",
    "호실적", "영업이익", "매출 증가", "목표가 상향", "기관 매수", "외국인 매수",
    "earnings", "guidance", "upgrade", "data center", "ai demand",
]

NEGATIVE_NEWS_KEYWORDS = [
    "유상증자", "전환사채", "cb", "bw", "하한가", "소송", "과징금",
    "실적 부진", "실적부진", "가이던스 하향", "적자", "감자", "상장폐지",
    "횡령", "배임", "리콜", "규제", "조사", "경고", "목표가 하향", "매도 리포트",
    "downgrade", "lawsuit", "sec", "recall", "miss", "delay",
]

KST = timezone(timedelta(hours=9))


def resolve_mode(mode: str) -> str:
    mode = str(mode or "").strip().lower()
    if mode in ("lunch", "evening", "manual", "morning"):
        return mode

    hour = datetime.now(KST).hour
    if hour < 11:
        return "morning"
    if hour < 15:
        return "lunch"
    return "evening"


def _cut(text: str, n: int = 68) -> str:
    text = str(text or "").strip()
    return text if len(text) <= n else text[: n - 1] + "…"


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


def _get_news_by_market(market: str, code: str, name: str, limit: int = 2) -> list[dict]:
    market = _market_of(market)
    if market == "US":
        return get_us_news(code, limit=max(1, limit))
    return get_kor_news(name, limit=max(1, limit))


def _get_quote_and_daily(item: dict, token: str | None = None) -> tuple[dict, list[dict]]:
    market = _market_of(item.get("market", "KOR"))
    code = str(item.get("code", "")).strip()

    if market == "US":
        quote = get_us_current_price(code)
        daily = get_us_daily_chart(code, days=60)
        return quote, daily

    if not token:
        token = get_access_token()

    quote = get_domestic_current_price(code=code, token=token)
    daily = get_domestic_daily_chart(code=code, token=token, days=60)
    return quote, daily


def evaluate_news_trade_signal(news_items: list[dict], news_summary: str) -> dict:
    text = " ".join(
        [str(news_summary or "")]
        + [str(x.get("title", "")) for x in news_items]
        + [str(x.get("description", "")) for x in news_items]
    ).lower()

    positive_hits = [kw for kw in POSITIVE_NEWS_KEYWORDS if kw in text]
    negative_hits = [kw for kw in NEGATIVE_NEWS_KEYWORDS if kw in text]

    bias = "NEUTRAL"
    score = 0

    if positive_hits:
        score += min(12, len(positive_hits) * 4)
    if negative_hits:
        score -= min(18, len(negative_hits) * 6)

    if negative_hits:
        bias = "NEGATIVE"
    elif positive_hits:
        bias = "POSITIVE"

    keyword_summary_parts = []
    if positive_hits:
        keyword_summary_parts.append("호재:" + ",".join(positive_hits[:3]))
    if negative_hits:
        keyword_summary_parts.append("악재:" + ",".join(negative_hits[:3]))

    return {
        "bias": bias,
        "score": score,
        "positive_hits": positive_hits[:3],
        "negative_hits": negative_hits[:3],
        "keyword_summary": " / ".join(keyword_summary_parts) if keyword_summary_parts else "특이 키워드 없음",
    }


def build_market_news_summary(items: list[dict]) -> str:
    if not items:
        return "시장 뉴스 포인트 없음"
    parts = []
    for row in items[:3]:
        name = str(row.get("name", "")).strip() or str(row.get("code", "")).strip()
        market = _market_of(row.get("market", "KOR"))
        summary = str(row.get("news_summary", "")).strip() or "관련 투자 뉴스 부족"
        parts.append(f"[{market} {name}] {summary}")
    return " / ".join(parts)


def format_news_lines(news_items: list[dict]) -> list[str]:
    if not news_items:
        return ["- 관련 투자 뉴스 부족"]
    lines = []
    for item in news_items[:2]:
        title = _cut(item.get("title", ""), 72)
        lines.append(f"- {title}")
    return lines


def rebuild_stage_after_macro(item: dict) -> dict:
    total_score = compute_weighted_stage_score(
        early_score=float(item.get("accumulation_score", 0) or 0),
        breakout_score=float(item.get("breakout_score", 0) or 0),
        theme_score=float(item.get("theme_score", 0) or 0),
        sentiment_adj=float(item.get("sentiment_adj", 0) or 0),
        risk_score=float(item.get("risk_score", 0) or 0),
    )
    stage = decide_stage_label(
        early_score=float(item.get("accumulation_score", 0) or 0),
        breakout_score=float(item.get("breakout_score", 0) or 0),
        risk_score=float(item.get("risk_score", 0) or 0),
        theme_score=float(item.get("theme_score", 0) or 0),
        total_score=float(total_score),
        rsi=float(item.get("rsi", 50) or 50),
        vol_rate=float(item.get("vol_rate", 0) or 0),
    )
    item["total_score"] = int(total_score)
    item["stage"] = stage
    return item


def split_rows_by_market(rows: list[dict]) -> dict:
    kor_rows = [x for x in rows if _market_of(x.get("market", "KOR")) == "KOR"]
    us_rows = [x for x in rows if _market_of(x.get("market", "KOR")) == "US"]

    return {
        "all": rows,
        "kor": kor_rows,
        "us": us_rows,
        "top_all": rows[0] if rows else None,
        "top_kor": kor_rows[0] if kor_rows else None,
        "top_us": us_rows[0] if us_rows else None,
    }


def _build_market_leader_block(title: str, row: dict | None, usdkrw: float) -> list[str]:
    if not row:
        return [title, "- 후보 없음"]

    market = _market_of(row.get("market", "KOR"))
    name = str(row.get("name", "")).strip() or str(row.get("code", "")).strip()

    return [
        title,
        f"{name} ({row.get('code', '')})",
        f"시장: {market}",
        f"현재가: {_format_price_with_krw(row.get('price', 0), market, usdkrw)}",
        f"제안매수가: {_format_price_with_krw(row.get('proposed_entry', 0), market, usdkrw)}",
        f"관심구간: {_format_price(row.get('entry_zone_low', 0), market)} ~ {_format_price(row.get('entry_zone_high', 0), market)}",
        f"최종단계: {row.get('final_stage', row.get('stage', ''))}",
        f"진입판정: {row.get('entry_decision', '')} (진입점수 {_safe_int(row.get('entry_score', 0))})",
        f"총점: {_safe_int(row.get('total_score', 0))} / 품질점수: {_safe_int(row.get('quality_score', 0))}",
        f"뉴스요약: {row.get('news_summary', '')}",
    ]


def _analyze_candidates(resolved_mode: str) -> list[dict]:
    candidates = get_combined_candidates()

    recent = get_recent_tickers(days=3)
    filtered_candidates = []
    for c in candidates:
        market = _market_of(c.get("market", "KOR"))
        ticker = str(c.get("code", "")).strip().upper()
        recent_key1 = ticker
        recent_key2 = f"{market}:{ticker}"
        if recent_key1 in recent or recent_key2 in recent:
            continue
        filtered_candidates.append(c)

    analyze_limit = int(os.getenv("ANALYZE_TOP_N", "12") or "12")
    candidates = filtered_candidates[: max(1, analyze_limit)]

    has_kor = any(_market_of(x.get("market", "KOR")) == "KOR" for x in candidates)
    token = get_access_token() if has_kor else None

    analyzed: list[dict] = []

    for item in candidates:
        market = _market_of(item.get("market", "KOR"))
        code = str(item.get("code", "")).strip().upper()
        if not code:
            continue

        name = str(item.get("name", code)).strip() or code
        theme = str(item.get("theme", "")).strip()

        try:
            quote, daily = _get_quote_and_daily(item, token=token)
        except Exception as e:
            print(f"candidate analyze skipped {market} {code}: {e}")
            continue

        if not quote:
            continue

        enriched = enrich_with_indicators(
            {
                "code": code,
                "name": name,
                "theme": theme,
                "source": item.get("source", ""),
                "memo": item.get("memo", ""),
                "market": market,
            },
            quote,
            daily,
        )

        if market == "US":
            long_name = str(quote.get("long_name", "")).strip()
            if long_name:
                enriched["name"] = long_name

        news_items = _get_news_by_market(market, code, name, limit=2)
        news_summary = summarize_news(name, news_items, market=market)
        news_signal = evaluate_news_trade_signal(news_items, news_summary)
        stage_info = analyze_stage_signals(enriched, quote, daily, news_signal)

        analyzed.append(
            {
                **enriched,
                **stage_info,
                "candidate_source": item.get("source", ""),
                "candidate_memo": item.get("memo", ""),
                "news_items": news_items,
                "news_summary": news_summary,
                "news_signal": news_signal,
                "market": market,
                "run_mode": resolved_mode,
                "currency": str(quote.get("currency", "USD" if market == "US" else "KRW")).strip() or ("USD" if market == "US" else "KRW"),
                "market_state": str(quote.get("market_state", "")).strip(),
            }
        )

    seen = set()
    unique_analyzed = []
    for row in analyzed:
        market = _market_of(row.get("market", "KOR"))
        code = str(row.get("code", "")).strip().upper()
        key = f"{market}:{code}"
        if not code or key in seen:
            continue
        seen.add(key)
        unique_analyzed.append(row)

    return unique_analyzed


def _apply_post_filters(rows: list[dict], resolved_mode: str) -> tuple[list[dict], dict]:
    macro = get_macro_snapshot()
    rows = apply_macro_risk_overlay(rows, macro, resolved_mode)
    rows = [rebuild_stage_after_macro(x) for x in rows]

    market_news_summary = build_market_news_summary(rows)
    macro_summary = ""
    if rows:
        macro_summary = str(rows[0].get("macro_summary", "")).strip()

    rows = review_candidates_with_gemini(
        rows=rows,
        run_type=resolved_mode.upper(),
        market_news_summary=market_news_summary,
        macro_summary=macro_summary,
    )

    rows.sort(
        key=lambda x: (
            0 if str(x.get("entry_decision", "")).upper() == "ENTRY" else 1 if str(x.get("entry_decision", "")).upper() == "WAIT" else 2,
            -_safe_int(x.get("entry_score", 0)),
            -_safe_int(x.get("quality_score", 0)),
            -_safe_int(x.get("total_score", 0)),
        )
    )
    return rows, macro


def build_entry_alert_payload(top: dict, resolved_mode: str, now_text: str) -> dict:
    market = _market_of(top.get("market", "KOR"))
    fx_value = _safe_float((get_macro_snapshot().get("usdkrw") or {}).get("value", 0), 0.0) if market == "US" else 1.0

    return {
        "market": market,
        "currency": str(top.get("currency", "USD" if market == "US" else "KRW")).strip() or ("USD" if market == "US" else "KRW"),
        "name": str(top.get("name", "")).strip() or str(top.get("code", "")).strip(),
        "code": str(top.get("code", "")).strip(),
        "mode": resolved_mode,
        "timestamp": now_text,
        "stage": str(top.get("stage", "")).strip(),
        "final_stage": str(top.get("final_stage", top.get("stage", ""))).strip(),
        "entry_decision": str(top.get("entry_decision", "")).strip(),
        "entry_reason": str(top.get("entry_reason", "")).strip(),
        "entry_score": _safe_int(top.get("entry_score", 0)),
        "quality_score": _safe_int(top.get("quality_score", 0)),
        "total_score": _safe_int(top.get("total_score", 0)),
        "proposed_entry": _safe_float(top.get("proposed_entry", 0)),
        "entry_zone_low": _safe_float(top.get("entry_zone_low", 0)),
        "entry_zone_high": _safe_float(top.get("entry_zone_high", 0)),
        "stop_loss": _safe_float(top.get("stop_loss", 0)),
        "target1": _safe_float(top.get("target1", 0)),
        "target2": _safe_float(top.get("target2", 0)),
        "current_price": _safe_float(top.get("price", 0)),
        "prev_close": _safe_float(top.get("prev_close", 0)),
        "rsi": _safe_float(top.get("rsi", 0)),
        "vol_rate": _safe_float(top.get("vol_rate", 0)),
        "news_bias": str((top.get("news_signal") or {}).get("bias", "")),
        "news_keywords": str((top.get("news_signal") or {}).get("keyword_summary", "")),
        "news_summary": str(top.get("news_summary", "")),
        "candidate_source": str(top.get("candidate_source", "")),
        "accumulation_flags": list(top.get("accumulation_flags", []) or []),
        "breakout_flags": list(top.get("breakout_flags", []) or []),
        "risk_flags": list(top.get("risk_flags", []) or []),
        "macro_regime": str(top.get("macro_regime", "")),
        "macro_summary": str(top.get("macro_summary", "")),
        "ai_verdict": str(top.get("ai_verdict", "")).strip(),
        "ai_risk": str(top.get("ai_risk", "")).strip(),
        "ai_confidence": _safe_int(top.get("ai_confidence", 0)),
        "fx_value": fx_value,
    }


def build_entry_alert_text(payload: dict) -> str:
    if not str(payload.get("entry_decision", "")).startswith("ENTRY"):
        return ""

    market = _market_of(payload.get("market", "KOR"))
    fx_value = _safe_float(payload.get("fx_value", 0), 0.0)

    lines = [
        "🚨 ENTRY ALERT",
        f"{payload.get('name', '')} ({payload.get('code', '')})",
        f"시장: {market}",
        f"모드: {payload.get('mode', '')}",
        f"시각: {payload.get('timestamp', '')}",
        "",
        f"단계: {payload.get('final_stage', payload.get('stage', ''))}",
        f"진입판정: {payload.get('entry_decision', '')} (진입점수 {payload.get('entry_score', 0)})",
        f"진입사유: {payload.get('entry_reason', '')}",
        f"제안매수가: {_format_price_with_krw(payload.get('proposed_entry', 0), market, fx_value)}",
        f"관심구간: {_format_price(payload.get('entry_zone_low', 0), market)} ~ {_format_price(payload.get('entry_zone_high', 0), market)}",
        f"손절가: {_format_price(payload.get('stop_loss', 0), market)}",
        f"목표가1: {_format_price(payload.get('target1', 0), market)} / 목표가2: {_format_price(payload.get('target2', 0), market)}",
        "",
        f"뉴스 판정: {payload.get('news_bias', '')}",
        f"뉴스 키워드: {payload.get('news_keywords', '')}",
        f"AI 의견: {payload.get('ai_verdict', '')}",
        f"AI 리스크: {payload.get('ai_risk', '')}",
        "메모: 관심구간 접근 후 분할·반등 확인 우선",
    ]
    return "\n".join(lines)


def build_report_text(rows: list[dict], macro: dict, resolved_mode: str, now_text: str) -> str:
    if not rows:
        return f"📊 Signal Forge 리포트\n모드: {resolved_mode}\n시각: {now_text}\n\n추천 종목 없음"

    grouped = split_rows_by_market(rows)
    top_all = grouped["top_all"]
    top_kor = grouped["top_kor"]
    top_us = grouped["top_us"]

    market_news = build_market_news_summary(rows)
    macro_regime = str((top_all or {}).get("macro_regime", "NEUTRAL"))
    macro_summary = str((top_all or {}).get("macro_summary", "")).strip() or "매크로 중립"
    usdkrw = _safe_float((macro.get("usdkrw") or {}).get("value", 0), 0.0)

    title_line = "🔥 오늘 통합 1등"
    strategy_line = "💡 전략: 시장별 1등 후보를 각각 비교해 관심구간 접근 여부 확인"
    if resolved_mode == "lunch":
        title_line = "🔥 점심 통합 1등"
        strategy_line = "💡 점심 전략: 국내/해외 대표주 장중 위치 비교"
    elif resolved_mode == "evening":
        title_line = "🔥 저녁 통합 1등"
        strategy_line = "💡 저녁 전략: 다음 거래 세션용 국내/해외 대표주 준비"
    elif resolved_mode == "morning":
        title_line = "🔥 오전 통합 1등"
        strategy_line = "💡 오전 전략: 매크로 레짐과 시장별 대표주 동시 점검"

    top_all_name = str((top_all or {}).get("name", "")).strip() or str((top_all or {}).get("code", "")).strip()
    top_all_market = _market_of((top_all or {}).get("market", "KOR"))

    lines = [
        "📊 Signal Forge 리포트 [DUAL MARKET PATCH]",
        f"모드: {resolved_mode}",
        f"시각: {now_text}",
        "",
        f"🌐 매크로 레짐: {macro_regime}",
        f"🌐 매크로 요약: {macro_summary}",
        f"🌐 USD/KRW: {usdkrw:.2f}",
        "",
        f"🧭 시장 뉴스 포인트: {market_news}",
        "",
        title_line,
        f"{top_all_name} ({(top_all or {}).get('code', '')})",
        f"시장: {top_all_market}",
        f"현재가: {_format_price_with_krw((top_all or {}).get('price', 0), top_all_market, usdkrw)}",
        f"제안매수가: {_format_price_with_krw((top_all or {}).get('proposed_entry', 0), top_all_market, usdkrw)}",
        f"관심구간: {_format_price((top_all or {}).get('entry_zone_low', 0), top_all_market)} ~ {_format_price((top_all or {}).get('entry_zone_high', 0), top_all_market)}",
        f"최종단계: {(top_all or {}).get('final_stage', (top_all or {}).get('stage', ''))}",
        f"진입판정: {(top_all or {}).get('entry_decision', '')} (진입점수 {_safe_int((top_all or {}).get('entry_score', 0))})",
        "",
    ]

    lines.extend(_build_market_leader_block("🇰🇷 국내 1등", top_kor, usdkrw))
    lines.append("")
    lines.extend(_build_market_leader_block("🇺🇸 해외 1등", top_us, usdkrw))

    if top_all:
        lines += [
            "",
            "📰 통합 1등 최근 기사:",
        ]
        lines.extend(format_news_lines((top_all or {}).get("news_items", [])))
        lines += [
            "",
            f"AI 의견: {(top_all or {}).get('ai_verdict', '')}",
            f"AI 리스크: {(top_all or {}).get('ai_risk', '')}",
        ]

    lines += [
        "",
        strategy_line,
    ]

    return "\n".join(lines)


def run_report_pipeline(mode: str) -> dict:
    resolved_mode = resolve_mode(mode)
    now_text = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")

    rows = _analyze_candidates(resolved_mode)
    rows, macro = _apply_post_filters(rows, resolved_mode)

    top_tickers = [
        f"{_market_of(x.get('market', 'KOR'))}:{str(x.get('code', '')).strip()}"
        for x in rows[:6]
        if str(x.get("code", "")).strip()
    ]
    if top_tickers:
        add_recommendations(top_tickers)

    return {
        "mode": resolved_mode,
        "timestamp": now_text,
        "rows": rows,
        "macro": macro,
        "market_news_summary": build_market_news_summary(rows),
    }


def build_report_bundle(mode: str) -> dict:
    pipeline = run_report_pipeline(mode)
    rows = pipeline["rows"]
    macro = pipeline["macro"]
    resolved_mode = pipeline["mode"]
    now_text = pipeline["timestamp"]

    report_text = build_report_text(rows, macro, resolved_mode, now_text)

    grouped = split_rows_by_market(rows)
    entry_payloads = []
    entry_texts = []

    for top in [grouped["top_kor"], grouped["top_us"]]:
        if not top:
            continue
        payload = build_entry_alert_payload(top, resolved_mode, now_text)
        text = build_entry_alert_text(payload)
        if text:
            entry_payloads.append(payload)
            entry_texts.append(text)

    entry_alert_payload = entry_payloads[0] if entry_payloads else None
    entry_alert_text = "\n\n--------------------\n\n".join(entry_texts).strip()

    return {
        **pipeline,
        "report_text": report_text,
        "entry_alert_payload": entry_alert_payload,
        "entry_alert_payloads": entry_payloads,
        "entry_alert_text": entry_alert_text,
        "market_split": grouped,
    }


def build_report(mode: str) -> str:
    bundle = build_report_bundle(mode)
    return bundle["report_text"]
