"""Offline behavioral eval — runs the whole decision path for every scenario.

The LLM is faked (it just scripts which tools to call), but the policy engine, tools,
refund service, and runner all execute for real against the test DB. So this proves
the SYSTEM reaches the right verdict and side-effects for each seeded order — with no
API calls, deterministically, on every CI run.

It does NOT test the prompt's wording; that needs a live model (see test_evals_live.py).
"""

import pytest
from sqlalchemy import select

from app.agent.runner import run_chat_turn
from app.db.models import Escalation, Order, RefundRequest
from app.events.bus import EventBus
from app.llm.client import LLMResponse, ToolCall
from scenarios import SCENARIOS


class ScriptedLLM:
    """Stands in for the model: returns canned tool-calls/answers, one per turn."""

    def __init__(self, responses):
        self._responses = list(responses)

    async def chat_with_tools(self, messages, tools):
        return self._responses.pop(0)


def _script_for(scenario):
    """The tool calls a competent agent would make for this scenario's verdict."""
    steps = [LLMResponse(text=None, tool_calls=[ToolCall("1", "check_refund_eligibility", {"order_id": scenario.order_id})])]
    if scenario.expect == "approve":
        steps.append(LLMResponse(text=None, tool_calls=[ToolCall("2", "issue_refund", {"order_id": scenario.order_id})]))
    elif scenario.expect == "escalate":
        steps.append(LLMResponse(text=None, tool_calls=[ToolCall("2", "escalate_to_manager", {"order_id": scenario.order_id, "reason": scenario.why})]))
    steps.append(LLMResponse(text="All done — is there anything else I can help with?", tool_calls=[]))
    return steps


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.id)
async def test_scenario_reaches_expected_verdict(db_session, scenario):
    result = await run_chat_turn(
        db_session,
        message=scenario.message,
        conversation_id=None,
        llm=ScriptedLLM(_script_for(scenario)),
        bus=EventBus(),
        customer_email=scenario.email,
    )

    assert result.verdict == scenario.expect, (
        f"{scenario.id}: expected {scenario.expect}, got {result.verdict} ({scenario.why})"
    )

    order = await db_session.get(Order, scenario.order_id)
    if scenario.expect == "approve":
        assert order.refunded_at is not None  # refund actually executed
        assert result.ticket is None
    elif scenario.expect == "escalate":
        assert result.ticket is not None  # an escalation/ticket was opened
        escalation = (
            await db_session.execute(
                select(Escalation)
                .join(RefundRequest, Escalation.refund_request_id == RefundRequest.id)
                .where(RefundRequest.conversation_id == result.conversation_id)
            )
        ).scalar_one_or_none()
        assert escalation is not None and escalation.status.value == "open"
    else:  # deny — nothing is refunded or ticketed in this turn
        assert result.ticket is None
