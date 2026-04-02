import json
import os
from datetime import datetime, timedelta, timezone

from clients.gemini import summarize_news
from clients.kis import (
    enrich_with_indicators,
    get_access_token,
    get_domestic_current_price,
    get_domestic_daily_chart,
)
from clients.naver import get_news


DEFAULT_CANDIDATES = [
    {"market": "KOR", "code": "005930", "name": "삼성전자", "theme": "반도체 대형주"},
    {"market": "KOR", "code": "000660", "name": "SK하이닉스", "theme": "AI 반도체"},
    {"market": "KOR", "code": "035420", "name": "NAVER", "theme": "플랫폼/AI"},
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


def score_item(item: dict) -> tuple[int, list[str]]:
    score = 0
    reasons = []

    change_pct = float(item.get("change_pct", 0) or 0)
    vol_rate = float(item.get("vol_rate", 0) or 0)
    rsi = float(item.get("rsi", 50) or 50)

    if 120 <= vol_rate < 160:
        score += 25
        reasons.append("거래량 증가")
    elif 160 <= vol_rate < 240:
        score += 30
        reasons.append("거래량 강세")
    elif vol_rate >= 240:
        score += 15
        reasons.append("거래량 과열 가능")

    if 48 <= rsi <= 65:
        score += 30
        reasons.append("RSI 양호")
    elif 65 < rsi <= 75:
        score += 12
        reasons.append("RSI 높은 편")
    elif rsi > 75:
        score -= 10
        reasons.append("RSI 과열")

    if 0.3 <= change_pct <= 3.5:
        score += 25
        reasons.append("무난한 상승 흐름")
    elif 3.5 < change_pct <= 6.0:
        score += 12
        reasons.append("상승 강도 양호")
    elif change_pct > 6.0:
        score -= 10
        reasons.append("단기 추격 위험")
    elif change_pct < -2.0:
        score -= 8
        reasons.append("약세")

    theme = str(item.get("theme", "") or "")
    if "AI" in theme or "반도체" in theme:
        score += 10
        reasons.append("테마 우위")

    return score, reasons


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
        score, reasons = score_item(enriched)

        enriched_items.append(
            {
                **enriched,
                "score": score,
                "reasons": reasons,
                "news_summary": news_summary,
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

    lines = [
        "📊 Signal Forge 리포트",
        f"모드: {resolved_mode}",
        f"시각: {now}",
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
        "",
        "선정 사유:",
    ]

    for reason in top["reasons"]:
        lines.append(f"- {reason}")

    lines += [
        "",
        f"📰 뉴스 요약: {top['news_summary']}",
    ]

    if second:
        second_name = str(second.get("name", "")).strip() or str(second.get("code", "")).strip()
        lines += [
            "",
            "➕ 차순위 후보",
            f"{second_name} ({second['code']}) / 점수 {second['score']}",
        ]

    lines += [
        "",
        strategy_line,
    ]

    return "\n".join(lines)
