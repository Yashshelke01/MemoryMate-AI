"""Small server-side adapter for the configured LLM provider.

Supports the provider already configured by the project (Anthropic) and
OpenAI's Chat Completions API. Credentials are read only on the server and
are never included in errors or returned values.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any, Mapping

from app.config import get_settings


class ProviderError(RuntimeError):
    """A provider call could not be completed or decoded."""


_TRANSIENT_HTTP_STATUS_CODES = {408, 429, 500, 502, 503, 504}
_MAX_PROVIDER_ATTEMPTS = 3


def is_configured() -> bool:
    settings = get_settings()
    return bool(
        settings.llm_provider.strip().lower() in {"anthropic", "openai", "openai_compatible"}
        and settings.llm_api_key
        and settings.llm_api_key.get_secret_value().strip()
        and settings.llm_model.strip()
    )


def request_structured(
    *,
    system: str,
    user: str,
    schema_name: str,
    schema: Mapping[str, Any],
    max_tokens: int = 1200,
) -> dict[str, Any]:
    """Call a supported provider with a constrained JSON/tool schema."""
    settings = get_settings()
    if not settings.llm_api_key or not settings.llm_api_key.get_secret_value().strip():
        raise ProviderError("LLM credentials are not configured")
    if not settings.llm_model.strip():
        raise ProviderError("LLM model is not configured")

    provider = settings.llm_provider.strip().lower()
    base = (settings.llm_base_url or "").strip().rstrip("/")
    if not base:
        base = "https://api.anthropic.com" if provider == "anthropic" else "https://api.openai.com"
    if provider == "anthropic":
        endpoint = base if base.endswith("/v1") else f"{base}/v1"
        payload: dict[str, Any] = {
            "model": settings.llm_model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "tools": [{"name": schema_name, "description": "Return the requested structured result.", "input_schema": dict(schema)}],
            "tool_choice": {"type": "tool", "name": schema_name},
        }
        headers = {
            "x-api-key": settings.llm_api_key.get_secret_value(),
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        url = f"{endpoint}/messages"
        response_key = "anthropic"
    elif provider in {"openai", "openai_compatible"}:
        # Most OpenAI-compatible servers use ``/v1``. Google's Gemini
        # compatibility endpoint already includes its API version and
        # namespace (``/v1beta/openai``), so appending another ``/v1`` makes
        # the request URL invalid.
        endpoint = (
            base
            if base.endswith(("/v1", "/v1beta/openai"))
            else f"{base}/v1"
        )
        payload = {
            "model": settings.llm_model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": schema_name, "strict": True, "schema": dict(schema)},
            },
        }
        if provider == "openai_compatible" and "generativelanguage.googleapis.com" in endpoint:
            # Gemini 3.x defaults to medium reasoning, which adds latency to
            # these simple extraction and answer-formatting calls. Its
            # OpenAI-compatible endpoint supports reasoning_effort.
            payload["reasoning_effort"] = "low"
        headers = {"Authorization": f"Bearer {settings.llm_api_key.get_secret_value()}", "content-type": "application/json"}
        url = f"{endpoint}/chat/completions"
        response_key = "openai"
    else:
        raise ProviderError(f"Unsupported LLM_PROVIDER: {provider}")

    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    for attempt in range(_MAX_PROVIDER_ATTEMPTS):
        try:
            with urllib.request.urlopen(request, timeout=settings.llm_timeout_seconds) as response:
                envelope = json.loads(response.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as exc:
            if exc.code not in _TRANSIENT_HTTP_STATUS_CODES or attempt == _MAX_PROVIDER_ATTEMPTS - 1:
                # Do not retain or expose provider response bodies or secrets.
                raise ProviderError("LLM provider request failed") from exc
            exc.close()
            time.sleep(2**attempt)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            # Connection resets and timeouts are transient in the same way as
            # 503 responses. Retrying extraction is safe because it has no
            # side effects; persistence happens only after this returns.
            if attempt == _MAX_PROVIDER_ATTEMPTS - 1:
                # Do not retain or expose provider response bodies or secrets.
                raise ProviderError("LLM provider request failed") from exc
            time.sleep(2**attempt)
        except ValueError as exc:
            # Invalid JSON is a malformed provider response, not a transient
            # transport failure, so fail without repeating the request.
            raise ProviderError("LLM provider request failed") from exc

    try:
        if response_key == "anthropic":
            block = next(part for part in envelope["content"] if part.get("type") == "tool_use" and part.get("name") == schema_name)
            result = block["input"]
        else:
            content = envelope["choices"][0]["message"]["content"]
            result = json.loads(content)
    except (KeyError, IndexError, StopIteration, TypeError, ValueError) as exc:
        raise ProviderError("LLM provider returned malformed structured output") from exc
    if not isinstance(result, dict):
        raise ProviderError("LLM provider returned malformed structured output")
    return result
