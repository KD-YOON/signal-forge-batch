import os
import httpx


def summarize_news(stock_name: str, news_items: list[dict]) -> str:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()

    if not news_items:
        return "관련 투자 뉴스 부족"

    if not api_key:
        titles = [x.get("title", "").strip() for x in news_items[:2] if x.get("title")]
        return " / ".join(titles) if titles else "관련 투자 뉴스 부족"

    prompt_lines = [
        f"종목명: {stock_name}",
        "아래 뉴스는 주식 투자 관련 기사만 반영해 1문장으로 요약해라.",
        "교육, 공공기관, 행사, 채용, 일반 홍보성 내용은 무시해라.",
        "실적, 수주, 공급, 주가, 증권 리포트, 투자심리 관련 핵심 이슈만 반영해라.",
        "애매하면 '관련 투자 뉴스 부족'이라고 답해라.",
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
        text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        return text or "관련 투자 뉴스 부족"
    except Exception:
        return "관련 투자 뉴스 부족"
