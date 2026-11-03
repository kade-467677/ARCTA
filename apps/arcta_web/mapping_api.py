from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from cta_core.column_detection import (
    DEFAULT_COLUMN_ROLE_MIN_SCORE,
    suggest_column_mapping,
)
from cta_core.column_mapping import (
    arcta_column_mapping_from_dict,
)
from web_common.sessions import (
    SessionNotFoundError,
)

from apps.arcta_web.session_mapping import (
    MAPPING_STATUS_DRAFT,
    MAPPING_STATUS_VALIDATED,
    delete_session_mapping,
    load_session_mapping,
    save_session_mapping,
)
from apps.arcta_web.campaign_mapping_service import (
    inspect_session_mapping_compatibility,
)


class MappingSaveRequest(BaseModel):
    mapping: dict[str, Any]
    status: str = MAPPING_STATUS_DRAFT


class MappingSuggestRequest(BaseModel):
    columns: list[str]
    source_id: str | None = None
    sheet_name: str | None = None
    min_score: int = DEFAULT_COLUMN_ROLE_MIN_SCORE


def build_mapping_router(
    resolve_session: Callable[[str], Any],
) -> APIRouter:
    router = APIRouter()

    def session_or_404(
        session_id: str,
    ):
        try:
            session = resolve_session(
                session_id
            )
        except (
            SessionNotFoundError,
            KeyError,
        ):
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Session ARCTA inconnue : "
                    f"{session_id}"
                ),
            )

        if session is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Session ARCTA inconnue : "
                    f"{session_id}"
                ),
            )

        return session

    @router.get(
        "/api/sessions/{session_id}/mapping"
    )
    def get_mapping(
        session_id: str,
    ):
        session = session_or_404(
            session_id
        )

        stored = load_session_mapping(
            session
        )

        if stored is None:
            return {
                "session_id": session_id,
                "exists": False,
                "stored": None,
            }

        return {
            "session_id": session_id,
            "exists": True,
            "stored": stored.to_dict(),
        }

    @router.put(
        "/api/sessions/{session_id}/mapping"
    )
    def put_mapping(
        session_id: str,
        payload: MappingSaveRequest,
    ):
        session = session_or_404(
            session_id
        )

        try:
            mapping = (
                arcta_column_mapping_from_dict(
                    payload.mapping
                )
            )

            normalized_status = str(
                payload.status
            ).strip().upper()

            compatibility = None

            if (
                normalized_status
                == MAPPING_STATUS_VALIDATED
            ):
                mapping.validate()

                compatibility = (
                    inspect_session_mapping_compatibility(
                        session,
                        mapping,
                    )
                )

                if not compatibility[
                    "all_compatible"
                ]:
                    incompatible_count = int(
                        compatibility[
                            "incompatible_count"
                        ]
                    )

                    raise HTTPException(
                        status_code=422,
                        detail={
                            "code": (
                                "CAMPAIGN_MAPPING_"
                                "INCOMPATIBLE"
                            ),
                            "message": (
                                "Validation impossible : "
                                f"{incompatible_count} "
                                "fichier(s) de la campagne "
                                "sont incompatibles avec "
                                "le mapping."
                            ),
                            "report": compatibility,
                        },
                    )

            stored = save_session_mapping(
                session,
                mapping,
                status=normalized_status,
            )

        except (
            TypeError,
            ValueError,
        ) as exc:
            raise HTTPException(
                status_code=422,
                detail=str(exc),
            )

        return {
            "session_id": session_id,
            "stored": stored.to_dict(),
            "compatibility": compatibility,
        }

    @router.post(
        "/api/sessions/{session_id}/mapping/suggest"
    )
    def suggest_mapping(
        session_id: str,
        payload: MappingSuggestRequest,
    ):
        session_or_404(
            session_id
        )

        if not payload.columns:
            raise HTTPException(
                status_code=422,
                detail=(
                    "La liste des colonnes "
                    "ne peut pas être vide."
                ),
            )

        suggestion = suggest_column_mapping(
            columns=payload.columns,
            source_id=payload.source_id,
            sheet_name=payload.sheet_name,
            min_score=payload.min_score,
        )

        return {
            "session_id": session_id,
            **suggestion.to_dict(),
        }

    @router.delete(
        "/api/sessions/{session_id}/mapping"
    )
    def delete_mapping(
        session_id: str,
    ):
        session = session_or_404(
            session_id
        )

        deleted = delete_session_mapping(
            session
        )

        return {
            "session_id": session_id,
            "deleted": deleted,
        }

    return router