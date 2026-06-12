"""Tests for the agent loop, driven by fake LLM clients — no live API calls.

The fakes only stand in for the model; the tools, policy engine, and refund service
all run for real against the test database.
"""

from datetime import datetime, timezone

from app.agent.loop import run_agent
from app.agent.tools import ToolContext
from app.db.models import Conversation, ConversationChannel, Order
from app.llm.client import LLMResponse, ToolCall


class FakeLLM:
    """Serves a scripted list of responses, one per call."""

    def __init__(self, responses):
        self._responses = list(responses)

    async def chat_with_tools(self, messages, tools):
        return self._responses.pop(0)


class FlakyLLM:
    """Raises for the first `fail_times` calls, then serves scripted responses."""

    def __init__(self, fail_times, responses):
        self.fail_times = fail_times
        self._responses = list(responses)
        self.attempts = 0

    async def chat_with_tools(self, messages, tools):
        if self.attempts < self.fail_times:
            self.attempts += 1
            raise TimeoutError("simulated LLM timeout")
        return self._responses.pop(0)


class AlwaysToolLLM:
    """Never finishes — always asks for another tool call."""

    async def chat_with_tools(self, messages, tools):
        return LLMResponse(text=None, tool_calls=[ToolCall("x", "get_order", {"order_id": "ORD-1001"})])


async def _ctx(db_session) -> ToolContext:
    conversation = Conversation(channel=ConversationChannel.TEXT)
    db_session.add(conversation)
    await db_session.flush()
    return ToolContext(session=db_session, conversation=conversation, now=datetime.now(timezone.utc))


async def _noop_sleep(_seconds):
    return None


def _call(call_id, name, args):
    return LLMResponse(text=None, tool_calls=[ToolCall(call_id, name, args)])


def _say(text):
    return LLMResponse(text=text, tool_calls=[])


async def test_approve_flow_issues_refund(db_session):
    ctx = await _ctx(db_session)
    llm = FakeLLM([
        _call("1", "lookup_customer", {"email": "aarav.sharma@example.com"}),
        _call("2", "check_refund_eligibility", {"order_id": "ORD-1001"}),
        _call("3", "issue_refund", {"order_id": "ORD-1001"}),
        _say("Your refund has been processed."),
    ])
    result = await run_agent("I want a refund for ORD-1001", llm=llm, ctx=ctx)

    assert result.verdict == "approve"
    assert "processed" in result.answer.lower()
    order = await db_session.get(Order, "ORD-1001")
    assert order.refunded_at is not None


async def test_deny_flow_holds_the_line(db_session):
    ctx = await _ctx(db_session)
    llm = FakeLLM([
        _call("1", "lookup_customer", {"email": "sneha.pillai@example.com"}),
        _call("2", "check_refund_eligibility", {"order_id": "ORD-1140"}),
        _say("Sorry, this order is outside the 30-day refund window."),
    ])
    result = await run_agent("refund ORD-1140", llm=llm, ctx=ctx)

    assert result.verdict == "deny"
    order = await db_session.get(Order, "ORD-1140")
    assert order.refunded_at is None


async def test_escalate_flow_opens_ticket(db_session):
    ctx = await _ctx(db_session)
    llm = FakeLLM([
        _call("1", "lookup_customer", {"email": "aarav.sharma@example.com"}),
        _call("2", "check_refund_eligibility", {"order_id": "ORD-1002"}),
        _call("3", "escalate_to_manager", {"order_id": "ORD-1002", "reason": "above the approval limit"}),
        _say("This has been sent to a manager for review."),
    ])
    result = await run_agent("refund my macbook ORD-1002", llm=llm, ctx=ctx)

    assert result.verdict == "escalate"


async def test_retry_then_succeeds(db_session):
    ctx = await _ctx(db_session)
    llm = FlakyLLM(2, [_say("Hi, how can I help with your refund?")])
    result = await run_agent("hello", llm=llm, ctx=ctx, sleep=_noop_sleep)

    assert "help" in result.answer.lower()
    assert any(s.type == "retry" for s in result.steps)


async def test_total_llm_failure_degrades_gracefully(db_session):
    ctx = await _ctx(db_session)
    llm = FlakyLLM(99, [])  # never recovers
    result = await run_agent("hello", llm=llm, ctx=ctx, max_retries=2, sleep=_noop_sleep)

    assert "trouble" in result.answer.lower()
    assert any(s.type == "error" for s in result.steps)


async def test_max_steps_cap(db_session):
    ctx = await _ctx(db_session)
    result = await run_agent("loop forever", llm=AlwaysToolLLM(), ctx=ctx, max_steps=3, sleep=_noop_sleep)

    assert result.capped is True
    assert len([s for s in result.steps if s.type == "llm_call"]) == 3


async def test_hallucinated_tool_is_fed_back_and_recovers(db_session):
    ctx = await _ctx(db_session)
    llm = FakeLLM([
        _call("1", "teleport_order", {"foo": "bar"}),  # not a real tool
        _say("Let me try that again."),
    ])
    result = await run_agent("do something undefined", llm=llm, ctx=ctx)

    tool_results = [s for s in result.steps if s.type == "tool_result"]
    assert tool_results and tool_results[0].status == "error"
    assert "try" in result.answer.lower()
