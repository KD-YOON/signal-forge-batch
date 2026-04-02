import os

from app.utils import request_with_retry


def send_telegram(text: str) -> str:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()

    if not token or not chat_id:
        raise RuntimeError("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set")

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    resp = request_with_retry(
        "POST",
        url,
        data={"chat_id": chat_id, "text": text},
    )
    return resp.text[:300]
