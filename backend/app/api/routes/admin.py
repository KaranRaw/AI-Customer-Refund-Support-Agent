"""Admin observability routes — the live SSE stream and case reads.

Thin handlers: the query + assembly logic lives in app.cases.service.
"""

import asyncio
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_llm_client
from app.api.schemas import (
    CaseDetail,
    CaseSummary,
    CaseSummaryResult,
    ResolveRequest,
    ResolveResult,
)
from app.cases import service as case_service
from app.db.database import get_session
from app.events.bus import event_bus
from app.llm.client import LLMClient
from app.refunds.service import resolve_escalation

router = APIRouter(prefix="/admin", tags=["admin"])

_HEARTBEAT_SECONDS = 15.0


@router.get("/stream")
async def stream(conversation_id: int | None = None) -> StreamingResponse:
    queue = event_bus.subscribe(conversation_id)

    async def event_generator():
        # On client disconnect the iterator is cancelled; the finally unsubscribes.
        try:
            yield "retry: 3000\n\n"  # reconnect hint + an immediate first chunk on connect
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=_HEARTBEAT_SECONDS)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"  # keep the connection alive through proxies
        finally:
            event_bus.unsubscribe(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/cases", response_model=list[CaseSummary])
async def list_cases(session: AsyncSession = Depends(get_session)) -> list[CaseSummary]:
    return await case_service.list_cases(session)


@router.get("/cases/{conversation_id}", response_model=CaseDetail)
async def case_detail(
    conversation_id: int, session: AsyncSession = Depends(get_session)
) -> CaseDetail:
    detail = await case_service.get_case_detail(session, conversation_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return detail


@router.post("/cases/{conversation_id}/summary", response_model=CaseSummaryResult)
async def summarize_case(
    conversation_id: int,
    session: AsyncSession = Depends(get_session),
    llm: LLMClient = Depends(get_llm_client),
) -> CaseSummaryResult:
    """Generate (and cache) an AI triage summary of the case. Complements the trace —
    the manager triages with the summary and verifies with the full reasoning chain."""
    result = await case_service.generate_case_summary(
        session, conversation_id, llm, now=datetime.now(timezone.utc)
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return result


@router.post("/escalations/{escalation_id}/resolve", response_model=ResolveResult)
async def resolve(
    escalation_id: int,
    payload: ResolveRequest,
    session: AsyncSession = Depends(get_session),
) -> ResolveResult:
    """A mock manager approves (issues the refund) or denies an open escalation."""
    outcome = await resolve_escalation(
        session, escalation_id, payload.decision, now=datetime.now(timezone.utc)
    )
    if outcome is None:
        raise HTTPException(status_code=404, detail="Escalation not found or already resolved.")
    return ResolveResult(
        decision=outcome.decision, verdict=outcome.verdict.value, refunded=outcome.refunded
    )
