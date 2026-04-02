import os
from datetime import datetime

import requests


def send_telegram(text: str):
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()

    if not token or not chat_id:
        raise RuntimeError("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set")

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    r = requests.post(
        url,
        data={"chat_id": chat_id, "text": text},
        timeout=30,
    )
    r.raise_for_status()
    print("telegram ok:", r.text[:200])


def build_message(mode: str) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"✅ Signal Forge Cron 실행 성공\n모드: {mode}\n시간: {now}"


def main():
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else "manual"
    msg = build_message(mode)
    send_telegram(msg)


if __name__ == "__main__":
    main()
