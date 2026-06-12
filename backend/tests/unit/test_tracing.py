"""Tests for the tracing layer: steps are persisted to agent_steps and streamed live."""

from datetime import datetime, timezone

from sqlalchemy import select

from app.agent.loop import run_agent
from app.agent.tools import ToolContext
from app.agent.tracing import Tracer
from app.db.models import AgentStep, Conversation, ConversationChannel
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


async def _conversation(db_session) -> Conversation:
    conversation = Conversation(channel=ConversationChannel.TEXT)
    db_session.add(conversation)
    await db_session.flush()
    return conversation


async def test_steps_are_persisted_to_agent_steps(db_session):
    conversation = await _conversation(db_session)
    ctx = ToolContext(session=db_session, conversation=conversation, now=datetime.now(timezone.utc))
    tracer = Tracer(db_session, conversation.id, EventBus())

    llm = FakeLLM([
        _call("1", "lookup_customer", {"email": "aarav.sharma@example.com"}),
        _call("2", "check_refund_eligibility", {"order_id": "ORD-1001"}),
        _call("3", "issue_refund", {"order_id": "ORD-1001"}),
        _say("Your refund has been processed."),
    ])
    result = await run_agent("refund ORD-1001", llm=llm, ctx=ctx, emit=tracer.record)

    rows = (
        await db_session.execute(
            select(AgentStep)
            .where(AgentStep.conversation_id == conversation.id)
            .order_by(AgentStep.step_no)
        )
    ).scalars().all()

    assert len(rows) == len(result.steps)  # one row per emitted step
    assert rows[0].step_no == 1
    assert {r.type.value for r in rows} >= {"llm_call", "tool_call", "tool_result", "decision"}
    # the eligibility tool_result carries the 5 internal checks in its JSON payload
    elig = next(
        r for r in rows if r.tool_name == "check_refund_eligibility" and r.type.value == "tool_result"
    )
    assert len(elig.output_json["checks"]) == 5


async def test_events_are_streamed_to_a_subscriber(db_session):
    conversation = await _conversation(db_session)
    ctx = ToolContext(session=db_session, conversation=conversation, now=datetime.now(timezone.utc))
    bus = EventBus()
    queue = bus.subscribe()  # firehose
    tracer = Tracer(db_session, conversation.id, bus)

    llm = FakeLLM([
        _call("1", "lookup_customer", {"email": "aarav.sharma@example.com"}),
        _say("Hi, how can I help?"),
    ])
    await run_agent("hello", llm=llm, ctx=ctx, emit=tracer.record)

    received = []
    while not queue.empty():
        received.append(queue.get_nowait())

    assert received
    assert all(e["conversation_id"] == conversation.id for e in received)
    assert received[0]["step_no"] == 1
    assert "type" in received[0]


async def test_conversation_filter_isolates_streams():
    bus = EventBus()
    queue_a = bus.subscribe(conversation_id=1)

    await bus.publish({"conversation_id": 1, "step_no": 1, "type": "llm_call"})
    await bus.publish({"conversation_id": 2, "step_no": 1, "type": "llm_call"})

    received = []
    while not queue_a.empty():
        received.append(queue_a.get_nowait())

    assert len(received) == 1
    assert received[0]["conversation_id"] == 1
