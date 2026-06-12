"""Tests for the refund action layer.

The refusal path does not touch the database, so the forced-call attack — the core
holding-the-line guarantee — is verified purely in memory.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.models import (
    Conversation,
    ConversationChannel,
    Customer,
    CustomerTier,
    Escalation,
    EscalationStatus,
    Order,
    RefundRequest,
    Verdict,
)
from app.refunds.service import escalate_to_manager, issue_refund

NOW = datetime(2026, 6, 10, tzinfo=timezone.utc)
OWNER = Customer(id="cust-1", name="Aarav Sharma", email="aarav@example.com", tier=CustomerTier.REGULAR)


def make_order(**overrides) -> Order:
    defaults = dict(
        id="ORD-T",
        customer_id="cust-1",
        product_name="Test Product",
        amount=Decimal("10000"),
        delivered_at=NOW - timedelta(days=5),
        is_opened=False,
        is_defective=False,
        is_final_sale=False,
        refunded_at=None,
    )
    defaults.update(overrides)
    return Order(**defaults)


async def test_refuses_order_denied_by_window():
    order = make_order(delivered_at=NOW - timedelta(days=40))
    outcome = await issue_refund(order, OWNER, now=NOW)
    assert outcome.executed is False
    assert outcome.verdict is Verdict.DENY
    assert order.refunded_at is None


async def test_refuses_order_that_should_escalate():
    order = make_order(amount=Decimal("60000"))
    outcome = await issue_refund(order, OWNER, now=NOW)
    assert outcome.executed is False
    assert outcome.verdict is Verdict.ESCALATE
    assert order.refunded_at is None


async def test_refuses_opened_nondefective_even_when_forced():
    order = make_order(is_opened=True, is_defective=False)
    outcome = await issue_refund(order, OWNER, now=NOW, session=None)
    assert outcome.executed is False
    assert order.refunded_at is None


async def test_refusal_reason_explains_why_and_keeps_checks():
    order = make_order(is_final_sale=True)
    outcome = await issue_refund(order, OWNER, now=NOW)
    assert "not issued" in outcome.reason.lower()
    assert outcome.checks


# ── DB-backed: approval executes, escalation opens a ticket, attack stays blocked ──


async def _load_order(session, order_id: str) -> Order:
    result = await session.execute(
        select(Order).where(Order.id == order_id).options(selectinload(Order.customer))
    )
    return result.scalar_one()


async def _new_conversation(session, customer_id: str) -> Conversation:
    conversation = Conversation(customer_id=customer_id, channel=ConversationChannel.TEXT)
    session.add(conversation)
    await session.flush()
    return conversation


async def test_issue_refund_executes_on_approved_order(db_session):
    now = datetime.now(timezone.utc)
    order = await _load_order(db_session, "ORD-1001")
    conversation = await _new_conversation(db_session, order.customer_id)

    outcome = await issue_refund(
        order, order.customer, now=now, session=db_session, conversation=conversation
    )

    assert outcome.executed is True
    assert order.refunded_at is not None
    refund_request = (
        await db_session.execute(
            select(RefundRequest).where(RefundRequest.id == outcome.refund_request_id)
        )
    ).scalar_one()
    assert refund_request.verdict is Verdict.APPROVE
    assert refund_request.amount == order.amount


async def test_escalate_opens_a_manager_ticket(db_session):
    order = await _load_order(db_session, "ORD-1002")
    conversation = await _new_conversation(db_session, order.customer_id)

    outcome = await escalate_to_manager(
        order, "Amount over the approval limit",
        session=db_session, conversation=conversation,
    )

    assert outcome.escalated is True
    escalation = (
        await db_session.execute(
            select(Escalation).where(Escalation.id == outcome.escalation_id)
        )
    ).scalar_one()
    assert escalation.status is EscalationStatus.OPEN
    assert escalation.assigned_to == outcome.assigned_to


async def test_escalating_same_order_twice_reuses_the_open_ticket(db_session):
    order = await _load_order(db_session, "ORD-1002")  # over the threshold -> escalate

    conv1 = await _new_conversation(db_session, order.customer_id)
    first = await escalate_to_manager(order, "over the limit", session=db_session, conversation=conv1)

    # A second escalation — even from a different conversation — must reuse the open ticket.
    conv2 = await _new_conversation(db_session, order.customer_id)
    second = await escalate_to_manager(order, "asking again", session=db_session, conversation=conv2)

    assert second.escalation_id == first.escalation_id
    open_tickets = (
        await db_session.execute(
            select(Escalation)
            .join(RefundRequest, Escalation.refund_request_id == RefundRequest.id)
            .where(
                RefundRequest.order_id == "ORD-1002",
                Escalation.status == EscalationStatus.OPEN,
            )
        )
    ).scalars().all()
    assert len(open_tickets) == 1  # no duplicate raised


async def test_forced_refund_on_ineligible_seeded_order_persists_nothing(db_session):
    now = datetime.now(timezone.utc)
    order = await _load_order(db_session, "ORD-1090")  # opened, not defective -> DENY
    conversation = await _new_conversation(db_session, order.customer_id)

    outcome = await issue_refund(
        order, order.customer, now=now, session=db_session, conversation=conversation
    )

    assert outcome.executed is False
    assert order.refunded_at is None
    refunds = (await db_session.execute(select(RefundRequest))).scalars().all()
    assert refunds == []
