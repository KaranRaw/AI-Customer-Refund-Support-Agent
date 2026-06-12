"""The runner enforces that an ESCALATE verdict always produces a ticket — even if the
LLM composes an 'it's escalated' reply without ever calling escalate_to_manager."""

from sqlalchemy import select

from app.agent.runner import run_chat_turn
from app.db.models import Escalation, RefundRequest
from app.events.bus import EventBus
from app.llm.client import LLMResponse, ToolCall


class FakeLLM:
    def __init__(self, responses):
        self._responses = list(responses)

    async def chat_with_tools(self, messages, tools):
        return self._responses.pop(0)


def _call(call_id, name, args):
    return LLMResponse(text=None, tool_calls=[ToolCall(call_id, name, args)])


def _say(text):
    return LLMResponse(text=text, tool_calls=[])


async def test_escalate_verdict_creates_ticket_even_without_the_tool(db_session):
    # ORD-1002 is over the ₹50k threshold → ESCALATE. The faked agent then replies WITHOUT
    # calling escalate_to_manager — the runner must still create the escalation/ticket.
    llm = FakeLLM(
        [
            _call("1", "check_refund_eligibility", {"order_id": "ORD-1002"}),
            _say("Because this is over ₹50,000, I've sent it to a manager for approval."),
        ]
    )

    result = await run_chat_turn(
        db_session,
        message="refund ORD-1002",
        conversation_id=None,
        llm=llm,
        bus=EventBus(),
        customer_email="aarav.sharma@example.com",
    )

    assert result.verdict == "escalate"
    assert result.ticket is not None  # the runner backstopped the missing tool call

    escalation = (
        await db_session.execute(
            select(Escalation)
            .join(RefundRequest, Escalation.refund_request_id == RefundRequest.id)
            .where(RefundRequest.conversation_id == result.conversation_id)
        )
    ).scalar_one_or_none()
    assert escalation is not None
    assert escalation.status.value == "open"
