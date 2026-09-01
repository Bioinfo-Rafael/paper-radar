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


def test_per_operation_health_never_overwritten_by_unrelated_success(monkeypatch):
    ok = requests.Response()
    ok.status_code = 200
    ok.url = "https://api.semanticscholar.org/graph/v1/paper/batch"
    ok._content = b"{}"
    failing = requests.Response()
    failing.status_code = 429
    failing.url = "https://api.semanticscholar.org/graph/v1/paper/search"
    client = HttpClient(retries=0)

    monkeypatch.setattr(client.session, "request", lambda *a, **kw: ok)
    client.get_json(
        "https://api.semanticscholar.org/graph/v1/paper/batch",
        health_key="semantic_scholar.enrichment",
    )
    monkeypatch.setattr(client.session, "request", lambda *a, **kw: failing)
    with pytest.raises(requests.HTTPError):
        client.get_json(
            "https://api.semanticscholar.org/graph/v1/paper/search",
            health_key="semantic_scholar.search",
        )

    health = client.source_health()
    assert health["semantic_scholar.enrichment"] == "healthy"
    assert health["semantic_scholar.search"] == "rate_limit"
    assert health["semantic_scholar"] == "degraded"


def test_all_operations_failing_rolls_up_to_that_reason(monkeypatch):
    response = requests.Response()
    response.status_code = 429
    response.url = "https://api.semanticscholar.org/graph/v1/x"
    client = HttpClient(retries=0)
    monkeypatch.setattr(client.session, "request", lambda *a, **kw: response)
    for key in ("semantic_scholar.search", "semantic_scholar.recommendations"):
        with pytest.raises(requests.HTTPError):
            client.get_json("https://api.semanticscholar.org/graph/v1/x", health_key=key)
    assert client.source_health()["semantic_scholar"] == "rate_limit"


def test_same_key_success_then_failure_is_degraded_not_healthy(monkeypatch):
    """One lane's call to a source succeeding must not paper over a later
    lane's call to that exact same source failing within the same run.
    """
    ok = requests.Response()
    ok.status_code = 200
    ok.url = "https://api.openalex.org/works"
    ok._content = b"{}"
    failing = requests.Response()
    failing.status_code = 429
    failing.url = "https://api.openalex.org/works"
    client = HttpClient(retries=0)

    monkeypatch.setattr(client.session, "request", lambda *a, **kw: ok)
    client.get_json("https://api.openalex.org/works", health_key="openalex")
    monkeypatch.setattr(client.session, "request", lambda *a, **kw: failing)
    with pytest.raises(requests.HTTPError):
        client.get_json("https://api.openalex.org/works", health_key="openalex")

    assert client.source_health()["openalex"] == "degraded"


def test_all_operations_healthy_rolls_up_to_healthy(monkeypatch):
    response = requests.Response()
    response.status_code = 200
    response.url = "https://api.semanticscholar.org/graph/v1/x"
    response._content = b"{}"
    client = HttpClient(retries=0)
    monkeypatch.setattr(client.session, "request", lambda *a, **kw: response)
    for key in ("semantic_scholar.search", "semantic_scholar.enrichment"):
        client.get_json("https://api.semanticscholar.org/graph/v1/x", health_key=key)
    assert client.source_health()["semantic_scholar"] == "healthy"
