from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.templating import Jinja2Templates

from arcta.profiles import (
    ARCTA_RUN_PROFILE_LABELS,
    DEFAULT_ARCTA_RUN_PROFILE,
)
from web_common.sessions import SessionNotFoundError, is_trial_source

from arcta.reporting.options import (
    DEFAULT_POLY_STATS,
    DEFAULT_POLY_TYPES,
    POLY_STAT_OPTIONS,
    POLY_TYPE_OPTIONS,
    REPORT_GRAPH_OPTIONS,
    REPORT_SECTION_OPTIONS,
    SYNTHETIC_GRAPH_KEYS,
)


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


@router.get("/sessions/{session_id}/campaign")
def campaign_run_page(request: Request, session_id: str):
    session = _get_session_or_404(request, session_id)
    return templates.TemplateResponse(
        request=request,
        name="campaign_run.html",
        context={
            "session_id": session_id,
            "source_count": sum(
                is_trial_source(source)
                for source in getattr(session, "sources", {}).values()
            ),
            "workspace_path": str(session.storage_dir),
            "profile_options": tuple(ARCTA_RUN_PROFILE_LABELS.items()),
            "default_profile": DEFAULT_ARCTA_RUN_PROFILE,
            "report_graph_options": REPORT_GRAPH_OPTIONS,
            "report_section_options": REPORT_SECTION_OPTIONS,
            "poly_type_options": POLY_TYPE_OPTIONS,
            "poly_stat_options": POLY_STAT_OPTIONS,
            "synthetic_graph_keys": SYNTHETIC_GRAPH_KEYS,
            "default_poly_types": DEFAULT_POLY_TYPES,
            "default_poly_stats": DEFAULT_POLY_STATS,
        },
    )
