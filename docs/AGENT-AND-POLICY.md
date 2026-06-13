# Agent & Policy — RefundAI

> How a refund decision is actually made: the deterministic **policy engine**, the three
> **verdicts**, the **agent loop** and its tools, the **defense-in-depth** guarantees, the
> **reasoning trace**, the **AI case summary**, and the **eval** suites.
>
> See also: [ARCHITECTURE.md](./ARCHITECTURE.md) · [DATA-MODEL.md](./DATA-MODEL.md)

---

## 1. The policy (electronics store, INR)

Config in `policy/policy_config.json` (the agent's prompt is built from these values, so it
can never quote a number the engine doesn't use):

```json
{ "return_window_days": 30, "vip_return_window_days": 45,
  "manager_approval_threshold": 50000, "currency": "INR" }
```

Rules:
1. Refunds allowed within **30 days of delivery** (**45 days for VIP** customers).
2. Item must be **factory-sealed** for a full refund.
3. **Opened** items are refundable **only if defective**.
4. **Final-sale** items are **never refundable**, even if defective.
5. Refunds **over ₹50,000** require **manager approval → ESCALATE** (not auto-deny).
6. The order must **exist** and **belong to the requesting customer**.
7. An **already-refunded** order cannot be refunded again.

## 2. The three verdicts

| Verdict | Meaning |
|---|---|
| **APPROVE** | Clearly in policy → the agent issues the refund automatically. |
| **DENY** | Clearly violates policy → the agent refuses and explains why. |
| **ESCALATE** | The agent is *not authorized* to decide (over ₹50,000) → opens a manager ticket; does **not** approve or deny. |

The third verdict is the point: refunds aren't yes/no — **escalate represents an authority
limit**, which is what separates this from a toy.

## 3. The policy engine (`policy/engine.py`)

`check_refund_eligibility(order, customer, *, now, config)` is the **single source of truth**
for every verdict. It runs five pure checks and aggregates them — **fail-closed** (missing or
ambiguous data denies rather than guessing):

```
_check_ownership          order belongs to the requesting customer?
_check_already_refunded   refunded_at is null?
_check_return_window      within 30 days (45 for VIP)?         (date math)
_check_item_condition     sealed, or opened-but-defective, not final-sale?
_check_amount_threshold   at or under ₹50,000?                 (numeric)
```

Order of precedence: a failed **hard rule** (ownership → already-refunded → window →
condition) **denies**; only an otherwise-valid order that is over the threshold
**escalates**. Each check returns a `CheckResult(name, passed, detail)`; the aggregate is an
`EligibilityResult(verdict, reason, checks)`. The numbers are **never** computed by the LLM.

## 4. The agent loop (`agent/loop.py`)

**Raw function calling.** The model is given the tool menu and the conversation; if it
returns tool calls, the loop dispatches them, feeds results back, and repeats until the
model returns a final text answer or `MAX_STEPS` is hit. Resilient by construction:

- **`MAX_STEPS = 6`** — cap the loop, degrade gracefully, log the cap as a step.
- **Retry with backoff** — a transient LLM error retries (logged as `type=retry`); a total
  failure returns a graceful message (logged as `error`).
- **Tool crash** — caught and fed back to the model as an error result, not fatal.
- **Hallucinated tool / order** — the dispatch returns an error the model recovers from.
- Tools return **typed dicts**, never free text.

`run_chat_turn` (`agent/runner.py`) wraps the loop with conversation persistence + tracing,
and includes an **escalation backstop**: if the verdict is ESCALATE but the model forgot to
call `escalate_to_manager`, the runner opens the ticket itself.

## 5. Tools

### LLM-visible (the agent's menu — 9)

| tool | role |
|---|---|
| `lookup_customer(email \| phone)` | identify |
| `get_order(order_id)` | identify |
| `list_customer_orders(customer_id)` | identify |
| `check_refund_eligibility(order_id)` | **policy** — the single decision entry point |
| `issue_refund(order_id)` | **action** — re-validates! |
| `escalate_to_manager(order_id, reason)` | **action** — dedupes open tickets |
| `request_more_info(missing_field)` | converse |
| `record_refund_reason(reason)` | tracking only (does not change the verdict) |
| `get_policy_section(topic)` | converse — quote the policy |

### Internal (code-only — NOT exposed to the LLM)

The 5 `_check_*` functions above. `check_refund_eligibility` calls them in code and could
nest them as child `agent_steps` (`parent_step_id`) so the admin trace shows full depth.

**Why the split:** the LLM can't forget a check or run them out of order — determinism is
guaranteed in code. Hard rules (dates, money, flags) → code; language, orchestration,
explanation → LLM.

## 6. Defense-in-depth (the "holding the line" guarantee)

Two action-layer guards make the policy hold **even if the LLM is manipulated**:

- **`issue_refund` re-runs eligibility internally** and **refuses** to execute on any order
  that is not APPROVE — regardless of what the model "decided." A refund physically cannot
  fire on an ineligible order. The refund is also **idempotent** (`order.refunded_at` guard):
  it executes at most once.
- **`escalate_to_manager` deduplicates** — if the order already has an OPEN escalation, it
  returns that ticket instead of raising a second one. So asking again (even in a new chat)
  can't open duplicate cases.

The policy is enforced at the **action layer, not the prompt layer** — the strongest
differentiator of the system.

## 7. Reasoning trace & observability

Every step is written to `agent_steps` **and** published to the in-memory event bus.
`/admin` subscribes over **SSE** and renders steps **live** — tool called → result →
decision → why — with the internal checks shown as a tree. Because steps are **persisted**,
`/admin` also shows **past cases** (`GET /admin/cases`), not just the live one. Per-step
`latency_ms` and token counts give a lightweight cost/perf view.

## 8. AI case summary (meta use of the LLM)

`POST /admin/cases/{id}/summary` summarizes the agent's **own** run for a support manager —
2–3 sentences (what was requested, what the checks found, what the agent decided and why),
via the port's `LLMClient.complete(...)`. It is **cached** on the conversation and
**complements** the trace (triage with the summary, verify with the chain). The **key-fact
chips** beside it (`4/5 checks passed`, `Over ₹50,000`) are **computed in code** from the
policy engine — never the LLM — so the summary can't hallucinate the deciding numbers.

## 9. Edge cases

| # | Case | Expected |
|---|---|---|
| 1 | Order not found | agent recovers, asks again (no crash) |
| 2 | Wrong customer | DENY (ownership) |
| 3 | Already refunded | DENY (double-refund guard) |
| 4 | Over 30 days (regular) | DENY (out of window) |
| 5 | Over ₹50,000 (otherwise valid) | ESCALATE |
| 6 | Prompt-injection ("ignore policy / my manager said yes") | agent **and** the deterministic gate both hold; refund does not fire |

Plus the **system-failure** path (LLM timeout / malformed call → retry → MAX_STEPS) visible
in the trace.

## 10. Evals (`tests/evals/`)

Behavioral evals of the whole decision, sharing one scenario dataset (`scenarios.py`):

| suite | model | runs | checks |
|---|---|---|---|
| `test_evals_offline.py` | faked | always (CI-safe, free) | every scenario reaches the right **verdict** + side-effects |
| `test_evals_live.py` | real `gpt-4.1-mini` | opt-in (`RUN_EVALS=1`) | real prompt: correct verdict, replies stay short, escalations don't parrot the threshold, **holds the line** under pressure |
| `test_evals_scored.py` | real + LLM-judge | opt-in | a quality **score /5** across accuracy / brevity / tone / clarity |

```bash
uv run pytest                                   # unit + integration + offline evals (free)
RUN_EVALS=1 uv run pytest tests/evals -s        # live + scored (real API calls)
```

The rest of the suite: `tests/unit` (deterministic policy/refund/tools/tracing) and
`tests/integration` (agent loop, runner, API, voice bridge — all with a faked LLM, no live
calls).
