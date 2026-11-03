from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from cta_core.column_mapping import (
    ArctaColumnMapping,
    arcta_column_mapping_from_dict,
)

from apps.arcta_web.session_config import (
    session_config_path,
)

SESSION_MAPPING_FILENAME = "arcta_column_mapping.json"

MAPPING_STATUS_DRAFT = "DRAFT"
MAPPING_STATUS_VALIDATED = "VALIDATED"

MAPPING_STATUSES = {
    MAPPING_STATUS_DRAFT,
    MAPPING_STATUS_VALIDATED,
}


@dataclass(frozen=True)
class ArctaSessionMapping:
    mapping: ArctaColumnMapping
    status: str
    updated_at: str

    def __post_init__(self) -> None:
        normalized_status = str(self.status).strip().upper()

        if normalized_status not in MAPPING_STATUSES:
            raise ValueError(
                f"Statut de mapping invalide : {self.status!r}"
            )

        object.__setattr__(
            self,
            "status",
            normalized_status,
        )

    @property
    def validated(self) -> bool:
        return self.status == MAPPING_STATUS_VALIDATED

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "validated": self.validated,
            "updated_at": self.updated_at,
            "mapping": self.mapping.to_dict(),
        }


def _utc_now_iso() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


def session_mapping_path(
    session,
) -> Path:
    return session_config_path(
        session
    ).with_name(
        SESSION_MAPPING_FILENAME
    )

def save_session_mapping(
    session,
    mapping: ArctaColumnMapping,
    status: str = MAPPING_STATUS_DRAFT,
) -> ArctaSessionMapping:
    normalized_status = str(
        status
    ).strip().upper()

    if normalized_status not in MAPPING_STATUSES:
        raise ValueError(
            f"Statut de mapping invalide : {status!r}"
        )

    if normalized_status == MAPPING_STATUS_VALIDATED:
        mapping.validate()

    stored = ArctaSessionMapping(
        mapping=mapping,
        status=normalized_status,
        updated_at=_utc_now_iso(),
    )

    path = session_mapping_path(
        session
    )

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary = path.with_suffix(
        path.suffix + ".part"
    )

    temporary.write_text(
        json.dumps(
            stored.to_dict(),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    os.replace(
        temporary,
        path,
    )

    return stored


def load_session_mapping(
    session,
) -> Optional[ArctaSessionMapping]:
    path = session_mapping_path(
        session
    )

    if not path.exists():
        return None

    payload = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    if not isinstance(
        payload,
        dict,
    ):
        raise ValueError(
            "Le fichier de mapping de session est invalide."
        )

    mapping_payload = payload.get(
        "mapping"
    )

    if not isinstance(
        mapping_payload,
        dict,
    ):
        raise ValueError(
            "Le mapping de session est absent ou invalide."
        )

    mapping = arcta_column_mapping_from_dict(
        mapping_payload
    )

    return ArctaSessionMapping(
        mapping=mapping,
        status=payload.get(
            "status",
            MAPPING_STATUS_DRAFT,
        ),
        updated_at=str(
            payload.get(
                "updated_at",
                "",
            )
        ),
    )


def delete_session_mapping(
    session,
) -> bool:
    path = session_mapping_path(
        session
    )

    if not path.exists():
        return False

    path.unlink()

    return True