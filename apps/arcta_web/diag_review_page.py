from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.templating import Jinja2Templates

from web_common.sessions import SessionNotFoundError, is_trial_source


router = APIRouter()

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _get_session_or_404(request: Request, session_id: str):
    registry = request.app.state.session_registry

    try:
        return registry.get_session(session_id)
    except (SessionNotFoundError, KeyError):
        raise HTTPException(
            status_code=404,
            detail=f"Session ARCTA inconnue : {session_id}",
        )


@router.get("/sessions/{session_id}/diag")
def diag_review_page(request: Request, session_id: str):
    session = _get_session_or_404(request, session_id)
    raw_sources = getattr(session, "sources", {})
    source_count = sum(
        is_trial_source(source)
        for source in raw_sources.values()
    )

    return templates.TemplateResponse(
        request=request,
        name="diag_review.html",
        context={
            "session_id": session_id,
            "source_count": source_count,
        },
    )
