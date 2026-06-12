"""Read service for a customer's orders (the Orders page)."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import OrderListItem
from app.db.models import Escalation, EscalationStatus, Order, RefundRequest


async def list_customer_orders(session: AsyncSession, customer_id: str) -> list[OrderListItem]:
    orders = (
        await session.execute(
            select(Order).where(Order.customer_id == customer_id).order_by(Order.id)
        )
    ).scalars().all()

    # Surface an open escalation back to the customer as "refund in review · ticket",
    # and remember which conversation raised it so "View chat" can reopen that thread.
    tickets: dict[str, str] = {}
    convs: dict[str, int] = {}
    order_ids = [order.id for order in orders]
    if order_ids:
        rows = (
            await session.execute(
                select(RefundRequest.order_id, Escalation.id, RefundRequest.conversation_id)
                .join(Escalation, Escalation.refund_request_id == RefundRequest.id)
                .where(
                    RefundRequest.order_id.in_(order_ids),
                    Escalation.status == EscalationStatus.OPEN,
                )
            )
        ).all()
        for order_id, escalation_id, conversation_id in rows:
            tickets[order_id] = f"E-{escalation_id}"
            convs[order_id] = conversation_id

    return [
        OrderListItem(
            id=order.id,
            product_name=order.product_name,
            amount=float(order.amount),
            currency=order.currency,
            status=order.status.value if order.status else "",
            delivered_at=order.delivered_at,
            refunded=order.refunded_at is not None,
            # A refunded order is settled — never show a stale "in review" ticket on it.
            refund_ticket=None if order.refunded_at is not None else tickets.get(order.id),
            conversation_id=None if order.refunded_at is not None else convs.get(order.id),
        )
        for order in orders
    ]
