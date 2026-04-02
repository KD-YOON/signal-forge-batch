import os
from datetime import datetime

import requests


def send_telegram(text: str):
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()

    if not token or not chat_id:
        raise RuntimeError("텔레그램 ENV 누락")

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    resp = requests.post(
        url,
        data={"chat_id": chat_id, "text": text},
        timeout=30,
    )
    resp.raise_for_status()
    print("telegram ok:", resp.text[:200])


def get_candidate_stocks():
    """
    지금은 하드코딩 샘플 데이터.
    다음 단계에서 KIS/뉴스/Gemini로 교체할 자리.
    """
    return [
        {
            "name": "삼성전자",
            "code": "005930",
            "change_pct": 1.8,
            "volume_rate": 142,
            "rsi": 56,
            "theme": "반도체 대형주",
        },
        {
            "name": "SK하이닉스",
            "code": "000660",
            "change_pct": 2.9,
            "volume_rate": 168,
            "rsi": 61,
            "theme": "AI 반도체",
        },
        {
            "name": "NAVER",
            "code": "035420",
            "change_pct": 0.9,
            "volume_rate": 121,
            "rsi": 52,
            "theme": "플랫폼/AI",
        },
    ]


def score_stock(item: dict) -> tuple[int, list[str]]:
    score = 0
    reasons = []

    change_pct = float(item.get("change_pct", 0))
    volume_rate = float(item.get("volume_rate", 0))
    rsi = float(item.get("rsi", 0))

    # 1) 거래량
    if 120 <= volume_rate < 160:
        score += 25
        reasons.append("거래량 증가")
    elif 160 <= volume_rate < 220:
        score += 30
        reasons.append("거래량 강세")
    elif volume_rate >= 220:
        score += 18
        reasons.append("거래량 과열 가능")

    # 2) RSI
    if 50 <= rsi <= 65:
        score += 30
        reasons.append("RSI 양호")
    elif 45 <= rsi < 50:
        score += 18
        reasons.append("RSI 반등 초입")
    elif 65 < rsi <= 75:
        score += 12
        reasons.append("RSI 높음")
    elif rsi > 75:
        score -= 10
        reasons.append("RSI 과열")

    # 3) 등락률
    if 0.5 <= change_pct <= 3.5:
        score += 25
        reasons.append("무난한 상승 흐름")
    elif 3.5 < change_pct <= 6.0:
        score += 12
        reasons.append("상승 강함")
    elif change_pct > 6.0:
        score -= 12
        reasons.append("단기 추격 위험")
    elif change_pct < -2.0:
        score -= 10
        reasons.append("약세")

    # 4) 테마 가산
    theme = str(item.get("theme", ""))
    if "AI" in theme or "반도체" in theme:
        score += 10
        reasons.append("테마 우위")

    return score, reasons


def pick_top_stock(candidates: list[dict]) -> dict:
    ranked = []

    for item in candidates:
        score, reasons = score_stock(item)
        ranked.append({
            **item,
            "score": score,
            "reasons": reasons,
        })

    ranked.sort(key=lambda x: x["score"], reverse=True)
    return ranked[0] if ranked else {}


def build_message(mode: str) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    candidates = get_candidate_stocks()
    top = pick_top_stock(candidates)

    if not top:
        return f"📊 Signal Forge 리포트\n모드: {mode}\n시각: {now}\n\n추천 종목 없음"

    lines = [
        "📊 Signal Forge 리포트",
        f"모드: {mode}",
        f"시각: {now}",
        "",
        "🔥 오늘 최우선 종목",
        f"{top['name']} ({top['code']})",
        "",
        f"점수: {top['score']}",
        f"등락률: {top['change_pct']}%",
        f"거래량비: {top['volume_rate']}%",
        f"RSI: {top['rsi']}",
        f"테마: {top['theme']}",
        "",
        "선정 사유:",
    ]

    for reason in top["reasons"]:
        lines.append(f"- {reason}")

    lines += [
        "",
        "💡 전략: 눌림 또는 초반 반등 확인 후 접근",
    ]

    return "\n".join(lines)


def main():
    import sys

    mode = sys.argv[1] if len(sys.argv) > 1 else "manual"
    text = build_message(mode)
    send_telegram(text)


if __name__ == "__main__":
    main()
