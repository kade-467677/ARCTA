from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from cta_core.column_mapping import (
    ArctaColumnMapping,
    COLUMN_ROLE_DISPLAY_ORDER,
)


@dataclass(frozen=True)
class CampaignSourceSchema:
    source_id: str
    source_name: str
    columns: tuple[str, ...]
    sheet_name: Optional[str] = None
    header_row_1based: Optional[int] = None
    units_row_1based: Optional[int] = None

    def __post_init__(self) -> None:
        source_id = str(
            self.source_id
        ).strip()

        source_name = str(
            self.source_name
        ).strip()

        if not source_id:
            raise ValueError(
                "source_id est obligatoire."
            )

        if not source_name:
            raise ValueError(
                "source_name est obligatoire."
            )

        columns = tuple(
            str(column).strip()
            for column in self.columns
            if str(column).strip()
        )

        if not columns:
            raise ValueError(
                "La source doit contenir "
                "au moins une colonne."
            )

        if (
            len(set(columns))
            != len(columns)
        ):
            raise ValueError(
                "Les noms de colonnes "
                "de la source doivent "
                "être uniques."
            )

        object.__setattr__(
            self,
            "source_id",
            source_id,
        )

        object.__setattr__(
            self,
            "source_name",
            source_name,
        )

        object.__setattr__(
            self,
            "columns",
            columns,
        )

        if self.sheet_name is not None:
            sheet_name = str(
                self.sheet_name
            ).strip()

            object.__setattr__(
                self,
                "sheet_name",
                (
                    sheet_name
                    or None
                ),
            )

    def to_dict(self) -> dict:
        return {
            "source_id":
                self.source_id,
            "source_name":
                self.source_name,
            "sheet_name":
                self.sheet_name,
            "columns":
                list(self.columns),
            "header_row_1based":
                self.header_row_1based,
            "units_row_1based":
                self.units_row_1based,
        }


@dataclass(frozen=True)
class CampaignSourceCompatibility:
    source_id: str
    source_name: str
    sheet_name: Optional[str]
    compatible: bool
    missing_columns: tuple[str, ...]
    extra_columns: tuple[str, ...]
    header_row_1based: Optional[int]
    units_row_1based: Optional[int]

    def to_dict(self) -> dict:
        return {
            "source_id":
                self.source_id,
            "source_name":
                self.source_name,
            "sheet_name":
                self.sheet_name,
            "compatible":
                self.compatible,
            "missing_columns":
                list(
                    self.missing_columns
                ),
            "extra_columns":
                list(
                    self.extra_columns
                ),
            "header_row_1based":
                self.header_row_1based,
            "units_row_1based":
                self.units_row_1based,
        }


@dataclass(frozen=True)
class CampaignMappingCompatibilityReport:
    reference_source_id: Optional[str]
    reference_sheet_name: Optional[str]
    mapped_columns: tuple[str, ...]
    sources: tuple[
        CampaignSourceCompatibility,
        ...
    ]

    @property
    def total_sources(self) -> int:
        return len(
            self.sources
        )

    @property
    def compatible_count(self) -> int:
        return sum(
            source.compatible
            for source in self.sources
        )

    @property
    def incompatible_count(self) -> int:
        return (
            self.total_sources
            - self.compatible_count
        )

    @property
    def all_compatible(self) -> bool:
        return (
            self.total_sources > 0
            and self.incompatible_count == 0
        )

    @property
    def compatible_source_ids(
        self,
    ) -> tuple[str, ...]:
        return tuple(
            source.source_id
            for source in self.sources
            if source.compatible
        )

    @property
    def incompatible_source_ids(
        self,
    ) -> tuple[str, ...]:
        return tuple(
            source.source_id
            for source in self.sources
            if not source.compatible
        )

    def to_dict(self) -> dict:
        return {
            "reference_source_id":
                self.reference_source_id,
            "reference_sheet_name":
                self.reference_sheet_name,
            "mapped_columns":
                list(
                    self.mapped_columns
                ),
            "total_sources":
                self.total_sources,
            "compatible_count":
                self.compatible_count,
            "incompatible_count":
                self.incompatible_count,
            "all_compatible":
                self.all_compatible,
            "compatible_source_ids":
                list(
                    self.compatible_source_ids
                ),
            "incompatible_source_ids":
                list(
                    self.incompatible_source_ids
                ),
            "sources": [
                source.to_dict()
                for source in self.sources
            ],
        }


def mapped_columns_from_mapping(
    mapping: ArctaColumnMapping,
) -> tuple[str, ...]:
    """
    Retourne uniquement les colonnes
    réellement utilisées par le mapping.

    Les colonnes supplémentaires présentes
    dans les fichiers de la campagne ne
    participent pas au contrôle de
    compatibilité.
    """
    columns = []

    for role in (
        COLUMN_ROLE_DISPLAY_ORDER
    ):
        column = mapping.roles.get(
            role
        )

        if not column:
            continue

        column_name = str(
            column
        ).strip()

        if column_name:
            columns.append(
                column_name
            )

    if not columns:
        raise ValueError(
            "Le mapping ne contient "
            "aucune colonne affectée."
        )

    if (
        len(set(columns))
        != len(columns)
    ):
        raise ValueError(
            "Une même colonne ne peut "
            "pas être utilisée pour "
            "plusieurs rôles."
        )

    return tuple(
        columns
    )


def assess_source_compatibility(
    mapping: ArctaColumnMapping,
    source: CampaignSourceSchema,
) -> CampaignSourceCompatibility:
    mapped_columns = (
        mapped_columns_from_mapping(
            mapping
        )
    )

    available = set(
        source.columns
    )

    mapped = set(
        mapped_columns
    )

    missing = tuple(
        column
        for column in mapped_columns
        if column not in available
    )

    extra = tuple(
        column
        for column in source.columns
        if column not in mapped
    )

    return CampaignSourceCompatibility(
        source_id=
            source.source_id,
        source_name=
            source.source_name,
        sheet_name=
            source.sheet_name,
        compatible=
            not missing,
        missing_columns=
            missing,
        extra_columns=
            extra,
        header_row_1based=
            source.header_row_1based,
        units_row_1based=
            source.units_row_1based,
    )


def assess_campaign_mapping_compatibility(
    mapping: ArctaColumnMapping,
    sources: Iterable[
        CampaignSourceSchema
    ],
) -> CampaignMappingCompatibilityReport:
    """
    Contrôle structurel d'une campagne ARCTA.

    Hypothèse métier :
        le mapping a déjà été défini et
        validé sur un fichier représentatif.

    Une source est compatible lorsque
    toutes les colonnes réellement utilisées
    par ce mapping sont présentes.

    Les colonnes supplémentaires sont
    explicitement autorisées.
    """
    source_list = tuple(
        sources
    )

    if not source_list:
        raise ValueError(
            "La campagne doit contenir "
            "au moins une source."
        )

    mapped_columns = (
        mapped_columns_from_mapping(
            mapping
        )
    )

    results = tuple(
        assess_source_compatibility(
            mapping,
            source,
        )
        for source
        in source_list
    )

    return (
        CampaignMappingCompatibilityReport(
            reference_source_id=
                mapping.source_id,
            reference_sheet_name=
                mapping.sheet_name,
            mapped_columns=
                mapped_columns,
            sources=
                results,
        )
    )