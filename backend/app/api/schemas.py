"""Request/response models — the validated API contract."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: int | None = None
    customer_email: str | None = None  # set when a signed-in customer is chatting


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=200)


class OrderBrief(BaseModel):
    id: str
    product_name: str
    amount: float
    currency: str
    delivered_at: datetime | None = None


class ChatResponse(BaseModel):
    conversation_id: int
    reply: str
    verdict: str | None = None
    order: OrderBrief | None = None  # the order the agent focused on (-> OrderCard)
    ticket: str | None = None  # escalation ticket ref, e.g. "E-7" (-> TicketStrip)
    quick_replies: list[str] | None = None  # clickable options (e.g. refund reasons)


class StepOut(BaseModel):
    id: int
    step_no: int
    created_at: datetime
    type: str
    tool_name: str | None = None
    input: dict[str, Any] | None = None
    output: dict[str, Any] | None = None
    status: str
    latency_ms: int | None = None
    model: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None


class CaseSummary(BaseModel):
    conversation_id: int
    customer_name: str | None = None
    verdict: str | None = None
    order_id: str | None = None
    order_product: str | None = None
    order_amount: float | None = None
    currency: str | None = None
    created_at: datetime
    step_count: int


class CaseCustomer(BaseModel):
    id: str
    name: str
    email: str
    tier: str | None = None


class OrderDetail(BaseModel):
    id: str
    product_name: str
    amount: float
    currency: str
    delivered_at: datetime | None = None
    is_opened: bool
    is_final_sale: bool
    is_defective: bool
    over_threshold: bool


class CaseEscalation(BaseModel):
    id: int
    ref: str
    assigned_to: str
    reason: str
    status: str


class CaseFact(BaseModel):
    label: str
    tone: str = "neutral"  # "neutral" | "warn" — code-derived chip, never the LLM's words


class CaseDetail(BaseModel):
    conversation_id: int
    verdict: str | None = None
    channel: str
    refund_reason: str | None = None
    customer: CaseCustomer | None = None
    order: OrderDetail | None = None
    escalation: CaseEscalation | None = None
    steps: list[StepOut]
    ai_summary: str | None = None
    ai_summary_at: datetime | None = None
    summary_facts: list[CaseFact] = []  # key facts from the policy engine (shown as chips)


class CaseSummaryResult(BaseModel):
    conversation_id: int
    summary: str
    generated_at: datetime
    step_count: int
    model: str | None = None


class OrderListItem(BaseModel):
    id: str
    product_name: str
    amount: float
    currency: str
    status: str
    delivered_at: datetime | None = None
    refunded: bool
    refund_ticket: str | None = None  # open escalation ref, if a refund is in review
    conversation_id: int | None = None  # the chat where the open refund was raised
    # Policy engine says this order is still actionable (verdict != DENY) — used to rank
    # likely refund targets first in the chat starter.
    refund_eligible: bool = False


class ConversationCreated(BaseModel):
    conversation_id: int


class MessageOut(BaseModel):
    role: str
    text: str


class ConversationState(BaseModel):
    conversation_id: int
    status: str  # "active" | "closed"
    verdict: str | None = None
    closed_at: datetime | None = None


class ConversationHistory(BaseModel):
    conversation_id: int
    status: str = "active"
    verdict: str | None = None
    closed_at: datetime | None = None
    messages: list[MessageOut]


class ResolveRequest(BaseModel):
    decision: Literal["approve", "deny"]


class ResolveResult(BaseModel):
    decision: str
    verdict: str
    refunded: bool
