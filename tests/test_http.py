import logging

import pytest
import requests

from paper_radar.http import MAX_RETRY_SLEEP_SECONDS, HttpClient


def test_huge_retry_after_is_capped(monkeypatch, caplog):
    responses = [
        requests.Response(),
        requests.Response(),
    ]
    responses[0].status_code = 429
    responses[0].headers["Retry-After"] = "99999"
    responses[0].url = "https://example.test/api"
    responses[1].status_code = 200
    responses[1].url = "https://example.test/api"
    client = HttpClient(retries=1)
    monkeypatch.setattr(client.session, "request", lambda *args, **kwargs: responses.pop(0))
    sleeps = []
    monkeypatch.setattr("paper_radar.http.time.sleep", sleeps.append)
    monkeypatch.setattr("paper_radar.http.random.uniform", lambda *_: 0)

    with caplog.at_level(logging.WARNING):
        response = client.request("GET", "https://example.test/api")

    assert response.status_code == 200
    assert sleeps == [MAX_RETRY_SLEEP_SECONDS]
    assert "status=429" in caplog.text
    assert "Retry-After=99999" in caplog.text
    assert "sleep=45.00s" in caplog.text
    assert client.source_health() == {"http": "healthy"}


def test_final_rate_limit_is_degraded(monkeypatch):
    response = requests.Response()
    response.status_code = 429
    response.url = "https://api.semanticscholar.org/graph/v1/paper/search"
    client = HttpClient(retries=0)
    monkeypatch.setattr(client.session, "request", lambda *args, **kwargs: response)
    with pytest.raises(requests.HTTPError):
        client.request("GET", response.url)
    assert client.source_health() == {"semantic_scholar": "rate_limit"}
