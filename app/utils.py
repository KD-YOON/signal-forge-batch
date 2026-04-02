import time
import requests


def request_with_retry(method, url, retries=2, sleep_sec=1, **kwargs):
    last_error = None
    for i in range(retries + 1):
        try:
            resp = requests.request(method=method, url=url, timeout=30, **kwargs)
            resp.raise_for_status()
            return resp
        except Exception as e:
            last_error = e
            if i < retries:
                time.sleep(sleep_sec * (i + 1))
    raise last_error
