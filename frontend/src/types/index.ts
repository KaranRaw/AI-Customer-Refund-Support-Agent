/** Mirrors the backend API contract (app/api/schemas.py). */

export type Verdict = "approve" | "deny" | "escalate";

export interface OrderBrief {
  id: string;
  product_name: string;
  amount: number;
  currency: string;
  delivered_at: string | null;
}

export interface ChatResponse {
  conversation_id: number;
  reply: string;
  verdict: Verdict | null;
  order: OrderBrief | null;
  ticket: string | null;
  quick_replies: string[] | null;
}

export interface Step {
  id: number;
  step_no: number;
  created_at: string;
  type: string; // llm_call | tool_call | tool_result | decision | error | retry
  tool_name: string | null;
  input: Record<string, unknown> | null;
  output: Record<string, unknown> | null;
  status: string; // success | error | retried
  latency_ms: number | null;
  model: string | null;
  tokens_in: number | null;
  tokens_out: number | null;
}

export interface CaseSummary {
  conversation_id: number;
  customer_name: string | null;
  verdict: Verdict | null;
  order_id: string | null;
  order_product: string | null;
  order_amount: number | null;
  currency: string | null;
  created_at: string;
  step_count: number;
}

export interface CaseCustomer {
  id: string;
  name: string;
  email: string;
  tier: string | null;
}

/** The signed-in customer (same shape as CaseCustomer). */
export type Customer = CaseCustomer;

export interface OrderListItem {
  id: string;
  product_name: string;
  amount: number;
  currency: string;
  status: string;
  delivered_at: string | null;
  refunded: boolean;
  refund_ticket: string | null;
  conversation_id: number | null;
  refund_eligible: boolean;
}

export interface ConversationHistory {
  conversation_id: number;
  status: string; // "active" | "closed"
  verdict: Verdict | null;
  closed_at: string | null;
  messages: { role: "user" | "assistant"; text: string }[];
}

export interface ConversationState {
  conversation_id: number;
  status: string; // "active" | "closed"
  verdict: Verdict | null;
  closed_at: string | null;
}

export interface OrderDetail {
  id: string;
  product_name: string;
  amount: number;
  currency: string;
  delivered_at: string | null;
  is_opened: boolean;
  is_final_sale: boolean;
  is_defective: boolean;
  over_threshold: boolean;
}

export interface CaseEscalation {
  id: number;
  ref: string;
  assigned_to: string;
  reason: string;
  status: string;
}

export interface CaseFact {
  label: string;
  tone: string; // "neutral" | "warn"
}

export interface CaseDetail {
  conversation_id: number;
  verdict: Verdict | null;
  channel: string;
  refund_reason: string | null;
  customer: CaseCustomer | null;
  order: OrderDetail | null;
  escalation: CaseEscalation | null;
  steps: Step[];
  ai_summary: string | null;
  ai_summary_at: string | null;
  summary_facts: CaseFact[];
}

export interface CaseSummaryResult {
  conversation_id: number;
  summary: string;
  generated_at: string;
  step_count: number;
  model: string | null;
}

/** A live event off /admin/stream — a Step plus the conversation it belongs to. */
export interface StepEvent extends Step {
  conversation_id: number;
}
