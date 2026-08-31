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
        self._source_successes: dict[str, int] = {}
        self._source_failures: dict[str, str] = {}

    @staticmethod
    def source_name(url: str) -> str:
        if "semanticscholar.org" in url:
            return "semantic_scholar"
        if "ncbi.nlm.nih.gov" in url:
            return "pubmed"
        if "arxiv.org" in url:
            return "arxiv"
        if "biorxiv.org" in url:
            return "biorxiv"
        if "crossref.org" in url:
            return "crossref"
        return "http"

    def source_health(self) -> dict[str, str]:
        names = set(self._source_successes) | set(self._source_failures)
        return {
            name: "healthy" if self._source_successes.get(name, 0) else self._source_failures[name]
            for name in sorted(names)
        }

    def reset_source_health(self) -> None:
        self._source_successes.clear()
        self._source_failures.clear()

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
                    source = self.source_name(url)
                    self._source_successes[source] = self._source_successes.get(source, 0) + 1
                    return response
                last_error = requests.HTTPError(f"HTTP {response.status_code}", response=response)
                retry_after_value = response.headers.get("Retry-After")
                retry_after = _retry_after_seconds(retry_after_value)
                delay = retry_after if retry_after is not None else 2**attempt
            except requests.HTTPError as exc:
                source = self.source_name(url)
                self._source_failures[source] = (
                    "rate_limit"
                    if getattr(exc.response, "status_code", None) == 429
                    else "request_error"
                )
                raise
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
        source = self.source_name(url)
        if isinstance(last_error, requests.Timeout):
            reason = "timeout"
        elif isinstance(last_error, requests.HTTPError) and getattr(
            last_error.response, "status_code", None
        ) == 429:
            reason = "rate_limit"
        else:
            reason = "request_error"
        self._source_failures[source] = reason
        raise last_error

    def get_json(self, url: str, **kwargs: Any) -> dict[str, Any]:
        return self.request("GET", url, **kwargs).json()
