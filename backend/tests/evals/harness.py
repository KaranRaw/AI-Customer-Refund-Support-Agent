"""Shared eval harness — drive the agent the way the UI does.

Both the live and scored suites need the same thing: send a customer message and, if
the agent asks for a refund reason before deciding, send the reason as a second turn
(like clicking a reason chip), then read the final reply. Kept here so neither suite
re-implements that flow.
"""

from app.events.bus import EventBus

from app.agent.runner import run_chat_turn

# Stands in for the customer's reply when the agent asks why they want the refund.
FOLLOWUP_REASON = "No longer needed — please go ahead."


async def run_to_verdict(db_session, scenario, llm, *, max_turns=2):
    """Run the conversation until the agent reaches a verdict (or turns run out)."""
    bus = EventBus()
    conversation_id = None
    result = None
    for turn in range(max_turns):
        message = scenario.message if turn == 0 else FOLLOWUP_REASON
        result = await run_chat_turn(
            db_session,
            message=message,
            conversation_id=conversation_id,
            llm=llm,
            bus=bus,
            customer_email=scenario.email,
        )
        conversation_id = result.conversation_id
        if result.verdict is not None:
            break
    return result
