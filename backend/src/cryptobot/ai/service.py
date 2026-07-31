"""ChatService — orchestrates one chat turn.

Flow: budget check → injection screen → route model → build request
(cached system prefix + KB context + recent window) → agent loop with
tool-call limits → structured response → usage + audit records.

The chatbot is optional: any failure degrades to a safe message and the
trading engine never depends on this module.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from cryptobot.ai.budget import BudgetConfig, BudgetDecision, SpendState, check
from cryptobot.ai.prompts import PROMPT_VERSION, SYSTEM_PROMPT, TERMINOLOGY_BLOCK
from cryptobot.ai.provider import AIProvider, CompletionRequest, ToolDef
from cryptobot.ai.routing import RoutingConfig, route
from cryptobot.ai.tools import ToolRegistry, ToolValidationError
from cryptobot.core.logging import get_logger
from cryptobot.security.redaction import redact

logger = get_logger(__name__)

_INJECTION_PATTERNS = re.compile(
    r"(ignore (all |your |previous )*(instructions|rules)|reveal.*(system prompt|"
    r"api.?key|secret)|you are now|pretend (you have no|there are no) (rules|limits)|"
    r"developer mode|jailbreak)",
    re.IGNORECASE,
)


@dataclass
class ChatTurnResult:
    message: str = ""
    response_type: str = "answer"     # answer | refusal | error | needs_confirmation
    tools_used: list[str] = field(default_factory=list)
    data_timestamps: list[str] = field(default_factory=list)
    operating_mode: str = "paper"
    warnings: list[str] = field(default_factory=list)
    requires_confirmation: dict[str, Any] | None = None
    model: str = ""
    route_reason: str = ""
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    prompt_version: str = PROMPT_VERSION


@dataclass
class ChatService:
    provider: AIProvider
    registry: ToolRegistry
    routing: RoutingConfig = field(default_factory=RoutingConfig)
    budget: BudgetConfig = field(default_factory=BudgetConfig)
    operating_mode: str = "paper"
    max_history_messages: int = 12

    async def turn(
        self,
        user_message: str,
        history: list[dict[str, Any]],
        spend: SpendState,
        conversation_summary: str = "",
        explanation_mode: str = "simple",
    ) -> ChatTurnResult:
        # ── budget & rate gates ──────────────────────────────────────
        decision: BudgetDecision = check(self.budget, spend)
        if not decision.allowed:
            return ChatTurnResult(message=decision.reason, response_type="error",
                                  operating_mode=self.operating_mode)

        # ── injection screening (logged, refused, never obeyed) ──────
        if _INJECTION_PATTERNS.search(user_message):
            logger.warning("ai_injection_attempt", preview=redact(user_message[:120]))
            return ChatTurnResult(
                message=("I can't follow instructions that try to change my rules or "
                         "reveal internal details. I'm happy to help with your "
                         "portfolio, the market data, or how the app works."),
                response_type="refusal", operating_mode=self.operating_mode,
                warnings=["safety-rule override attempt detected and refused"],
            )

        routing_decision = route(
            user_message, self.routing,
            budget_exhausted_advanced=not decision.advanced_allowed,
        )

        mode_hint = (
            "Explanation mode: TECHNICAL — the user wants indicator values, "
            "timeframes, thresholds and risk-rule specifics."
            if explanation_mode == "technical"
            else "Explanation mode: SIMPLE — plain language, no jargon unless asked."
        )
        system_blocks = [
            SYSTEM_PROMPT,
            TERMINOLOGY_BLOCK,
            f"Current operating mode: {self.operating_mode}. {mode_hint} "
            f"Current UTC time: {datetime.now(UTC).isoformat(timespec='seconds')}.",
        ]
        messages: list[dict[str, Any]] = []
        if conversation_summary:
            messages.append({"role": "user", "content":
                            f"[Summary of earlier conversation]: {conversation_summary}"})
            messages.append({"role": "assistant", "content": "Understood."})
        messages.extend(history[-self.max_history_messages:])
        messages.append({"role": "user", "content": user_message[:4000]})

        tool_defs = [ToolDef(d["name"], d["description"], d["input_schema"])
                     for d in self.registry.definitions()]

        result = ChatTurnResult(operating_mode=self.operating_mode,
                                model=routing_decision.model,
                                route_reason="; ".join(routing_decision.reasons))

        # ── agent loop with hard tool-call cap ───────────────────────
        for _ in range(self.registry.max_calls_per_request + 1):
            try:
                completion = await self.provider.complete(CompletionRequest(
                    model=routing_decision.model, system_blocks=system_blocks,
                    messages=messages, tools=tool_defs,
                    max_tokens=self.routing.max_output_tokens,
                ))
            except RuntimeError as exc:
                logger.error("ai_provider_failed", error=str(exc))
                return ChatTurnResult(
                    message=("The AI assistant is temporarily unavailable. All "
                             "trading, risk controls and reports continue to run "
                             "normally without it."),
                    response_type="error", operating_mode=self.operating_mode)

            result.cost_usd += completion.cost_usd
            result.input_tokens += completion.usage.input_tokens
            result.output_tokens += completion.usage.output_tokens
            result.cache_read_tokens += completion.usage.cache_read_tokens

            if not completion.tool_calls:
                result.message = completion.text
                break

            if len(result.tools_used) + len(completion.tool_calls) > self.registry.max_calls_per_request:
                result.message = ("I hit the per-request tool limit before finishing. "
                                  "Here's what I found so far: " + (completion.text or ""))
                result.warnings.append("tool-call limit reached")
                break

            # execute tool calls, feed results back
            assistant_content: list[dict[str, Any]] = []
            if completion.text:
                assistant_content.append({"type": "text", "text": completion.text})
            tool_results: list[dict[str, Any]] = []
            for call in completion.tool_calls:
                assistant_content.append({"type": "tool_use", "id": call.id,
                                          "name": call.name, "input": call.arguments})
                try:
                    payload = await self.registry.execute(call.name, call.arguments)
                    result.tools_used.append(call.name)
                    meta = payload.get("_meta", {})
                    if "retrieved_at" in meta:
                        result.data_timestamps.append(meta["retrieved_at"])
                    if payload.get("requires_confirmation"):
                        result.requires_confirmation = payload
                        result.response_type = "needs_confirmation"
                except ToolValidationError as exc:
                    payload = {"error": f"invalid tool call: {exc}"}
                except Exception as exc:  # noqa: BLE001 — tool failure ≠ crash
                    logger.error("ai_tool_failed", tool=call.name, error=type(exc).__name__)
                    payload = {"error": f"the {call.name} service failed "
                                        f"({type(exc).__name__}); do not guess the value"}
                import json as _json

                tool_results.append({
                    "type": "tool_result", "tool_use_id": call.id,
                    "content": redact(_json.dumps(payload, default=str)[:6000]),
                })
            messages.append({"role": "assistant", "content": assistant_content})
            messages.append({"role": "user", "content": tool_results})
        else:
            result.message = "I couldn't complete that within the tool-call limit."
            result.warnings.append("tool-call limit reached")

        if not result.message:
            result.message = "I don't have a reliable answer for that."
        result.message = redact(result.message)
        return result
