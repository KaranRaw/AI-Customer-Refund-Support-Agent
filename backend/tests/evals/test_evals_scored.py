"""Scored eval — an LLM-as-judge rubric that produces an actual /5 score.

Unlike the pass/fail suites, this grades the *quality* of each reply. For every
scenario we run the real agent, then a judge model scores the reply 1-5 on four
dimensions (accuracy, brevity, tone, clarity). The per-scenario averages roll up to
one OVERALL SCORE / 5, printed as a scorecard.

Gated like the live suite (real API calls):

    RUN_EVALS=1 uv run pytest tests/evals/test_evals_scored.py -s

Caveat worth stating in the demo: the judge is the same model family as the agent
(gpt-4.1-mini is the only model this project has access to), so it is self-judging —
fine for a relative quality signal, not an absolute external grade.
"""

import json
import os

import pytest
from openai import AsyncOpenAI

from app.api.deps import get_llm_client
from app.config import get_settings
from harness import run_to_verdict
from scenarios import PRESSURE_SCENARIOS, SCENARIOS

DIMENSIONS = ["accuracy", "brevity", "tone", "clarity"]
MIN_OVERALL = 3.5  # a quality floor; the real output is the printed score

# What a correct reply should communicate, per verdict — given to the judge so it can
# grade "accuracy" against the policy-correct outcome rather than guessing.
_OUTCOME = {
    "approve": "the refund is APPROVED and being processed",
    "deny": "the refund is DENIED — politely, with the reason",
    "escalate": "the request is ESCALATED to a manager for approval",
}

_JUDGE_SYSTEM = (
    "You are a strict QA reviewer for a customer-support refund agent at an electronics "
    "store. Grade the agent's reply to the customer. Score each dimension from 1 (poor) "
    "to 5 (excellent); be calibrated — 5 means genuinely excellent, 3 acceptable, 1 bad. "
    "Respond with a JSON object only."
)

pytestmark = [
    pytest.mark.eval,
    pytest.mark.skipif(
        os.getenv("RUN_EVALS") != "1",
        reason="scored eval makes real API calls — set RUN_EVALS=1 to run",
    ),
    pytest.mark.skipif(
        get_settings().openai_api_key is None,
        reason="no OPENAI_API_KEY configured",
    ),
]


def _judge_prompt(reply: str, scenario) -> str:
    return (
        f"Customer situation: {scenario.why}.\n"
        f"Policy-correct outcome: {_OUTCOME[scenario.expect]}.\n\n"
        f"Customer: {scenario.message}\n"
        f"Agent: {reply}\n\n"
        "Grade the AGENT's reply 1-5 on each dimension:\n"
        f"- accuracy: does it convey the policy-correct outcome ({scenario.expect}) and a sensible reason?\n"
        "- brevity: concise and voice-friendly (ideally 1-2 short sentences); penalize restating amounts/thresholds.\n"
        "- tone: warm, empathetic, professional — even when denying or under pressure.\n"
        "- clarity: clear about what happens next, no internal jargon.\n\n"
        'Return JSON exactly like: {"accuracy": 5, "brevity": 5, "tone": 5, "clarity": 5, "comment": "one short sentence"}'
    )


def _clamp(value, low=1, high=5) -> int:
    try:
        n = int(round(float(value)))
    except (TypeError, ValueError):
        return low
    return max(low, min(high, n))


async def _judge(judge: AsyncOpenAI, reply: str, scenario) -> dict:
    response = await judge.chat.completions.create(
        model=get_settings().llm_model,
        messages=[
            {"role": "system", "content": _JUDGE_SYSTEM},
            {"role": "user", "content": _judge_prompt(reply, scenario)},
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    data = json.loads(response.choices[0].message.content)
    return {d: _clamp(data.get(d)) for d in DIMENSIONS} | {"comment": str(data.get("comment", ""))[:80]}


async def test_scored_eval(db_session):
    scenarios = SCENARIOS + PRESSURE_SCENARIOS
    judge = AsyncOpenAI(api_key=get_settings().openai_api_key)

    rows = []
    for scenario in scenarios:
        result = await run_to_verdict(db_session, scenario, get_llm_client())
        scores = await _judge(judge, result.reply, scenario)
        avg = sum(scores[d] for d in DIMENSIONS) / len(DIMENSIONS)
        rows.append({"id": scenario.id, "scores": scores, "avg": avg, "reply": result.reply})

    dim_avg = {d: sum(r["scores"][d] for r in rows) / len(rows) for d in DIMENSIONS}
    overall = sum(r["avg"] for r in rows) / len(rows)

    # Scorecard (visible with -s).
    model = get_settings().llm_model
    line = "=" * 86
    print(f"\n{line}\nSCORED EVAL   agent: {model}   judge: {model} (self-judged)\n{line}")
    print(f"{'scenario':34}" + "".join(f"{d[:4]:>6}" for d in DIMENSIONS) + f"{'avg':>7}   comment")
    print("-" * 86)
    for r in rows:
        cells = "".join(f"{r['scores'][d]:>6}" for d in DIMENSIONS)
        print(f"{r['id']:34}{cells}{r['avg']:>7.2f}   {r['scores']['comment']}")
    print("-" * 86)
    print(f"{'dimension average':34}" + "".join(f"{dim_avg[d]:>6.1f}" for d in DIMENSIONS))
    print(f"\n  OVERALL SCORE:  {overall:.2f} / 5   (n={len(rows)} scenarios)\n{line}\n")

    assert overall >= MIN_OVERALL, f"overall quality {overall:.2f} below floor {MIN_OVERALL}"
