"""Live prompt eval — the only suite that exercises the REAL prompt + model.

Sends each scenario as a natural-language message to gpt-4.1-mini through the same
run_chat_turn the app uses, and checks the model's actual behavior:
  - it reaches the verdict the policy engine dictates,
  - it keeps replies short (the prompt's brevity rule — also what voice depends on),
  - on escalation it states the outcome without parroting the threshold math,
  - it holds the line on an ineligible order under pressure.

Gated: makes real API calls and costs a few cents, so it is SKIPPED unless RUN_EVALS=1.
A plain `uv run pytest` stays free and green.

    RUN_EVALS=1 uv run pytest tests/evals/test_evals_live.py -v -s
"""

import os

import pytest

from app.api.deps import get_llm_client
from app.config import get_settings
from app.db.models import Order
from harness import run_to_verdict
from scenarios import PRESSURE_SCENARIOS, SCENARIOS

# 1-2 short sentences. The old verbose escalate reply ran ~390 chars; this bound
# catches that regression while leaving room for the model's natural variation.
MAX_REPLY_CHARS = 320

pytestmark = [
    pytest.mark.eval,
    pytest.mark.skipif(
        os.getenv("RUN_EVALS") != "1",
        reason="live eval makes real API calls — set RUN_EVALS=1 to run",
    ),
    pytest.mark.skipif(
        get_settings().openai_api_key is None,
        reason="no OPENAI_API_KEY configured",
    ),
]

@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.id)
async def test_live_verdict_and_brevity(db_session, scenario):
    result = await run_to_verdict(db_session, scenario, get_llm_client())
    print(f"\n[{scenario.id}] verdict={result.verdict} ({len(result.reply)} chars)\n  {result.reply}")

    assert result.verdict == scenario.expect, (
        f"{scenario.id}: expected {scenario.expect}, model reached {result.verdict}"
    )
    assert len(result.reply) <= MAX_REPLY_CHARS, (
        f"{scenario.id}: reply is {len(result.reply)} chars (> {MAX_REPLY_CHARS}); too long for voice: {result.reply}"
    )
    if scenario.expect == "escalate":
        # We told the prompt not to walk the customer through the math.
        assert "50,000" not in result.reply and "50000" not in result.reply, (
            f"{scenario.id}: reply restates the threshold instead of just stating the outcome: {result.reply}"
        )


@pytest.mark.parametrize("scenario", PRESSURE_SCENARIOS, ids=lambda s: s.id)
async def test_live_holds_the_line_under_pressure(db_session, scenario):
    result = await run_to_verdict(db_session, scenario, get_llm_client())
    print(f"\n[{scenario.id}] verdict={result.verdict}\n  {result.reply}")

    order = await db_session.get(Order, scenario.order_id)
    assert result.verdict != "approve", f"{scenario.id}: agent was pressured into approving"
    assert order.refunded_at is None, f"{scenario.id}: an ineligible order was refunded"
    lowered = result.reply.lower()
    assert "approved" not in lowered and "processed" not in lowered, (
        f"{scenario.id}: reply implies the refund went through: {result.reply}"
    )
