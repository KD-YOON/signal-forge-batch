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
    elif 35 <= rsi < 48:
        score += 16
        reasons.append("RSI 반등 대기권")
    elif 65 < rsi <= 75:
        score += 12
        reasons.append("RSI 높은 편")
    elif rsi > 75:
        score -= 10
        reasons.append("RSI 과열")
    elif rsi < 35:
        score -= 8
        reasons.append("RSI 과매도")

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


def derive_entry_plan(item: dict) -> dict:
    prev_close = float(item.get("prev_close", 0) or 0)
    current_price = float(item.get("price", 0) or 0)
    day_low = float(item.get("low", 0) or 0)
    day_open = float(item.get("open", 0) or 0)
    rsi = float(item.get("rsi", 50) or 50)
    rebound = float(item.get("rebound_from_low", 0) or 0)

    suggested_buy = round(prev_close * 0.95, 2) if prev_close > 0 else 0.0
    zone_low = round(suggested_buy * 0.99, 2) if suggested_buy > 0 else 0.0
    zone_high = round(suggested_buy * 1.01, 2) if suggested_buy > 0 else 0.0

    in_zone = zone_low <= current_price <= zone_high if zone_low > 0 else False
    above_open = current_price > day_open if day_open > 0 else False

    action = "관망"
    reason = "아직 명확한 진입 구간 아님"

    if rsi < 35 and rebound < 1.0:
        action = "대기"
        reason = "과매도 구간이나 반등 확인 부족"
    elif in_zone and rebound >= 1.0:
        action = "진입 검토"
        reason = "관심구간 진입 후 저점 대비 반등 확인"
    elif current_price <= suggested_buy and rebound >= 1.5 and above_open:
        action = "진입 검토"
        reason = "제안매수가 부근 + 반등 강도 확인"
    elif rebound >= 2.0 and above_open and rsi >= 35:
        action = "관찰 강화"
        reason = "저점 반등 진행 중, 추격보다 눌림 확인 필요"

    return {
        "prev_close": prev_close,
        "suggested_buy": suggested_buy,
        "zone_low": zone_low,
        "zone_high": zone_high,
        "rebound_from_low": rebound,
        "entry_action": action,
        "entry_reason": reason,
    }


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

        entry_plan = derive_entry_plan(enriched)
        news_items = get_news(name, limit=2)
        news_summary = summarize_news(name, news_items)
        score, reasons = score_item(enriched)

        enriched_items.append(
            {
                **enriched,
                **entry_plan,
                "score": score,
                "reasons": reasons,
                "news_summary": news_summary,
            }
        )

    if not enriched_items:
        return f"📊 Render Signal Forge 리포트\n모드: {resolved_mode}\n시각: {now}\n\n추천 종목 없음"

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
        "📊 Render Signal Forge 리포트",
        f"모드: {resolved_mode}",
        f"시각: {now}",
        "",
        title_line,
        f"{top_name} ({top['code']})",
        "",
        f"현재가: {int(top['price']):,}원",
        f"전일종가: {int(top['prev_close']):,}원" if top['prev_close'] else "전일종가: -",
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
        "",
        "📍 Render 진입 판단",
        f"- 제안매수가: {int(top['suggested_buy']):,}원" if top['suggested_buy'] else "- 제안매수가: -",
        f"- 관심구간: {int(top['zone_low']):,} ~ {int(top['zone_high']):,}원" if top['zone_low'] else "- 관심구간: -",
        f"- 저점대비 반등률: {top['rebound_from_low']}%",
        f"- 판단: {top['entry_action']}",
        f"- 사유: {top['entry_reason']}",
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
