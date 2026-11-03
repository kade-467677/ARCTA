from __future__ import annotations

from typing import Callable

from fastapi import (
    APIRouter,
    HTTPException,
)

from cta_core.column_mapping import (
    ArctaColumnMapping,
)

from web_common.sessions import (
    SessionNotFoundError,
)

from apps.arcta_web.campaign_mapping_service import (
    inspect_session_mapping_compatibility,
)


def _mapping_from_payload(
    payload: dict,
) -> ArctaColumnMapping:
    roles = payload.get(
        "roles",
        {},
    )

    if not isinstance(
        roles,
        dict,
    ):
        raise ValueError(
            "Le champ roles du mapping "
            "doit être un objet."
        )

    return ArctaColumnMapping(
        roles=dict(
            roles
        ),
        source_id=
            payload.get(
                "source_id"
            ),
        sheet_name=
            payload.get(
                "sheet_name"
            ),
    )


def build_campaign_mapping_router(
    resolve_session: Callable,
) -> APIRouter:
    router = APIRouter()

    def get_session_or_404(
        session_id: str,
    ):
        try:
            session = (
                resolve_session(
                    session_id
                )
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

        if session is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    "Session ARCTA inconnue : "
                    f"{session_id}"
                ),
            )

        return session

    @router.post(
        "/api/sessions/"
        "{session_id}/mapping/"
        "compatibility"
    )
    def inspect_mapping_compatibility(
        session_id: str,
        payload: dict,
    ):
        session = (
            get_session_or_404(
                session_id
            )
        )

        raw_mapping = (
            payload.get(
                "mapping"
            )
        )

        if not isinstance(
            raw_mapping,
            dict,
        ):
            raise HTTPException(
                status_code=422,
                detail=(
                    "Le champ mapping "
                    "est obligatoire."
                ),
            )

        try:
            mapping = (
                _mapping_from_payload(
                    raw_mapping
                )
            )

            report = (
                inspect_session_mapping_compatibility(
                    session,
                    mapping,
                )
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
            "session_id":
                session_id,
            "report":
                report,
        }

    return router