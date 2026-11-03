from __future__ import annotations

from pathlib import Path

from cta_core.campaign_mapping import (
    CampaignSourceSchema,
    assess_source_compatibility,
    mapped_columns_from_mapping,
)
from cta_core.column_mapping import (
    ArctaColumnMapping,
)

from apps.arcta_web.source_preview import (
    read_source_preview,
)
from web_common.sessions import is_trial_source


def _session_sources(
    session,
) -> tuple:
    raw_sources = getattr(
        session,
        "sources",
        {},
    )

    if isinstance(
        raw_sources,
        dict,
    ):
        return tuple(
            source
            for source in raw_sources.values()
            if is_trial_source(source)
        )

    return tuple(
        source
        for source in raw_sources
        if is_trial_source(source)
    )


def _source_name(
    source,
) -> str:
    return str(
        getattr(
            source,
            "original_name",
            getattr(
                source,
                "source_id",
                "",
            ),
        )
    ).strip()


def _source_path(
    source,
) -> Path:
    path = getattr(
        source,
        "storage_path",
        None,
    )

    if path is None:
        raise ValueError(
            "La source ne possède pas "
            "de chemin de stockage."
        )

    return Path(path)


def _sheet_for_source(
    source,
    mapping: ArctaColumnMapping,
) -> str | None:
    extension = (
        _source_path(
            source
        )
        .suffix
        .lower()
    )

    if extension == ".xlsx":
        return mapping.sheet_name

    return None


def inspect_session_mapping_compatibility(
    session,
    mapping: ArctaColumnMapping,
) -> dict[str, object]:
    """
    Contrôle le mapping unique de campagne
    sur toutes les sources réellement
    chargées dans la WebSession.

    Le source_id / sheet_name du mapping
    représentent la provenance du fichier
    utilisé comme référence.

    Ils ne limitent pas le mapping à cette
    seule source.
    """
    sources = _session_sources(
        session
    )

    if not sources:
        raise ValueError(
            "La campagne ne contient "
            "aucune source."
        )

    if not mapping.source_id:
        raise ValueError(
            "Le mapping doit conserver "
            "la source de référence."
        )

    source_ids = {
        str(
            getattr(
                source,
                "source_id",
                "",
            )
        )
        for source
        in sources
    }

    if (
        mapping.source_id
        not in source_ids
    ):
        raise ValueError(
            "La source de référence "
            "du mapping n'appartient "
            "pas à la campagne."
        )

    mapped_columns = (
        mapped_columns_from_mapping(
            mapping
        )
    )

    reference_name = None
    results = []

    for source in sources:
        source_id = str(
            getattr(
                source,
                "source_id",
                "",
            )
        ).strip()

        source_name = (
            _source_name(
                source
            )
        )

        if (
            source_id
            == mapping.source_id
        ):
            reference_name = (
                source_name
            )

        sheet_name = (
            _sheet_for_source(
                source,
                mapping,
            )
        )

        try:
            preview = (
                read_source_preview(
                    _source_path(
                        source
                    ),
                    sheet_name=
                        sheet_name,
                    max_rows=20,
                )
            )

            schema = (
                CampaignSourceSchema(
                    source_id=
                        source_id,
                    source_name=
                        source_name,
                    sheet_name=
                        preview.get(
                            "selected_sheet"
                        ),
                    columns=tuple(
                        preview.get(
                            "columns",
                            [],
                        )
                    ),
                    header_row_1based=
                        preview.get(
                            "header_row_1based"
                        ),
                    units_row_1based=
                        preview.get(
                            "units_row_1based"
                        ),
                )
            )

            compatibility = (
                assess_source_compatibility(
                    mapping,
                    schema,
                )
            )

            row = (
                compatibility
                .to_dict()
            )

            row[
                "read_error"
            ] = None

        except Exception as exc:
            row = {
                "source_id":
                    source_id,
                "source_name":
                    source_name,
                "sheet_name":
                    sheet_name,
                "compatible":
                    False,
                "missing_columns":
                    list(
                        mapped_columns
                    ),
                "extra_columns":
                    [],
                "header_row_1based":
                    None,
                "units_row_1based":
                    None,
                "read_error":
                    str(exc),
            }

        results.append(
            row
        )

    compatible_count = sum(
        bool(
            result[
                "compatible"
            ]
        )
        for result in results
    )

    total_sources = len(
        results
    )

    incompatible_count = (
        total_sources
        - compatible_count
    )

    return {
        "reference_source_id":
            mapping.source_id,
        "reference_source_name":
            reference_name,
        "reference_sheet_name":
            mapping.sheet_name,
        "mapped_columns":
            list(
                mapped_columns
            ),
        "total_sources":
            total_sources,
        "compatible_count":
            compatible_count,
        "incompatible_count":
            incompatible_count,
        "all_compatible":
            (
                total_sources > 0
                and
                incompatible_count == 0
            ),
        "sources":
            results,
    }
