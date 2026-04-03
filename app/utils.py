import time
import requests


RETRY_STATUS_CODES = {429, 500, 502, 503, 504}


def request_with_retry(
    method,
    url,
    retries=2,
    sleep_sec=1,
    timeout=30,
    retry_status_codes=None,
    **kwargs,
):
    """
    공통 HTTP 요청 함수

    원칙:
    - 2xx: 즉시 반환
    - 429/5xx: 재시도
    - 4xx(특히 400/401/403/404): 보통 재시도하지 않고 즉시 실패
    - 응답 본문 일부를 에러 메시지에 포함하여 디버깅 가능하게 함
    """
    retry_status_codes = set(retry_status_codes or RETRY_STATUS_CODES)
    last_error = None

    for i in range(retries + 1):
        try:
            resp = requests.request(method=method, url=url, timeout=timeout, **kwargs)

            # 재시도 대상 상태코드
            if resp.status_code in retry_status_codes:
                text_preview = (resp.text or "")[:500]
                last_error = RuntimeError(
                    f"HTTP {resp.status_code} for {url}: {text_preview}"
                )
                if i < retries:
                    time.sleep(sleep_sec * (i + 1))
                    continue
                raise last_error

            # 그 외는 즉시 상태 확인
            resp.raise_for_status()
            return resp

        except requests.exceptions.RequestException as e:
            last_error = e
            if i < retries:
                time.sleep(sleep_sec * (i + 1))
                continue

        except Exception as e:
            last_error = e
            if i < retries:
                time.sleep(sleep_sec * (i + 1))
                continue

    raise last_error
