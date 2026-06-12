"""Unit tests for the live-voice AgentBridge — faked agent turn, no DB/LLM/audio."""

import contextlib

from pipecat.frames.frames import (
    TranscriptionFrame,
    TTSSpeakFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from app.voice import agent_bridge as bridge_mod
from app.voice.agent_bridge import AgentBridge


class _FakeResult:
    def __init__(self, conversation_id: int, reply: str) -> None:
        self.conversation_id = conversation_id
        self.reply = reply


def _transcript(text: str) -> TranscriptionFrame:
    return TranscriptionFrame(text=text, user_id="cust-1", timestamp="t")


async def _feed(bridge: AgentBridge, frame) -> None:
    await bridge.process_frame(frame, FrameDirection.DOWNSTREAM)


async def test_run_turn_persists_conversation_id_across_turns(monkeypatch):
    """First turn opens a new conversation; later turns reuse its id (one voice session)."""
    seen_ids = []

    async def fake_run_chat_turn(session, *, message, conversation_id, **kwargs):
        seen_ids.append(conversation_id)
        return _FakeResult(conversation_id=99, reply=f"echo: {message}")

    @contextlib.asynccontextmanager
    async def fake_session_factory():
        yield object()

    monkeypatch.setattr(bridge_mod, "run_chat_turn", fake_run_chat_turn)
    monkeypatch.setattr(bridge_mod, "SessionFactory", fake_session_factory)

    bridge = AgentBridge(llm=object(), customer_email="aarav.sharma@example.com")
    first = await bridge._run_turn("refund my order")
    await bridge._run_turn("what about the cable")

    assert first == "echo: refund my order"
    assert seen_ids == [None, 99]


async def test_accumulates_fragments_and_speaks_on_stop(monkeypatch):
    """Transcript fragments accumulate; the FULL utterance runs the agent on stop, spoken via TTS."""
    pushed = []

    async def capture(frame, direction):
        pushed.append(frame)

    async def noop_super(self, frame, direction):  # stub the FrameProcessor lifecycle
        return None

    async def fake_turn(text):
        return f"got: {text}"

    monkeypatch.setattr(FrameProcessor, "process_frame", noop_super)

    bridge = AgentBridge(llm=object())
    monkeypatch.setattr(bridge, "_run_turn", fake_turn)
    monkeypatch.setattr(bridge, "push_frame", capture)

    await _feed(bridge, _transcript("Can you tell me my last"))
    await _feed(bridge, _transcript("order?"))
    await _feed(bridge, UserStoppedSpeakingFrame())  # fires on stop, not per fragment
    assert bridge._task is not None
    await bridge._task

    spoken = [f for f in pushed if isinstance(f, TTSSpeakFrame)]
    assert [f.text for f in spoken] == ["got: Can you tell me my last order?"]


async def test_blank_utterance_does_not_run_agent(monkeypatch):
    """A stop with no buffered speech does not invoke the agent."""
    called = False

    async def capture(frame, direction):
        return None

    async def noop_super(self, frame, direction):
        return None

    async def fake_turn(text):
        nonlocal called
        called = True
        return "should not happen"

    monkeypatch.setattr(FrameProcessor, "process_frame", noop_super)

    bridge = AgentBridge(llm=object())
    monkeypatch.setattr(bridge, "_run_turn", fake_turn)
    monkeypatch.setattr(bridge, "push_frame", capture)

    await _feed(bridge, _transcript("   "))
    await _feed(bridge, UserStoppedSpeakingFrame())

    assert called is False
    assert bridge._task is None
