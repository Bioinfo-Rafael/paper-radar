from __future__ import annotations

import logging
import random
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import requests

LOGGER = logging.getLogger(__name__)
MAX_RETRY_SLEEP_SECONDS = 45.0


def _retry_after_seconds(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            when = parsedate_to_datetime(value)
            if when.tzinfo is None:
                when = when.replace(tzinfo=UTC)
            return max(0.0, (when - datetime.now(UTC)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None


class HttpClient:
    def __init__(self, timeout: float = 25, retries: int = 4) -> None:
        self.timeout = timeout
        self.retries = retries
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "paper-radar/0.1 (personal research alert bot)"})

    def request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        retry_statuses = {429, 500, 502, 503, 504}
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            retry_after_value: str | None = None
            status: int | None = None
            try:
                response = self.session.request(method, url, timeout=self.timeout, **kwargs)
                status = response.status_code
                if response.status_code not in retry_statuses:
                    response.raise_for_status()
                    return response
                last_error = requests.HTTPError(f"HTTP {response.status_code}", response=response)
                retry_after_value = response.headers.get("Retry-After")
                retry_after = _retry_after_seconds(retry_after_value)
                delay = retry_after if retry_after is not None else 2**attempt
            except (requests.Timeout, requests.ConnectionError) as exc:
                last_error = exc
                delay = 2**attempt
                LOGGER.warning(
                    "HTTP request error url=%s attempt=%d/%d error=%s",
                    url,
                    attempt + 1,
                    self.retries + 1,
                    type(exc).__name__,
                )
            if attempt < self.retries:
                sleep_seconds = min(delay + random.uniform(0, 0.25), MAX_RETRY_SLEEP_SECONDS)
                LOGGER.warning(
                    "HTTP retry url=%s status=%s attempt=%d/%d Retry-After=%s sleep=%.2fs",
                    url,
                    status if status is not None else "connection-error",
                    attempt + 1,
                    self.retries + 1,
                    retry_after_value or "none",
                    sleep_seconds,
                )
                time.sleep(sleep_seconds)
        assert last_error is not None
        raise last_error

    def get_json(self, url: str, **kwargs: Any) -> dict[str, Any]:
        return self.request("GET", url, **kwargs).json()
