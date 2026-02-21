import time
from typing import Callable, Iterable, Optional

import requests

RequestCallable = Callable[..., requests.Response]

DEFAULT_RETRY_STATUS_CODES = (429, 500, 502, 503, 504)


def request_with_retry(
    method: str,
    url: str,
    *,
    timeout: int = 10,
    max_retries: int = 3,
    backoff_factor: float = 0.5,
    retry_status_codes: Optional[Iterable[int]] = None,
    request_func: Optional[RequestCallable] = None,
    **kwargs
) -> requests.Response:
    if max_retries < 1:
        raise ValueError("max_retries must be >= 1")

    retry_codes = set(retry_status_codes or DEFAULT_RETRY_STATUS_CODES)
    requester = request_func or requests.request

    for attempt in range(1, max_retries + 1):
        try:
            response = requester(method, url, timeout=timeout, **kwargs)
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
            if attempt == max_retries:
                raise
        else:
            if response.status_code not in retry_codes:
                return response
            if attempt == max_retries:
                response.raise_for_status()

        sleep_seconds = backoff_factor * (2 ** (attempt - 1))
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)

    raise RuntimeError("request_with_retry reached an unexpected state")
