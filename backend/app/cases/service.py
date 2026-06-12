"""Read service for the admin observability views — case history, case detail, and the
on-demand AI case summary.

Keeps the query + assembly logic out of the route handlers (which stay thin),
the same way the chat route delegates to agent.runner.
"""

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import (
    CaseCustomer,
    CaseDetail,
    CaseEscalation,
    CaseFact,
    CaseSummary,
    CaseSummaryResult,
    OrderDetail,
    StepOut,
)
from app.db.models import AgentStep, Conversation, Customer, Escalation, Order, RefundRequest
from app.llm.client import LLMClient, system_message, user_message
from app.policy.engine import PolicyConfig, check_refund_eligibility, load_policy_config


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


async def _latest_escalation(session: AsyncSession, conversation_id: int) -> Escalation | None:
    return (
        await session.execute(
            select(Escalation)
            .join(RefundRequest, Escalation.refund_request_id == RefundRequest.id)
            .where(RefundRequest.conversation_id == conversation_id)
            .order_by(Escalation.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


# ── Key-fact chips: derived from the policy engine, never from the LLM ────────


def _fail_chip(name: str, order: Order, config: PolicyConfig) -> CaseFact:
    if name == "amount_threshold":
        return CaseFact(
            label=f"Over {config.currency} {config.manager_approval_threshold:,.0f}", tone="warn"
        )
    if name == "return_window":
        return CaseFact(label="Out of window", tone="warn")
    if name == "item_condition":
        if order.is_final_sale:
            return CaseFact(label="Final sale", tone="warn")
        if order.is_opened and not order.is_defective:
            return CaseFact(label="Opened item", tone="warn")
        return CaseFact(label="Item not eligible", tone="warn")
    if name == "already_refunded":
        return CaseFact(label="Already refunded", tone="warn")
    return CaseFact(label="Ownership mismatch", tone="warn")


def _summary_facts(order: Order | None, customer: Customer | None, *, now: datetime) -> list[CaseFact]:
    """The hard facts an admin should see at a glance — computed in code so the AI
    summary can never hallucinate the numbers that decide the case."""
    if order is None or customer is None:
        return []
    config = load_policy_config()
    result = check_refund_eligibility(order, customer, now=now, config=config)
    passed = sum(1 for check in result.checks if check.passed)
    facts: list[CaseFact] = [CaseFact(label=f"{passed}/{len(result.checks)} checks passed")]
    for check in result.checks:
        if not check.passed:
            facts.append(_fail_chip(check.name, order, config))
    if passed == len(result.checks):  # an approve — surface a positive context chip
        facts.append(CaseFact(label="Defective — covered" if order.is_defective else "In window · eligible"))
    return facts[:3]


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

    customer_record = (
        await session.get(Customer, conversation.customer_id)
        if conversation.customer_id is not None
        else None
    )
    customer = (
        CaseCustomer(
            id=customer_record.id,
            name=customer_record.name,
            email=customer_record.email,
            tier=_enum_value(customer_record.tier),
        )
        if customer_record is not None
        else None
    )

    order_record = (
        await session.get(Order, conversation.order_id)
        if conversation.order_id is not None
        else None
    )
    order = None
    if order_record is not None:
        threshold = load_policy_config().manager_approval_threshold
        order = OrderDetail(
            id=order_record.id,
            product_name=order_record.product_name,
            amount=float(order_record.amount),
            currency=order_record.currency,
            delivered_at=order_record.delivered_at,
            is_opened=order_record.is_opened,
            is_final_sale=order_record.is_final_sale,
            is_defective=order_record.is_defective,
            over_threshold=order_record.amount > threshold,
        )

    escalation_row = await _latest_escalation(session, conversation_id)
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
        ai_summary=conversation.ai_summary,
        ai_summary_at=conversation.ai_summary_at,
        summary_facts=_summary_facts(order_record, customer_record, now=datetime.now(timezone.utc)),
    )


# ── AI case summary (the meta use of the LLM: summarizing the agent's own run) ──

_SUMMARY_SYSTEM = (
    "You write a short case summary for a support manager reviewing an AI refund agent's "
    "decisions. Use ONLY the facts provided — never invent order details, amounts, or outcomes. "
    "Write 2-3 plain sentences: what the customer requested, what the policy checks found, and "
    "what the agent decided and why. No greeting, no sign-off, no bullet points."
)


def _summary_context(
    conversation: Conversation,
    order: Order | None,
    customer: Customer | None,
    escalation: Escalation | None,
    *,
    now: datetime,
) -> str:
    lines: list[str] = []
    if customer is not None:
        lines.append(f"Customer: {customer.name} ({_enum_value(customer.tier)} tier)")
    if order is not None:
        config = load_policy_config()
        lines.append(f"Order: {order.product_name} — {order.currency} {order.amount:,.0f}")
        if order.delivered_at is not None:
            lines.append(f"Delivered: {order.delivered_at.date().isoformat()}")
        lines.append(
            f"Condition: opened={order.is_opened}, defective={order.is_defective}, "
            f"final_sale={order.is_final_sale}"
        )
        over = order.amount > config.manager_approval_threshold
        lines.append(
            f"Manager-approval threshold: {order.currency} {config.manager_approval_threshold:,.0f} "
            f"({'over' if over else 'under'})"
        )
        if customer is not None:
            result = check_refund_eligibility(order, customer, now=now, config=config)
            passed = sum(1 for c in result.checks if c.passed)
            lines.append(f"Policy checks ({passed}/{len(result.checks)} passed):")
            lines += [
                f"  - {c.name}: {'PASS' if c.passed else 'FAIL'} — {c.detail}" for c in result.checks
            ]
    lines.append(f"Customer's stated reason: {conversation.refund_reason or 'none given'}")
    lines.append(f"Agent verdict: {(_enum_value(conversation.verdict) or 'none').upper()}")
    if escalation is not None:
        lines.append(f"Escalation: ticket E-{escalation.id}, status {escalation.status.value}")
    return "\n".join(lines)


async def generate_case_summary(
    session: AsyncSession, conversation_id: int, llm: LLMClient, *, now: datetime
) -> CaseSummaryResult | None:
    """Generate (and cache) a manager-facing summary of the case. Regenerate = call again."""
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None:
        return None

    customer = (
        await session.get(Customer, conversation.customer_id)
        if conversation.customer_id is not None
        else None
    )
    order = (
        await session.get(Order, conversation.order_id)
        if conversation.order_id is not None
        else None
    )
    escalation = await _latest_escalation(session, conversation_id)
    steps = (
        await session.execute(
            select(AgentStep).where(AgentStep.conversation_id == conversation_id)
        )
    ).scalars().all()

    context = _summary_context(conversation, order, customer, escalation, now=now)
    summary = (
        await llm.complete([system_message(_SUMMARY_SYSTEM), user_message(f"Case facts:\n{context}")])
    ).strip()

    conversation.ai_summary = summary
    conversation.ai_summary_at = now
    await session.commit()

    model = next((step.model for step in steps if step.model), None)
    return CaseSummaryResult(
        conversation_id=conversation_id,
        summary=summary,
        generated_at=now,
        step_count=len(steps),
        model=model,
    )
