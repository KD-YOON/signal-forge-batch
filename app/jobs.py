import os
from datetime import datetime

import requests


def send_telegram(text: str):
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()

    if not token or not chat_id:
        raise RuntimeError("텔레그램 ENV 누락")

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    r = requests.post(
        url,
        data={"chat_id": chat_id, "text": text},
        timeout=30,
    )
    r.raise_for_status()
    print("telegram ok")


def build_message(mode: str) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 👉 지금은 하드코딩 (다음 단계에서 자동화)
    stocks = [
        {"name": "삼성전자", "code": "005930", "reason": "거래량 증가 + 반등 시그널"},
        {"name": "SK하이닉스", "code": "000660", "reason": "AI 반도체 수급 지속"}
    ]

    lines = [
        "📊 Signal Forge 리포트",
        f"모드: {mode}",
        f"시각: {now}",
        "",
        "🔥 오늘 주목 종목",
    ]

    for i, s in enumerate(stocks, 1):
        lines.append(f"{i}. {s['name']} ({s['code']})")
        lines.append(f"   → {s['reason']}")

    lines += [
        "",
        "💡 전략: 눌림 후 반등 확인 시 접근",
    ]

    return "\n".join(lines)


def main():
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else "manual"

    text = build_message(mode)
    send_telegram(text)


if __name__ == "__main__":
    main()
