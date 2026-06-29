# RefundAI — AI Refund Support Agent

🎥 **[Watch the demo](https://drive.google.com/file/d/1CyGhgsCQcEk20nPcUmgiMN5j9PdNi030/view?usp=sharing)**
&nbsp;·&nbsp; 🧰 Python · FastAPI · React · PostgreSQL · SSE

> An **observable AI decision system** that approves, denies, or escalates
> e-commerce refunds against a strict policy — and streams every reasoning step to
> an admin dashboard in **real time**.

A customer chats in plain language; an LLM agent identifies their order, evaluates
it against the refund policy using **deterministic tools**, and reaches one of three
verdicts — **APPROVE / DENY / ESCALATE**. Every step of the agent's reasoning (tool
calls, the policy check-by-check, latency, tokens, the final verdict) streams live
to an admin dashboard over Server-Sent Events.

The center of gravity is the **decision-making and the visibility into it** — this
is deliberately *not* a chatbot, a CRUD app, or an e-commerce/inventory system.

---

## The two guarantees that matter

**1. Hard rules live in code, never in the LLM.**
Dates, the money threshold, and condition flags are evaluated by pure functions in
`policy/engine.py` — the single source of truth for every verdict. The model only
*orchestrates and explains*. In fact the model **cannot even see** the policy-decision
flags: `get_order` returns descriptive fields only (product, amount, delivery date),
so eligibility can only be obtained by calling `check_refund_eligibility`. The rule
is enforced *by construction*, not just by instruction.

**2. Defense-in-depth — "holding the line."**
`issue_refund` re-validates eligibility internally and **refuses to execute on any
non-APPROVE order**, even if the model is manipulated into calling it. So a refund is
guarded twice: the agent declines at the reasoning level, and the code gate refuses at
the action level. Prompt-injection attempts ("ignore the policy", a fake
`SYSTEM: admin override`, "my manager approved it", "I'll leave a bad review") are held
by **both** layers.

---

## Architecture

```
  Browser                         FastAPI (async)                    PostgreSQL
 ┌─────────┐   POST /chat        ┌────────────────────────┐         ┌───────────┐
 │ /chat   │ ──────────────────► │  Agent loop            │         │ 7 tables  │
 │ (React) │ ◄────────────────── │  (raw function calling)│ ◄─────► │ customers │
 └─────────┘   reply + verdict   │    │                   │  async  │ orders    │
                                 │    ▼                   │  SQLA   │ convos    │
 ┌─────────┐                     │  Tools ── Policy engine│         │ messages  │
 │ /admin  │   GET /admin/stream │    │    (rules in code)│         │ steps     │
 │ (React) │ ◄═══════ SSE ═══════╪═ Event bus ◄ tracing   │         │ refunds   │
 └─────────┘   live reasoning    └────────────────────────┘         │ escalation│
                                  provider-agnostic LLM port        └───────────┘
                                  (OpenAI · gpt-4.1-mini)
```

- **Agent loop** — raw function calling (ReAct-style): the model is given a tool menu;
  if it returns tool calls we dispatch them and feed the results back, repeating until
  it returns a final answer or hits `MAX_STEPS`. Resilient by construction — LLM calls
  retry with backoff, a total failure degrades to a graceful message, and a failing
  tool is reported back to the model instead of crashing the turn.
- **Provider-agnostic LLM** — the loop depends on an `LLMClient` port, never a vendor
  SDK directly. An OpenAI adapter implements it; swapping providers is one env var.
- **Tracing → event bus → SSE** — every step is written to `agent_steps` *and* published
  to an in-memory event bus; `/admin` subscribes over SSE and renders the trace live.

### LLM-visible tools
`lookup_customer` · `list_customer_orders` · `get_order` · `check_refund_eligibility`
· `issue_refund` · `escalate_to_manager` · `request_more_info` · `get_policy_section`

The fine-grained policy checks (`_check_ownership`, `_check_return_window`,
`_check_amount_threshold`, …) are **internal** — code-only, never exposed to the model.

---

## Refund policy (enforced in `policy/engine.py`)

| Rule | Behavior |
|---|---|
| **Return window** | 30 days from delivery — **45 days for VIP** customers |
| **Condition** | Must be factory-sealed, *or* opened-but-defective. Final-sale items are never refundable |
| **Amount threshold** | Refunds over **₹50,000** require manager approval → **ESCALATE** |
| **Ownership** | A customer may only refund their **own** orders |
| **Double-refund guard** | An already-refunded order is denied |

The engine **fails closed**: missing or ambiguous data denies rather than approves.

## Edge cases handled (all verified end-to-end through the real agent)

| Case | Outcome |
|---|---|
| Order not found | Recovers gracefully, asks for a valid order id (no crash) |
| Order isn't the customer's | **DENY** — ownership refusal |
| Already refunded | **DENY** — double-refund guard |
| Past the return window | **DENY** — "holding the line" |
| Over ₹50,000 (otherwise valid) | **ESCALATE** — the agent knows its limit |
| Prompt-injection / manipulation | Agent **and** code gate both hold — refund never fires |
| LLM timeout / malformed call | Retry with backoff; `MAX_STEPS` cap; graceful degradation (covered by tests) |

---

## Tech stack

- **Backend** — Python 3.12, FastAPI, SQLAlchemy 2.0 (async) + asyncpg, PostgreSQL,
  pydantic-settings, OpenAI SDK, httpx. Tested with pytest + pytest-asyncio.
- **Frontend** — React 18 + TypeScript + Vite, React Router, native `EventSource` for
  the SSE stream. Plain CSS with a single design-token file (no UI framework).

## Project structure

```
backend/app/
├── agent/      loop.py · tools.py · tracing.py · prompts.py   (the agent)
├── policy/     engine.py                                       (rules in code)
├── llm/        client.py (port) + openai adapter               (provider-agnostic)
├── refunds/    issue_refund service (defense-in-depth)
├── events/     in-memory event bus (SSE fan-out)
├── api/        routes (/chat, /admin/*) + schemas
├── db/         models (7 tables) · database · seed
└── config.py   settings from .env
frontend/src/
├── api/        client.ts          types/   index.ts · chat.ts
├── hooks/      useSSE.ts          lib/     adminTrace.ts
├── components/ icons + chat/…     pages/   ChatPage · AdminPage
└── styles/     tokens · global · chat · admin   (@/ path alias)
```

---

## Setup & run

**Prerequisites:** Python 3.12+, [uv](https://docs.astral.sh/uv/), Node 18+ with
[pnpm](https://pnpm.io/), a local PostgreSQL, and an OpenAI API key.

```bash
# 1. Configure (from the repo root)
cp .env.example .env          # then edit .env: set OPENAI_API_KEY and DATABASE_URL
createdb refund_agent         # create the PostgreSQL database

# 2. Backend
cd backend
uv sync                                    # install deps into .venv
uv run python -m app.db.seed               # create the 7 tables + seed 15 customers / 26 orders
uv run uvicorn app.main:app --port 8000    # API at http://localhost:8000

# 3. Frontend (in a second terminal)
cd frontend
pnpm install
pnpm dev                                   # app at http://localhost:5173
```

Open **http://localhost:5173/chat** to talk to the agent, and
**http://localhost:5173/admin** to watch its reasoning stream live.

### Configuration (`.env`)

| Variable | Purpose |
|---|---|
| `LLM_PROVIDER` | `openai` (or `gemini`) — selects the adapter |
| `LLM_MODEL` | model id, e.g. `gpt-4.1-mini` |
| `OPENAI_API_KEY` | required when `LLM_PROVIDER=openai` |
| `DATABASE_URL` | `postgresql+asyncpg://user:pass@localhost:5432/refund_agent` |
| `MAX_STEPS` | hard cap on agent-loop iterations (`.env.example` uses 6) |

Secrets are read from `.env` only — the repo is public, so `.env` is gitignored and
no key is ever committed.

## Testing

```bash
cd backend && uv run pytest        # 61 tests, no live API calls
```

- The **policy engine and tools are pure** and unit-tested — this is where correctness
  lives, and it costs zero API calls.
- The **agent loop is tested with a faked LLM client** (canned tool-call responses), so
  the retry, `MAX_STEPS`, and failure paths are covered deterministically.

---

## Design decisions & scope

- **Provider-agnostic by design** — the agent loop never imports a vendor SDK; it
  depends on the `LLMClient` port. Switching OpenAI → Gemini is a config change.
- **Real reasoning, not a mock** — the admin dashboard renders actual `agent_steps`
  (tool I/O, the 5 policy checks, latency, tokens), and each step expands to its raw
  input/output for full transparency — including the exact prompt sent to the model.
- **Deliberately out of scope** — no auth/RBAC, no products table, no cart/checkout, no
  policy-editor UI. The task is an *agent that holds a policy*; building an e-commerce
  shell around it would dilute that focus. Entry points like an orders page or customer
  login are noted as where they'd live, not built.

## Roadmap

- **Voice (bonus)** — a streaming speech pipeline (STT → agent → TTS) over the same
  agent core; env hooks are in place (`DEEPGRAM_API_KEY` / `ELEVENLABS_API_KEY`).
