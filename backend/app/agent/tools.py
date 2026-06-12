"""LLM-visible tools and their dispatcher.

These are the only functions the model may call. Each takes a ToolContext plus the
arguments the model supplied and returns a JSON-serializable dict — ORM objects and
domain types never leak to the model. The fine-grained policy checks stay internal
to the engine; the model only sees the aggregated verdict.
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Conversation, Customer, Order
from app.policy.engine import check_refund_eligibility as run_eligibility
from app.refunds.service import escalate_to_manager as run_escalate
from app.refunds.service import issue_refund as run_issue_refund

_POLICY_PATH = Path(__file__).resolve().parents[1] / "policy" / "policy.md"


@dataclass
class ToolContext:
    session: AsyncSession
    conversation: Conversation
    now: datetime
    customer: Customer | None = None


def _order_to_dict(order: Order) -> dict:
    # Descriptive fields only — the policy-decision flags (condition, final-sale,
    # refund status) are deliberately withheld so the model cannot judge eligibility
    # itself and must defer to check_refund_eligibility.
    return {
        "id": order.id,
        "product_name": order.product_name,
        "category": order.category,
        "amount": float(order.amount),
        "currency": order.currency,
        "delivered_at": order.delivered_at.isoformat() if order.delivered_at else None,
        "status": order.status.value if order.status else None,
    }


def _customer_to_dict(customer: Customer) -> dict:
    return {
        "id": customer.id,
        "name": customer.name,
        "email": customer.email,
        "phone": customer.phone,
        "tier": customer.tier.value if customer.tier else None,
    }


async def lookup_customer(ctx: ToolContext, *, email: str | None = None, phone: str | None = None) -> dict:
    if not email and not phone:
        return {"ok": False, "error": "Provide an email or phone to look up a customer."}

    stmt = select(Customer).options(selectinload(Customer.orders))
    stmt = stmt.where(Customer.email == email) if email else stmt.where(Customer.phone == phone)
    customer = (await ctx.session.execute(stmt)).scalar_one_or_none()
    if customer is None:
        return {"ok": True, "found": False}

    ctx.customer = customer
    ctx.conversation.customer_id = customer.id
    return {
        "ok": True,
        "found": True,
        "customer": _customer_to_dict(customer),
        "orders": [_order_to_dict(o) for o in customer.orders],
    }


async def get_order(ctx: ToolContext, *, order_id: str) -> dict:
    order = await ctx.session.get(Order, order_id)
    if order is None:
        return {"ok": True, "found": False, "order_id": order_id}
    return {"ok": True, "found": True, "order": _order_to_dict(order)}


async def list_customer_orders(ctx: ToolContext, *, customer_id: str) -> dict:
    orders = (await ctx.session.execute(select(Order).where(Order.customer_id == customer_id))).scalars().all()
    return {"ok": True, "orders": [_order_to_dict(o) for o in orders]}


async def check_refund_eligibility(ctx: ToolContext, *, order_id: str) -> dict:
    order = await ctx.session.get(Order, order_id)
    if order is None:
        return {"ok": True, "found": False, "order_id": order_id}
    if ctx.customer is None:
        return {"ok": False, "error": "Identify the customer before checking eligibility."}

    result = run_eligibility(order, ctx.customer, now=ctx.now)
    return {
        "ok": True,
        "found": True,
        "verdict": result.verdict.value,
        "reason": result.reason,
        "checks": [{"name": c.name, "passed": c.passed, "detail": c.detail} for c in result.checks],
    }


async def issue_refund(ctx: ToolContext, *, order_id: str) -> dict:
    order = await ctx.session.get(Order, order_id)
    if order is None:
        return {"ok": True, "found": False, "order_id": order_id}
    if ctx.customer is None:
        return {"ok": False, "error": "Identify the customer before issuing a refund."}

    outcome = await run_issue_refund(
        order, ctx.customer, now=ctx.now, session=ctx.session, conversation=ctx.conversation
    )
    return {
        "ok": True,
        "executed": outcome.executed,
        "verdict": outcome.verdict.value,
        "reason": outcome.reason,
        "refund_request_id": outcome.refund_request_id,
    }


async def escalate_to_manager(ctx: ToolContext, *, order_id: str, reason: str) -> dict:
    order = await ctx.session.get(Order, order_id)
    if order is None:
        return {"ok": True, "found": False, "order_id": order_id}

    outcome = await run_escalate(order, reason, session=ctx.session, conversation=ctx.conversation)
    return {
        "ok": True,
        "escalated": outcome.escalated,
        "assigned_to": outcome.assigned_to,
        "escalation_id": outcome.escalation_id,
        "reason": outcome.reason,
    }


async def request_more_info(ctx: ToolContext, *, missing_field: str) -> dict:
    return {"ok": True, "missing_field": missing_field, "ask": f"Could you share your {missing_field}?"}


async def record_refund_reason(ctx: ToolContext, *, reason: str) -> dict:
    # Tracking only — stored on the conversation; it never influences the policy verdict.
    ctx.conversation.refund_reason = reason
    return {"ok": True, "recorded": True, "reason": reason}


async def get_policy_section(ctx: ToolContext, *, topic: str) -> dict:
    text = _POLICY_PATH.read_text(encoding="utf-8")
    sections = text.split("\n## ")
    matches = [s for s in sections if topic.lower() in s.lower()]
    body = "\n## ".join(matches) if matches else text
    return {"ok": True, "topic": topic, "text": body.strip()}


_TOOLS = {
    "lookup_customer": lookup_customer,
    "get_order": get_order,
    "list_customer_orders": list_customer_orders,
    "check_refund_eligibility": check_refund_eligibility,
    "issue_refund": issue_refund,
    "escalate_to_manager": escalate_to_manager,
    "request_more_info": request_more_info,
    "record_refund_reason": record_refund_reason,
    "get_policy_section": get_policy_section,
}


async def dispatch(name: str, arguments: dict, ctx: ToolContext) -> dict:
    tool = _TOOLS.get(name)
    if tool is None:
        return {"ok": False, "error": f"Unknown tool: {name}"}
    try:
        return await tool(ctx, **arguments)
    except TypeError as exc:
        return {"ok": False, "error": f"Invalid arguments for {name}: {exc}"}


def _schema(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
    }


# The tool menu advertised to the model (OpenAI function-calling format).
TOOL_SCHEMAS = [
    _schema(
        "lookup_customer",
        "Find a customer by email or phone, returning their profile and orders.",
        {"email": {"type": "string"}, "phone": {"type": "string"}},
        [],
    ),
    _schema(
        "get_order",
        "Fetch a single order and its condition flags by order ID.",
        {"order_id": {"type": "string"}},
        ["order_id"],
    ),
    _schema(
        "list_customer_orders",
        "List all orders belonging to a customer ID.",
        {"customer_id": {"type": "string"}},
        ["customer_id"],
    ),
    _schema(
        "check_refund_eligibility",
        "Evaluate an order against the refund policy and return the verdict "
        "(approve/deny/escalate) with the per-rule checks. Call this before issuing any refund.",
        {"order_id": {"type": "string"}},
        ["order_id"],
    ),
    _schema(
        "issue_refund",
        "Issue a refund for an order. Re-validates eligibility and only succeeds on an APPROVED order.",
        {"order_id": {"type": "string"}},
        ["order_id"],
    ),
    _schema(
        "escalate_to_manager",
        "Escalate an order to a manager for review, used when the verdict is escalate.",
        {"order_id": {"type": "string"}, "reason": {"type": "string"}},
        ["order_id", "reason"],
    ),
    _schema(
        "request_more_info",
        "Ask the customer for a missing piece of information.",
        {"missing_field": {"type": "string"}},
        ["missing_field"],
    ),
    _schema(
        "record_refund_reason",
        "Record the customer's stated reason for the refund (e.g. defective/bad quality, "
        "wrong item, not as described, no longer needed, other). For tracking only — it does "
        "NOT affect eligibility, which is decided solely by check_refund_eligibility.",
        {"reason": {"type": "string"}},
        ["reason"],
    ),
    _schema(
        "get_policy_section",
        "Retrieve the refund policy text relevant to a topic, to explain a decision.",
        {"topic": {"type": "string"}},
        ["topic"],
    ),
]
