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
        "너는 한국 주식 단기매매용 뉴스 필터 분석기다.",
        f"종목명: {stock_name}",
        "",
        "[목표]",
        "입력된 기사 중 주가에 직접 영향을 줄 수 있는 투자 정보만 골라 1문장으로 요약한다.",
        "",
        "[반드시 지킬 규칙]",
        "1. 현재 시세를 추정하거나 만들어 쓰지 마라.",
        "2. 기사 내용에 없는 숫자·등락률·날짜를 임의로 쓰지 마라.",
        "3. 교육, 공공기관, 행사, 채용, 홍보성 기사, 일반 사회뉴스는 무시하라.",
        "4. 실적, 수주, 공급, 계약, 가이던스, 증권사 리포트, 투자심리, 정책 수혜만 반영하라.",
        "5. 기사들이 서로 애매하거나 투자 정보가 약하면 정확히 '관련 투자 뉴스 부족'이라고 답하라.",
        "6. 한 문장, 70자 안팎, 존댓말 없이 간결하게 써라.",
        "7. 출력은 문장 1개만, 불릿/번호/설명 추가 금지.",
        "",
        "[좋은 출력 예시]",
        "AI 서버용 반도체 수요 기대와 증권사 긍정 평가가 투자심리를 지지",
        "대규모 공급계약과 실적 개선 기대가 주가 모멘텀 요인으로 부각",
        "관련 투자 뉴스 부족",
        "",
        "[기사 목록]",
    ]

    for i, item in enumerate(news_items[:4], start=1):
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
        text = text.replace("\n", " ").strip()
        if not text:
            return "관련 투자 뉴스 부족"
        if len(text) > 90:
            text = text[:89].rstrip() + "…"
        return text
    except Exception:
        return "관련 투자 뉴스 부족"
