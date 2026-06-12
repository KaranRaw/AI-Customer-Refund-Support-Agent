# RefundAI — Docs

Internal documentation for **RefundAI**, an observable AI refund-decision system for a mock
electronics store. Read these top-to-bottom to understand the whole system.

| Doc | What it covers |
|---|---|
| [ARCHITECTURE.md](./ARCHITECTURE.md) | The system end-to-end: frontend routes, backend layering, the request path, the agent loop, the SSE event bus, voice, and the key design decisions. |
| [DATA-MODEL.md](./DATA-MODEL.md) | The 7 PostgreSQL tables, their relationships, design decisions, and the seed dataset (15 customers + 26 orders covering every edge case) + how to reseed. |
| [AGENT-AND-POLICY.md](./AGENT-AND-POLICY.md) | How a refund decision is made: the deterministic policy engine, the three verdicts, the tools, defense-in-depth, the reasoning trace, the AI case summary, and the eval suites. |

**One-line summary:** a customer chats (text or voice) with the RefundAI agent → the agent
identifies the order and evaluates it against a strict policy using deterministic tools →
**APPROVE / DENY / ESCALATE** → every reasoning step streams live to `/admin`. Hard rules
live in code; the LLM orchestrates and explains. All money is in **INR (₹)**.

Run instructions and the public overview live in the repo's top-level
[`README.md`](../README.md).
