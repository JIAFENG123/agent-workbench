from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx
import structlog

from app.config import get_settings
from app.llm.cost import compute_cost, estimate_tokens
from app.llm.http import get_http_client
from app.llm.types import (
    ChatMessage,
    ChatResult,
    StreamEvent,
    ToolCall,
    ToolSpec,
    Usage,
    messages_to_openai,
)

logger = structlog.get_logger(__name__)
settings = get_settings()

RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


class LLMError(RuntimeError):
    """Non-retryable failure (bad request, auth, exhausted providers)."""


class RetryableLLMError(LLMError):
    """Transient failure — rate limit, timeout, upstream 5xx."""


@dataclass(frozen=True)
class Provider:
    name: str
    base_url: str
    api_key: str
    default_model: str

    def url(self, path: str) -> str:
        return f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"

    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }


@dataclass
class _ToolCallAccumulator:
    """Streaming tool calls arrive as fragments keyed by index — reassemble them."""

    index: int
    id: str = ""
    name: str = ""
    arguments: str = ""
    fragments: list[str] = field(default_factory=list)

    def absorb(self, delta: dict[str, Any]) -> None:
        if delta.get("id"):
            self.id = delta["id"]
        function = delta.get("function") or {}
        if function.get("name"):
            self.name = function["name"]
        if function.get("arguments"):
            self.fragments.append(function["arguments"])

    def build(self) -> ToolCall:
        return ToolCall(
            id=self.id or f"call_{self.index}",
            name=self.name,
            arguments="".join(self.fragments),
        )


def build_providers() -> list[Provider]:
    providers: list[Provider] = []
    if settings.nvidia_api_key:
        providers.append(
            Provider(
                name="nvidia",
                base_url=settings.nvidia_base_url,
                api_key=settings.nvidia_api_key,
                default_model=settings.llm_model,
            )
        )
    if settings.fallback_enabled and settings.fallback_api_key and settings.fallback_base_url:
        providers.append(
            Provider(
                name="fallback",
                base_url=settings.fallback_base_url,
                api_key=settings.fallback_api_key,
                default_model=settings.fallback_model or settings.llm_model,
            )
        )
    return providers


class ChatClient:
    """Chat completions with retry, provider fallback, streaming and usage accounting."""

    def __init__(self, providers: Sequence[Provider] | None = None) -> None:
        self.providers: list[Provider] = list(providers or build_providers())
        self.max_retries = max(1, settings.llm_max_retries)
        self._semaphore = asyncio.Semaphore(settings.llm_max_concurrency)

    @property
    def configured(self) -> bool:
        return bool(self.providers)

    def _payload(
        self,
        provider: Provider,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolSpec] | None,
        model: str | None,
        temperature: float | None,
        max_tokens: int | None,
        stream: bool,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model or provider.default_model,
            "messages": messages_to_openai(messages),
            "temperature": settings.llm_temperature if temperature is None else temperature,
            "max_tokens": max_tokens or settings.llm_max_tokens,
            "stream": stream,
        }
        if tools:
            payload["tools"] = [tool.to_openai() for tool in tools]
            payload["tool_choice"] = "auto"
        if stream:
            payload["stream_options"] = {"include_usage": True}
        return payload

    @staticmethod
    def _classify_error(status: int, body: str, provider: Provider) -> LLMError:
        detail = body[:500]
        message = f"{provider.name} returned {status}: {detail}"
        if status in RETRYABLE_STATUS:
            return RetryableLLMError(message)
        return LLMError(message)

    @staticmethod
    def _backoff(attempt: int) -> float:
        return min(0.5 * (2 ** (attempt - 1)), 8.0)

    async def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[ToolSpec] | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> ChatResult:
        if not self.providers:
            raise LLMError("No LLM provider configured. Set NVIDIA_API_KEY.")

        async with self._semaphore:
            last_error: Exception | None = None
            for provider in self.providers:
                for attempt in range(1, self.max_retries + 1):
                    try:
                        return await self._chat_once(
                            provider, messages, tools, model, temperature, max_tokens
                        )
                    except RetryableLLMError as exc:
                        last_error = exc
                        logger.warning(
                            "llm_retry",
                            provider=provider.name,
                            attempt=attempt,
                            error=str(exc)[:200],
                        )
                        if attempt < self.max_retries:
                            await asyncio.sleep(self._backoff(attempt))
                    except LLMError as exc:
                        last_error = exc
                        logger.error(
                            "llm_provider_failed",
                            provider=provider.name,
                            error=str(exc)[:200],
                        )
                        break
            raise LLMError(f"All providers failed. Last error: {last_error}")

    async def _chat_once(
        self,
        provider: Provider,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolSpec] | None,
        model: str | None,
        temperature: float | None,
        max_tokens: int | None,
    ) -> ChatResult:
        payload = self._payload(provider, messages, tools, model, temperature, max_tokens, False)
        started = time.perf_counter()
        try:
            response = await get_http_client().post(
                provider.url("chat/completions"),
                json=payload,
                headers=provider.headers(),
            )
        except httpx.TimeoutException as exc:
            raise RetryableLLMError(f"{provider.name} timed out: {exc}") from exc
        except httpx.HTTPError as exc:
            raise RetryableLLMError(f"{provider.name} transport error: {exc}") from exc

        if response.status_code >= 400:
            raise self._classify_error(response.status_code, response.text, provider)

        body = response.json()
        choice = (body.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        usage_block = body.get("usage") or {}
        resolved_model = body.get("model") or payload["model"]

        tool_calls = [
            ToolCall(
                id=call.get("id") or f"call_{index}",
                name=(call.get("function") or {}).get("name", ""),
                arguments=(call.get("function") or {}).get("arguments", "") or "",
            )
            for index, call in enumerate(message.get("tool_calls") or [])
        ]

        prompt_tokens = int(usage_block.get("prompt_tokens") or 0)
        completion_tokens = int(usage_block.get("completion_tokens") or 0)
        if not prompt_tokens:
            prompt_tokens = sum(estimate_tokens(message.content) for message in messages)

        return ChatResult(
            content=message.get("content") or "",
            tool_calls=tool_calls,
            usage=Usage(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens),
            model=resolved_model,
            provider=provider.name,
            finish_reason=choice.get("finish_reason") or "",
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    async def stream(
        self,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[ToolSpec] | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[StreamEvent]:
        if not self.providers:
            raise LLMError("No LLM provider configured. Set NVIDIA_API_KEY.")

        async with self._semaphore:
            last_error: Exception | None = None
            for provider in self.providers:
                attempt = 0
                while attempt < self.max_retries:
                    attempt += 1
                    emitted = False
                    try:
                        async for event in self._stream_once(
                            provider, messages, tools, model, temperature, max_tokens
                        ):
                            if event.type != "done":
                                emitted = True
                            yield event
                        return
                    except RetryableLLMError as exc:
                        last_error = exc
                        if emitted:
                            raise LLMError(
                                f"Stream broke mid-flight on {provider.name} after emitting "
                                f"output; not retrying to avoid duplicated text: {exc}"
                            ) from exc
                        logger.warning(
                            "llm_stream_retry",
                            provider=provider.name,
                            attempt=attempt,
                            error=str(exc)[:200],
                        )
                        if attempt < self.max_retries:
                            await asyncio.sleep(self._backoff(attempt))
                    except LLMError as exc:
                        last_error = exc
                        logger.error(
                            "llm_stream_provider_failed",
                            provider=provider.name,
                            error=str(exc)[:200],
                        )
                        break
            raise LLMError(f"All providers failed. Last error: {last_error}")

    async def _stream_once(
        self,
        provider: Provider,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolSpec] | None,
        model: str | None,
        temperature: float | None,
        max_tokens: int | None,
    ) -> AsyncIterator[StreamEvent]:
        payload = self._payload(provider, messages, tools, model, temperature, max_tokens, True)
        started = time.perf_counter()
        text_parts: list[str] = []
        accumulators: dict[int, _ToolCallAccumulator] = {}
        finish_reason = ""
        usage = Usage()
        resolved_model = payload["model"]

        async with get_http_client().stream(
            "POST",
            provider.url("chat/completions"),
            json=payload,
            headers=provider.headers(),
        ) as response:
            if response.status_code >= 400:
                body = (await response.aread()).decode("utf-8", errors="replace")
                raise self._classify_error(response.status_code, body, provider)

            async for line in response.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    logger.warning("llm_stream_bad_chunk", provider=provider.name)
                    continue

                if chunk.get("model"):
                    resolved_model = chunk["model"]
                if chunk.get("usage"):
                    usage = Usage(
                        prompt_tokens=int(chunk["usage"].get("prompt_tokens") or 0),
                        completion_tokens=int(chunk["usage"].get("completion_tokens") or 0),
                    )

                for choice in chunk.get("choices") or []:
                    if choice.get("finish_reason"):
                        finish_reason = choice["finish_reason"]
                    delta = choice.get("delta") or {}
                    text = delta.get("content")
                    if text:
                        text_parts.append(text)
                        yield StreamEvent(type="delta", text=text)
                    for call_delta in delta.get("tool_calls") or []:
                        index = int(call_delta.get("index") or 0)
                        accumulator = accumulators.setdefault(
                            index, _ToolCallAccumulator(index=index)
                        )
                        accumulator.absorb(call_delta)

        tool_calls = [accumulators[key].build() for key in sorted(accumulators)]
        content = "".join(text_parts)
        if not usage.prompt_tokens:
            usage = Usage(
                prompt_tokens=sum(estimate_tokens(message.content) for message in messages),
                completion_tokens=estimate_tokens(content),
            )

        result = ChatResult(
            content=content,
            tool_calls=tool_calls,
            usage=usage,
            model=resolved_model,
            provider=provider.name,
            finish_reason=finish_reason,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        if tool_calls:
            yield StreamEvent(type="tool_calls", tool_calls=tool_calls)
        yield StreamEvent(type="done", result=result)


_client: ChatClient | None = None


def get_chat_client() -> ChatClient:
    global _client
    if _client is None:
        _client = ChatClient()
    return _client


def reset_chat_client() -> None:
    """Used by tests and by config reloads."""
    global _client
    _client = None


__all__ = [
    "ChatClient",
    "LLMError",
    "Provider",
    "RetryableLLMError",
    "compute_cost",
    "get_chat_client",
    "reset_chat_client",
]
