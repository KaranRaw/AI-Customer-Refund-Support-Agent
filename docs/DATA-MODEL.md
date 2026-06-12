# Data Model — RefundAI

> PostgreSQL, accessed via SQLAlchemy **async** + `asyncpg`. **7 domain tables.**
> Categorical fields are stored as `VARCHAR + CHECK` (StrEnum values) — typed in Python,
> validated in the DB, without native-enum migration friction. Money is `Numeric` (never
> float); timestamps are timezone-aware; agent-step payloads are `JSONB`.
>
> See also: [ARCHITECTURE.md](./ARCHITECTURE.md) · [AGENT-AND-POLICY.md](./AGENT-AND-POLICY.md)

## ER overview

```
customers ──< orders ───────────────┐
    │                                │
    └──< conversations ──< refund_requests ──< agent_steps   ⭐ (the reasoning spine)
              │                  │
              └──< messages      └──< escalations            (the ESCALATE path)
```

A **case** in the admin panel is keyed by a `conversation`. Refunds and escalations are a
**separate lifecycle** from the chat: closing a chat never resolves an open escalation.

## Tables

### `customers` — the 15 CRM profiles
| column | notes |
|---|---|
| `id` | e.g. `cust-1` |
| `name`, `email` (unique), `phone` | login matches `email` |
| `tier` | `regular` \| `vip` — VIP gets a longer return window |
| `created_at` | |

### `orders` — product snapshot embedded (no separate products table)
| column | drives |
|---|---|
| `id` | e.g. `ORD-1002` |
| `customer_id` → customers | ownership check |
| `product_name`, `category` | disambiguation |
| `amount` (Numeric), `currency` (`INR`) | the ₹50,000 threshold |
| `order_date`, `delivered_at` | the 30/45-day window |
| `status` | placed \| shipped \| delivered \| cancelled |
| `is_final_sale` | non-refundable rule |
| `is_opened` | sealed-vs-opened rule |
| `is_defective` | the defective exception |
| `refunded_at` (nullable) | already-refunded guard (refund idempotency) |

### `conversations` — a chat/voice session (the admin "case")
| column | notes |
|---|---|
| `id`, `customer_id` (nullable until identified), `channel` (text\|voice), `started_at` | |
| `status` | `active` \| `closed` |
| `closed_at` | stamped when the customer ends the chat |
| `verdict` | sticky outcome: approve \| deny \| escalate |
| `order_id` | the order the agent focused on |
| `refund_reason` | customer's stated reason — **tracking only, never feeds the policy** |
| `ai_summary`, `ai_summary_at` | cached AI triage summary (see AGENT-AND-POLICY.md) |

### `messages` — turns within a conversation
`id`, `conversation_id`, `role` (user \| assistant \| tool), `content`, `created_at`.

### `refund_requests` — ⭐ the *case record* + anchor for the execution trace
| column | notes |
|---|---|
| `id`, `order_id`, `conversation_id` | |
| `status` | pending \| in_progress \| decided \| resolved |
| `verdict` | null \| approve \| deny \| escalate |
| `reason`, `amount`, `decided_by` (agent \| manager) | |
| `created_at`, `resolved_at` (nullable) | set when a manager resolves an escalation |

*Lifecycle:* `decided` on the agent's verdict; on **escalate** it stays effectively open
until a manager resolves it → `resolved`. (We folded "agent_runs" into this table — the
case *is* the run anchor.)

### `agent_steps` — ⭐⭐ the reasoning-log spine
Powers the live admin trace and proves failure/retry handling. **This table + the agent
loop are where the real build effort goes.**

| column | notes |
|---|---|
| `id`, `conversation_id`, `refund_request_id` (nullable) | |
| `step_no` | order within the run |
| `type` | llm_call \| tool_call \| tool_result \| decision \| error \| retry |
| `tool_name` | tool steps only |
| `input_json`, `output_json` | JSONB payloads |
| `status` | success \| error \| retried |
| `latency_ms`, `model`, `tokens_in`, `tokens_out` | per-step observability |
| `parent_step_id` | nests internal checks under their parent → admin renders a **tree** |
| `created_at` | |

### `escalations` — manager tickets (the ESCALATE path; mock)
`id`, `refund_request_id`, `reason`, `status` (open \| resolved), `assigned_to` (a constant
"Refunds Manager"), `created_at`, `resolved_at`. An order has **at most one open
escalation** — `escalate_to_manager` reuses an existing open ticket (dedupe).

## Design decisions

- **No `products` table** — the order snapshots name/price/flags (real order systems
  snapshot at purchase time; catalogs change).
- **No `audit_log`** — `refund_requests` + `agent_steps` already form the immutable
  decision + execution record.
- **No `managers` table** — a constant assignee is enough for mock escalations.
- **No `agent_runs` table** — folded into `refund_requests`.
- 4 of the 7 tables (customers, orders, conversations, messages) are near-trivial; the
  weight is in `agent_steps` + the loop.

> **Stale table note:** an `auth_users` table may exist in a dev DB from an earlier schema.
> It is **not in the current models** and **not referenced by any code** (login uses
> `customers.email`). It survives `drop_all` only because it isn't registered on the
> metadata — harmless, and dropped if you recreate the DB from scratch.

## Seed data — `app/db/seed.py`

**15 customers + 26 orders**, with delivery dates relative to seed time so the 30-day-window
cases stay valid on every reseed. The dataset is built to trigger **every edge case**:

| Edge case | Example seeded order |
|---|---|
| APPROVE (in window, sealed, under ₹50k) | `ORD-1001` Sony WH-1000XM5, 9d, sealed |
| APPROVE (opened **but defective**) | `ORD-1021` Anker power bank, opened+defective |
| APPROVE (VIP extended window) | `ORD-1003` USB-C cable, 40d, VIP (within 45d) |
| DENY (out of window) | `ORD-1140` Sennheiser, 45d, regular |
| DENY (final sale) | `ORD-1030` clearance webcam |
| DENY (opened, not defective) | `ORD-1031` Razer mouse |
| DENY (already refunded) | `ORD-1010` Dell monitor, refunded |
| ESCALATE (over ₹50,000) | `ORD-1002` MacBook Pro, ₹2,39,900 |

### Reseed (drops + recreates + inserts)

```bash
cd backend && uv run python -m app.db.seed
# -> "Seeded 15 customers and 26 orders."
```

`seed.py` runs `drop_all()` → `create_all()` → insert, so a reseed always rebuilds the
schema with the latest columns and clears any prior conversations/escalations.
The test DB (`refund_agent_test`) is seeded the same way per test via `tests/conftest.py`.
