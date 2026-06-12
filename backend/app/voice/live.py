"""Full-duplex live voice — a Pipecat pipeline over a FastAPI WebSocket.

Additive to the turn-based /voice/transcribe + /voice/speak endpoints. Runs
in-process so the agent's reasoning still streams to /admin over the same event
bus. Pipeline (1.3.0):

    input -> VAD -> rtvi -> STT -> AgentBridge -> TTS -> output

VAD is a pipeline processor in 1.3.0 (not a transport param); the RTVI processor
is required for the @pipecat-ai JS client's connect handshake.
"""

import logging

from fastapi import WebSocket
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.audio.vad_processor import VADProcessor
from pipecat.processors.frameworks.rtvi import RTVIObserver, RTVIProcessor
from pipecat.serializers.protobuf import ProtobufFrameSerializer
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)
from pipecat.workers.runner import WorkerRunner

from app.api.deps import get_llm_client
from app.config import get_settings
from app.voice.agent_bridge import AgentBridge

logger = logging.getLogger(__name__)


async def run_voice_session(
    websocket: WebSocket,
    customer_email: str | None = None,
    conversation_id: int | None = None,
) -> None:
    await websocket.accept()
    settings = get_settings()

    transport = FastAPIWebsocketTransport(
        websocket=websocket,
        params=FastAPIWebsocketParams(
            serializer=ProtobufFrameSerializer(),
            audio_in_enabled=True,
            audio_out_enabled=True,
            add_wav_header=False,  # protobuf carries raw PCM frames
            session_timeout=300,
        ),
    )

    stt = DeepgramSTTService(api_key=settings.deepgram_api_key)
    tts = ElevenLabsTTSService(
        api_key=settings.elevenlabs_api_key,
        voice_id=settings.elevenlabs_voice_id,
    )
    rtvi = RTVIProcessor(transport=transport)
    agent = AgentBridge(
        llm=get_llm_client(),
        customer_email=customer_email,
        conversation_id=conversation_id,
        rtvi=rtvi,
    )

    pipeline = Pipeline(
        [
            transport.input(),
            # stop_secs = how long you pause before the agent takes its turn.
            # 0.7s lets you breathe mid-sentence without being cut off (default 0.2 is too eager).
            VADProcessor(vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=0.7))),
            rtvi,
            stt,
            agent,
            tts,
            transport.output(),
        ]
    )

    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(enable_metrics=True),
        observers=[RTVIObserver(rtvi)],
    )

    @transport.event_handler("on_client_disconnected")
    async def _on_disconnect(_transport, _client):  # noqa: ANN001
        logger.info("voice/live client disconnected")
        await worker.cancel()

    runner = WorkerRunner(handle_sigint=False)  # inside FastAPI — don't own signals
    await runner.add_workers(worker)
    await runner.run()
