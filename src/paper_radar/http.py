from __future__ import annotations

import logging
import random
import time
from typing import Any

import requests

LOGGER = logging.getLogger(__name__)


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
            try:
                response = self.session.request(method, url, timeout=self.timeout, **kwargs)
                if response.status_code not in retry_statuses:
                    response.raise_for_status()
                    return response
                last_error = requests.HTTPError(f"HTTP {response.status_code}", response=response)
                retry_after = response.headers.get("Retry-After")
                delay = float(retry_after) if retry_after and retry_after.isdigit() else 2**attempt
            except (requests.Timeout, requests.ConnectionError) as exc:
                last_error = exc
                delay = 2**attempt
            if attempt < self.retries:
                delay += random.uniform(0, 0.25)
                LOGGER.warning("HTTP retry", extra={"url": url, "attempt": attempt + 1})
                time.sleep(delay)
        assert last_error is not None
        raise last_error

    def get_json(self, url: str, **kwargs: Any) -> dict[str, Any]:
        return self.request("GET", url, **kwargs).json()
