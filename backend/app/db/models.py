"""Database models for the refund domain.

Categorical fields are stored as VARCHAR + CHECK (native_enum=False) using StrEnum
classes, giving typed values in Python and DB-level validation without the
migration friction of native PostgreSQL enum types. Money is Numeric (never float),
step payloads are JSONB, timestamps are timezone-aware.
"""

import enum
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


def _enum(enum_cls: type[enum.Enum]) -> Enum:
    """Store a StrEnum as its value in a VARCHAR + CHECK column."""
    return Enum(
        enum_cls,
        native_enum=False,
        values_callable=lambda cls: [member.value for member in cls],
    )


# ── Categorical value sets ────────────────────────────────────────────────


class CustomerTier(enum.StrEnum):
    REGULAR = "regular"
    VIP = "vip"


class OrderStatus(enum.StrEnum):
    PLACED = "placed"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


class ConversationChannel(enum.StrEnum):
    TEXT = "text"
    VOICE = "voice"


class ConversationStatus(enum.StrEnum):
    ACTIVE = "active"
    CLOSED = "closed"


class MessageRole(enum.StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class RefundStatus(enum.StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DECIDED = "decided"
    RESOLVED = "resolved"


class Verdict(enum.StrEnum):
    APPROVE = "approve"
    DENY = "deny"
    ESCALATE = "escalate"


class DecidedBy(enum.StrEnum):
    AGENT = "agent"
    MANAGER = "manager"


class StepType(enum.StrEnum):
    LLM_CALL = "llm_call"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    DECISION = "decision"
    ERROR = "error"
    RETRY = "retry"


class StepStatus(enum.StrEnum):
    SUCCESS = "success"
    ERROR = "error"
    RETRIED = "retried"


class EscalationStatus(enum.StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"


# ── Tables ──────────────────────────────────────────────────────────────────


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(32))
    tier: Mapped[CustomerTier] = mapped_column(
        _enum(CustomerTier), default=CustomerTier.REGULAR
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    orders: Mapped[list["Order"]] = relationship(back_populates="customer")


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)
    product_name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str | None] = mapped_column(String(40))
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    order_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[OrderStatus] = mapped_column(_enum(OrderStatus))
    is_final_sale: Mapped[bool] = mapped_column(Boolean, default=False)
    is_opened: Mapped[bool] = mapped_column(Boolean, default=False)
    is_defective: Mapped[bool] = mapped_column(Boolean, default=False)
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    customer: Mapped["Customer"] = relationship(back_populates="orders")


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[str | None] = mapped_column(
        ForeignKey("customers.id"), index=True
    )
    channel: Mapped[ConversationChannel] = mapped_column(
        _enum(ConversationChannel), default=ConversationChannel.TEXT
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    status: Mapped[ConversationStatus] = mapped_column(
        _enum(ConversationStatus), default=ConversationStatus.ACTIVE
    )
    # Stamped when the customer ends the chat — distinct from the refund/escalation
    # lifecycle, which the manager resolves separately.
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verdict: Mapped[Verdict | None] = mapped_column(_enum(Verdict))
    order_id: Mapped[str | None] = mapped_column(ForeignKey("orders.id"), index=True)
    # The customer's stated reason for the refund — tracking only, never feeds the policy.
    refund_reason: Mapped[str | None] = mapped_column(Text)
    # AI triage summary of the case for the admin panel — generated on demand, cached here.
    ai_summary: Mapped[str | None] = mapped_column(Text)
    ai_summary_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )
    refund_requests: Mapped[list["RefundRequest"]] = relationship(
        back_populates="conversation"
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id"), index=True
    )
    role: Mapped[MessageRole] = mapped_column(_enum(MessageRole))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")


class RefundRequest(Base):
    """A refund case and the anchor for its execution trace (agent_steps)."""

    __tablename__ = "refund_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), index=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id"), index=True
    )
    status: Mapped[RefundStatus] = mapped_column(
        _enum(RefundStatus), default=RefundStatus.PENDING
    )
    verdict: Mapped[Verdict | None] = mapped_column(_enum(Verdict))
    reason: Mapped[str | None] = mapped_column(Text)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    decided_by: Mapped[DecidedBy | None] = mapped_column(_enum(DecidedBy))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    order: Mapped["Order"] = relationship()
    conversation: Mapped["Conversation"] = relationship(
        back_populates="refund_requests"
    )
    steps: Mapped[list["AgentStep"]] = relationship(
        back_populates="refund_request",
        cascade="all, delete-orphan",
        order_by="AgentStep.step_no",
    )
    escalations: Mapped[list["Escalation"]] = relationship(
        back_populates="refund_request"
    )


class AgentStep(Base):
    """The reasoning-log spine. parent_step_id nests internal checks for a tree."""

    __tablename__ = "agent_steps"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), index=True)
    refund_request_id: Mapped[int | None] = mapped_column(
        ForeignKey("refund_requests.id"), index=True
    )
    step_no: Mapped[int] = mapped_column(Integer)
    type: Mapped[StepType] = mapped_column(_enum(StepType))
    tool_name: Mapped[str | None] = mapped_column(String(80))
    input_json: Mapped[dict | None] = mapped_column(JSONB)
    output_json: Mapped[dict | None] = mapped_column(JSONB)
    status: Mapped[StepStatus] = mapped_column(
        _enum(StepStatus), default=StepStatus.SUCCESS
    )
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    model: Mapped[str | None] = mapped_column(String(60))
    tokens_in: Mapped[int | None] = mapped_column(Integer)
    tokens_out: Mapped[int | None] = mapped_column(Integer)
    parent_step_id: Mapped[int | None] = mapped_column(
        ForeignKey("agent_steps.id"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    conversation: Mapped["Conversation"] = relationship()
    refund_request: Mapped["RefundRequest | None"] = relationship(back_populates="steps")
    parent: Mapped["AgentStep | None"] = relationship(
        back_populates="children", remote_side="AgentStep.id"
    )
    children: Mapped[list["AgentStep"]] = relationship(back_populates="parent")


class Escalation(Base):
    __tablename__ = "escalations"

    id: Mapped[int] = mapped_column(primary_key=True)
    refund_request_id: Mapped[int] = mapped_column(
        ForeignKey("refund_requests.id"), index=True
    )
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[EscalationStatus] = mapped_column(
        _enum(EscalationStatus), default=EscalationStatus.OPEN
    )
    assigned_to: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    refund_request: Mapped["RefundRequest"] = relationship(
        back_populates="escalations"
    )
