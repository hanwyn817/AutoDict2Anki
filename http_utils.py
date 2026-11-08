import time
from typing import Callable, Iterable, Optional
from urllib.parse import urlsplit

import requests
from log_utils import get_logger

logger = get_logger(__name__)

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
    request_label: Optional[str] = None,
    **kwargs
) -> requests.Response:
    if max_retries < 1:
        raise ValueError("max_retries must be >= 1")

    retry_codes = set(retry_status_codes or DEFAULT_RETRY_STATUS_CODES)
    requester = request_func or requests.request
    label = request_label or urlsplit(url).hostname or "HTTP"

    for attempt in range(1, max_retries + 1):
        try:
            response = requester(method, url, timeout=timeout, **kwargs)
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
            reason = "请求超时" if isinstance(exc, requests.exceptions.Timeout) else "连接失败"
            if attempt == max_retries:
                logger.warning("%s %s，已用尽 %s 次请求机会", label, reason, max_retries)
                raise
        else:
            if response.status_code not in retry_codes:
                return response
            if attempt == max_retries:
                logger.warning("%s 返回 HTTP %s，已用尽 %s 次请求机会", label, response.status_code, max_retries)
                response.raise_for_status()
            reason = f"返回 HTTP {response.status_code}"

        sleep_seconds = backoff_factor * (2 ** (attempt - 1))
        logger.warning(
            "%s %s，%.1f 秒后重试请求，第 %s/%s 次",
            label, reason, sleep_seconds, attempt + 1, max_retries,
        )
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)

    raise RuntimeError("request_with_retry reached an unexpected state")
