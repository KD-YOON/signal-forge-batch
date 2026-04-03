import os
from datetime import datetime, timedelta, timezone
from typing import Any

from app.clients.gemini import summarize_news
from app.clients.kis import (
    enrich_with_indicators,
    get_access_token,
    get_domestic_current_price,
    get_domestic_daily_chart,
)
from app.clients.naver import get_news
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
]

NEGATIVE_NEWS_KEYWORDS = [
    "유상증자", "전환사채", "cb", "bw", "하한가", "소송", "과징금",
    "실적 부진", "실적부진", "가이던스 하향", "적자", "감자", "상장폐지",
    "횡령", "배임", "리콜", "규제", "조사", "경고", "목표가 하향", "매도 리포트",
]


def resolve_mode(mode: str) -> str:
    mode = str(mode or "").strip().lower()
    if mode in ("lunch", "evening", "manual", "morning"):
        return mode

    kst = timezone(timedelta(hours=9))
    hour = datetime.now(kst).hour
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
    for row in items[:2]:
        name = str(row.get("name", "")).strip() or str(row.get("code", "")).strip()
        summary = str(row.get("news_summary", "")).strip() or "관련 투자 뉴스 부족"
        parts.append(f"[{name}] {summary}")
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


def _analyze_candidates(resolved_mode: str) -> list[dict]:
    candidates = get_combined_candidates()

    recent = get_recent_tickers(days=3)
    filtered_candidates = []
    for c in candidates:
        ticker = str(c.get("code", "")).strip()
        if ticker in recent:
            continue
        filtered_candidates.append(c)

    analyze_limit = int(os.getenv("ANALYZE_TOP_N", "8") or "8")
    candidates = filtered_candidates[: max(1, analyze_limit)]

    token = get_access_token()
    analyzed: list[dict] = []

    for item in candidates:
        if str(item.get("market", "")).upper() != "KOR":
            continue

        code = str(item.get("code", "")).strip()
        name = str(item.get("name", code)).strip()
        theme = str(item.get("theme", "")).strip()

        quote = get_domestic_current_price(code=code, token=token)
        daily = get_domestic_daily_chart(code=code, token=token, days=60)

        enriched = enrich_with_indicators(
            {"code": code, "name": name, "theme": theme, "source": item.get("source", ""), "memo": item.get("memo", "")},
            quote,
            daily,
        )

        news_items = get_news(name, limit=2)
        news_summary = summarize_news(name, news_items)
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
                "market": "KOR",
                "run_mode": resolved_mode,
            }
        )

    seen = set()
    unique_analyzed = []
    for row in analyzed:
        code = str(row.get("code", "")).strip()
        if not code or code in seen:
            continue
        seen.add(code)
        unique_analyzed.append(row)

    return unique_analyzed


def _apply_post_filters(rows: list[dict], resolved_mode: str) -> tuple[list[dict], dict]:
    macro = get_macro_snapshot()
    rows = apply_macro_risk_overlay(rows, macro, resolved_mode)
    rows = [rebuild_stage_after_macro(x) for x in rows]

    rows.sort(
        key=lambda x: (
            0 if x.get("entry_decision") == "ENTRY" else 1 if x.get("entry_decision") == "WAIT" else 2,
            -_safe_int(x.get("entry_score", 0)),
            -_safe_int(x.get("quality_score", 0)),
            -_safe_int(x.get("total_score", 0)),
        )
    )
    return rows, macro


def build_entry_alert_payload(top: dict, resolved_mode: str, now_text: str) -> dict:
    return {
        "name": str(top.get("name", "")).strip() or str(top.get("code", "")).strip(),
        "code": str(top.get("code", "")).strip(),
        "mode": resolved_mode,
        "timestamp": now_text,
        "stage": str(top.get("stage", "")).strip(),
        "entry_decision": str(top.get("entry_decision", "")).strip(),
        "entry_reason": str(top.get("entry_reason", "")).strip(),
        "entry_score": _safe_int(top.get("entry_score", 0)),
        "quality_score": _safe_int(top.get("quality_score", 0)),
        "total_score": _safe_int(top.get("total_score", 0)),
        "proposed_entry": _safe_int(top.get("proposed_entry", 0)),
        "entry_zone_low": _safe_int(top.get("entry_zone_low", 0)),
        "entry_zone_high": _safe_int(top.get("entry_zone_high", 0)),
        "stop_loss": _safe_int(top.get("stop_loss", 0)),
        "target1": _safe_int(top.get("target1", 0)),
        "target2": _safe_int(top.get("target2", 0)),
        "current_price": _safe_int(top.get("price", 0)),
        "prev_close": _safe_int(top.get("prev_close", 0)),
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
    }


def build_entry_alert_text(payload: dict) -> str:
    if not str(payload.get("entry_decision", "")).startswith("ENTRY"):
        return ""

    lines = [
        "🚨 ENTRY ALERT",
        f"{payload.get('name', '')} ({payload.get('code', '')})",
        f"모드: {payload.get('mode', '')}",
        f"시각: {payload.get('timestamp', '')}",
        "",
        f"단계: {payload.get('stage', '')}",
        f"진입판정: {payload.get('entry_decision', '')} (진입점수 {payload.get('entry_score', 0)})",
        f"진입사유: {payload.get('entry_reason', '')}",
        f"제안매수가: {payload.get('proposed_entry', 0):,}원",
        f"관심구간: {payload.get('entry_zone_low', 0):,} ~ {payload.get('entry_zone_high', 0):,}원",
        f"손절가: {payload.get('stop_loss', 0):,}원",
        f"목표가1: {payload.get('target1', 0):,}원 / 목표가2: {payload.get('target2', 0):,}원",
        "",
        f"뉴스 판정: {payload.get('news_bias', '')}",
        f"뉴스 키워드: {payload.get('news_keywords', '')}",
        "메모: 관심구간 접근 후 분할·반등 확인 우선",
    ]
    return "\n".join(lines)


def build_report_text(rows: list[dict], macro: dict, resolved_mode: str, now_text: str) -> str:
    if not rows:
        return f"📊 Signal Forge 리포트\n모드: {resolved_mode}\n시각: {now_text}\n\n추천 종목 없음"

    top = rows[0]
    second = rows[1] if len(rows) > 1 else None
    market_news = build_market_news_summary(rows)
    macro_regime = str(top.get("macro_regime", "NEUTRAL"))
    macro_summary = str(top.get("macro_summary", "")).strip() or "매크로 중립"

    title_line = "🔥 오늘 최우선 종목"
    strategy_line = "💡 전략: 제안매수가 근처 접근 후 반등 확인"
    if resolved_mode == "lunch":
        title_line = "🔥 점심 체크 종목"
        strategy_line = "💡 점심 전략: 관심구간 접근 여부와 장중 반등 확인"
    elif resolved_mode == "evening":
        title_line = "🔥 저녁 준비 종목"
        strategy_line = "💡 저녁 전략: 내일 시가와 제안매수가 위치 비교"
    elif resolved_mode == "morning":
        title_line = "🔥 오전 우선 종목"
        strategy_line = "💡 오전 전략: 매크로 레짐과 초반 수급 함께 확인"

    top_name = str(top.get("name", "")).strip() or str(top.get("code", "")).strip()

    lines = [
        "📊 Signal Forge 리포트 [PIPELINE PATCH]",
        f"모드: {resolved_mode}",
        f"시각: {now_text}",
        "",
        f"🌐 매크로 레짐: {macro_regime}",
        f"🌐 매크로 요약: {macro_summary}",
        f"🌐 USD/KRW: {float((macro.get('usdkrw') or {}).get('value', 0) or 0):.2f}",
        "",
        f"🧭 시장 뉴스 포인트: {market_news}",
        "",
        title_line,
        f"{top_name} ({top['code']})",
        f"후보출처: {top.get('candidate_source', '')}",
        "",
        f"현재가: {_safe_int(top.get('price', 0)):,}원",
        f"전일종가 기준 제안매수가: {_safe_int(top.get('proposed_entry', 0)):,}원",
        f"관심구간: {_safe_int(top.get('entry_zone_low', 0)):,} ~ {_safe_int(top.get('entry_zone_high', 0)):,}원",
        f"손절가: {_safe_int(top.get('stop_loss', 0)):,}원",
        f"목표가1: {_safe_int(top.get('target1', 0)):,}원 / 목표가2: {_safe_int(top.get('target2', 0)):,}원",
        "",
        f"최종단계: {top.get('stage', '')}",
        f"진입판정: {top.get('entry_decision', '')} (진입점수 {_safe_int(top.get('entry_score', 0))})",
        f"진입사유: {top.get('entry_reason', '')}",
        "",
        f"등락률: {_safe_float(top.get('change_pct', 0)):.2f}%",
        f"거래량비: {_safe_float(top.get('vol_rate', 0)):.1f}%",
        f"RSI: {_safe_float(top.get('rsi', 0)):.1f}",
        f"총점: {_safe_int(top.get('total_score', 0))}",
        f"품질점수: {_safe_int(top.get('quality_score', 0))}",
        f"매집점수: {_safe_int(top.get('accumulation_score', 0))} / 돌파점수: {_safe_int(top.get('breakout_score', 0))} / 리스크점수: {_safe_int(top.get('risk_score', 0))}",
        f"테마: {top.get('theme', '')}",
        f"뉴스 판정: {(top.get('news_signal') or {}).get('bias', '')}",
        f"뉴스 키워드: {(top.get('news_signal') or {}).get('keyword_summary', '')}",
        "",
        "세부 신호:",
        f"- 매집: {', '.join(top.get('accumulation_flags', []) or []) if top.get('accumulation_flags') else '특이사항 없음'}",
        f"- 돌파: {', '.join(top.get('breakout_flags', []) or []) if top.get('breakout_flags') else '특이사항 없음'}",
        f"- 리스크: {', '.join(top.get('risk_flags', []) or []) if top.get('risk_flags') else '낮음'}",
        "",
        f"📰 최근 기사 요약: {top.get('news_summary', '')}",
        "🗞 최근 기사:",
    ]
    lines.extend(format_news_lines(top.get("news_items", [])))

    if second:
        second_name = str(second.get("name", "")).strip() or str(second.get("code", "")).strip()
        lines += [
            "",
            "➕ 차순위 후보",
            f"{second_name} ({second['code']}) / 출처 {second.get('candidate_source', '')}",
            f"단계 {second.get('stage', '')} / 진입판정 {second.get('entry_decision', '')} / 진입점수 {_safe_int(second.get('entry_score', 0))}",
        ]

    lines += [
        "",
        "제외 기준: 과열 추격, 부정 뉴스, 리스크 과다 종목은 PASS 처리 가능",
        strategy_line,
    ]

    return "\n".join(lines)


def run_report_pipeline(mode: str) -> dict:
    resolved_mode = resolve_mode(mode)
    now_text = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M:%S")

    rows = _analyze_candidates(resolved_mode)
    rows, macro = _apply_post_filters(rows, resolved_mode)

    top_tickers = [str(x.get("code", "")).strip() for x in rows[:5] if str(x.get("code", "")).strip()]
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

    entry_alert_payload = None
    entry_alert_text = ""
    if rows:
        entry_alert_payload = build_entry_alert_payload(rows[0], resolved_mode, now_text)
        entry_alert_text = build_entry_alert_text(entry_alert_payload)

    return {
        **pipeline,
        "report_text": report_text,
        "entry_alert_payload": entry_alert_payload,
        "entry_alert_text": entry_alert_text,
    }


def build_report(mode: str) -> str:
    """
    기존 jobs.py 호환용
    """
    bundle = build_report_bundle(mode)
    return bundle["report_text"]
