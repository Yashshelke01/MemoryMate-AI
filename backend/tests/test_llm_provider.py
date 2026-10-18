from __future__ import annotations

import io
import json
from types import SimpleNamespace
import urllib.error

from pydantic import SecretStr

from app.services import _llm_provider


def test_gemini_compatible_base_url_does_not_get_extra_v1(monkeypatch):
    settings = SimpleNamespace(
        llm_provider="openai_compatible",
        llm_base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        llm_api_key=SecretStr("test-key"),
        llm_model="gemini-3.8-flash",
        llm_timeout_seconds=120,
    )
    monkeypatch.setattr(_llm_provider, "get_settings", lambda: settings)
    captured = {}

    class FakeResponse(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_):
            self.close()

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["payload"] = json.loads(request.data.decode())
        return FakeResponse(json.dumps({"choices": [{"message": {"content": "{}"}}]}).encode())

    monkeypatch.setattr(_llm_provider.urllib.request, "urlopen", fake_urlopen)

    result = _llm_provider.request_structured(
        system="system", user="user", schema_name="test", schema={"type": "object"}
    )

    assert result == {}
    assert captured["url"] == (
        "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    )
    assert captured["timeout"] == 120
    assert captured["payload"]["reasoning_effort"] == "low"


def test_provider_retries_transient_service_unavailable(monkeypatch):
    settings = SimpleNamespace(
        llm_provider="openai_compatible",
        llm_base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        llm_api_key=SecretStr("test-key"),
        llm_model="gemini-3.8-flash",
        llm_timeout_seconds=120,
    )
    monkeypatch.setattr(_llm_provider, "get_settings", lambda: settings)
    attempts = []
    delays = []

    class FakeResponse(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_):
            self.close()

    def fake_urlopen(request, timeout):
        attempts.append(request.full_url)
        if len(attempts) == 1:
            raise urllib.error.HTTPError(request.full_url, 503, "Unavailable", {}, None)
        return FakeResponse(json.dumps({"choices": [{"message": {"content": "{}"}}]}).encode())

    monkeypatch.setattr(_llm_provider.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(_llm_provider.time, "sleep", delays.append)

    result = _llm_provider.request_structured(
        system="system", user="user", schema_name="test", schema={"type": "object"}
    )

    assert result == {}
    assert len(attempts) == 2
    assert delays == [1]


def test_provider_retries_connection_reset(monkeypatch):
    settings = SimpleNamespace(
        llm_provider="openai_compatible",
        llm_base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        llm_api_key=SecretStr("test-key"),
        llm_model="gemini-3.8-flash",
        llm_timeout_seconds=120,
    )
    monkeypatch.setattr(_llm_provider, "get_settings", lambda: settings)
    attempts = []
    delays = []

    class FakeResponse(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_):
            self.close()

    def fake_urlopen(request, timeout):
        attempts.append(request.full_url)
        if len(attempts) == 1:
            raise ConnectionResetError("simulated connection reset")
        return FakeResponse(json.dumps({"choices": [{"message": {"content": "{}"}}]}).encode())

    monkeypatch.setattr(_llm_provider.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(_llm_provider.time, "sleep", delays.append)

    result = _llm_provider.request_structured(
        system="system", user="user", schema_name="test", schema={"type": "object"}
    )

    assert result == {}
    assert len(attempts) == 2
    assert delays == [1]
