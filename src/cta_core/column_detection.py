from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Optional

from cta_core.column_mapping import (
    ArctaColumnMapping,
    column_role_label,
)
from cta_core.parsing import norm_text


DEFAULT_COLUMN_ROLE_MIN_SCORE = 6

ROLE_PATTERNS = {
    "Y": [
        (r"\btension\b", 10),
        (r"\bforce\b", 9),
        (r"\beffort\b", 8),
        (r"\bcharge\b", 7),
        (r"\btraction\b", 6),
        (r"\baxial\b", 5),
        (r"\bload\b", 5),
        (r"\bn\b", 1),
        (r"\bch\s*1\b", 8),
        (r"\bch1\b", 8),
    ],
    "Xg": [
        (r"\bxg\b", 12),
        (r"\bcouple\s+global\b", 12),
        (r"\bcouple\s+total\b", 12),
        (r"\btorque\s+global\b", 12),
        (r"\btorque\s+total\b", 12),
        (r"\bglobal\b", 7),
        (r"\btotal\b", 7),
        (r"\bcouple\b", 3),
        (r"\btorque\b", 3),
        (r"\bmoment\b", 3),
        (r"\bnm\b", 1),
        (r"\bch\s*2\b", 8),
        (r"\bch2\b", 8),
    ],
    "Xh": [
        (r"\bxh\b", 12),
        (r"\bsous\s+tete\b", 12),
        (r"\bcouple\s+sous\s+tete\b", 13),
        (r"\bcst\b", 11),
        (r"\bhead\b", 8),
        (r"\btete\b", 7),
        (r"\bunder\s+head\b", 10),
        (r"\bnm\b", 1),
        (r"\bch\s*4\b", 8),
        (r"\bch4\b", 8),
    ],
    "Xt": [
        (r"\bxt\b", 12),
        (r"\bfilet\b", 10),
        (r"\bfilets\b", 10),
        (r"\bcouple\s+filets?\b", 13),
        (r"\bcf\b", 11),
        (r"\bthread\b", 9),
        (r"\bthreads\b", 9),
        (r"\bvis\b", 4),
        (r"\bnm\b", 1),
        (r"\bch\s*3\b", 8),
        (r"\bch3\b", 8),
    ],
    "A": [
        (r"\bangle\b", 12),
        (r"\brotation\b", 8),
        (r"\bdegre\b", 8),
        (r"\bdeg\b", 8),
        (r"\btour\b", 4),
        (r"\bturn\b", 4),
        (r"\bch\s*5\b", 8),
        (r"\bch5\b", 8),
    ],
}


@dataclass(frozen=True)
class ColumnRoleDetection:
    column_name: str
    role: Optional[str]
    score: int
    margin: int
    status: str
    scores: dict[str, int]

    @property
    def label(self) -> Optional[str]:
        if self.role is None:
            return None
        return column_role_label(self.role)

    def to_dict(self) -> dict:
        return {
            "column_name": self.column_name,
            "role": self.role,
            "label": self.label,
            "score": self.score,
            "margin": self.margin,
            "status": self.status,
            "scores": dict(self.scores),
        }


@dataclass(frozen=True)
class ColumnMappingSuggestion:
    mapping: ArctaColumnMapping
    detections: tuple[ColumnRoleDetection, ...]
    ready: bool

    def to_dict(self) -> dict:
        return {
            "mapping": self.mapping.to_dict(),
            "detections": [
                detection.to_dict()
                for detection in self.detections
            ],
            "ready": self.ready,
        }


def score_header(
    header: str,
    patterns: list[tuple[str, int]],
) -> int:
    normalized = norm_text(header)

    return sum(
        weight
        for regex, weight in patterns
        if re.search(regex, normalized)
    )


def score_header_all_roles(
    column_name: str,
) -> dict[str, int]:
    return {
        role: score_header(
            column_name,
            patterns,
        )
        for role, patterns in ROLE_PATTERNS.items()
    }


def detect_column_role(
    column_name: str,
    min_score: int = DEFAULT_COLUMN_ROLE_MIN_SCORE,
) -> ColumnRoleDetection:
    name = str(column_name).strip()
    scores = score_header_all_roles(name)

    ranked = sorted(
        scores.items(),
        key=lambda item: item[1],
        reverse=True,
    )

    best_score = ranked[0][1]
    second_score = ranked[1][1]

    best_roles = [
        role
        for role, score in ranked
        if score == best_score
    ]

    if best_score < min_score:
        return ColumnRoleDetection(
            column_name=name,
            role=None,
            score=best_score,
            margin=best_score - second_score,
            status="UNRECOGNIZED",
            scores=scores,
        )

    if len(best_roles) > 1:
        return ColumnRoleDetection(
            column_name=name,
            role=None,
            score=best_score,
            margin=0,
            status="AMBIGUOUS",
            scores=scores,
        )

    return ColumnRoleDetection(
        column_name=name,
        role=best_roles[0],
        score=best_score,
        margin=best_score - second_score,
        status="SUGGESTED",
        scores=scores,
    )


def suggest_column_mapping(
    columns: Iterable[str],
    source_id: Optional[str] = None,
    sheet_name: Optional[str] = None,
    min_score: int = DEFAULT_COLUMN_ROLE_MIN_SCORE,
) -> ColumnMappingSuggestion:
    column_names = [
        str(column).strip()
        for column in columns
        if str(column).strip()
    ]

    initial = [
        detect_column_role(
            column,
            min_score=min_score,
        )
        for column in column_names
    ]

    by_role: dict[str, list[tuple[int, ColumnRoleDetection]]] = {}

    for index, detection in enumerate(initial):
        if (
            detection.status == "SUGGESTED"
            and detection.role is not None
        ):
            by_role.setdefault(
                detection.role,
                [],
            ).append(
                (index, detection)
            )

    accepted_indices: set[int] = set()
    conflict_indices: set[int] = set()

    for candidates in by_role.values():
        if len(candidates) == 1:
            accepted_indices.add(
                candidates[0][0]
            )
            continue

        ordered = sorted(
            candidates,
            key=lambda item: (
                item[1].score,
                item[1].margin,
            ),
            reverse=True,
        )

        best_index, best = ordered[0]
        second = ordered[1][1]

        if (
            best.score == second.score
            and best.margin == second.margin
        ):
            conflict_indices.update(
                index
                for index, _ in ordered
            )
            continue

        accepted_indices.add(
            best_index
        )

        conflict_indices.update(
            index
            for index, _ in ordered[1:]
        )

    detections: list[ColumnRoleDetection] = []
    roles: dict[str, str] = {}

    for index, detection in enumerate(initial):
        if index in conflict_indices:
            detections.append(
                ColumnRoleDetection(
                    column_name=detection.column_name,
                    role=detection.role,
                    score=detection.score,
                    margin=detection.margin,
                    status="ROLE_CONFLICT",
                    scores=detection.scores,
                )
            )
            continue

        detections.append(
            detection
        )

        if (
            index in accepted_indices
            and detection.role is not None
        ):
            roles[detection.role] = (
                detection.column_name
            )

    mapping = ArctaColumnMapping(
        roles=roles,
        source_id=source_id,
        sheet_name=sheet_name,
    )

    try:
        mapping.validate(
            column_names
        )
        ready = True
    except ValueError:
        ready = False

    return ColumnMappingSuggestion(
        mapping=mapping,
        detections=tuple(detections),
        ready=ready,
    )