# === app/services/candidates.py START ===
from __future__ import annotations

import json
import os

from app.clients.kis import get_access_token, get_domestic_volume_rank_candidates


DEFAULT_CANDIDATES = [
    {"market": "KOR", "code": "005930", "name": "삼성전자", "theme": "반도체 대형주", "source": "DEFAULT", "rank": 9001},
    {"market": "KOR", "code": "000660", "name": "SK하이닉스", "theme": "AI 반도체", "source": "DEFAULT", "rank": 9002},
    {"market": "KOR", "code": "035420", "name": "NAVER", "theme": "플랫폼/AI", "source": "DEFAULT", "rank": 9003},
    {"market": "US", "code": "NVDA", "name": "NVIDIA", "theme": "AI 반도체", "source": "DEFAULT", "rank": 9101},
    {"market": "US", "code": "TSLA", "name": "Tesla", "theme": "전기차", "source": "DEFAULT", "rank": 9102},
    {"market": "US", "code": "MSFT", "name": "Microsoft", "theme": "플랫폼/AI", "source": "DEFAULT", "rank": 9103},
]


def _normalize_market(value: str) -> str:
    market = str(value or "KOR").upper().strip()
    return market if market in {"KOR", "US"} else "KOR"


def _normalize_code(code: str, market: str = "KOR") -> str:
    market = _normalize_market(market)

    if market == "US":
        raw = str(code or "").strip().upper()
        return "".join(ch for ch in raw if ch.isalnum())

    raw = "".join(ch for ch in str(code or "") if ch.isdigit())
    return raw.zfill(6) if raw else ""


def _parse_json_env(name: str) -> list[dict]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return data
    except Exception:
        return []
    return []


def load_default_candidates() -> list[dict]:
    return list(DEFAULT_CANDIDATES)


def load_watchlist_candidates() -> list[dict]:
    rows = _parse_json_env("WATCHLIST_JSON")
    out = []

    for idx, row in enumerate(rows, start=1):
        market = _normalize_market(row.get("market", "KOR"))
        code = _normalize_code(row.get("code", ""), market)
        if not code:
            continue

        use_yn = str(row.get("use", row.get("useYn", "Y"))).upper().strip()
        if use_yn != "Y":
            continue

        out.append(
            {
                "market": market,
                "code": code,
                "name": str(row.get("name", code)).strip() or code,
                "theme": str(row.get("theme", "")).strip(),
                "source": "WATCHLIST",
                "rank": 1000 + idx,
                "memo": str(row.get("memo", "")).strip(),
            }
        )

    return out


def load_auto_candidates() -> list[dict]:
    rows = _parse_json_env("AUTO_CANDIDATES_JSON")
    out = []

    for idx, row in enumerate(rows, start=1):
        market = _normalize_market(row.get("market", "KOR"))
        code = _normalize_code(row.get("code", ""), market)
        if not code:
            continue

        out.append(
            {
                "market": market,
                "code": code,
                "name": str(row.get("name", code)).strip() or code,
                "theme": str(row.get("theme", "")).strip(),
                "source": "AUTO",
                "rank": 2000 + idx,
                "memo": str(row.get("memo", "")).strip(),
            }
        )

    return out


def load_volume_rank_candidates() -> list[dict]:
    try:
        token = get_access_token()
        limit = int(os.getenv("MAX_VOLUME_RANK_FETCH", "40") or "40")
        return get_domestic_volume_rank_candidates(token=token, limit=limit)
    except Exception:
        return []


def merge_candidate_lists(*lists: list[dict]) -> list[dict]:
    merged: dict[str, dict] = {}

    for candidate_list in lists:
        for idx, item in enumerate(candidate_list or [], start=1):
            market = _normalize_market(item.get("market", "KOR"))
            code = _normalize_code(item.get("code", ""), market)
            if not code:
                continue

            key = f"{market}:{code}"
            incoming_rank = int(item.get("rank", idx) or idx)

            if key not in merged:
                merged[key] = {
                    **item,
                    "market": market,
                    "code": code,
                    "_rank": incoming_rank,
                }
                continue

            prev = merged[key]
            prev_source = str(prev.get("source", "")).strip()
            new_source = str(item.get("source", "")).strip()

            source_joined = "+".join([s for s in [prev_source, new_source] if s])

            merged[key] = {
                **prev,
                **item,
                "market": market,
                "code": code,
                "name": str(item.get("name") or prev.get("name") or code).strip(),
                "theme": str(item.get("theme") or prev.get("theme") or "").strip(),
                "memo": str(item.get("memo") or prev.get("memo") or "").strip(),
                "source": source_joined,
                "_rank": min(int(prev.get("_rank", 999999)), incoming_rank),
            }

    return [
        {k: v for k, v in row.items() if k != "_rank"}
        for row in sorted(merged.values(), key=lambda x: int(x.get("_rank", 999999)))
    ]


def get_combined_candidates() -> list[dict]:
    """
    우선순위:
    1) 거래량 랭킹 후보(KOR 전용)
    2) WATCHLIST
    3) AUTO_CANDIDATES_JSON
    4) DEFAULT fallback
    """
    volume_rows = load_volume_rank_candidates()
    watchlist = load_watchlist_candidates()
    auto_rows = load_auto_candidates()
    defaults = load_default_candidates()

    merged = merge_candidate_lists(volume_rows, watchlist, auto_rows, defaults)

    analyze_limit = int(os.getenv("MAX_TOTAL_ANALYZE", "20") or "20")
    return merged[: max(1, analyze_limit)]
# === app/services/candidates.py END ===
