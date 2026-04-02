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
    flags: list[str] = []

    if positive_hits:
        score += min(12, len(positive_hits) * 4)
        flags.append("뉴스 호재")
    if negative_hits:
        score -= min(18, len(negative_hits) * 6)
        flags.append("뉴스 악재")

    if "관련 투자 뉴스 부족" in text:
        flags.append("뉴스 부족")

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
        "flags": flags,
        "positive_hits": positive_hits[:3],
        "negative_hits": negative_hits[:3],
        "keyword_summary": " / ".join(keyword_summary_parts) if keyword_summary_parts else "특이 키워드 없음",
    }


def score_item(item: dict, news_signal: dict) -> tuple[int, list[str]]:
    score = 0
    reasons = []

    change_pct = float(item.get("change_pct", 0) or 0)
    vol_rate = float(item.get("vol_rate", 0) or 0)
    rsi = float(item.get("rsi", 50) or 50)

    if 120 <= vol_rate < 160:
        score += 20
        reasons.append("거래량 증가")
    elif 160 <= vol_rate < 240:
        score += 26
        reasons.append("거래량 강세")
    elif 240 <= vol_rate < 320:
        score += 10
        reasons.append("거래량 과열 주의")
    elif vol_rate >= 320:
        score -= 8
        reasons.append("거래량 과열 경계")

    if 48 <= rsi <= 65:
        score += 26
        reasons.append("RSI 양호")
    elif 65 < rsi <= 75:
        score += 8
        reasons.append("RSI 높은 편")
    elif 35 <= rsi < 48:
        score += 3
        reasons.append("RSI 보통 이하")
    elif 25 <= rsi < 35:
        score -= 10
        reasons.append("RSI 약세권")
    elif rsi < 25:
        score -= 18
        reasons.append("과매도 경계")
    elif rsi > 75:
        score -= 12
        reasons.append("RSI 과열")

    if 0.3 <= change_pct <= 3.5:
        score += 24
        reasons.append("무난한 상승 흐름")
    elif 3.5 < change_pct <= 6.0:
        score += 10
        reasons.append("상승 강도 양호")
    elif 6.0 < change_pct <= 9.0:
        score -= 12
        reasons.append("단기 추격 위험")
    elif -2.0 <= change_pct < 0.3:
        score -= 4
        reasons.append("보합/약세")
    elif -4.0 <= change_pct < -2.0:
        score -= 18
        reasons.append("하락 부담")
    elif -7.0 <= change_pct < -4.0:
        score -= 35
        reasons.append("급락 경계")
    elif change_pct < -7.0:
        score -= 60
        reasons.append("급락 제외 수준")

    theme = str(item.get("theme", "") or "")
    if "AI" in theme or "반도체" in theme:
        score += 10
        reasons.append("테마 우위")
    elif theme:
        score += 4
        reasons.append("테마 보유")

    news_score = int(news_signal.get("score", 0) or 0)
    score += news_score

    bias = str(news_signal.get("bias", "NEUTRAL"))
    if bias == "POSITIVE":
        reasons.append("뉴스 우호적")
    elif bias == "NEGATIVE":
        reasons.append("뉴스 부담")

    return score, reasons


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
    enriched_items = []

    for item in candidates:
        if str(item.get("market", "")).upper() != "KOR":
            continue

        code = str(item.get("code", "")).strip()
        name = str(item.get("name", code)).strip()
        theme = str(item.get("theme", "")).strip()

        quote = get_domestic_current_price(code=code, token=token)
        daily = get_domestic_daily_chart(code=code, token=token, days=30)

        enriched = enrich_with_indicators(
            {"code": code, "name": name, "theme": theme},
            quote,
            daily,
        )

        news_items = get_news(name, limit=2)
        news_summary = summarize_news(name, news_items)
        news_signal = evaluate_news_trade_signal(news_items, news_summary)
        score, reasons = score_item(enriched, news_signal)

        # 너무 급한 급락주는 추천 후보에서 제외
        if float(enriched.get("change_pct", 0) or 0) < -7.0:
            continue

        enriched_items.append(
            {
                **enriched,
                "score": score,
                "reasons": reasons,
                "news_items": news_items,
                "news_summary": news_summary,
                "news_signal": news_signal,
            }
        )

    if not enriched_items:
        return f"📊 Signal Forge 리포트\n모드: {resolved_mode}\n시각: {now}\n\n추천 종목 없음"

    enriched_items.sort(key=lambda x: x["score"], reverse=True)
    top = enriched_items[0]
    second = enriched_items[1] if len(enriched_items) > 1 else None

    top_name = str(top.get("name", "")).strip() or str(top.get("code", "")).strip()

    strategy_line = "💡 전략: 눌림 또는 초반 반등 확인 후 접근"
    title_line = "🔥 오늘 최우선 종목"

    if resolved_mode == "lunch":
        strategy_line = "💡 점심 전략: 장중 눌림/반등 체크, 추격 매수는 보수적으로"
        title_line = "🔥 점심 체크 종목"
    elif resolved_mode == "evening":
        strategy_line = "💡 저녁 전략: 내일 시가/초반 흐름 관찰 후 접근"
        title_line = "🔥 저녁 준비 종목"

    market_news = build_market_news_summary(enriched_items)

    lines = [
        "📊 Signal Forge 리포트",
        f"모드: {resolved_mode}",
        f"시각: {now}",
        "",
        f"🧭 시장 뉴스 포인트: {market_news}",
        "",
        title_line,
        f"{top_name} ({top['code']})",
        "",
        f"현재가: {int(top['price']):,}원",
        f"등락률: {top['change_pct']}%",
        f"거래량비: {top['vol_rate']}%",
        f"RSI: {top['rsi']}",
        f"점수: {top['score']}",
        f"테마: {top.get('theme', '')}",
        f"뉴스 판정: {top['news_signal']['bias']}",
        f"뉴스 키워드: {top['news_signal']['keyword_summary']}",
        "",
        "선정 사유:",
    ]

    for reason in top["reasons"]:
        lines.append(f"- {reason}")

    lines += [
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
            f"{second_name} ({second['code']}) / 점수 {second['score']}",
            f"뉴스 판정: {second['news_signal']['bias']} / 요약: {second['news_summary']}",
        ]

    lines += [
        "",
        strategy_line,
    ]

    return "\n".join(lines)
