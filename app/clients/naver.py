import os
import requests

def get_news(query: str, limit: int = 2) -> list[dict]:
    client_id = os.getenv("NAVER_CLIENT_ID", "").strip()
    client_secret = os.getenv("NAVER_CLIENT_SECRET", "").strip()

    if not client_id or not client_secret:
        return []

    url = "https://openapi.naver.com/v1/search/news.json"
    params = {"query": query, "display": limit, "sort": "date"}
    headers = {
        "X-Naver-Client-Id": client_id,
        "X-Naver-Client-Secret": client_secret,
    }

    resp = requests.get(url, params=params, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    return data.get("items", [])
