from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from web_common.sessions import SessionNotFoundError

from apps.arcta_web.diag_execution_service import (
    DiagExecutionPrerequisiteError,
    execute_session_diag,
)
from apps.arcta_web.session_diag_review import (
    ArctaSessionDiagReview,
    SessionDiagReviewError,
    assess_session_diag_review,
    build_diag_campaign_context,
    create_session_diag_review,
    load_session_diag_review,
    update_session_diag_trial_decision,
    validate_session_diag_review,
)


class DiagValidationRequest(BaseModel):
    selflock_token: str | None = None


class DiagRunRequest(BaseModel):
    force: bool = False


class DiagTrialDecisionRequest(BaseModel):
    decision: str
    comment: str = ""


def _review_response(
    session_id: str,
    session,
    state: ArctaSessionDiagReview,
) -> dict[str, object]:
    assessment = assess_session_diag_review(session, state)

    return {
        "session_id": session_id,
        "exists": True,
        **assessment,
        "stored": state.to_dict(),
    }


def build_diag_review_router(
    resolve_session: Callable[[str], Any],
) -> APIRouter:
    router = APIRouter()

    def session_or_404(session_id: str):
        try:
            session = resolve_session(session_id)
        except (SessionNotFoundError, KeyError):
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Session ARCTA inconnue : {session_id}"
                ),
            )

        if session is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Session ARCTA inconnue : {session_id}"
                ),
            )

        return session

    def review_or_404(session_id: str, session):
        state = load_session_diag_review(session)

        if state is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "DIAG_REVIEW_NOT_FOUND",
                    "message": (
                        "Aucune revue DIAG n'est enregistrée "
                        "pour cette session."
                    ),
                },
            )

        return state

    @router.get(
        "/api/sessions/{session_id}/diag/review"
    )
    def get_diag_review(session_id: str):
        session = session_or_404(session_id)
        state = load_session_diag_review(session)

        if state is None:
            return {
                "session_id": session_id,
                "exists": False,
                "stale": False,
                "reasons": [],
                "stored": None,
            }

        return _review_response(
            session_id,
            session,
            state,
        )

    @router.post(
        "/api/sessions/{session_id}/diag/run"
    )
    def run_diag(
        session_id: str,
        payload: DiagRunRequest | None = None,
    ):
        session = session_or_404(session_id)
        request = payload or DiagRunRequest()
        current = load_session_diag_review(session)

        if current is not None:
            assessment = assess_session_diag_review(session, current)

            if (
                current.review.validated
                and not assessment["stale"]
                and not request.force
            ):
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "DIAG_REVIEW_ALREADY_VALIDATED",
                        "message": (
                            "La revue DIAG courante est déjà validée. "
                            "Une nouvelle exécution exige force=true."
                        ),
                    },
                )

        try:
            context_before = build_diag_campaign_context(session)
            execution = execute_session_diag(session)
            context_after = build_diag_campaign_context(session)

            if (
                context_before["signature"]
                != context_after["signature"]
            ):
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "DIAG_CAMPAIGN_CHANGED_DURING_RUN",
                        "message": (
                            "Les sources ou le mapping ont changé pendant "
                            "le DIAG. Aucun résultat n'a été enregistré."
                        ),
                    },
                )

            state = create_session_diag_review(
                session,
                execution,
                campaign_context=context_before,
            )
        except DiagExecutionPrerequisiteError as exc:
            detail = {
                "code": exc.code,
                "message": str(exc),
            }

            if exc.compatibility is not None:
                detail["compatibility"] = exc.compatibility

            raise HTTPException(
                status_code=422,
                detail=detail,
            )
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "DIAG_EXECUTION_INVALID",
                    "message": str(exc),
                },
            )

        return _review_response(
            session_id,
            session,
            state,
        )

    @router.put(
        "/api/sessions/{session_id}/diag/review/"
        "trials/{source_id}"
    )
    def put_trial_decision(
        session_id: str,
        source_id: str,
        payload: DiagTrialDecisionRequest,
    ):
        session = session_or_404(session_id)
        state = review_or_404(session_id, session)

        try:
            state = update_session_diag_trial_decision(
                session,
                state,
                source_id=source_id,
                decision=payload.decision,
                comment=payload.comment,
            )
        except SessionDiagReviewError as exc:
            status_code = (
                404
                if exc.code == "DIAG_REVIEW_SOURCE_NOT_FOUND"
                else 409
            )
            raise HTTPException(
                status_code=status_code,
                detail={
                    "code": exc.code,
                    "message": str(exc),
                },
            )
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "DIAG_REVIEW_INVALID_DECISION",
                    "message": str(exc),
                },
            )

        return _review_response(
            session_id,
            session,
            state,
        )

    @router.post(
        "/api/sessions/{session_id}/diag/review/validate"
    )
    def validate_diag_review(session_id: str, request: DiagValidationRequest | None = None):
        session = session_or_404(session_id)
        state = review_or_404(session_id, session)

        try:
            state = validate_session_diag_review(
                session,
                state,
                selflock_token=request.selflock_token if request else None,
            )
        except SessionDiagReviewError as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": exc.code,
                    "message": str(exc),
                },
            )
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "DIAG_REVIEW_VALIDATION_FAILED",
                    "message": str(exc),
                },
            )

        return _review_response(
            session_id,
            session,
            state,
        )

    @router.get("/api/sessions/{session_id}/diag/review/selflock-config")
    def selflock_config_preview(session_id: str):
        from .diag_selflock_config import proposal
        session = session_or_404(session_id)
        state = review_or_404(session_id, session)
        if assess_session_diag_review(session, state)["stale"]:
            raise HTTPException(status_code=409, detail="Revue DIAG périmée.")
        return proposal(session, state)

    return router
