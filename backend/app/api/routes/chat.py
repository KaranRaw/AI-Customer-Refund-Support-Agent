"""POST /chat — the customer entry point."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.runner import run_chat_turn
from app.api.deps import get_llm_client
from app.api.schemas import (
    ChatRequest,
    ChatResponse,
    ConversationCreated,
    ConversationHistory,
    ConversationState,
    MessageOut,
    OrderBrief,
)
from app.db.database import get_session
from app.db.models import Conversation, ConversationChannel, ConversationStatus, Message
from app.events.bus import event_bus
from app.llm.client import LLMClient

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    session: AsyncSession = Depends(get_session),
    llm: LLMClient = Depends(get_llm_client),
) -> ChatResponse:
    # A closed conversation is final — don't append to it. The UI mints a fresh one
    # for "Start a new chat", so this only fires on a stale/forged request.
    if request.conversation_id is not None:
        existing = await session.get(Conversation, request.conversation_id)
        if existing is not None and existing.status is ConversationStatus.CLOSED:
            raise HTTPException(status_code=409, detail="This conversation is closed.")
    result = await run_chat_turn(
        session,
        message=request.message,
        conversation_id=request.conversation_id,
        llm=llm,
        bus=event_bus,
        customer_email=request.customer_email,
    )
    order = (
        OrderBrief(
            id=result.order.id,
            product_name=result.order.product_name,
            amount=float(result.order.amount),
            currency=result.order.currency,
            delivered_at=result.order.delivered_at,
        )
        if result.order is not None
        else None
    )
    return ChatResponse(
        conversation_id=result.conversation_id,
        reply=result.reply,
        verdict=result.verdict,
        order=order,
        ticket=result.ticket,
        quick_replies=result.quick_replies,
    )


@router.post("/conversations", response_model=ConversationCreated)
async def create_conversation(
    session: AsyncSession = Depends(get_session),
) -> ConversationCreated:
    """Mint an empty conversation so chat + voice can share one thread (voice-first)."""
    conversation = Conversation(channel=ConversationChannel.TEXT)
    session.add(conversation)
    await session.commit()
    return ConversationCreated(conversation_id=conversation.id)


@router.get("/conversations/{conversation_id}/messages", response_model=ConversationHistory)
async def conversation_messages(
    conversation_id: int, session: AsyncSession = Depends(get_session)
) -> ConversationHistory:
    """Load a past conversation's messages — powers 'View chat' from the orders page."""
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    rows = (
        await session.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at, Message.id)
        )
    ).scalars().all()
    return ConversationHistory(
        conversation_id=conversation_id,
        status=conversation.status.value,
        verdict=conversation.verdict.value if conversation.verdict else None,
        closed_at=conversation.closed_at,
        messages=[MessageOut(role=m.role.value, text=m.content) for m in rows],
    )


@router.post("/conversations/{conversation_id}/close", response_model=ConversationState)
async def close_conversation(
    conversation_id: int, session: AsyncSession = Depends(get_session)
) -> ConversationState:
    """End a chat: flip it to CLOSED and stamp the time. Idempotent.

    This closes the *conversation* only — any open escalation/refund_request stays open
    until a manager resolves it. The two lifecycles are intentionally separate.
    """
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if conversation.status is not ConversationStatus.CLOSED:
        conversation.status = ConversationStatus.CLOSED
        conversation.closed_at = datetime.now(timezone.utc)
        await session.commit()
    return ConversationState(
        conversation_id=conversation.id,
        status=conversation.status.value,
        verdict=conversation.verdict.value if conversation.verdict else None,
        closed_at=conversation.closed_at,
    )
