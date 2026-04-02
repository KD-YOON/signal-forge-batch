import os
import httpx


def summarize_news(stock_name: str, news_items: list[dict]) -> str:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()

    if not news_items:
        return "관련 뉴스 없음"

    if not api_key:
        titles = [x.get("title", "").strip() for x in news_items[:2] if x.get("title")]
        return " / ".join(titles) if titles else "관련 뉴스 수집됨"

    prompt_lines = [
        f"종목명: {stock_name}",
        "아래 뉴스 제목과 설명을 1문장으로 요약해줘.",
        "투자판단 문구 대신 핵심 이슈만 담아줘.",
    ]

    for i, item in enumerate(news_items[:3], start=1):
        prompt_lines.append(f"{i}. 제목: {item.get('title', '')}")
        prompt_lines.append(f"   설명: {item.get('description', '')}")

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": "\n".join(prompt_lines)}
                ]
            }
        ]
    }

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"

    with httpx.Client(timeout=30.0) as client:
        resp = client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()

    try:
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception:
        titles = [x.get("title", "").strip() for x in news_items[:2] if x.get("title")]
        return " / ".join(titles) if titles else "뉴스 요약 실패"
