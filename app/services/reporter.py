import json
import os
from datetime import datetime, timedelta, timezone

from app.clients.gemini import summarize_news
from app.clients.kis import (
    enrich_with_indicators,
    get_access_token,
    get_domestic_current_price,
    get_domestic_daily_chart,
)
from app.clients.naver import get_news
from app.services.signals import analyze_stage_signals


DEFAULT_CANDIDATES = [
    {"market": "KOR", "code": "005930", "name": "삼성전자", "theme": "반도체 대형주"},
    {"market": "KOR", "code": "000660", "name": "SK하이닉스", "theme": "AI 반도체"},
    {"market": "KOR", "code": "035420", "name": "NAVER", "theme": "플랫폼/AI"},
]

POSITIVE_NEWS_KEYWORDS = [
    "수주", "계약", "공급", "양산", "실적 개선", "실적개선", "흑자전환",
    "가이던스 상향", "증설", "인수", "합병", "파트너십", "정책 수혜",
    "데이터센터", "ai", "반도체", "전기차", "국책", "대규모",
    "호실적", "영업이익", "매출 증가", "목표가 상향", "기관 매수", "외국인 매수"
]

NEGATIVE_NEWS_KEYWORDS = [
    "유상증자", "전환사채", "cb", "bw", "하한가", "소송", "과징금",
    "실적 부진", "실적부진", "가이던스 하향", "적자", "감자", "상장폐지",
    "횡령", "배임", "리콜", "규제", "조사", "경고", "목표가 하향", "매도 리포트"
]


def load_candidates() -> list[dict]:
    raw = os.getenv("CANDIDATES_JSON", "").strip()
    if not raw:
        return DEFAULT_CANDIDATES
    try:
        data = json.loads(raw)
        if isinstance(data, list) and data:
            return data
    except Exception:
        pass
    return DEFAULT_CANDIDATES


def resolve_mode(mode: str) -> str:
    mode = str(mode or "").strip().lower()
    if mode in ("lunch", "evening", "manual"):
        return mode
    kst = timezone(timedelta(hours=9))
    hour = datetime.now(kst).hour
    return "lunch" if hour < 15 else "evening"


def _cut(text: str, n: int = 68) -> str:
    text = str(text or "").strip()
    return text if len(text) <= n else text[: n - 1] + "…"


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


def build_report(mode: str) -> str:
    resolved_mode = resolve_mode(mode)
    now = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M:%S")
    candidates = load_candidates()

    token = get_access_token()
    analyzed = []

    for item in candidates:
        if str(item.get("market", "")).upper() != "KOR":
            continue

        code = str(item.get("code", "")).strip()
        name = str(item.get("name", code)).strip()
        theme = str(item.get("theme", "")).strip()

        quote = get_domestic_current_price(code=code, token=token)
        daily = get_domestic_daily_chart(code=code, token=token, days=30)
        enriched = enrich_with_indicators({"code": code, "name": name, "theme": theme}, quote, daily)

        news_items = get_news(name, limit=2)
        news_summary = summarize_news(name, news_items)
        news_signal = evaluate_news_trade_signal(news_items, news_summary)

        stage_info = analyze_stage_signals(enriched, quote, daily, news_signal)

        analyzed.append({
            **enriched,
            **stage_info,
            "news_items": news_items,
            "news_summary": news_summary,
            "news_signal": news_signal,
        })

    if not analyzed:
        return f"📊 Signal Forge 리포트\n모드: {resolved_mode}\n시각: {now}\n\n추천 종목 없음"

    analyzed.sort(
        key=lambda x: (
            0 if x["entry_decision"] == "ENTRY" else 1 if x["entry_decision"] == "WAIT" else 2,
            -x["entry_score"],
            -x["total_score"],
        )
    )

    top = analyzed[0]
    second = analyzed[1] if len(analyzed) > 1 else None
    market_news = build_market_news_summary(analyzed)

    title_line = "🔥 오늘 최우선 종목"
    strategy_line = "💡 전략: 제안매수가 근처 접근 후 반등 확인"
    if resolved_mode == "lunch":
        title_line = "🔥 점심 체크 종목"
        strategy_line = "💡 점심 전략: 관심구간 접근 여부와 장중 반등 확인"
    elif resolved_mode == "evening":
        title_line = "🔥 저녁 준비 종목"
        strategy_line = "💡 저녁 전략: 내일 시가와 제안매수가 위치 비교"

    top_name = str(top.get("name", "")).strip() or str(top.get("code", "")).strip()

    lines = [
        "📊 Signal Forge 리포트 [STAGE+ENTRY PATCH]",
        f"모드: {resolved_mode}",
        f"시각: {now}",
        "",
        f"🧭 시장 뉴스 포인트: {market_news}",
        "",
        title_line,
        f"{top_name} ({top['code']})",
        "",
        f"현재가: {int(top['price']):,}원",
        f"전일종가 기준 제안매수가: {int(top['proposed_entry']):,}원",
        f"관심구간: {int(top['entry_zone_low']):,} ~ {int(top['entry_zone_high']):,}원",
        f"손절가: {int(top['stop_loss']):,}원",
        f"목표가1: {int(top['target1']):,}원 / 목표가2: {int(top['target2']):,}원",
        "",
        f"최종단계: {top['stage']}",
        f"진입판정: {top['entry_decision']} (진입점수 {top['entry_score']})",
        f"진입사유: {top['entry_reason']}",
        "",
        f"등락률: {top['change_pct']}%",
        f"거래량비: {top['vol_rate']}%",
        f"RSI: {top['rsi']}",
        f"총점: {top['total_score']}",
        f"매집점수: {top['accumulation_score']} / 돌파점수: {top['breakout_score']} / 리스크점수: {top['risk_score']}",
        f"테마: {top.get('theme', '')}",
        f"뉴스 판정: {top['news_signal']['bias']}",
        f"뉴스 키워드: {top['news_signal']['keyword_summary']}",
        "",
        "세부 신호:",
        f"- 매집: {', '.join(top['accumulation_flags']) if top['accumulation_flags'] else '특이사항 없음'}",
        f"- 돌파: {', '.join(top['breakout_flags']) if top['breakout_flags'] else '특이사항 없음'}",
        f"- 리스크: {', '.join(top['risk_flags']) if top['risk_flags'] else '낮음'}",
        "",
        f"📰 최근 기사 요약: {top['news_summary']}",
        "🗞 최근 기사:",
    ]
    lines.extend(format_news_lines(top.get("news_items", [])))

    if second:
        second_name = str(second.get("name", "")).strip() or str(second.get("code", "")).strip()
        lines += [
            "",
            "➕ 차순위 후보",
            f"{second_name} ({second['code']}) / 단계 {second['stage']} / 진입판정 {second['entry_decision']}",
            f"제안매수가 {int(second['proposed_entry']):,}원 / 점수 {second['entry_score']}",
        ]

    lines += [
        "",
        "제외 기준: 과열 추격, 부정 뉴스, 리스크 과다 종목은 PASS 처리 가능",
        strategy_line,
    ]

    return "\n".join(lines)
