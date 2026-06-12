"""Read service for the admin observability views — case history and case detail.

Keeps the query + assembly logic out of the route handlers (which stay thin),
the same way the chat route delegates to agent.runner.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import (
    CaseCustomer,
    CaseDetail,
    CaseEscalation,
    CaseSummary,
    OrderDetail,
    StepOut,
)
from app.db.models import AgentStep, Conversation, Customer, Escalation, Order, RefundRequest
from app.policy.engine import load_policy_config


def _enum_value(value):
    return value.value if value is not None and hasattr(value, "value") else value


def _step_out(step: AgentStep) -> StepOut:
    return StepOut(
        id=step.id,
        step_no=step.step_no,
        created_at=step.created_at,
        type=step.type.value,
        tool_name=step.tool_name,
        input=step.input_json,
        output=step.output_json,
        status=step.status.value,
        latency_ms=step.latency_ms,
        model=step.model,
        tokens_in=step.tokens_in,
        tokens_out=step.tokens_out,
    )


async def list_cases(session: AsyncSession) -> list[CaseSummary]:
    step_count = (
        select(func.count(AgentStep.id))
        .where(AgentStep.conversation_id == Conversation.id)
        .scalar_subquery()
    )
    stmt = (
        select(
            Conversation.id,
            Customer.name,
            Conversation.verdict,
            Order.id,
            Order.product_name,
            Order.amount,
            Order.currency,
            Conversation.started_at,
            step_count,
        )
        .outerjoin(Customer, Conversation.customer_id == Customer.id)
        .outerjoin(Order, Conversation.order_id == Order.id)
        .order_by(Conversation.started_at.desc())
    )
    rows = (await session.execute(stmt)).all()
    return [
        CaseSummary(
            conversation_id=cid,
            customer_name=name,
            verdict=_enum_value(verdict),
            order_id=order_id,
            order_product=product,
            order_amount=float(amount) if amount is not None else None,
            currency=currency,
            created_at=started_at,
            step_count=count,
        )
        for cid, name, verdict, order_id, product, amount, currency, started_at, count in rows
    ]


async def get_case_detail(session: AsyncSession, conversation_id: int) -> CaseDetail | None:
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None:
        return None

    customer = None
    if conversation.customer_id is not None:
        record = await session.get(Customer, conversation.customer_id)
        if record is not None:
            customer = CaseCustomer(
                id=record.id, name=record.name, email=record.email, tier=_enum_value(record.tier)
            )

    order = None
    if conversation.order_id is not None:
        record = await session.get(Order, conversation.order_id)
        if record is not None:
            threshold = load_policy_config().manager_approval_threshold
            order = OrderDetail(
                id=record.id,
                product_name=record.product_name,
                amount=float(record.amount),
                currency=record.currency,
                delivered_at=record.delivered_at,
                is_opened=record.is_opened,
                is_final_sale=record.is_final_sale,
                is_defective=record.is_defective,
                over_threshold=record.amount > threshold,
            )

    escalation_row = (
        await session.execute(
            select(Escalation)
            .join(RefundRequest, Escalation.refund_request_id == RefundRequest.id)
            .where(RefundRequest.conversation_id == conversation_id)
            .order_by(Escalation.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    escalation = (
        CaseEscalation(
            id=escalation_row.id,
            ref=f"E-{escalation_row.id}",
            assigned_to=escalation_row.assigned_to,
            reason=escalation_row.reason,
            status=escalation_row.status.value,
        )
        if escalation_row is not None
        else None
    )

    steps = (
        await session.execute(
            select(AgentStep)
            .where(AgentStep.conversation_id == conversation_id)
            .order_by(AgentStep.step_no)
        )
    ).scalars().all()

    return CaseDetail(
        conversation_id=conversation_id,
        verdict=_enum_value(conversation.verdict),
        channel=conversation.channel.value,
        refund_reason=conversation.refund_reason,
        customer=customer,
        order=order,
        escalation=escalation,
        steps=[_step_out(step) for step in steps],
    )
