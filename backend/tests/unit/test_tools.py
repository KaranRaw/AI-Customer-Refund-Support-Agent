"""Tests for the LLM-visible tools and the dispatcher.

These run through dispatch() the way the agent loop will, against seeded data.
"""

from datetime import datetime, timezone

from app.agent.tools import ToolContext, dispatch
from app.db.models import Conversation, ConversationChannel


async def _ctx(db_session) -> ToolContext:
    conversation = Conversation(channel=ConversationChannel.TEXT)
    db_session.add(conversation)
    await db_session.flush()
    return ToolContext(session=db_session, conversation=conversation, now=datetime.now(timezone.utc))


async def test_lookup_customer_found_sets_context(db_session):
    ctx = await _ctx(db_session)
    result = await dispatch("lookup_customer", {"email": "aarav.sharma@example.com"}, ctx)
    assert result["found"] is True
    assert result["customer"]["tier"] == "vip"
    assert len(result["orders"]) == 3
    assert ctx.customer is not None


async def test_lookup_customer_not_found(db_session):
    ctx = await _ctx(db_session)
    result = await dispatch("lookup_customer", {"email": "nobody@example.com"}, ctx)
    assert result["found"] is False


async def test_get_order_found_and_missing(db_session):
    ctx = await _ctx(db_session)
    found = await dispatch("get_order", {"order_id": "ORD-1001"}, ctx)
    assert found["found"] is True
    assert found["order"]["currency"] == "INR"

    missing = await dispatch("get_order", {"order_id": "ORD-9999"}, ctx)
    assert missing["found"] is False


async def test_eligibility_requires_identified_customer(db_session):
    ctx = await _ctx(db_session)
    result = await dispatch("check_refund_eligibility", {"order_id": "ORD-1001"}, ctx)
    assert result["ok"] is False


async def test_eligibility_returns_verdict_and_all_checks(db_session):
    ctx = await _ctx(db_session)
    await dispatch("lookup_customer", {"email": "aarav.sharma@example.com"}, ctx)
    result = await dispatch("check_refund_eligibility", {"order_id": "ORD-1001"}, ctx)
    assert result["verdict"] == "approve"
    assert len(result["checks"]) == 5


async def test_issue_refund_tool_executes_when_eligible(db_session):
    ctx = await _ctx(db_session)
    await dispatch("lookup_customer", {"email": "aarav.sharma@example.com"}, ctx)
    result = await dispatch("issue_refund", {"order_id": "ORD-1001"}, ctx)
    assert result["executed"] is True
    assert result["verdict"] == "approve"


async def test_issue_refund_tool_refuses_ineligible(db_session):
    ctx = await _ctx(db_session)
    await dispatch("lookup_customer", {"email": "kavya.rao@example.com"}, ctx)  # owns ORD-1090
    result = await dispatch("issue_refund", {"order_id": "ORD-1090"}, ctx)
    assert result["executed"] is False
    assert result["verdict"] == "deny"


async def test_escalate_tool_opens_ticket(db_session):
    ctx = await _ctx(db_session)
    await dispatch("lookup_customer", {"email": "aarav.sharma@example.com"}, ctx)
    result = await dispatch("escalate_to_manager", {"order_id": "ORD-1002", "reason": "over limit"}, ctx)
    assert result["escalated"] is True
    assert result["assigned_to"]


async def test_get_policy_section_returns_text(db_session):
    ctx = await _ctx(db_session)
    result = await dispatch("get_policy_section", {"topic": "final sale"}, ctx)
    assert "final sale" in result["text"].lower()


async def test_dispatch_unknown_tool(db_session):
    ctx = await _ctx(db_session)
    result = await dispatch("delete_everything", {}, ctx)
    assert result["ok"] is False


async def test_dispatch_bad_arguments(db_session):
    ctx = await _ctx(db_session)
    result = await dispatch("get_order", {"wrong_arg": "x"}, ctx)
    assert result["ok"] is False
