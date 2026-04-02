import os
import httpx

def summarize_news(stock_name: str, news_items: list[dict]) -> str:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()

    if not news_items:
        return "관련 뉴스 없음"

    if not api_key:
        return news_items[0].get("title", "뉴스 없음")

    payload = {
        "contents": [
            {"parts": [{"text": str(news_items[:2])}]}
        ]
    }

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"

    with httpx.Client(timeout=30.0) as client:
        resp = client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()

    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception:
        return "요약 실패"
