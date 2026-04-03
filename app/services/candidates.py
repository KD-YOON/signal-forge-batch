from __future__ import annotations

import json
import os


DEFAULT_CANDIDATES = [
    {"market": "KOR", "code": "005930", "name": "삼성전자", "theme": "반도체 대형주", "source": "DEFAULT", "rank": 1},
    {"market": "KOR", "code": "000660", "name": "SK하이닉스", "theme": "AI 반도체", "source": "DEFAULT", "rank": 2},
    {"market": "KOR", "code": "035420", "name": "NAVER", "theme": "플랫폼/AI", "source": "DEFAULT", "rank": 3},
]


def _normalize_code(code: str) -> str:
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
        market = str(row.get("market", "KOR")).upper().strip()
        if market != "KOR":
            continue
        code = _normalize_code(row.get("code", ""))
        if not code:
            continue
        use_yn = str(row.get("use", row.get("useYn", "Y"))).upper().strip()
        if use_yn != "Y":
            continue
        out.append({
            "market": "KOR",
            "code": code,
            "name": str(row.get("name", code)).strip(),
            "theme": str(row.get("theme", "")).strip(),
            "source": "WATCHLIST",
            "rank": idx,
            "memo": str(row.get("memo", "")).strip(),
        })
    return out


def load_auto_candidates() -> list[dict]:
    rows = _parse_json_env("AUTO_CANDIDATES_JSON")
    out = []
    for idx, row in enumerate(rows, start=1):
        market = str(row.get("market", "KOR")).upper().strip()
        if market != "KOR":
            continue
        code = _normalize_code(row.get("code", ""))
        if not code:
            continue
        out.append({
            "market": "KOR",
            "code": code,
            "name": str(row.get("name", code)).strip(),
            "theme": str(row.get("theme", "")).strip(),
            "source": "AUTO",
            "rank": idx,
            "memo": str(row.get("memo", "")).strip(),
        })
    return out


def merge_candidate_lists(*lists: list[dict]) -> list[dict]:
    merged = {}
    for candidate_list in lists:
        for idx, item in enumerate(candidate_list or [], start=1):
            code = _normalize_code(item.get("code", ""))
            if not code:
                continue

            incoming_rank = int(item.get("rank", idx))
            if code not in merged:
                merged[code] = {
                    **item,
                    "code": code,
                    "_rank": incoming_rank,
                }
                continue

            prev = merged[code]
            sources = [str(prev.get("source", "")).strip(), str(item.get("source", "")).strip()]
            merged[code] = {
                **prev,
                **item,
                "code": code,
                "name": str(item.get("name") or prev.get("name") or code).strip(),
                "theme": str(item.get("theme") or prev.get("theme") or "").strip(),
                "source": "+".join([s for s in sources if s]),
                "_rank": min(int(prev.get("_rank", 999)), incoming_rank),
            }

    return [
        {k: v for k, v in row.items() if k != "_rank"}
        for row in sorted(merged.values(), key=lambda x: int(x.get("_rank", 999)))
    ]


def get_combined_candidates() -> list[dict]:
    defaults = load_default_candidates()
    watchlist = load_watchlist_candidates()
    auto_rows = load_auto_candidates()
    return merge_candidate_lists(watchlist, auto_rows, defaults)
