"""Phase-3 dev-10 infra failure: proxy session cookies accumulated in the
default httpx jar across thousands of calls until '431 Request headers are
too large' poisoned every judge arm. The OpenAI client must never persist
response cookies."""

from __future__ import annotations

import pytest

httpx = pytest.importorskip("httpx")


def _client_or_skip():
    pytest.importorskip("openai")
    import os

    os.environ.setdefault("OPENAI_API_KEY", "sk-test-dummy")
    from exp_graph.llm.openai_client import OpenAIChatClient

    return OpenAIChatClient(platform="openai")


def test_http_client_does_not_store_response_cookies():
    client = _client_or_skip()
    http_client = client._client._client  # openai SDK wraps an httpx.Client
    request = httpx.Request("GET", "https://api.openai.com/v1/models")
    response = httpx.Response(
        200, headers={"set-cookie": "lb_session=abcdef; Path=/"}, request=request
    )
    # Simulate what httpx does after every response: extract into the
    # client's jar. The pinned property must leave nothing persisted.
    http_client.cookies.extract_cookies(response)
    assert len(http_client.cookies.jar) == 0, "response cookies must never persist"


def test_keep_cookies_env_restores_default(monkeypatch):
    pytest.importorskip("openai")
    monkeypatch.setenv("OPENAI_KEEP_COOKIES", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-dummy")
    from exp_graph.llm.openai_client import OpenAIChatClient

    client = OpenAIChatClient(platform="openai")
    jar = client._client._client.cookies
    request = httpx.Request("GET", "https://api.openai.com/v1/models")
    response = httpx.Response(
        200, headers={"set-cookie": "lb_session=abcdef; Path=/"}, request=request
    )
    jar.extract_cookies(response)
    assert len(jar.jar) == 1, "opt-out env must restore the default jar"
