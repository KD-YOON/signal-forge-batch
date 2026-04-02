import os
import re

from app.utils import request_with_retry

BAD_KEYWORDS = [
    "교육지원청", "지원청", "교육청", "학교", "학생", "교사", "공무원",
    "채용", "행사", "센터", "협약", "복지", "문화원", "박람회", "도서관",
    "프로그램", "설명회", "기관", "연수", "세미나", "수강", "강좌",
    "공공", "지자체", "축제", "봉사", "장학", "평생교육", "수련회",
    "아카데미", "캠페인", "기념식", "출범식", "간담회", "공연", "전시",
    "입학", "졸업", "특강", "봉사활동", "체험", "홍보관", "후원"
]

GOOD_KEYWORDS = [
    "주가", "주식", "실적", "수주", "공급", "계약", "매출", "영업이익",
    "증권", "투자", "목표가", "리포트", "반도체", "ai", "외국인", "기관 매수",
    "상승", "하락", "호실적", "어닝", "가이던스", "매수", "매도",
    "흑자전환", "적자축소", "턴어라운드", "신제품", "양산", "데이터센터",
    "정책 수혜", "수혜", "모멘텀", "밸류에이션", "실적 개선", "증설"
]


def _clean_html(text: str) -> str:
    text = str(text or "")
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&quot;", '"').replace("&apos;", "'").replace("&amp;", "&")
    return text.strip()


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def _contains_bad_keyword(text: str) -> bool:
    lowered = _normalize_text(text)
    return any(_normalize_text(bad) in lowered for bad in BAD_KEYWORDS)


def _is_bad_news(title: str, desc: str) -> bool:
    text = f"{title} {desc}"
    return _contains_bad_keyword(text)


def _stock_name_variants(stock_name: str) -> list[str]:
    raw = str(stock_name or "").strip()
    variants = {raw, raw.lower()}

    compact = re.sub(r"\s+", "", raw)
    if compact:
        variants.add(compact)
        variants.add(compact.lower())

    if raw.upper() == "NAVER":
        variants.update(["네이버", "naver"])
    if raw.upper() == "SK하이닉스":
        variants.update(["하이닉스", "sk hynix", "skhynix"])
    if raw == "삼성전자":
        variants.update(["삼성", "samsung electronics"])

    return [v for v in variants if v]


def _relevance_score(stock_name: str, title: str, desc: str) -> int:
    title_n = _normalize_text(title)
    desc_n = _normalize_text(desc)
    text = f"{title_n} {desc_n}"

    score = 0
    variants = _stock_name_variants(stock_name)

    exact_name_in_title = any(v.lower() in title_n for v in variants)
    exact_name_in_desc = any(v.lower() in desc_n for v in variants)

    if exact_name_in_title:
        score += 10
    elif exact_name_in_desc:
        score += 6

    for kw in GOOD_KEYWORDS:
        kw_n = _normalize_text(kw)
        if kw_n in title_n:
            score += 4
        elif kw_n in desc_n:
            score += 2

    if "주식" in text or "주가" in text or "증권" in text:
        score += 3

    if "목표가" in text or "리포트" in text:
        score += 3

    if "실적" in text or "영업이익" in text or "매출" in text:
        score += 3

    if "계약" in text or "수주" in text or "공급" in text:
        score += 4

    if _contains_bad_keyword(text):
        score -= 20

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

    resp = request_with_retry("GET", url, params=params, headers=headers)
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
    stock_name = str(stock_name or "").strip()
    if not stock_name:
        return []

    queries = [
        f"{stock_name} 주식 주가 증권",
        f"{stock_name} 실적 영업이익 매출 증권",
        f"{stock_name} 수주 공급 계약 투자",
        f"{stock_name} 목표가 리포트 증권",
    ]

    seen = set()
    ranked = []

    for query in queries:
        for item in _fetch_news_once(query, limit=6):
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

            # 약한 기사 제거
            if score < 8:
                continue

            ranked.append(
                {
                    **item,
                    "relevance_score": score,
                }
            )

    ranked.sort(
        key=lambda x: (
            x.get("relevance_score", 0),
            len(x.get("title", "")),
        ),
        reverse=True,
    )
    return ranked[:limit]
