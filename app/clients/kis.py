from __future__ import annotations

import json
import os
import time
from datetime import datetime
from statistics import mean

import requests

from app.utils import request_with_retry

DEFAULT_BASE_URL = "https://openapi.koreainvestment.com:9443"
DEFAULT_TOKEN_CACHE_FILE = "kis_token_cache.json"
DEFAULT_TOKEN_CACHE_KEY = "signal_forge:kis:access_token"

# 실행 프로세스 내 캐시
_TOKEN_CACHE = {
    "token": "",
    "expires_at": 0.0,  # epoch seconds
}

_REDIS_CLIENT = None
_REDIS_INIT_DONE = False


def _get_env(name: str, required: bool = True, default: str = "") -> str:
    value = os.getenv(name, default).strip()
    if required and not value:
        raise RuntimeError(f"{name} not set")
    return value


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(float(value))
    except Exception:
        return int(default)


def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _token_cache_file() -> str:
    """
    환경변수로 캐시 파일 경로를 지정할 수 있게 함.
    미지정 시 프로젝트 루트 기준 kis_token_cache.json 사용.
    """
    return os.getenv("KIS_TOKEN_CACHE_FILE", DEFAULT_TOKEN_CACHE_FILE).strip() or DEFAULT_TOKEN_CACHE_FILE


def _token_cache_key() -> str:
    return os.getenv("KIS_TOKEN_CACHE_KEY", DEFAULT_TOKEN_CACHE_KEY).strip() or DEFAULT_TOKEN_CACHE_KEY


def _token_cache_ttl_sec() -> int:
    return _safe_int(os.getenv("KIS_TOKEN_CACHE_TTL_SEC", "86400"), 86400)


def _parse_expiry_seconds(data: dict) -> int:
    """
    KIS 응답에서 expires_in(초) 또는 access_token_token_expired(시각)를 이용해 남은 초를 계산.
    """
    if not isinstance(data, dict):
        return 0

    expires_in = _safe_int(data.get("expires_in", 0), 0)
    if expires_in > 0:
        return expires_in

    expired_at_raw = str(data.get("access_token_token_expired", "") or "").strip()
    if expired_at_raw:
        # 예: 2026-04-04 15:37:55
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y%m%d%H%M%S"):
            try:
                dt = datetime.strptime(expired_at_raw, fmt)
                remain = int(dt.timestamp() - time.time())
                return max(0, remain)
            except Exception:
                continue

    return 0


def _load_token_cache_file() -> dict:
    path = _token_cache_file()
    if not os.path.exists(path):
        return {}

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception as e:
        print("[KIS DEBUG] token cache load failed", str(e))

    return {}


def _save_token_cache_file(token: str, expires_at: float) -> None:
    path = _token_cache_file()
    payload = {
        "access_token": token,
        "expires_at": float(expires_at),
        "saved_at": time.time(),
    }

    try:
        folder = os.path.dirname(path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
    except Exception as e:
        print("[KIS DEBUG] token cache save failed", str(e))


def _is_token_usable(token: str, expires_at: float, buffer_sec: int = 1800) -> bool:
    """
    buffer_sec 이내 만료 예정이면 재발급 대상으로 본다.
    기본 30분 버퍼.
    """
    if not token or not expires_at:
        return False
    return float(expires_at) > time.time() + max(0, int(buffer_sec))


def _get_redis_client():
    global _REDIS_CLIENT, _REDIS_INIT_DONE

    if _REDIS_INIT_DONE:
        return _REDIS_CLIENT

    _REDIS_INIT_DONE = True

    redis_url = os.getenv("KIS_TOKEN_CACHE_REDIS_URL", "").strip()
    if not redis_url:
        return None

    try:
        import redis  # type: ignore

        client = redis.from_url(redis_url, decode_responses=True)
        client.ping()
        _REDIS_CLIENT = client
        print("[KIS DEBUG] redis cache connected")
        return _REDIS_CLIENT
    except Exception as e:
        print("[KIS DEBUG] redis cache unavailable", str(e))
        _REDIS_CLIENT = None
        return None


def _load_token_cache_redis() -> dict:
    client = _get_redis_client()
    if not client:
        return {}

    try:
        raw = client.get(_token_cache_key())
        if not raw:
            return {}

        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except Exception as e:
        print("[KIS DEBUG] redis cache load failed", str(e))

    return {}


def _save_token_cache_redis(token: str, expires_at: float) -> None:
    client = _get_redis_client()
    if not client:
        return

    payload = {
        "access_token": token,
        "expires_at": float(expires_at),
        "saved_at": time.time(),
    }

    try:
        ttl = max(60, _token_cache_ttl_sec())
        client.set(_token_cache_key(), json.dumps(payload, ensure_ascii=False), ex=ttl)
    except Exception as e:
        print("[KIS DEBUG] redis cache save failed", str(e))


def _get_valid_cached_token(buffer_sec: int = 1800) -> str:
    """
    우선순위:
    1) 메모리 캐시
    2) Redis/Valkey 외부 캐시
    3) 파일 캐시
    buffer_sec 이내 만료 예정이면 재발급
    """
    global _TOKEN_CACHE

    # 1. 메모리 캐시
    mem_token = str(_TOKEN_CACHE.get("token", "") or "").strip()
    mem_exp = float(_TOKEN_CACHE.get("expires_at", 0) or 0)
    if _is_token_usable(mem_token, mem_exp, buffer_sec=buffer_sec):
        print("[KIS DEBUG] token source = memory_cache")
        return mem_token

    # 2. Redis/Valkey 캐시
    cached_redis = _load_token_cache_redis()
    redis_token = str(cached_redis.get("access_token", "") or "").strip()
    redis_exp = float(cached_redis.get("expires_at", 0) or 0)
    if _is_token_usable(redis_token, redis_exp, buffer_sec=buffer_sec):
        _TOKEN_CACHE["token"] = redis_token
        _TOKEN_CACHE["expires_at"] = redis_exp
        print("[KIS DEBUG] token source = redis_cache")
        return redis_token

    # 3. 파일 캐시
    cached_file = _load_token_cache_file()
    file_token = str(cached_file.get("access_token", "") or "").strip()
    file_exp = float(cached_file.get("expires_at", 0) or 0)
    if _is_token_usable(file_token, file_exp, buffer_sec=buffer_sec):
        _TOKEN_CACHE["token"] = file_token
        _TOKEN_CACHE["expires_at"] = file_exp
        print("[KIS DEBUG] token source = file_cache")
        return file_token

    return ""


def _set_cached_token(token: str, expires_in: int) -> None:
    global _TOKEN_CACHE

    if expires_in <= 0:
        # 비정상 응답 대비 기본 6시간
        expires_in = 60 * 60 * 6

    expires_at = time.time() + int(expires_in)

    _TOKEN_CACHE["token"] = token
    _TOKEN_CACHE["expires_at"] = expires_at

    _save_token_cache_redis(token, expires_at)
    _save_token_cache_file(token, expires_at)


def clear_cached_token() -> None:
    """
    수동 점검용. 필요 시 강제 초기화에 사용.
    """
    global _TOKEN_CACHE
    _TOKEN_CACHE["token"] = ""
    _TOKEN_CACHE["expires_at"] = 0.0

    # 파일 캐시 삭제
    path = _token_cache_file()
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception as e:
        print("[KIS DEBUG] token cache clear failed", str(e))

    # Redis 캐시 삭제
    client = _get_redis_client()
    if client:
        try:
            client.delete(_token_cache_key())
        except Exception as e:
            print("[KIS DEBUG] redis cache clear failed", str(e))


def get_access_token(force_refresh: bool = False) -> str:
    """
    원칙:
    - force_refresh=False 이면 캐시 우선
    - 살아있는 토큰이 있으면 절대 재발급하지 않음
    - 응답 body 에서 토큰을 확인하고 expires_in / access_token_token_expired 기준으로 저장
    """
    if not force_refresh:
        cached_token = _get_valid_cached_token(
            buffer_sec=_safe_int(os.getenv("KIS_TOKEN_BUFFER_SEC", "1800"), 1800)
        )
        if cached_token:
            return cached_token

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
            "force_refresh": force_refresh,
            "cache_file": _token_cache_file(),
            "cache_key": _token_cache_key(),
            "has_redis": bool(os.getenv("KIS_TOKEN_CACHE_REDIS_URL", "").strip()),
        },
    )

    last_error = None

    for i in range(3):
        try:
            resp = requests.post(url, json=payload, timeout=30)

            print("[KIS DEBUG] token status", resp.status_code)

            try:
                data = resp.json()
            except Exception:
                data = {}

            if isinstance(data, dict):
                print("[KIS DEBUG] token response keys", list(data.keys()))
            else:
                print("[KIS DEBUG] token response type", type(data).__name__)

            token = data.get("access_token", "") if isinstance(data, dict) else ""
            if token:
                expires_in = _parse_expiry_seconds(data)
                _set_cached_token(token, expires_in)
                print("[KIS DEBUG] token source = issued_new")
                return token

            body_preview = (resp.text or "")[:300]
            if resp.status_code >= 400:
                last_error = RuntimeError(f"KIS token HTTP {resp.status_code}: {body_preview}")
            else:
                last_error = RuntimeError(f"KIS token error: {body_preview}")

        except Exception as e:
            last_error = e

        if i < 2:
            time.sleep(i + 1)

    raise last_error


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
