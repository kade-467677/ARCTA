from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping, Optional

from cta_core.models import ColumnSelection


ARCTA_COLUMN_MAPPING_SCHEMA_VERSION = "1.0"

COLUMN_ROLES = (
    "Xg",
    "Xh",
    "Xt",
    "Y",
    "A",
)

COLUMN_ROLE_DISPLAY_ORDER = (
    "Xg",
    "Xt",
    "Xh",
    "Y",
    "A",
)

COLUMN_ROLE_LABELS = {
    "Xg": "Couple Global",
    "Xt": "Couple Filet",
    "Xh": "Couple Sous-Tête",
    "Y": "Tension",
    "A": "Angle",
}


def column_role_label(role: str) -> str:
    role = str(role).strip()

    if role not in COLUMN_ROLE_LABELS:
        raise ValueError(
            f"Rôle de colonne ARCTA inconnu : {role!r}"
        )

    return COLUMN_ROLE_LABELS[role]


def column_role_options() -> list[dict[str, str]]:
    return [
        {
            "role": role,
            "label": COLUMN_ROLE_LABELS[role],
        }
        for role in COLUMN_ROLE_DISPLAY_ORDER
    ]


@dataclass
class ArctaColumnMapping:
    roles: dict[str, str] = field(default_factory=dict)
    source_id: Optional[str] = None
    sheet_name: Optional[str] = None
    schema_version: str = ARCTA_COLUMN_MAPPING_SCHEMA_VERSION

    def __post_init__(self) -> None:
        normalized: dict[str, str] = {}

        for role, column in dict(self.roles).items():
            role_name = str(role).strip()

            if role_name not in COLUMN_ROLES:
                raise ValueError(
                    f"Rôle de colonne ARCTA inconnu : {role_name!r}"
                )

            column_name = str(column).strip()

            if column_name:
                normalized[role_name] = column_name

        self.roles = normalized

        if self.source_id is not None:
            self.source_id = str(self.source_id).strip() or None

        if self.sheet_name is not None:
            self.sheet_name = str(self.sheet_name).strip() or None

    @property
    def has_angle(self) -> bool:
        return bool(
            self.roles.get("A")
        )

    @property
    def has_fine(self) -> bool:
        return all(
            self.roles.get(role)
            for role in ("Xg", "Xh", "Xt")
        )

    @property
    def mode(self) -> str:
        return (
            "fine"
            if self.has_fine
            else "global"
        )

    def to_column_selection(self) -> ColumnSelection:
        selection = ColumnSelection(
            dict(self.roles)
        )

        selection.validate()

        return selection

    def validate(
        self,
        available_columns: Optional[Iterable[str]] = None,
    ) -> None:
        self.to_column_selection()

        mapped_columns = list(
            self.roles.values()
        )

        if len(mapped_columns) != len(set(mapped_columns)):
            raise ValueError(
                "Une même colonne source ne peut pas être affectée "
                "à plusieurs rôles ARCTA."
            )

        if available_columns is None:
            return

        available = {
            str(column)
            for column in available_columns
        }

        missing = [
            column
            for column in mapped_columns
            if column not in available
        ]

        if missing:
            raise ValueError(
                "Colonnes mappées absentes de la source : "
                + ", ".join(missing)
            )

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "source_id": self.source_id,
            "sheet_name": self.sheet_name,
            "roles": dict(self.roles),
            "mode": self.mode,
            "has_angle": self.has_angle,
            "has_fine": self.has_fine,
        }


def arcta_column_mapping_from_dict(
    payload: Mapping,
) -> ArctaColumnMapping:
    if not isinstance(payload, Mapping):
        raise TypeError(
            "Le mapping des colonnes doit être un objet de type mapping."
        )

    schema_version = str(
        payload.get(
            "schema_version",
            ARCTA_COLUMN_MAPPING_SCHEMA_VERSION,
        )
    ).strip()

    if schema_version != ARCTA_COLUMN_MAPPING_SCHEMA_VERSION:
        raise ValueError(
            "Version de schéma de mapping non supportée : "
            f"{schema_version!r}"
        )

    roles = payload.get(
        "roles",
        {},
    )

    if not isinstance(roles, Mapping):
        raise TypeError(
            "Le champ 'roles' doit être un mapping."
        )

    return ArctaColumnMapping(
        roles=dict(roles),
        source_id=payload.get("source_id"),
        sheet_name=payload.get("sheet_name"),
        schema_version=schema_version,
    )