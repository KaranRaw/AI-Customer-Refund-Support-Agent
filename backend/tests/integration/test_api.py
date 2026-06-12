"""In-process HTTP tests for the API, with a fake LLM injected (no live calls)."""

import asyncio
from datetime import datetime, timezone

import httpx
import pytest_asyncio
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.deps import get_llm_client
from app.config import get_settings
from app.db import models  # noqa: F401 - import registers models on Base.metadata
from app.db.database import Base, get_session
from app.db.seed import _build_customers, _build_orders
from app.llm.client import LLMResponse, ToolCall
from app.main import app


class FakeLLM:
    def __init__(self, responses, summary="Aarav requested a refund; it was escalated to a manager."):
        self._responses = list(responses)
        self._summary = summary

    async def chat_with_tools(self, messages, tools):
        return self._responses.pop(0)

    async def complete(self, messages):
        return self._summary


def call(call_id, name, args):
    return LLMResponse(text=None, tool_calls=[ToolCall(call_id, name, args)])


def say(text):
    return LLMResponse(text=text, tool_calls=[])


def set_llm(responses):
    app.dependency_overrides[get_llm_client] = lambda: FakeLLM(responses)


def _test_database_url() -> str:
    base, _, _name = get_settings().database_url.rpartition("/")
    return f"{base}/refund_agent_test"


@pytest_asyncio.fixture
async def client():
    engine = create_async_engine(_test_database_url())
    async with engine.begin() as conn:
        # Drop first so model changes (e.g. new columns) take effect on a reused test DB.
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        for table in reversed(Base.metadata.sorted_tables):
            await session.execute(delete(table))
        session.add_all(_build_customers())
        session.add_all(_build_orders(datetime.now(timezone.utc)))
        await session.commit()

    async def override_get_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client
    app.dependency_overrides.clear()
    await engine.dispose()


async def test_chat_approve_persists_and_shows_in_history(client):
    set_llm([
        call("1", "lookup_customer", {"email": "aarav.sharma@example.com"}),
        call("2", "check_refund_eligibility", {"order_id": "ORD-1001"}),
        call("3", "issue_refund", {"order_id": "ORD-1001"}),
        say("Your refund has been processed."),
    ])
    response = await client.post("/chat", json={"message": "refund ORD-1001"})
    assert response.status_code == 200
    body = response.json()
    assert body["verdict"] == "approve"
    assert "processed" in body["reply"].lower()
    conversation_id = body["conversation_id"]

    cases = (await client.get("/admin/cases")).json()
    case = next(c for c in cases if c["conversation_id"] == conversation_id)
    assert case["verdict"] == "approve"
    assert case["step_count"] > 0

    detail = (await client.get(f"/admin/cases/{conversation_id}")).json()
    assert len(detail["steps"]) == case["step_count"]
    assert detail["steps"][0]["step_no"] == 1


async def test_chat_deny_records_verdict_in_history(client):
    set_llm([
        call("1", "lookup_customer", {"email": "sneha.pillai@example.com"}),
        call("2", "check_refund_eligibility", {"order_id": "ORD-1140"}),
        say("Sorry, that order is outside the 30-day refund window."),
    ])
    response = await client.post("/chat", json={"message": "refund ORD-1140"})
    body = response.json()
    assert body["verdict"] == "deny"
    conversation_id = body["conversation_id"]

    cases = (await client.get("/admin/cases")).json()
    case = next(c for c in cases if c["conversation_id"] == conversation_id)
    assert case["verdict"] == "deny"  # denied cases now show their verdict in history


async def test_chat_empty_message_is_422(client):
    response = await client.post("/chat", json={"message": ""})
    assert response.status_code == 422


async def test_chat_multiturn_keeps_same_conversation(client):
    set_llm([
        call("1", "request_more_info", {"missing_field": "order id"}),
        say("Sure — what's your order ID?"),
    ])
    first = await client.post("/chat", json={"message": "I want a refund"})
    conversation_id = first.json()["conversation_id"]

    set_llm([say("Thanks, looking into it.")])
    second = await client.post(
        "/chat", json={"message": "ORD-1001", "conversation_id": conversation_id}
    )
    assert second.json()["conversation_id"] == conversation_id


async def test_close_conversation_keeps_escalation_open_and_blocks_posts(client):
    set_llm([
        call("1", "check_refund_eligibility", {"order_id": "ORD-1002"}),
        call("2", "escalate_to_manager", {"order_id": "ORD-1002", "reason": "over threshold"}),
        say("Sent to a manager for review."),
    ])
    first = await client.post(
        "/chat",
        json={"message": "refund ORD-1002", "customer_email": "aarav.sharma@example.com"},
    )
    cid = first.json()["conversation_id"]

    closed = await client.post(f"/conversations/{cid}/close")
    assert closed.status_code == 200
    state = closed.json()
    assert state["status"] == "closed"
    assert state["closed_at"] is not None
    assert state["verdict"] == "escalate"

    # Closing the chat is a separate lifecycle — it must NOT resolve the escalation.
    detail = (await client.get(f"/admin/cases/{cid}")).json()
    assert detail["escalation"]["status"] == "open"

    # History reflects the closed state (powers "View chat").
    history = (await client.get(f"/conversations/{cid}/messages")).json()
    assert history["status"] == "closed"
    assert history["closed_at"] is not None

    # And a closed conversation refuses further messages.
    set_llm([say("should not run")])
    blocked = await client.post("/chat", json={"message": "more", "conversation_id": cid})
    assert blocked.status_code == 409


async def test_close_unknown_conversation_404(client):
    response = await client.post("/conversations/999999/close")
    assert response.status_code == 404


async def test_case_summary_facts_then_generate_and_cache(client):
    set_llm([
        call("1", "check_refund_eligibility", {"order_id": "ORD-1002"}),
        call("2", "escalate_to_manager", {"order_id": "ORD-1002", "reason": "over threshold"}),
        say("Sent to a manager for review."),
    ])
    first = await client.post(
        "/chat",
        json={"message": "refund ORD-1002", "customer_email": "aarav.sharma@example.com"},
    )
    cid = first.json()["conversation_id"]

    # Before generating: no summary yet, but the code-derived fact chips are present.
    detail = (await client.get(f"/admin/cases/{cid}")).json()
    assert detail["ai_summary"] is None
    labels = [f["label"] for f in detail["summary_facts"]]
    assert any("checks passed" in label for label in labels)
    assert any(label.startswith("Over") for label in labels)  # over ₹50,000 → warn chip

    # Generate the summary.
    gen = await client.post(f"/admin/cases/{cid}/summary")
    assert gen.status_code == 200
    body = gen.json()
    assert body["summary"]
    assert body["step_count"] > 0

    # Cached: re-reading the case returns the stored summary + timestamp.
    detail2 = (await client.get(f"/admin/cases/{cid}")).json()
    assert detail2["ai_summary"] == body["summary"]
    assert detail2["ai_summary_at"] is not None


async def test_case_summary_unknown_404(client):
    assert (await client.post("/admin/cases/999999/summary")).status_code == 404


async def test_case_detail_unknown_id_404(client):
    response = await client.get("/admin/cases/999999")
    assert response.status_code == 404


async def test_admin_stream_yields_published_events():
    import json

    from app.api.routes.admin import stream
    from app.events.bus import event_bus

    response = await stream(conversation_id=None)
    assert response.media_type == "text/event-stream"

    generator = response.body_iterator
    try:
        first = await asyncio.wait_for(generator.__anext__(), timeout=2)
        assert first.startswith("retry:")  # immediate reconnect hint on connect

        await event_bus.publish({"conversation_id": 7, "step_no": 1, "type": "llm_call"})
        chunk = await asyncio.wait_for(generator.__anext__(), timeout=2)
        assert json.loads(chunk.removeprefix("data: ").strip())["type"] == "llm_call"
    finally:
        await generator.aclose()
