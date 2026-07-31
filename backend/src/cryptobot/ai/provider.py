"""AIProvider interface + Anthropic and Mock implementations.

Model names and prices are configuration, never hard-coded call sites.
Verified against official Anthropic docs (2026-08): the Messages API at
POST https://api.anthropic.com/v1/messages with `anthropic-version` header,
tool use via `tools` + `tool_use`/`tool_result` content blocks, and prompt
caching via `cache_control: {"type": "ephemeral"}` on system/tool blocks.
"""

from __future__ import annotations

import asyncio
import json
import random
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from cryptobot.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class ModelPrice:
    """USD per million tokens; cache reads billed at cache_read_per_mtok."""

    input_per_mtok: float
    output_per_mtok: float
    cache_read_per_mtok: float


@dataclass(frozen=True)
class ToolDef:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


@dataclass
class CompletionRequest:
    model: str
    system_blocks: list[str]                 # first blocks are cacheable prefix
    messages: list[dict[str, Any]]           # provider-native message dicts
    tools: list[ToolDef] = field(default_factory=list)
    max_tokens: int = 1024
    temperature: float = 0.2
    timeout_s: float = 60.0


@dataclass
class CompletionResult:
    text: str
    tool_calls: list[ToolCall]
    stop_reason: str
    usage: Usage
    cost_usd: float
    model: str


class AIProvider(Protocol):
    name: str

    async def complete(self, request: CompletionRequest) -> CompletionResult: ...


def compute_cost(usage: Usage, price: ModelPrice) -> float:
    return (
        usage.input_tokens * price.input_per_mtok
        + usage.output_tokens * price.output_per_mtok
        + usage.cache_read_tokens * price.cache_read_per_mtok
    ) / 1_000_000


class AnthropicProvider:
    name = "anthropic"
    _API_URL = "https://api.anthropic.com/v1/messages"
    _API_VERSION = "2023-06-01"

    def __init__(self, api_key: str, prices: dict[str, ModelPrice],
                 max_retries: int = 3) -> None:
        self._api_key = api_key
        self._prices = prices
        self._max_retries = max_retries

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        system: list[dict[str, Any]] = []
        for i, block in enumerate(request.system_blocks):
            entry: dict[str, Any] = {"type": "text", "text": block}
            if i == len(request.system_blocks) - 1:
                entry["cache_control"] = {"type": "ephemeral"}   # cache the static prefix
            system.append(entry)
        body: dict[str, Any] = {
            "model": request.model,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "system": system,
            "messages": request.messages,
        }
        if request.tools:
            body["tools"] = [
                {"name": t.name, "description": t.description,
                 "input_schema": t.input_schema}
                for t in request.tools
            ]

        last_error: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                async with httpx.AsyncClient(timeout=request.timeout_s) as client:
                    response = await client.post(
                        self._API_URL, json=body,
                        headers={"x-api-key": self._api_key,
                                 "anthropic-version": self._API_VERSION},
                    )
                if response.status_code == 429 or response.status_code >= 500:
                    raise httpx.HTTPStatusError("retryable", request=response.request,
                                                response=response)
                response.raise_for_status()
                return self._parse(response.json(), request.model)
            except httpx.HTTPError as exc:
                last_error = exc
                await asyncio.sleep(min(2**attempt, 10) + random.uniform(0, 0.5))
        raise RuntimeError(f"AI provider unavailable after retries: {type(last_error).__name__}")

    def _parse(self, data: dict[str, Any], model: str) -> CompletionResult:
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in data.get("content", []):
            if block.get("type") == "text":
                text_parts.append(block["text"])
            elif block.get("type") == "tool_use":
                tool_calls.append(ToolCall(
                    id=block["id"], name=block["name"],
                    arguments=block.get("input", {}),
                ))
        raw_usage = data.get("usage", {})
        usage = Usage(
            input_tokens=int(raw_usage.get("input_tokens", 0)),
            output_tokens=int(raw_usage.get("output_tokens", 0)),
            cache_read_tokens=int(raw_usage.get("cache_read_input_tokens", 0)),
            cache_write_tokens=int(raw_usage.get("cache_creation_input_tokens", 0)),
        )
        price = self._prices.get(model)
        cost = compute_cost(usage, price) if price else 0.0
        return CompletionResult(
            text="\n".join(text_parts), tool_calls=tool_calls,
            stop_reason=str(data.get("stop_reason", "")), usage=usage,
            cost_usd=round(cost, 6), model=model,
        )


class MockProvider:
    """Deterministic provider for tests and the evaluation suite.

    Script entries are either {'text': ...} or
    {'tool': name, 'arguments': {...}} followed by a closing text turn.
    """

    name = "mock"

    def __init__(self, script: list[dict[str, Any]] | None = None) -> None:
        self._script = list(script or [{"text": "mock response"}])
        self._step = 0
        self.requests: list[CompletionRequest] = []

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        self.requests.append(request)
        entry = self._script[min(self._step, len(self._script) - 1)]
        self._step += 1
        usage = Usage(input_tokens=100, output_tokens=50)
        if "tool" in entry:
            return CompletionResult(
                text="", tool_calls=[ToolCall(id=f"m{self._step}", name=entry["tool"],
                                              arguments=entry.get("arguments", {}))],
                stop_reason="tool_use", usage=usage, cost_usd=0.0, model=request.model,
            )
        return CompletionResult(
            text=str(entry["text"]), tool_calls=[], stop_reason="end_turn",
            usage=usage, cost_usd=0.0, model=request.model,
        )
