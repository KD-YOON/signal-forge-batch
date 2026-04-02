import os
import re

import requests


BAD_KEYWORDS = [
    "교육지원청", "지원청", "교육청", "학교", "학생", "교사", "공무원",
    "채용", "행사", "센터", "협약", "복지", "문화원", "박람회", "도서관",
    "프로그램", "설명회", "기관", "연수", "세미나", "수강", "강좌"
]

GOOD_KEYWORDS = [
    "주가", "주식", "실적", "수주", "공급", "계약", "매출", "영업이익",
    "증권", "투자", "목표가", "리포트", "반도체", "AI", "외국인", "기관 매수"
]


def _clean_html(text: str) -> str:
    text = str(text or "")
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()


def _is_bad_news(title: str, desc: str) -> bool:
    text = f"{title} {desc}"
    return any(bad in text for bad in BAD_KEYWORDS)


def _relevance_score(stock_name: str, title: str, desc: str) -> int:
    text = f"{title} {desc}"
    score = 0

    if stock_name and stock_name in text:
        score += 5

    for kw in GOOD_KEYWORDS:
        if kw in text:
            score += 2

    if "주식" in text or "주가" in text:
        score += 2

    return score


def _fetch_news_once(query: str, limit: int = 5) -> list[dict]:
    client_id = os.getenv("NAVER_CLIENT_ID", "").strip()
    client_secret = os.getenv("NAVER_CLIENT_SECRET", "").strip()

    if not client_id or not client_secret:
        return []

    url = "https://openapi.naver.com/v1/search/news.json"
    params = {
        "query": query,
        "display": max(1, min(limit, 10)),
        "sort": "date",
    }
    headers = {
        "X-Naver-Client-Id": client_id,
        "X-Naver-Client-Secret": client_secret,
    }

    resp = requests.get(url, params=params, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    items = data.get("items", [])
    out = []
    for item in items:
        out.append(
            {
                "title": _clean_html(item.get("title", "")),
                "description": _clean_html(item.get("description", "")),
                "link": str(item.get("link", "")).strip(),
            }
        )
    return out


def get_news(stock_name: str, limit: int = 2) -> list[dict]:
    queries = [
        f"{stock_name} 주식",
        f"{stock_name} 실적",
        f"{stock_name} 수주",
    ]

    seen = set()
    ranked = []

    for query in queries:
        for item in _fetch_news_once(query, limit=5):
            title = item.get("title", "")
            desc = item.get("description", "")
            link = item.get("link", "")

            key = link or title
            if not key or key in seen:
                continue
            seen.add(key)

            if _is_bad_news(title, desc):
                continue

            score = _relevance_score(stock_name, title, desc)
            if score < 3:
                continue

            ranked.append({
                **item,
                "relevance_score": score,
            })

    ranked.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)
    return ranked[:limit]
