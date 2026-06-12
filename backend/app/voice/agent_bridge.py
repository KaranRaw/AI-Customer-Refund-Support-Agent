"""Bridge between Pipecat's audio pipeline and our own agent loop.

Pipecat moves audio + does STT/TTS; it never calls an LLM here. We reuse the exact
same `run_chat_turn` as text chat (same policy engine, tools, defense-in-depth, and
reasoning trace), and because it emits to the in-memory event bus, voice
conversations also stream live to /admin.

Turn-taking details that matter:
- Deepgram splits one spoken sentence into several FINAL `TranscriptionFrame`s
  ("Can you tell me my last" + "order?"). We ACCUMULATE those fragments and run the
  agent once, when the VAD says the user stopped speaking — not per fragment.
- The reply is injected as a `TTSSpeakFrame` (speak this exact string), which is more
  robust across interruptions than a bare `TextFrame`.
- The agent takes a couple of seconds, so it runs as a background task; awaiting it
  inside `process_frame` would stall audio I/O. A `_busy` flag prevents overlap.
"""

import asyncio
import logging

from pipecat.frames.frames import (
    Frame,
    TranscriptionFrame,
    TTSSpeakFrame,
    UserStoppedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.processors.frameworks.rtvi import RTVIProcessor

from app.agent.runner import run_chat_turn
from app.db.database import SessionFactory
from app.db.models import ConversationChannel
from app.events.bus import event_bus
from app.llm.client import LLMClient

logger = logging.getLogger(__name__)

# The VAD emits VADUserStoppedSpeakingFrame; the STT layer may also re-emit the
# standard UserStoppedSpeakingFrame. Either means "the user finished their turn".
_STOP_FRAMES = (UserStoppedSpeakingFrame, VADUserStoppedSpeakingFrame)


class AgentBridge(FrameProcessor):
    def __init__(
        self,
        llm: LLMClient,
        customer_email: str | None = None,
        conversation_id: int | None = None,
        rtvi: RTVIProcessor | None = None,
    ) -> None:
        super().__init__()
        self._llm = llm
        self._customer_email = customer_email
        # Used to push the reply TEXT to the client (BotTranscript doesn't fire for the
        # TTSSpeakFrame we inject, so the chat bubble comes from a server message).
        self._rtvi = rtvi
        # Seeded from the chat so voice continues the SAME conversation; then carried
        # across voice turns.
        self._conversation_id: int | None = conversation_id
        self._buffer = ""
        self._busy = False
        self._task: asyncio.Task | None = None

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        # super() first: it drives the StartFrame/EndFrame/interruption lifecycle.
        await super().process_frame(frame, direction)

        if isinstance(frame, TranscriptionFrame):
            if frame.text.strip():
                self._buffer = f"{self._buffer} {frame.text}".strip()
            return  # consume so TTS never echoes the user's words

        if isinstance(frame, _STOP_FRAMES):
            logger.info(
                "AgentBridge: user stopped (buffer=%r, busy=%s)", self._buffer, self._busy
            )
            if self._buffer and not self._busy:
                text, self._buffer = self._buffer, ""
                self._busy = True
                self._task = asyncio.create_task(self._handle(text, direction))

        # Audio / control / VAD / interruption frames pass straight through.
        await self.push_frame(frame, direction)

    async def _handle(self, text: str, direction: FrameDirection) -> None:
        try:
            logger.info("AgentBridge: running agent on %r", text)
            # Tell the client the agent is working, so the voice orb can show its
            # "thinking" state between the user's turn and the spoken reply.
            if self._rtvi is not None:
                await self._rtvi.send_server_message({"type": "thinking"})
            reply = await self._run_turn(text)
            logger.info("AgentBridge: reply -> %r", reply)
            if reply.strip():
                if self._rtvi is not None:
                    await self._rtvi.send_server_message({"type": "bot_reply", "text": reply})
                await self.push_frame(TTSSpeakFrame(reply), direction)
        except Exception:
            logger.exception("AgentBridge: agent turn failed")
        finally:
            self._busy = False

    async def _run_turn(self, text: str) -> str:
        async with SessionFactory() as session:
            result = await run_chat_turn(
                session,
                message=text,
                conversation_id=self._conversation_id,
                llm=self._llm,
                bus=event_bus,
                channel=ConversationChannel.VOICE,
                customer_email=self._customer_email,
            )
        self._conversation_id = result.conversation_id
        return result.reply
