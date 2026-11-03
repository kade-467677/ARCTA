from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from web_common.sessions import SessionNotFoundError, is_trial_source
from apps.arcta_web.session_canonical_config import (
    load_session_canonical_config,
)


router = APIRouter()

TEMPLATES_DIR = (
    Path(__file__).resolve().parent
    / "templates"
)

templates = Jinja2Templates(
    directory=str(TEMPLATES_DIR)
)


def _get_session_or_404(
    request: Request,
    session_id: str,
):
    registry = (
        request.app.state
        .session_registry
    )

    try:
        return registry.get_session(
            session_id
        )
    except (
        SessionNotFoundError,
        KeyError,
    ):
        raise HTTPException(
            status_code=404,
            detail=(
                "Session ARCTA inconnue : "
                f"{session_id}"
            ),
        )


def _session_sources(
    session,
) -> list[dict[str, str]]:
    raw_sources = getattr(
        session,
        "sources",
        {},
    )

    if isinstance(
        raw_sources,
        dict,
    ):
        items = raw_sources.values()
    else:
        items = raw_sources

    result = []

    for source in items:
        if not is_trial_source(source):
            continue

        source_id = str(
            getattr(
                source,
                "source_id",
                "",
            )
        ).strip()

        filename = str(
            getattr(
                source,
                "original_name",
                source_id,
            )
        ).strip()

        if not source_id:
            continue

        result.append({
            "source_id": source_id,
            "filename": (
                filename
                or source_id
            ),
        })

    return result


@router.get(
    "/sessions/{session_id}/mapping"
)
def mapping_page(
    request: Request,
    session_id: str,
):
    session = _get_session_or_404(
        request,
        session_id,
    )

    canonical_load_failed = False

    try:
        canonical_state = load_session_canonical_config(session)
    except Exception:
        canonical_state = None
        canonical_load_failed = True

    if canonical_load_failed or (
        canonical_state is not None
        and (
            not canonical_state.validated
            or canonical_state.config is None
            or not canonical_state.config.validation_summary()["calculation_ready"]
        )
    ):
        return RedirectResponse(
            url=f"/sessions/{session_id}/config?blocked=mapping",
            status_code=303,
        )

    sources = _session_sources(
        session
    )

    return templates.TemplateResponse(
        request=request,
        name="mapping.html",
        context={
            "session_id": session_id,
            "sources": sources,
        },
    )
