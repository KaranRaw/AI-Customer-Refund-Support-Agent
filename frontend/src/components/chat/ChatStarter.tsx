import { Link } from "react-router-dom";

import { ChevronIcon, LaptopIcon } from "@/components/icons";

export type StarterStatus = "review" | "delivered" | "refunded" | "transit";

export interface StarterOrder {
  id: string;
  product: string;
  meta: string; // "ORD-1002 · delivered Jun 7 · ₹2,39,900"
  statusKind: StarterStatus;
  statusLabel: string;
  conversationId: number | null; // set when a case is already open → reopen it, don't re-escalate
}

const STATUS_CLASS: Record<StarterStatus, string> = {
  review: "cs-stat warn",
  delivered: "cs-stat ok",
  refunded: "cs-stat",
  transit: "cs-stat",
};

const QUICK_ASKS = ["Where's my refund?", "What's your return policy?"];

interface Props {
  orders: StarterOrder[];
  hasMore: boolean;
  onPick: (order: StarterOrder) => void;
  onAsk: (question: string) => void;
}

export function ChatStarter({ orders, hasMore, onPick, onAsk }: Props) {
  return (
    <div className="cs">
      <p className="cs-label">YOUR RECENT ORDERS</p>
      <div className="cs-orders">
        {orders.map((order) => (
          <button key={order.id} type="button" className="cs-ocard" onClick={() => onPick(order)}>
            <span className="cs-thumb">
              <LaptopIcon />
            </span>
            <span className="cs-info">
              <b>{order.product}</b>
              <small>{order.meta}</small>
            </span>
            <span className="cs-sp" />
            <span className={STATUS_CLASS[order.statusKind]}>{order.statusLabel}</span>
            <span className="cs-arrow">
              <ChevronIcon />
            </span>
          </button>
        ))}
      </div>
      {hasMore && (
        <Link to="/orders" className="cs-viewall">
          View all orders →
        </Link>
      )}

      <p className="cs-label">OR ASK ABOUT</p>
      <div className="cs-asks">
        {QUICK_ASKS.map((ask) => (
          <button key={ask} type="button" className="cs-ask" onClick={() => onAsk(ask)}>
            {ask}
          </button>
        ))}
      </div>
    </div>
  );
}
