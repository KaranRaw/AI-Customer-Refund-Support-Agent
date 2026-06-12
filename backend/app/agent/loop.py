"""The agent loop: raw function calling over the LLMClient port.

The model is asked to respond given the tool menu; if it returns tool calls we
dispatch them and feed the results back, repeating until it returns a final text
answer or MAX_STEPS is reached. The loop is resilient by construction: LLM calls
are retried with backoff, a total failure degrades to a graceful message, and a
failing tool is reported back to the model rather than crashing the turn.

Each step is emitted as a StepEvent. The loop does not persist them itself — a
caller (the tracing layer) can pass `emit` to stream and store them.
"""

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.agent.prompts import build_system_prompt
from app.agent.tools import TOOL_SCHEMAS, ToolContext, dispatch
from app.config import get_settings
from app.llm.client import (
    LLMClient,
    LLMResponse,
    Message,
    assistant_message,
    system_message,
    tool_result_message,
    user_message,
)

logger = logging.getLogger(__name__)
from app.policy.engine import PolicyConfig, load_policy_config

_LLM_FAILURE_MESSAGE = (
    "I'm sorry — I'm having trouble processing this right now. "
    "Please try again in a moment, or ask for a human agent."
)


@dataclass
class StepEvent:
    type: str  # llm_call | tool_call | tool_result | decision | error | retry
    tool_name: str | None = None
    input: dict | None = None
    output: dict | None = None
    status: str = "success"  # success | error | retried
    latency_ms: int | None = None
    model: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None


@dataclass
class AgentResult:
    answer: str
    verdict: str | None
    steps: list[StepEvent]
    messages: list[Message]
    capped: bool = False


def _backoff_seconds(attempt: int) -> float:
    return 0.5 * (2**attempt)


def _next_verdict(current: str | None, tool_name: str, result: dict) -> str | None:
    if tool_name == "issue_refund" and result.get("executed"):
        return "approve"
    if tool_name == "escalate_to_manager" and result.get("escalated"):
        return "escalate"
    if tool_name == "check_refund_eligibility" and result.get("verdict"):
        return result["verdict"]
    return current


async def _call_llm_with_retry(
    llm: LLMClient,
    messages: list[Message],
    max_retries: int,
    sleep: Callable[[float], Awaitable[None]],
    record: Callable[["StepEvent"], Awaitable[None]],
) -> LLMResponse:
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return await llm.chat_with_tools(messages, TOOL_SCHEMAS)
        except Exception as exc:  # noqa: BLE001 - any provider error is treated as retryable
            last_exc = exc
            if attempt < max_retries:
                logger.warning(
                    "LLM call failed (attempt %d/%d), retrying: %s", attempt + 1, max_retries, exc
                )
                await record(
                    StepEvent("retry", output={"attempt": attempt + 1, "error": str(exc)}, status="retried")
                )
                await sleep(_backoff_seconds(attempt))
    assert last_exc is not None
    raise last_exc


async def run_agent(
    user_text: str,
    *,
    llm: LLMClient,
    ctx: ToolContext,
    history: list[Message] | None = None,
    config: PolicyConfig | None = None,
    max_steps: int | None = None,
    max_retries: int = 2,
    emit: Callable[[StepEvent], Awaitable[None]] | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> AgentResult:
    config = config or load_policy_config()
    max_steps = max_steps if max_steps is not None else get_settings().max_steps

    messages: list[Message] = [system_message(build_system_prompt(config, ctx.customer))]
    messages += history or []
    messages.append(user_message(user_text))

    steps: list[StepEvent] = []
    verdict: str | None = None

    async def record(event: StepEvent) -> None:
        steps.append(event)
        if emit is not None:
            await emit(event)

    for _ in range(max_steps):
        llm_started = time.monotonic()
        try:
            response = await _call_llm_with_retry(llm, messages, max_retries, sleep, record)
        except Exception as exc:  # noqa: BLE001 - degrade gracefully on total LLM failure
            logger.error("Agent LLM call failed after retries: %s", exc)
            await record(StepEvent("error", output={"error": str(exc)}, status="error"))
            return AgentResult(_LLM_FAILURE_MESSAGE, verdict, steps, messages)
        llm_latency_ms = int((time.monotonic() - llm_started) * 1000)

        await record(
            StepEvent(
                "llm_call",
                input={"messages": list(messages)},  # snapshot of the exact prompt sent this turn
                output={
                    "text": response.text,
                    "tool_calls": [
                        {"name": tc.name, "arguments": tc.arguments} for tc in response.tool_calls
                    ],
                },
                latency_ms=llm_latency_ms,
                model=response.model,
                tokens_in=response.prompt_tokens,
                tokens_out=response.completion_tokens,
            )
        )

        if not response.tool_calls:
            messages.append(assistant_message(response.text))
            await record(StepEvent("decision", output={"answer": response.text, "verdict": verdict}))
            return AgentResult(response.text or "", verdict, steps, messages)

        messages.append(assistant_message(response.text, response.tool_calls))
        for tool_call in response.tool_calls:
            await record(StepEvent("tool_call", tool_name=tool_call.name, input=tool_call.arguments))
            tool_started = time.monotonic()
            try:
                result = await dispatch(tool_call.name, tool_call.arguments, ctx)
                status = "success" if result.get("ok", True) else "error"
            except Exception as exc:  # noqa: BLE001 - a tool crash is fed back, not fatal
                logger.warning("Tool %s crashed: %s", tool_call.name, exc)
                result = {"ok": False, "error": str(exc)}
                status = "error"
            tool_latency_ms = int((time.monotonic() - tool_started) * 1000)
            await record(
                StepEvent(
                    "tool_result",
                    tool_name=tool_call.name,
                    output=result,
                    status=status,
                    latency_ms=tool_latency_ms,
                )
            )
            verdict = _next_verdict(verdict, tool_call.name, result)
            messages.append(tool_result_message(tool_call.id, tool_call.name, json.dumps(result)))

    logger.warning("Agent hit MAX_STEPS (%d) without a final answer", max_steps)
    await record(StepEvent("error", output={"error": f"MAX_STEPS ({max_steps}) exceeded"}, status="error"))
    return AgentResult(_LLM_FAILURE_MESSAGE, verdict, steps, messages, capped=True)
