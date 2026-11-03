from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cta_core.config_model import (
    CanonicalCampaignConfig,
    UnsupportedConfigSourceError,
    canonical_campaign_config_from_dict,
    extract_canonical_campaign_config,
)
from web_common import is_config_source


SESSION_CANONICAL_CONFIG_FILENAME = "arcta_canonical_config.json"
SESSION_CANONICAL_CONFIG_SCHEMA_VERSION = "1.0"
SESSION_CANONICAL_CONFIG_STATUSES = frozenset({
    "EXTRACTED",
    "ERROR",
})
SESSION_CANONICAL_CONFIG_WORKFLOW_STATUSES = frozenset({
    "DRAFT",
    "VALIDATED",
})

CONFIG_PROFILE_UNSUPPORTED = "CONFIG_PROFILE_UNSUPPORTED"
CONFIG_EXTRACTION_FAILED = "CONFIG_EXTRACTION_FAILED"

_WINDOWS_RETRY_DELAYS = (0.02, 0.05, 0.1, 0.2, 0.4)


class CanonicalConfigStaleError(ValueError):
    """L'état canonique ne correspond plus à la source CONFIG courante."""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ArctaSessionCanonicalConfig:
    source_id: str
    source_original_name: str
    source_sha256: str
    status: str
    source_profile: str = ""
    config: CanonicalCampaignConfig | None = None
    warnings: tuple[str, ...] = ()
    error_code: str = ""
    error_message: str = ""
    workflow_status: str = "DRAFT"
    updated_at: str = ""
    selflock_history: tuple = ()
    schema_version: str = SESSION_CANONICAL_CONFIG_SCHEMA_VERSION

    def __post_init__(self) -> None:
        source_id = str(self.source_id).strip()
        source_name = str(self.source_original_name).strip()
        source_sha256 = str(self.source_sha256).strip().lower()
        status = str(self.status).strip().upper()
        source_profile = str(self.source_profile).strip()
        error_code = str(self.error_code).strip().upper()
        error_message = str(self.error_message).strip()
        workflow_status = str(self.workflow_status).strip().upper()
        schema_version = str(self.schema_version).strip()

        if not source_id or not source_name:
            raise ValueError("La source CONFIG canonique est incomplète.")

        if (
            len(source_sha256) != 64
            or any(character not in "0123456789abcdef" for character in source_sha256)
        ):
            raise ValueError("L'empreinte de la source CONFIG est invalide.")

        if isinstance(self.warnings, (str, bytes)):
            raise ValueError("Les avertissements CONFIG doivent former une liste.")

        if status not in SESSION_CANONICAL_CONFIG_STATUSES:
            raise ValueError(f"Statut CONFIG canonique inconnu : {status}")

        if schema_version != SESSION_CANONICAL_CONFIG_SCHEMA_VERSION:
            raise ValueError(
                "Version de persistance CONFIG canonique non supportée : "
                f"{schema_version or '(absente)'}"
            )

        if workflow_status not in SESSION_CANONICAL_CONFIG_WORKFLOW_STATUSES:
            raise ValueError(
                "Statut de workflow CONFIG canonique inconnu : "
                f"{workflow_status}"
            )

        if status == "EXTRACTED":
            if self.config is None or not source_profile:
                raise ValueError(
                    "Un état CONFIG EXTRACTED exige un contrat et un profil."
                )

            if self.config.source_profile != source_profile:
                raise ValueError(
                    "Le profil de l'état CONFIG diffère de celui du contrat."
                )

            if error_code or error_message:
                raise ValueError(
                    "Un état CONFIG EXTRACTED ne peut pas porter d'erreur."
                )
        else:
            if self.config is not None:
                raise ValueError(
                    "Un état CONFIG ERROR ne peut pas porter de contrat."
                )

            if not error_code or not error_message:
                raise ValueError(
                    "Un état CONFIG ERROR doit expliciter son erreur."
                )

            if workflow_status != "DRAFT":
                raise ValueError(
                    "Un état CONFIG ERROR ne peut pas être validé."
                )

        if workflow_status == "VALIDATED":
            validation = self.config.validation_summary()

            if not validation["calculation_ready"]:
                raise ValueError(
                    "La CONFIG canonique ne peut pas être validée : "
                    "les données obligatoires au calcul sont incomplètes."
                )

        object.__setattr__(self, "source_id", source_id)
        object.__setattr__(self, "source_original_name", source_name)
        object.__setattr__(self, "source_sha256", source_sha256)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "source_profile", source_profile)
        object.__setattr__(self, "warnings", tuple(map(str, self.warnings)))
        object.__setattr__(self, "error_code", error_code)
        object.__setattr__(self, "error_message", error_message)
        object.__setattr__(self, "workflow_status", workflow_status)
        object.__setattr__(self, "schema_version", schema_version)
        object.__setattr__(self, "updated_at", str(self.updated_at).strip())

        if not self.updated_at:
            object.__setattr__(self, "updated_at", _utc_now_iso())

    @property
    def extracted(self) -> bool:
        return self.status == "EXTRACTED"

    @property
    def validated(self) -> bool:
        return self.workflow_status == "VALIDATED"

    def summary_dict(self) -> dict[str, object]:
        validation = (
            self.config.validation_summary()
            if self.config is not None
            else None
        )
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "workflow_status": self.workflow_status,
            "updated_at": self.updated_at,
            "source_id": self.source_id,
            "source_original_name": self.source_original_name,
            "source_sha256": self.source_sha256,
            "source_profile": self.source_profile,
            "warnings": list(self.warnings),
            "error": (
                None
                if self.extracted
                else {
                    "code": self.error_code,
                    "message": self.error_message,
                }
            ),
            "validation": validation,
        }

    def to_dict(self) -> dict[str, object]:
        payload = self.summary_dict()
        payload["selflock_history"] = list(self.selflock_history)
        payload["canonical_config"] = (
            self.config.to_dict()
            if self.config is not None
            else None
        )
        return payload


def session_canonical_config_path(session) -> Path:
    return Path(session.storage_dir) / SESSION_CANONICAL_CONFIG_FILENAME


def _replace_with_retry(source: Path, destination: Path) -> None:
    for attempt in range(len(_WINDOWS_RETRY_DELAYS) + 1):
        try:
            os.replace(source, destination)
            return
        except PermissionError:
            if attempt >= len(_WINDOWS_RETRY_DELAYS):
                raise
            time.sleep(_WINDOWS_RETRY_DELAYS[attempt])


def _atomic_write(path: Path, payload: dict[str, object]) -> None:
    temporary = path.with_name(path.name + ".part")

    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        _replace_with_retry(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def save_session_canonical_config(
    session,
    state: ArctaSessionCanonicalConfig,
) -> ArctaSessionCanonicalConfig:
    if state.config is not None and state.config.campaign_id != session.session_id:
        raise ValueError(
            "Le campaign_id du contrat canonique diffère de la session."
        )

    _atomic_write(session_canonical_config_path(session), state.to_dict())
    return state


def _state_from_dict(payload: dict[str, Any]) -> ArctaSessionCanonicalConfig:
    raw_config = payload.get("canonical_config")
    config = None

    if raw_config is not None:
        if not isinstance(raw_config, dict):
            raise ValueError("canonical_config doit être un objet ou null.")
        config = canonical_campaign_config_from_dict(raw_config)

    raw_error = payload.get("error")
    error_code = ""
    error_message = ""

    if raw_error is not None:
        if not isinstance(raw_error, dict):
            raise ValueError("error doit être un objet ou null.")
        error_code = str(raw_error.get("code", ""))
        error_message = str(raw_error.get("message", ""))

    return ArctaSessionCanonicalConfig(
        selflock_history=tuple(payload.get("selflock_history", ())),
        source_id=payload.get("source_id", ""),
        source_original_name=payload.get("source_original_name", ""),
        source_sha256=payload.get("source_sha256", ""),
        status=payload.get("status", ""),
        source_profile=payload.get("source_profile", ""),
        config=config,
        warnings=tuple(payload.get("warnings", ())),
        error_code=error_code,
        error_message=error_message,
        workflow_status=payload.get("workflow_status", "DRAFT"),
        updated_at=str(payload.get("updated_at", "")),
        schema_version=payload.get("schema_version", ""),
    )


def _assert_current_source(session, state: ArctaSessionCanonicalConfig) -> None:
    source = session.sources.get(state.source_id)

    if source is None or not is_config_source(source):
        raise CanonicalConfigStaleError(
            "La source du contrat canonique n'est plus la source CONFIG."
        )

    if source.sha256.lower() != state.source_sha256:
        raise CanonicalConfigStaleError(
            "L'empreinte de la source CONFIG a changé."
        )

    if source.original_name != state.source_original_name:
        raise CanonicalConfigStaleError(
            "Le nom de la source CONFIG a changé."
        )

    if state.config is not None and state.config.campaign_id != session.session_id:
        raise CanonicalConfigStaleError(
            "Le contrat canonique appartient à une autre campagne."
        )


def load_session_canonical_config(
    session,
    *,
    require_current_source: bool = True,
) -> ArctaSessionCanonicalConfig | None:
    path = session_canonical_config_path(session)

    if not path.is_file():
        return None

    payload = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(payload, dict):
        raise ValueError("L'état CONFIG canonique doit être un objet JSON.")

    state = _state_from_dict(payload)

    if require_current_source:
        _assert_current_source(session, state)

    return state


def extract_and_save_session_canonical_config(
    session,
    source,
) -> ArctaSessionCanonicalConfig:
    if not is_config_source(source):
        raise ValueError("La source fournie n'est pas de rôle CONFIG.")

    try:
        if source.original_name == 'DABCTA_REANALYSE.csv':
            from .dabcta_arcta_bridge import extract_config
            return extract_config(session, source)
        result = extract_canonical_campaign_config(
            campaign_id=session.session_id,
            source_path=source.storage_path,
            source_name=source.original_name,
        )
        state = ArctaSessionCanonicalConfig(
            source_id=source.source_id,
            source_original_name=source.original_name,
            source_sha256=source.sha256,
            status="EXTRACTED",
            source_profile=result.source_profile,
            config=result.config,
            warnings=result.warnings,
        )
    except UnsupportedConfigSourceError as exc:
        state = ArctaSessionCanonicalConfig(
            source_id=source.source_id,
            source_original_name=source.original_name,
            source_sha256=source.sha256,
            status="ERROR",
            error_code=CONFIG_PROFILE_UNSUPPORTED,
            error_message=str(exc),
        )
    except Exception as exc:
        state = ArctaSessionCanonicalConfig(
            source_id=source.source_id,
            source_original_name=source.original_name,
            source_sha256=source.sha256,
            status="ERROR",
            error_code=CONFIG_EXTRACTION_FAILED,
            error_message=str(exc),
        )

    return save_session_canonical_config(session, state)


def ensure_session_canonical_config(session) -> ArctaSessionCanonicalConfig | None:
    try:
        current = load_session_canonical_config(session)
    except CanonicalConfigStaleError:
        current = None

    if current is not None:
        return current

    sources = [
        source
        for source in session.sources.values()
        if is_config_source(source)
    ]

    if not sources:
        return None

    if len(sources) > 1:
        raise ValueError(
            "Plusieurs sources CONFIG empêchent la reconstruction canonique."
        )

    return extract_and_save_session_canonical_config(session, sources[0])
