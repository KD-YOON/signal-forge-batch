from __future__ import annotations

import os
from datetime import datetime
from statistics import mean

from app.utils import request_with_retry

DEFAULT_BASE_URL = "https://openapi.koreainvestment.com:9443"


def _get_env(name: str, required: bool = True, default: str = "") -> str:
    value = os.getenv(name, default).strip()
    if required and not value:
        raise RuntimeError(f"{name} not set")
    return value


def get_access_token() -> str:
    app_key = _get_env("KIS_APP_KEY")
    app_secret = _get_env("KIS_APP_SECRET")
    base_url = _get_env("KIS_BASE_URL", required=False, default=DEFAULT_BASE_URL)

    url = f"{base_url}/oauth2/tokenP"
    payload = {
        "grant_type": "client_credentials",
        "appkey": app_key,
        "appsecret": app_secret,
    }

    print(
        "[KIS DEBUG] token request",
        {
            "base_url": base_url,
            "app_key_prefix": app_key[:6] if app_key else "",
            "app_secret_prefix": app_secret[:6] if app_secret else "",
        },
    )

    resp = request_with_retry("POST", url, json=payload)
    data = resp.json()

    print("[KIS DEBUG] token response keys", list(data.keys()) if isinstance(data, dict) else type(data))

    token = data.get("access_token", "")
    if not token:
        raise RuntimeError(f"KIS token error: {data}")
    return token


def _headers(token: str, tr_id: str) -> dict:
    return {
        "content-type": "application/json",
        "authorization": f"Bearer {token}",
        "appkey": _get_env("KIS_APP_KEY"),
        "appsecret": _get_env("KIS_APP_SECRET"),
        "tr_id": tr_id,
    }


def _normalize_code(code: str) -> str:
    raw = "".join(ch for ch in str(code or "") if ch.isdigit())
    return raw.zfill(6)


def get_domestic_current_price(code: str, token: str) -> dict:
    base_url = _get_env("KIS_BASE_URL", required=False, default=DEFAULT_BASE_URL)
    url = f"{base_url}/uapi/domestic-stock/v1/quotations/inquire-price"
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": _normalize_code(code),
    }

    resp = request_with_retry(
        "GET",
        url,
        headers=_headers(token, "FHKST01010100"),
        params=params,
    )
    data = resp.json()
    out = data.get("output", {})

    kis_name = (
        str(out.get("hts_kor_isnm", "") or "").strip()
        or str(out.get("prdt_name", "") or "").strip()
        or str(out.get("bstp_kor_isnm", "") or "").strip()
    )

    return {
        "code": _normalize_code(code),
        "price": float(out.get("stck_prpr", 0) or 0),
        "open": float(out.get("stck_oprc", 0) or 0),
        "high": float(out.get("stck_hgpr", 0) or 0),
        "low": float(out.get("stck_lwpr", 0) or 0),
        "change_pct": float(out.get("prdy_ctrt", 0) or 0),
        "volume": float(out.get("acml_vol", 0) or 0),
        "prev_close": float(out.get("stck_sdpr", 0) or 0),
        "kis_name": kis_name,
    }


def get_domestic_daily_chart(code: str, token: str, days: int = 30) -> list[dict]:
    base_url = _get_env("KIS_BASE_URL", required=False, default=DEFAULT_BASE_URL)
    url = f"{base_url}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
    today = datetime.now().strftime("%Y%m%d")

    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": _normalize_code(code),
        "FID_INPUT_DATE_1": "20240101",
        "FID_INPUT_DATE_2": today,
        "FID_PERIOD_DIV_CODE": "D",
        "FID_ORG_ADJ_PRC": "0",
    }

    resp = request_with_retry(
        "GET",
        url,
        headers=_headers(token, "FHKST03010100"),
        params=params,
    )
    data = resp.json()
    rows = data.get("output2", [])[:days]

    out = []
    for row in rows:
        try:
            out.append(
                {
                    "date": str(row.get("stck_bsop_date", "")).strip(),
                    "open": float(row.get("stck_oprc", 0) or 0),
                    "high": float(row.get("stck_hgpr", 0) or 0),
                    "low": float(row.get("stck_lwpr", 0) or 0),
                    "close": float(row.get("stck_clpr", 0) or 0),
                    "volume": float(row.get("acml_vol", 0) or 0),
                }
            )
        except Exception:
            continue
    return out


def get_domestic_volume_rank_candidates(token: str, limit: int = 40) -> list[dict]:
    """
    Apps Script의 getDomesticVolumeRankCandidates_() 역할을 Python으로 옮긴 버전
    """
    base_url = _get_env("KIS_BASE_URL", required=False, default=DEFAULT_BASE_URL)
    url = f"{base_url}/uapi/domestic-stock/v1/quotations/volume-rank"
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_COND_SCR_DIV_CODE": "20171",
        "FID_INPUT_ISCD": "0000",
        "FID_DIV_CLS_CODE": "0",
        "FID_BLNG_CLS_CODE": "0",
        "FID_TRGT_CLS_CODE": "111111111",
        "FID_TRGT_EXLS_CLS_CODE": "000000",
    }

    resp = request_with_retry(
        "GET",
        url,
        headers=_headers(token, "FHPST01710000"),
        params=params,
    )
    data = resp.json()
    rows = data.get("output", [])[: max(1, min(limit, 100))]

    out = []
    for idx, row in enumerate(rows, start=1):
        code = _normalize_code(row.get("mksc_shrn_iscd", ""))
        name = str(row.get("hts_kor_isnm", "") or "").strip()
        if not code or not name:
            continue

        out.append(
            {
                "market": "KOR",
                "code": code,
                "name": name,
                "theme": "",
                "source": "VOLUME_RANK",
                "rank": idx,
                "memo": "",
            }
        )
    return out


def calculate_rsi(closes: list[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0

    gains = []
    losses = []

    for i in range(1, period + 1):
        diff = closes[i - 1] - closes[i]
        if diff >= 0:
            gains.append(diff)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(abs(diff))

    avg_gain = mean(gains) if gains else 0.0
    avg_loss = mean(losses) if losses else 0.0

    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def enrich_with_indicators(item: dict, quote: dict, daily: list[dict]) -> dict:
    closes = [float(x.get("close", 0) or 0) for x in daily if float(x.get("close", 0) or 0) > 0]
    volumes = [float(x.get("volume", 0) or 0) for x in daily if float(x.get("volume", 0) or 0) >= 0]

    rsi = calculate_rsi(closes, 14) if closes else 50.0
    avg_vol_20 = mean(volumes[:20]) if volumes[:20] else 0.0
    current_vol = float(quote.get("volume", 0) or 0)
    vol_rate = (current_vol / avg_vol_20 * 100) if avg_vol_20 > 0 else 0.0

    merged_name = (
        str(item.get("name", "")).strip()
        or str(quote.get("kis_name", "")).strip()
        or str(item.get("code", "")).strip()
    )

    return {
        **item,
        **quote,
        "name": merged_name,
        "rsi": round(rsi, 1),
        "vol_rate": round(vol_rate, 1),
    }


# === app/clients/kis.py ADD START ===
def get_domestic_volume_rank_candidates(token: str, limit: int = 40) -> list[dict]:
    """
    Apps Script의 getDomesticVolumeRankCandidates_() 역할
    """
    base_url = _get_env("KIS_BASE_URL", required=False, default=DEFAULT_BASE_URL)
    url = f"{base_url}/uapi/domestic-stock/v1/quotations/volume-rank"
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_COND_SCR_DIV_CODE": "20171",
        "FID_INPUT_ISCD": "0000",
        "FID_DIV_CLS_CODE": "0",
        "FID_BLNG_CLS_CODE": "0",
        "FID_TRGT_CLS_CODE": "111111111",
        "FID_TRGT_EXLS_CLS_CODE": "000000",
    }

    resp = request_with_retry(
        "GET",
        url,
        headers=_headers(token, "FHPST01710000"),
        params=params,
    )
    data = resp.json()
    rows = data.get("output", [])[: max(1, min(limit, 100))]

    out = []
    for idx, row in enumerate(rows, start=1):
        code = _normalize_code(row.get("mksc_shrn_iscd", ""))
        name = str(row.get("hts_kor_isnm", "") or "").strip()
        if not code or not name:
            continue

        out.append(
            {
                "market": "KOR",
                "code": code,
                "name": name,
                "theme": "",
                "source": "VOLUME_RANK",
                "rank": idx,
                "memo": "",
            }
        )
    return out
# === app/clients/kis.py ADD END ===
