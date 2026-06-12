"""Live full-duplex voice — a Pipecat pipeline over a WebSocket.

Thin handler: the pipeline lives in app.voice.live.
"""

from fastapi import APIRouter, WebSocket

from app.voice.live import run_voice_session

router = APIRouter(prefix="/voice", tags=["voice"])


@router.websocket("/live")
async def voice_live(
    websocket: WebSocket, email: str | None = None, conversation_id: int | None = None
) -> None:
    """Full-duplex live voice. `email` ties the session to a signed-in customer;
    `conversation_id` continues an existing chat thread so voice + text share context."""
    await run_voice_session(websocket, customer_email=email, conversation_id=conversation_id)
