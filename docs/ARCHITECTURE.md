# Architecture — RefundAI

> An **observable AI refund-decision system** for a mock electronics store (RefundAI).
> A customer talks to an AI agent by text or voice; the agent identifies the order,
> evaluates it against a strict refund policy using **deterministic tools**, and reaches
> one of three verdicts — **APPROVE / DENY / ESCALATE**. Every reasoning step streams
> live to an admin dashboard. The system is built to **hold the line**: it refuses or
> escalates out-of-policy requests even under pressure or prompt-injection.
>
> The center of gravity is the **agent's decision-making and the visibility into it** —
> not the UI or the data. All money is in **INR (₹)**.

See also: [DATA-MODEL.md](./DATA-MODEL.md) · [AGENT-AND-POLICY.md](./AGENT-AND-POLICY.md)

---

## 1. The big picture

```
┌──────────────────────────────┐          ┌─────────────────────────────────────┐
│  FRONTEND  (React + Vite/TS)  │          │  BACKEND  (FastAPI + PostgreSQL)    │
│                               │  HTTP    │                                     │
│  /home    landing             │ ───────▶ │  POST /chat        → agent loop     │
│  /login   sign in (email)     │          │  POST /conversations/{id}/close     │
│  /orders  customer orders     │          │  GET  /conversations/{id}/messages  │
│  /chat    customer chat ──────┼───SSE──▶ │  GET  /admin/stream  (live trace)   │
│  /voice   full-duplex voice ──┼──WS────▶ │  GET  /admin/cases   (history)      │
│  /admin   reasoning logs   ◀──┘          │  POST /admin/cases/{id}/summary     │
│                               │          │                                     │
└──────────────────────────────┘          │  agent emits step events ──┐        │
                                           │                            ▼        │
                                           │              ┌──────────────────┐   │
                                           │              │  in-memory event │   │
                                           │              │  bus (pub/sub)   │──SSE
                                           │              └──────────────────┘   │
                                           │  TOOLS  (9 LLM-visible)             │
                                           │  POLICY ENGINE (deterministic, code)│
                                           │  PostgreSQL (7 tables + seed)       │
                                           └─────────────────────────────────────┘
```

## 2. Frontend routes

| Route | Page | Notes |
|---|---|---|
| `/` | → redirects to `/home` | |
| `/home` | Landing | public; "Sign in" when logged out |
| `/login` | Sign in | email-only (no password) → matches a seeded `customers.email` |
| `/orders` | Customer orders | requires a session; "Request a refund" deep-links to `/chat` |
| `/chat` | Customer chat | text + inline voice; recent-order starter on a fresh chat |
| `/voice` | Full-duplex voice | reactive orb (idle / listening / thinking / speaking) |
| `/admin` | Reasoning dashboard | live trace + case history + AI case summary |

One React app, two *audiences*: the **customer** surface (`/home /login /orders /chat /voice`)
and the **operator** surface (`/admin`). The customer is never linked into `/admin`.

## 3. The request path (text chat)

```
customer message
  → POST /chat
  → run_chat_turn() loads/creates the conversation, persists the user message
  → run_agent() — the loop: LLM picks a tool → dispatch → feed result back → repeat
        each step is (a) written to agent_steps  AND  (b) published to the event bus
  → SSE forwards each step to any /admin listener, live
  → final answer + verdict + order + ticket return to /chat
```

The reasoning logs are **real-time because of the SSE event bus**, independent of whether
the turn arrived as text or voice.

## 4. Key architectural decisions

- **Raw function calling** for the agent loop — no LangGraph/CrewAI. Less code, fully
  transparent control flow, fewer dependencies. (The brief allows it.)
- **Provider-agnostic LLM via a port.** The loop depends on a thin `LLMClient` Protocol
  (`chat_with_tools(...)`, plus `complete(...)` for summaries), never a vendor SDK. The
  **OpenAI adapter** is implemented (model `gpt-4.1-mini`); a Gemini adapter is the
  documented extension point — `LLM_PROVIDER` selects it. The loop never imports `openai`.
- **Hard rules live in code, never in the LLM.** Dates, money thresholds, and condition
  flags are evaluated by deterministic functions in `policy/engine.py`. The LLM
  orchestrates and explains; it never *computes* a rule. See AGENT-AND-POLICY.md.
- **Defense-in-depth.** `issue_refund` re-validates eligibility and refuses to execute on
  any non-APPROVE order — even if the model is manipulated. `escalate_to_manager` reuses
  an open ticket instead of duplicating one. The policy is enforced at the **action
  layer**, not the prompt.
- **SSE for the live trace** — one-way server→browser, purpose-built for a feed. Not
  WebSocket (overkill one-direction) and not polling. WebSocket is reserved for **voice**.
- **In-memory event bus** (an `asyncio.Queue` per subscriber) decouples the agent
  (producer) from the admin stream (consumer). *Scale note:* swap for Redis pub/sub to go
  multi-instance — in-memory is the correct scope for a single-tenant demo.
- **Auth deliberately scoped out.** "Login" is an email lookup against the seeded
  customers (identity-by-reference, like real support: "what's your order number?"). The
  `/admin` route is open in the demo; in production it would sit behind role-based access.

## 5. Backend layering

```
backend/app/
  main.py            FastAPI app, CORS, logging config, global exception handler
  config.py          settings: DATABASE_URL, LLM_PROVIDER, llm_model, API keys
  db/
    database.py      async engine (asyncpg) + session + create_all/drop_all
    models.py        the 7 SQLAlchemy models
    seed.py          15 customers + 26 orders (covers every edge case)
  policy/
    policy.md        human-readable policy (the agent can quote it)
    policy_config.json   machine values (window, threshold, currency)
    engine.py        5 internal checks + check_refund_eligibility (single source of truth)
  refunds/
    service.py       issue_refund (defense-in-depth), escalate (dedupe), resolve
  llm/
    client.py        LLMClient port + normalized message/response types
    openai_client.py OpenAI adapter (chat_with_tools + complete)
  agent/
    loop.py          the loop: MAX_STEPS, retry/backoff, graceful degradation
    tools.py         9 LLM-visible tool fns + dispatch
    prompts.py       system prompt (built from live policy config)
    runner.py        run_chat_turn: persistence + tracing + escalation backstop
    tracing.py       emits steps → agent_steps + event bus
  events/bus.py      in-memory pub/sub
  cases/service.py   admin reads: case list, case detail, AI case summary
  orders/service.py  a customer's orders (+ policy-aware refund_eligible flag)
  api/routes/        chat.py, admin.py, auth.py, orders.py, voice.py
  voice/             live.py (Pipecat pipeline) + agent_bridge.py
```

## 6. Voice (full-duplex)

Voice is a **Pipecat** pipeline running in-process over a FastAPI WebSocket
(`/voice/live`). Audio in → VAD → Deepgram STT → **the same agent loop** (`run_chat_turn`,
so voice turns also stream to `/admin`) → ElevenLabs TTS → audio out. The browser uses the
`@pipecat-ai/client-js` WebSocket transport. The `/voice` orb reacts to the real mic level
(`onLocalAudioLevel`) and the bot's TTS level (`onRemoteAudioLevel`), and shows a
**thinking** state while the agent runs (a server message between the user's turn and the
spoken reply).

This is the realtime/interruptible tier — barge-in works because VAD detects the user
speaking over the bot.

## 7. Tech stack

- **Backend:** Python + FastAPI, SQLAlchemy **async** + **PostgreSQL** (`asyncpg`), SSE via
  `StreamingResponse`, `httpx`/SDKs for vendor calls.
- **Frontend:** React + Vite + TypeScript, `EventSource` for the admin stream,
  `@pipecat-ai/client-js` for voice.
- **LLM:** provider-agnostic `LLMClient` port → OpenAI adapter (`gpt-4.1-mini`).
- **Voice:** Pipecat 1.3 + Deepgram (STT) + ElevenLabs (TTS) + Silero VAD.
- **Tests:** `pytest` — `tests/unit` (deterministic), `tests/integration` (faked LLM),
  `tests/evals` (offline + live + scored). See AGENT-AND-POLICY.md §Evals.
