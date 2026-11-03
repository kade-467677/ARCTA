from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from cta_core.column_detection import (
    ColumnMappingSuggestion,
)
from cta_core.column_mapping import (
    ArctaColumnMapping,
    COLUMN_ROLE_DISPLAY_ORDER,
    column_role_label,
)


REQUIRED_MAPPING_ROLES = {
    "Xg",
    "Y",
}


@dataclass(frozen=True)
class MappingRoleRow:
    role: str
    label: str
    selected_column: Optional[str]
    required: bool

    @property
    def selected(self) -> bool:
        return bool(
            self.selected_column
        )

    def to_dict(self) -> dict:
        return {
            "role": self.role,
            "label": self.label,
            "selected_column": self.selected_column,
            "required": self.required,
            "selected": self.selected,
        }


@dataclass(frozen=True)
class MappingColumnRow:
    column_name: str
    suggested_role: Optional[str]
    suggested_label: Optional[str]
    status: str
    score: int
    margin: int

    def to_dict(self) -> dict:
        return {
            "column_name": self.column_name,
            "suggested_role": self.suggested_role,
            "suggested_label": self.suggested_label,
            "status": self.status,
            "score": self.score,
            "margin": self.margin,
        }


@dataclass(frozen=True)
class MappingPageModel:
    source_id: Optional[str]
    sheet_name: Optional[str]
    mode: str
    ready: bool
    validated: bool
    roles: tuple[MappingRoleRow, ...]
    columns: tuple[MappingColumnRow, ...]

    def to_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "sheet_name": self.sheet_name,
            "mode": self.mode,
            "ready": self.ready,
            "validated": self.validated,
            "roles": [
                row.to_dict()
                for row in self.roles
            ],
            "columns": [
                row.to_dict()
                for row in self.columns
            ],
        }


def build_mapping_role_rows(
    mapping: ArctaColumnMapping,
) -> tuple[MappingRoleRow, ...]:
    return tuple(
        MappingRoleRow(
            role=role,
            label=column_role_label(
                role
            ),
            selected_column=(
                mapping.roles.get(
                    role
                )
            ),
            required=(
                role
                in REQUIRED_MAPPING_ROLES
            ),
        )
        for role
        in COLUMN_ROLE_DISPLAY_ORDER
    )


def build_mapping_column_rows(
    columns: Iterable[str],
    suggestion: Optional[
        ColumnMappingSuggestion
    ] = None,
) -> tuple[MappingColumnRow, ...]:
    detection_by_column = {}

    if suggestion is not None:
        detection_by_column = {
            detection.column_name:
            detection
            for detection
            in suggestion.detections
        }

    rows = []

    for column in columns:
        column_name = str(
            column
        ).strip()

        if not column_name:
            continue

        detection = (
            detection_by_column.get(
                column_name
            )
        )

        if detection is None:
            rows.append(
                MappingColumnRow(
                    column_name=column_name,
                    suggested_role=None,
                    suggested_label=None,
                    status="UNASSIGNED",
                    score=0,
                    margin=0,
                )
            )
            continue

        rows.append(
            MappingColumnRow(
                column_name=column_name,
                suggested_role=(
                    detection.role
                ),
                suggested_label=(
                    detection.label
                ),
                status=(
                    detection.status
                ),
                score=(
                    detection.score
                ),
                margin=(
                    detection.margin
                ),
            )
        )

    return tuple(
        rows
    )


def build_mapping_page_model(
    columns: Iterable[str],
    mapping: ArctaColumnMapping,
    *,
    suggestion: Optional[
        ColumnMappingSuggestion
    ] = None,
    validated: bool = False,
) -> MappingPageModel:
    column_names = tuple(
        str(column).strip()
        for column in columns
        if str(column).strip()
    )

    try:
        mapping.validate(
            column_names
        )
        ready = True
    except ValueError:
        ready = False

    return MappingPageModel(
        source_id=mapping.source_id,
        sheet_name=mapping.sheet_name,
        mode=mapping.mode,
        ready=ready,
        validated=bool(
            validated
        ),
        roles=build_mapping_role_rows(
            mapping
        ),
        columns=build_mapping_column_rows(
            column_names,
            suggestion=suggestion,
        ),
    )