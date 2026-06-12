import { useEffect, useState, type ReactNode } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";

import { getOrders } from "@/api/client";
import { BackButton } from "@/components/BackButton";
import { BoltIcon, BotIcon, ChatBubbleIcon, LaptopIcon } from "@/components/icons";
import { useSession } from "@/lib/session";
import type { OrderListItem } from "@/types";
import "@/styles/orders.css";

type Tab = "all" | "delivered" | "transit" | "refunds";

function initials(name: string): string {
  const parts = name.trim().split(/\s+/);
  return ((parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "")).toUpperCase() || "?";
}

function formatInr(amount: number, currency: string): string {
  if (currency === "INR") {
    return new Intl.NumberFormat("en-IN", {
      style: "currency",
      currency: "INR",
      maximumFractionDigits: 0,
    }).format(amount);
  }
  return `${currency} ${amount}`;
}

function deliveredLabel(iso: string | null): string {
  if (!iso) return "";
  return `delivered ${new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric" })}`;
}

function statusInfo(order: OrderListItem): { badge: string; cls: string; note: ReactNode } {
  if (order.refund_ticket) {
    return {
      badge: "Refund in review",
      cls: "st-rev",
      note: (
        <>
          Ticket <code>#{order.refund_ticket}</code> · awaiting manager approval
        </>
      ),
    };
  }
  if (order.refunded) return { badge: "Refunded", cls: "st-del", note: "Refund completed" };
  if (order.status === "delivered") {
    return { badge: "Delivered", cls: "st-del", note: "Within the return window" };
  }
  return { badge: "In transit", cls: "st-ship", note: "Refund available after delivery" };
}

function actionFor(
  order: OrderListItem,
  onRefund: (o: OrderListItem) => void,
  onViewChat: (o: OrderListItem) => void,
): ReactNode {
  if (order.refund_ticket) {
    return (
      <button type="button" className="btn" onClick={() => onViewChat(order)}>
        <ChatBubbleIcon />
        View chat
      </button>
    );
  }
  if (order.refunded) return <span className="btn muted">Refunded</span>;
  if (order.status === "delivered") {
    return (
      <button type="button" className="btn primary" onClick={() => onRefund(order)}>
        <ChatBubbleIcon />
        Request a refund
      </button>
    );
  }
  return <span className="btn muted">In transit</span>;
}

export function OrdersPage() {
  const { customer } = useSession();
  const navigate = useNavigate();
  const [orders, setOrders] = useState<OrderListItem[]>([]);
  const [tab, setTab] = useState<Tab>("all");

  useEffect(() => {
    if (!customer) return;
    getOrders(customer.id)
      .then(setOrders)
      .catch(() => setOrders([]));
  }, [customer]);

  if (!customer) return <Navigate to="/" replace />;

  const filtered = orders.filter((order) => {
    if (tab === "delivered") {
      return order.status === "delivered" && !order.refunded && !order.refund_ticket;
    }
    if (tab === "transit") return order.status !== "delivered";
    if (tab === "refunds") return order.refunded || Boolean(order.refund_ticket);
    return true;
  });

  function requestRefund(order: OrderListItem) {
    navigate("/chat", {
      state: { autoMessage: `I'd like a refund for my ${order.product_name} (${order.id}).` },
    });
  }

  function viewChat(order: OrderListItem) {
    if (order.conversation_id != null) {
      navigate("/chat", { state: { conversationId: order.conversation_id } });
    }
  }

  const tabs: { key: Tab; label: string }[] = [
    { key: "all", label: "All" },
    { key: "delivered", label: "Delivered" },
    { key: "transit", label: "In transit" },
    { key: "refunds", label: "Refunds" },
  ];

  return (
    <div className="orders">
      <nav>
        <div className="brand">
          <div className="mark">
            <BoltIcon />
          </div>
          <b>KaranKart</b>
        </div>
        <div className="links">
          <span className="on">Orders</span>
          <Link to="/chat">Support</Link>
          <div className="me" title={customer.name}>
            {initials(customer.name)}
          </div>
        </div>
      </nav>

      <BackButton />

      <div className="page">
        <p className="h">Your orders</p>
        <p className="sub">
          {orders.length} orders · signed in as {customer.email}
        </p>

        <div className="tabs">
          {tabs.map((entry) => (
            <button
              key={entry.key}
              type="button"
              className={`tab${tab === entry.key ? " on" : ""}`}
              onClick={() => setTab(entry.key)}
            >
              {entry.label}
            </button>
          ))}
        </div>

        {filtered.length === 0 && <p className="empty">No orders here.</p>}

        {filtered.map((order) => {
          const stat = statusInfo(order);
          return (
            <div className="ocard" key={order.id}>
              <div className="o-top">
                <div className="thumb">
                  <LaptopIcon />
                </div>
                <div className="o-info">
                  <b>{order.product_name}</b>
                  <small>
                    <code>{order.id}</code> · {deliveredLabel(order.delivered_at) || order.status}
                  </small>
                </div>
                <span className="price">{formatInr(order.amount, order.currency)}</span>
              </div>
              <div className="o-bottom">
                <span className={`stat ${stat.cls}`}>{stat.badge}</span>
                <span className="note">{stat.note}</span>
                <span className="sp" />
                {actionFor(order, requestRefund, viewChat)}
              </div>
            </div>
          );
        })}

        <div className="help">
          <div className="bot">
            <BotIcon />
          </div>
          <div>
            <b>Issue with something else?</b>
            <small>Our AI assistant resolves most refund requests in under a minute</small>
          </div>
          <span className="sp" />
          <Link to="/chat" className="btn primary">
            Start a chat
          </Link>
        </div>

        <p className="ord-foot">
          Refunds are checked against our return policy · Decisions over ₹50,000 are reviewed by a
          manager
        </p>
      </div>
    </div>
  );
}
