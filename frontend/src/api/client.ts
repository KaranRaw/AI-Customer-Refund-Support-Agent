import type {
  CaseDetail,
  CaseSummary,
  CaseSummaryResult,
  ChatResponse,
  ConversationHistory,
  ConversationState,
  Customer,
  OrderListItem,
} from "@/types";

const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

export function postChat(
  message: string,
  conversationId: number | null,
  customerEmail?: string | null,
): Promise<ChatResponse> {
  return request<ChatResponse>("/chat", {
    method: "POST",
    body: JSON.stringify({
      message,
      conversation_id: conversationId,
      customer_email: customerEmail ?? null,
    }),
  });
}

export function login(email: string): Promise<Customer> {
  return request<Customer>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email }),
  });
}

export function getOrders(customerId: string): Promise<OrderListItem[]> {
  return request<OrderListItem[]>(`/customers/${customerId}/orders`);
}

export function getConversationMessages(conversationId: number): Promise<ConversationHistory> {
  return request<ConversationHistory>(`/conversations/${conversationId}/messages`);
}

export function getCases(): Promise<CaseSummary[]> {
  return request<CaseSummary[]>("/admin/cases");
}

export function resolveEscalation(
  escalationId: number,
  decision: "approve" | "deny",
): Promise<{ decision: string; verdict: string; refunded: boolean }> {
  return request(`/admin/escalations/${escalationId}/resolve`, {
    method: "POST",
    body: JSON.stringify({ decision }),
  });
}

export function getCase(conversationId: number): Promise<CaseDetail> {
  return request<CaseDetail>(`/admin/cases/${conversationId}`);
}

/** Generate (and cache) the AI triage summary for a case. */
export function generateCaseSummary(conversationId: number): Promise<CaseSummaryResult> {
  return request<CaseSummaryResult>(`/admin/cases/${conversationId}/summary`, { method: "POST" });
}

export function streamUrl(conversationId?: number): string {
  const query = conversationId != null ? `?conversation_id=${conversationId}` : "";
  return `${API_URL}/admin/stream${query}`;
}

/** Mint an empty conversation so chat + voice can share one thread. */
export function createConversation(): Promise<{ conversation_id: number }> {
  return request<{ conversation_id: number }>("/conversations", { method: "POST" });
}

/** End a chat — flips the conversation to CLOSED. Does not resolve any escalation. */
export function closeConversation(conversationId: number): Promise<ConversationState> {
  return request<ConversationState>(`/conversations/${conversationId}/close`, { method: "POST" });
}

/** WebSocket URL for the live-voice pipeline; `conversationId` shares the chat thread. */
export function voiceLiveUrl(email?: string | null, conversationId?: number | null): string {
  const ws = API_URL.replace(/^http/, "ws");
  const params = new URLSearchParams();
  if (email) params.set("email", email);
  if (conversationId != null) params.set("conversation_id", String(conversationId));
  const qs = params.toString();
  return `${ws}/voice/live${qs ? `?${qs}` : ""}`;
}

