import os
import re

import requests


def _clean_html(text: str) -> str:
    text = str(text or "")
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()


def get_news(query: str, limit: int = 2) -> list[dict]:
    client_id = os.getenv("NAVER_CLIENT_ID", "").strip()
    client_secret = os.getenv("NAVER_CLIENT_SECRET", "").strip()

    if not client_id or not client_secret:
        return []

    url = "https://openapi.naver.com/v1/search/news.json"
    params = {
        "query": query,
        "display": max(1, min(limit, 5)),
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
