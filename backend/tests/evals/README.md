# Evals

Behavioral evals for the refund agent — "does the agent *decide* and *speak*
correctly?", as opposed to the unit/integration tests that check individual pieces.

Both suites run the same ground-truth scenarios from `scenarios.py` (one real seeded
order per decision path, plus an adversarial pressure case), so they can't drift apart.

| File | Model | Runs | Checks |
|------|-------|------|--------|
| `test_evals_offline.py` | **faked** | always, free, in CI | the engine + tools + runner reach the right **verdict** and side-effects (refund executed / ticket opened / nothing) for every scenario |
| `test_evals_live.py` | **real** (`gpt-4.1-mini`) | opt-in, costs a few cents | the real **prompt**, pass/fail: correct verdict, replies stay short (≤ 320 chars — also what voice needs), escalations don't parrot the threshold math, and the agent **holds the line** under pressure |
| `test_evals_scored.py` | **real** + **judge** | opt-in | a quality **score /5**: a judge model grades each reply 1-5 on accuracy / brevity / tone / clarity, rolled up to one OVERALL SCORE |

## Running

```bash
# offline evals run as part of the normal suite — no key, no cost
uv run pytest tests/evals/test_evals_offline.py -v

# live + scored evals are gated; they make real API calls
RUN_EVALS=1 uv run pytest tests/evals/test_evals_live.py -v -s
RUN_EVALS=1 uv run pytest tests/evals/test_evals_scored.py -s   # prints the scorecard
```

Without `RUN_EVALS=1` the live and scored suites self-skip, so `uv run pytest` stays free and green.

## The score

`test_evals_scored.py` prints a scorecard ending in `OVERALL SCORE: X.XX / 5`. It's a
*relative* quality signal, not an absolute grade — two honest caveats:
- **Self-judged.** The judge is the same model family as the agent (the only model this
  project has access to), so treat it as a sanity check, not an external authority.
- **One run, non-deterministic.** A single score is a snapshot; run it a few times if
  you need a stable number.

## Adding a scenario

Add a `Scenario(...)` row to `scenarios.py` pointing at a seeded order, with the
verdict the policy (`app/policy/policy_config.json`: 30-day window, 45 for VIP,
₹50,000 threshold) dictates. Both suites pick it up automatically.
