import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";

import {
  closeConversation,
  createConversation,
  getConversationMessages,
  getOrders,
  postChat,
} from "@/api/client";
import { BackButton } from "@/components/BackButton";
import { ChatPanel, type ClosedInfo } from "@/components/chat/ChatPanel";
import type { StarterOrder } from "@/components/chat/ChatStarter";
import { BoltIcon, LockIcon } from "@/components/icons";
import { useSession } from "@/lib/session";
import type { Customer, OrderBrief, OrderListItem, Verdict } from "@/types";
import "@/styles/chat.css";
import type { ChatMessage, OrderInfo } from "@/types/chat";

function initials(name: string): string {
  const parts = name.trim().split(/\s+/);
  return ((parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "")).toUpperCase() || "?";
}

function greetingFor(customer: Customer | null): ChatMessage {
  if (customer) {
    const firstName = customer.name.split(" ")[0];
    return {
      id: "greeting",
      role: "assistant",
      text: `Hi ${firstName}! I can see your account — tell me which order you need help with and what's wrong, and I'll sort out the refund.`,
    };
  }
  return {
    id: "greeting",
    role: "assistant",
    text:
      "Hi! I'm KaranKart's refund assistant. Share your order ID and the email you used at " +
      "checkout, and I'll help you with a refund.",
  };
}

function formatPrice(amount: number, currency: string): string {
  if (currency === "INR") {
    return new Intl.NumberFormat("en-IN", {
      style: "currency",
      currency: "INR",
      maximumFractionDigits: 0,
    }).format(amount);
  }
  return `${currency} ${amount}`;
}

function formatDate(iso: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function toOrderInfo(order: OrderBrief): OrderInfo {
  const date = formatDate(order.delivered_at);
  return {
    product: order.product_name,
    meta: date ? `${order.id} · delivered ${date}` : order.id,
    price: formatPrice(order.amount, order.currency),
  };
}

function toStarterOrder(order: OrderListItem): StarterOrder {
  const statusKind: StarterOrder["statusKind"] = order.refund_ticket
    ? "review"
    : order.refunded
      ? "refunded"
      : order.status === "delivered"
        ? "delivered"
        : "transit";
  const statusLabel =
    statusKind === "review"
      ? "Refund in review"
      : statusKind === "refunded"
        ? "Refunded"
        : statusKind === "delivered"
          ? "Delivered"
          : "In transit";
  const date = formatDate(order.delivered_at);
  const meta = [order.id, date ? `delivered ${date}` : null, formatPrice(order.amount, order.currency)]
    .filter(Boolean)
    .join(" · ");
  return {
    id: order.id,
    product: order.product_name,
    meta,
    statusKind,
    statusLabel,
    conversationId: order.conversation_id,
  };
}

// Most-likely refund target first: an open case, then policy-eligible, then most recent.
function rankForStarter(orders: OrderListItem[]): OrderListItem[] {
  const score = (o: OrderListItem) => (o.refund_ticket ? 0 : o.refund_eligible ? 1 : 2);
  return [...orders].sort((a, b) => {
    const byScore = score(a) - score(b);
    if (byScore !== 0) return byScore;
    const ad = a.delivered_at ? Date.parse(a.delivered_at) : 0;
    const bd = b.delivered_at ? Date.parse(b.delivered_at) : 0;
    return bd - ad;
  });
}

export function ChatPage() {
  const { customer } = useSession();
  const location = useLocation();
  const autoSentRef = useRef(false);
  const [messages, setMessages] = useState<ChatMessage[]>(() => [greetingFor(customer)]);
  const [conversationId, setConversationId] = useState<number | null>(null);
  const [typing, setTyping] = useState(false);
  // The latest verdict (sticky across follow-up turns) — drives the closing chips.
  const [outcome, setOutcome] = useState<Verdict | null>(null);
  const [closed, setClosed] = useState<ClosedInfo | null>(null);
  // Set when the user picks "I have another issue" so the closing chips hide until the
  // next verdict.
  const [closingDismissed, setClosingDismissed] = useState(false);
  const [orders, setOrders] = useState<OrderListItem[]>([]);

  const starterOrders = useMemo(
    () => rankForStarter(orders).slice(0, 3).map(toStarterOrder),
    [orders],
  );

  function addVoiceMessage(role: "user" | "assistant", text: string) {
    setMessages((prev) => [...prev, { id: crypto.randomUUID(), role, text }]);
  }

  // Mint the shared conversation (if needed) so voice + text continue the SAME thread —
  // the agent keeps context across both.
  async function ensureConversation(): Promise<number | null> {
    if (conversationId != null) return conversationId;
    try {
      const { conversation_id } = await createConversation();
      setConversationId(conversation_id);
      return conversation_id;
    } catch {
      return null;
    }
  }

  // Reopen an existing conversation in place — used by "View chat" and by tapping an
  // already-in-review order in the starter (so we never start a duplicate escalation).
  function loadConversation(convId: number) {
    getConversationMessages(convId)
      .then((data) => {
        setMessages(
          data.messages.map((m) => ({ id: crypto.randomUUID(), role: m.role, text: m.text })),
        );
        setConversationId(convId);
        setOutcome(data.verdict);
        setClosed(data.status === "closed" ? { at: data.closed_at, verdict: data.verdict } : null);
      })
      .catch(() => undefined);
  }

  async function handleSend(text: string) {
    if (typing) return;
    setMessages((prev) => [...prev, { id: crypto.randomUUID(), role: "user", text }]);
    setTyping(true);
    try {
      const response = await postChat(text, conversationId, customer?.email);
      setConversationId(response.conversation_id);
      setTyping(false);
      if (response.verdict) {
        setOutcome(response.verdict);
        setClosingDismissed(false); // a fresh resolution → offer the closing chips again
      }
      setMessages((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          text: response.reply,
          order: response.order ? toOrderInfo(response.order) : undefined,
          ticket: response.ticket ?? undefined,
          chips: response.quick_replies ?? undefined,
        },
      ]);
    } catch {
      setTyping(false);
      setMessages((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          text: "Sorry — something went wrong. Please try again.",
        },
      ]);
    }
  }

  async function handleEndChat() {
    if (closed) return;
    // No persisted conversation yet (user ended before sending) → close locally.
    if (conversationId == null) {
      setClosed({ at: new Date().toISOString(), verdict: outcome });
      return;
    }
    try {
      const state = await closeConversation(conversationId);
      setClosed({ at: state.closed_at, verdict: state.verdict ?? outcome });
    } catch {
      setClosed({ at: new Date().toISOString(), verdict: outcome });
    }
  }

  function handleContinue() {
    setClosingDismissed(true);
  }

  // Tapping a recent-order card starts the turn for the customer — no need to know an ID.
  // If the order already has an open case, reopen that thread instead of sending a new
  // request, so the agent can't be made to raise a duplicate escalation.
  function handlePickOrder(order: StarterOrder) {
    if (order.conversationId != null) {
      loadConversation(order.conversationId);
      return;
    }
    void handleSend(`I'd like a refund for my ${order.product} (${order.id}).`);
  }

  function handleAsk(question: string) {
    void handleSend(question);
  }

  function handleNewChat() {
    setMessages([greetingFor(customer)]);
    setConversationId(null);
    setTyping(false);
    setOutcome(null);
    setClosed(null);
    setClosingDismissed(false);
  }

  // On arrival from an Orders-page "Request a refund", auto-send the order context once.
  useEffect(() => {
    if (autoSentRef.current) return;
    const auto = (location.state as { autoMessage?: string } | null)?.autoMessage;
    if (auto) {
      autoSentRef.current = true;
      void handleSend(auto);
    }
  }, []);

  // On arrival from "View chat", load that conversation's messages and continue it.
  useEffect(() => {
    const convId = (location.state as { conversationId?: number } | null)?.conversationId;
    if (convId != null) loadConversation(convId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // The customer's orders power the recent-order picker shown on a fresh chat.
  useEffect(() => {
    if (!customer) return;
    getOrders(customer.id)
      .then(setOrders)
      .catch(() => setOrders([]));
  }, [customer]);

  return (
    <div className="chat">
      <nav className="chat-nav">
        <div className="chat-brand">
          <div className="chat-mark">
            <BoltIcon />
          </div>
          <b>KaranKart</b>
        </div>
        <div className="chat-links">
          <Link to="/orders">Orders</Link>
          <span className="on">Support</span>
          <Link to="/voice">Live voice</Link>
          {customer ? (
            <div className="chat-me" title={customer.name}>
              {initials(customer.name)}
            </div>
          ) : (
            <Link to="/">Sign in</Link>
          )}
        </div>
      </nav>

      <BackButton />

      <div className="chat-page">
        <p className="chat-h">How can we help?</p>
        <p className="chat-sub">Our AI assistant resolves most refund requests in under a minute</p>
        <ChatPanel
          caseId={conversationId != null ? `RR-${conversationId}` : "NEW"}
          messages={messages}
          typing={typing}
          onSend={handleSend}
          voice={{
            customerEmail: customer?.email,
            ensureConversation,
            onUserTurn: (text) => addVoiceMessage("user", text),
            onBotTurn: (text) => addVoiceMessage("assistant", text),
          }}
          closed={closed}
          canEnd={conversationId != null}
          showClosing={outcome != null && closed == null && !closingDismissed}
          starter={
            customer != null &&
            conversationId == null &&
            closed == null &&
            messages.length === 1 &&
            starterOrders.length > 0
              ? {
                  orders: starterOrders,
                  hasMore: orders.length > 3,
                  onPick: handlePickOrder,
                  onAsk: handleAsk,
                }
              : null
          }
          onEndChat={handleEndChat}
          onContinue={handleContinue}
          onNewChat={handleNewChat}
        />
        <p className="trust">
          <LockIcon />
          Verified by order lookup · Powered by KaranKart AI support
        </p>
      </div>
    </div>
  );
}
