from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cta_core.config_model import (
    ArctaInputConfig,
    arcta_input_config_from_dict,
)


SESSION_CONFIG_FILENAME = "arcta_config.json"

SESSION_CONFIG_STATUSES = frozenset({
    "DRAFT",
    "VALIDATED",
})


def _utc_now_iso() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


@dataclass(frozen=True)
class ArctaSessionConfig:
    config: ArctaInputConfig
    status: str = "DRAFT"
    updated_at: str = ""
    template_source_id: str | None = None

    def __post_init__(self) -> None:
        normalized_status = str(
            self.status
        ).strip().upper()

        if normalized_status not in SESSION_CONFIG_STATUSES:
            raise ValueError(
                "Statut de CONFIG session inconnu : "
                f"{normalized_status}"
            )

        object.__setattr__(
            self,
            "status",
            normalized_status,
        )

        if not self.updated_at:
            object.__setattr__(
                self,
                "updated_at",
                _utc_now_iso(),
            )

    @property
    def validated(self) -> bool:
        return self.status == "VALIDATED"

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "updated_at": self.updated_at,
            "template_source_id":
                self.template_source_id,
            "config":
                self.config.to_dict(),
        }


def session_config_path(
    session,
) -> Path:
    return (
        Path(session.storage_dir)
        / SESSION_CONFIG_FILENAME
    )


def save_session_config(
    session,
    config: ArctaInputConfig,
    *,
    status: str = "DRAFT",
    template_source_id: str | None = None,
) -> ArctaSessionConfig:
    state = ArctaSessionConfig(
        config=config,
        status=status,
        updated_at=_utc_now_iso(),
        template_source_id=template_source_id,
    )

    path = session_config_path(
        session
    )

    temporary = path.with_name(
        path.name + ".part"
    )

    payload = state.to_dict()

    try:
        temporary.write_text(
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )

        os.replace(
            temporary,
            path,
        )

    except Exception:
        try:
            temporary.unlink(
                missing_ok=True
            )
        except Exception:
            pass

        raise

    return state


def load_session_config(
    session,
) -> ArctaSessionConfig | None:
    path = session_config_path(
        session
    )

    if not path.is_file():
        return None

    payload: dict[str, Any] = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    raw_config = payload.get(
        "config"
    )

    if not isinstance(
        raw_config,
        dict,
    ):
        raise ValueError(
            "CONFIG session invalide : "
            "'config' absent ou invalide."
        )

    config = (
        arcta_input_config_from_dict(
            raw_config
        )
    )

    return ArctaSessionConfig(
        config=config,
        status=payload.get(
            "status",
            "DRAFT",
        ),
        updated_at=str(
            payload.get(
                "updated_at",
                "",
            )
        ),
        template_source_id=(
            payload.get(
                "template_source_id"
            )
        ),
    )