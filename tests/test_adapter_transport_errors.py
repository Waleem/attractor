from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from attractor_llm.adapters.anthropic import AnthropicAdapter
from attractor_llm.adapters.base import ProviderConfig
from attractor_llm.adapters.gemini import GeminiAdapter
from attractor_llm.adapters.openai import OpenAIAdapter
from attractor_llm.errors import ProviderError
from attractor_llm.types import Request


def _connect_error_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("dns unavailable", request=request)

    return httpx.MockTransport(handler)


@pytest.mark.parametrize(
    ("adapter_factory", "provider", "model"),
    [
        (OpenAIAdapter, "openai", "gpt-4.1-mini"),
        (AnthropicAdapter, "anthropic", "claude-3-5-haiku-latest"),
        (GeminiAdapter, "gemini", "gemini-1.5-flash"),
    ],
)
async def test_complete_wraps_transport_errors_as_provider_errors(
    adapter_factory: Callable[[ProviderConfig], object],
    provider: str,
    model: str,
) -> None:
    adapter = adapter_factory(ProviderConfig(api_key="test-key"))
    await adapter._client.aclose()  # type: ignore[attr-defined]  # noqa: SLF001
    adapter._client = httpx.AsyncClient(  # type: ignore[attr-defined]  # noqa: SLF001
        transport=_connect_error_transport()
    )

    try:
        with pytest.raises(ProviderError) as exc_info:
            await adapter.complete(Request.simple(model, "Hello"))  # type: ignore[attr-defined]
    finally:
        await adapter.close()  # type: ignore[attr-defined]

    assert exc_info.value.provider == provider
    assert exc_info.value.retryable is True
