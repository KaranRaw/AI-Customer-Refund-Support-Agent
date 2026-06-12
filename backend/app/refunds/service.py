"""Refund and escalation actions (the side-effecting layer).

issue_refund re-validates eligibility before changing anything: the action itself is
the policy boundary, so an ineligible order cannot be refunded even if a caller —
including a manipulated LLM — invokes it directly.
"""

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Conversation,
    Customer,
    DecidedBy,
    Escalation,
    EscalationStatus,
    Order,
    RefundRequest,
    RefundStatus,
    Verdict,
)
from app.policy.engine import CheckResult, PolicyConfig, check_refund_eligibility

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RefundOutcome:
    executed: bool
    verdict: Verdict
    reason: str
    checks: list[CheckResult]
    refund_request_id: int | None = None


ASSIGNED_MANAGER = "Refunds Manager"


@dataclass(frozen=True)
class EscalationOutcome:
    escalated: bool
    reason: str
    assigned_to: str
    escalation_id: int | None = None
    refund_request_id: int | None = None


async def issue_refund(
    order: Order,
    customer: Customer,
    *,
    now: datetime,
    session: AsyncSession | None = None,
    conversation: Conversation | None = None,
    config: PolicyConfig | None = None,
) -> RefundOutcome:
    eligibility = check_refund_eligibility(order, customer, now=now, config=config)

    # Anything other than APPROVE is refused before any state changes, so a refund
    # cannot fire on an ineligible order regardless of what the caller intended.
    if eligibility.verdict is not Verdict.APPROVE:
        return RefundOutcome(
            executed=False,
            verdict=eligibility.verdict,
            reason=f"Refund not issued — eligibility is {eligibility.verdict.value.upper()}. {eligibility.reason}",
            checks=eligibility.checks,
        )

    if session is None or conversation is None:
        raise ValueError("issue_refund requires a session and conversation to execute an approved refund.")

    order.refunded_at = now
    refund_request = RefundRequest(
        order_id=order.id,
        conversation_id=conversation.id,
        status=RefundStatus.DECIDED,
        verdict=Verdict.APPROVE,
        reason=eligibility.reason,
        amount=order.amount,
        decided_by=DecidedBy.AGENT,
        resolved_at=now,
    )
    session.add(refund_request)
    await session.commit()
    await session.refresh(refund_request)

    logger.info(
        "Refund issued: order=%s amount=%s request=%s", order.id, order.amount, refund_request.id
    )
    return RefundOutcome(
        executed=True,
        verdict=Verdict.APPROVE,
        reason="Refund issued.",
        checks=eligibility.checks,
        refund_request_id=refund_request.id,
    )


async def escalate_to_manager(
    order: Order,
    reason: str,
    *,
    session: AsyncSession,
    conversation: Conversation,
) -> EscalationOutcome:
    # Defense-in-depth: an order must not accumulate multiple open escalations. If one is
    # already open (e.g. the customer asks again in a new chat), return it instead of
    # raising a duplicate ticket — the same guarantee issue_refund gives via refunded_at.
    existing = (
        await session.execute(
            select(Escalation)
            .join(RefundRequest, Escalation.refund_request_id == RefundRequest.id)
            .where(
                RefundRequest.order_id == order.id,
                Escalation.status == EscalationStatus.OPEN,
            )
            .order_by(Escalation.id)
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        logger.info(
            "Escalation already open for order=%s ticket=E-%s — reusing, not duplicating",
            order.id,
            existing.id,
        )
        return EscalationOutcome(
            escalated=True,
            reason=existing.reason,
            assigned_to=existing.assigned_to,
            escalation_id=existing.id,
            refund_request_id=existing.refund_request_id,
        )

    refund_request = RefundRequest(
        order_id=order.id,
        conversation_id=conversation.id,
        status=RefundStatus.DECIDED,
        verdict=Verdict.ESCALATE,
        reason=reason,
        amount=order.amount,
        decided_by=DecidedBy.AGENT,
    )
    session.add(refund_request)
    await session.flush()

    escalation = Escalation(
        refund_request_id=refund_request.id,
        reason=reason,
        status=EscalationStatus.OPEN,
        assigned_to=ASSIGNED_MANAGER,
    )
    session.add(escalation)
    await session.commit()
    await session.refresh(escalation)

    logger.info("Escalated to manager: order=%s ticket=E-%s", order.id, escalation.id)
    return EscalationOutcome(
        escalated=True,
        reason=reason,
        assigned_to=ASSIGNED_MANAGER,
        escalation_id=escalation.id,
        refund_request_id=refund_request.id,
    )


@dataclass(frozen=True)
class ResolveOutcome:
    decision: str
    verdict: Verdict
    refunded: bool
    escalation_id: int


async def resolve_escalation(
    session: AsyncSession, escalation_id: int, decision: str, *, now: datetime
) -> ResolveOutcome | None:
    """A (mock) manager resolves an open escalation.

    APPROVE issues the refund — the manager's authority is exactly what the escalate
    verdict is for — and DENY simply closes it. Either way the ticket flips OPEN ->
    RESOLVED. Returns None (no-op) if the escalation is missing or already resolved.
    """
    escalation = await session.get(Escalation, escalation_id)
    if escalation is None or escalation.status is not EscalationStatus.OPEN:
        return None

    refund_request = await session.get(RefundRequest, escalation.refund_request_id)
    order = await session.get(Order, refund_request.order_id)
    conversation = await session.get(Conversation, refund_request.conversation_id)

    approved = decision == "approve"
    verdict = Verdict.APPROVE if approved else Verdict.DENY

    escalation.status = EscalationStatus.RESOLVED
    refund_request.status = RefundStatus.RESOLVED
    refund_request.verdict = verdict
    refund_request.decided_by = DecidedBy.MANAGER
    refund_request.resolved_at = now

    refunded = False
    if approved and order is not None and order.refunded_at is None:
        order.refunded_at = now
        refunded = True
    if conversation is not None:
        conversation.verdict = verdict

    await session.commit()
    logger.info(
        "Manager resolved escalation E-%s as %s (order=%s, refunded=%s)",
        escalation_id,
        decision,
        refund_request.order_id,
        refunded,
    )
    return ResolveOutcome(decision, verdict, refunded, escalation_id)
