from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from cta_core.parsing import (
    _as_float_fr,
    _cell_to_indices,
    norm_text,
)

from .model import (
    ArctaConfigField,
    ArctaInputConfig,
    build_arcta_input_config,
)


DEFAULT_TEMPLATESYNTH_IMPORT_SPEC = {
    "sheet_name": None,
    "cell_map": {
        "thread_size": None,
        "p_mm": None,
        "d2_mm": None,
        "dm_vis_mm": None,
        "dm_ecrou_mm": None,
        "d_int_vis_mm": None,
        "d_ext_vis_mm": None,
        "d_int_ecrou_mm": None,
        "d_ext_ecrou_mm": None,
        "tightening_application": None,
    },
    "label_map": {
        "thread_size": {
            "label": "Taille et pas (mm)",
            "label_col": 1,
            "value_col": 2,
        },
        "d2_mm": {
            "label":
                "Diamètre au flanc des filets (mm)",
            "label_col": 4,
            "value_col": 7,
        },
        "d_int_vis_mm": {
            "label": "Diamètre intérieur (mm)",
            "label_col": 1,
            "value_col": 2,
        },
        "d_ext_vis_mm": {
            "label": "Diamètre extérieur (mm)",
            "label_col": 1,
            "value_col": 2,
        },
        "d_int_ecrou_mm": {
            "label": "Diamètre intérieur (mm)",
            "label_col": 1,
            "value_col": 4,
        },
        "d_ext_ecrou_mm": {
            "label": "Diamètre extérieur (mm)",
            "label_col": 1,
            "value_col": 4,
        },
        "tightening_application": {
            "label": "Application du serrage",
            "label_col": 1,
            "value_col": 2,
            "fallback_value_col": 4,
        },
    },
}


@dataclass(frozen=True)
class TemplateSynthImportResult:
    config: ArctaInputConfig
    template_present: bool
    template_path: str = ""
    template_sheet: str = ""
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "template_present":
                self.template_present,
            "template_path":
                self.template_path,
            "template_sheet":
                self.template_sheet,
            "warnings":
                list(self.warnings),
            "config":
                self.config.to_dict(),
        }


def build_default_campaign_config(
    campaign_id: str,
) -> ArctaInputConfig:
    """
    Crée la CONFIG de base d'une campagne.

    Elle existe même lorsqu'aucun TemplateSynth
    n'est fourni.
    """
    fields = [
        ArctaConfigField(
            key="thread_size",
            label="Taille / désignation du filetage",
            category="assemblage",
            value_type="text",
            status="MISSING",
        ),
        ArctaConfigField(
            key="p_mm",
            label="Pas",
            category="geometrie_filetage",
            unit="mm",
            value_type="float",
            required=True,
            status="MISSING",
        ),
        ArctaConfigField(
            key="d2_mm",
            label="Diamètre au flanc des filets",
            category="geometrie_filetage",
            unit="mm",
            value_type="float",
            required=True,
            status="MISSING",
        ),
        ArctaConfigField(
            key="d_int_vis_mm",
            label="Diamètre intérieur sous tête vis",
            category="portee_vis",
            unit="mm",
            value_type="float",
            status="MISSING",
        ),
        ArctaConfigField(
            key="d_ext_vis_mm",
            label="Diamètre extérieur sous tête vis",
            category="portee_vis",
            unit="mm",
            value_type="float",
            status="MISSING",
        ),
        ArctaConfigField(
            key="dm_vis_mm",
            label="Diamètre moyen sous tête vis",
            category="portee_vis",
            unit="mm",
            value_type="float",
            status="MISSING",
        ),
        ArctaConfigField(
            key="d_int_ecrou_mm",
            label="Diamètre intérieur sous écrou",
            category="portee_ecrou",
            unit="mm",
            value_type="float",
            status="MISSING",
        ),
        ArctaConfigField(
            key="d_ext_ecrou_mm",
            label="Diamètre extérieur sous écrou",
            category="portee_ecrou",
            unit="mm",
            value_type="float",
            status="MISSING",
        ),
        ArctaConfigField(
            key="dm_ecrou_mm",
            label="Diamètre moyen sous écrou",
            category="portee_ecrou",
            unit="mm",
            value_type="float",
            status="MISSING",
        ),
        ArctaConfigField(
            key="tightening_application",
            label="Application du serrage",
            category="serrage",
            value_type="text",
            status="MISSING",
        ),
        ArctaConfigField(
            key="type_serrage",
            label="Type de serrage",
            category="serrage",
            value_type="text",
            status="MISSING",
        ),
        ArctaConfigField(
            key="Db_mm",
            label="Diamètre moyen de portée actif",
            category="serrage",
            unit="mm",
            value_type="float",
            required=True,
            status="MISSING",
        ),
    ]

    return build_arcta_input_config(
        campaign_id=campaign_id,
        fields=fields,
    )


def find_templatesynth_candidate(
    paths: Sequence[str | Path],
) -> Path | None:
    """
    Détection automatique volontairement conservative.

    Un fichier équivalent non reconnu automatiquement
    pourra être désigné explicitement par l'utilisateur
    dans l'interface Web.
    """
    candidates: list[Path] = []

    for raw_path in paths:
        path = Path(raw_path)

        if (
            not path.is_file()
            or path.suffix.lower() != ".xlsx"
            or path.name.startswith("~$")
        ):
            continue

        normalized = re.sub(
            r"[^a-z0-9]+",
            "",
            path.stem.lower(),
        )

        if "templatesynth" in normalized:
            candidates.append(path)

    if not candidates:
        return None

    unique = list(
        dict.fromkeys(
            path.resolve()
            for path in candidates
        )
    )

    if len(unique) > 1:
        raise ValueError(
            "Plusieurs TemplateSynth candidats : "
            + ", ".join(
                str(path)
                for path in unique
            )
        )

    return unique[0]


def _clean_excel_value(
    value: Any,
) -> Any:
    if value is None:
        return None

    try:
        if pd.isna(value):
            return None
    except Exception:
        pass

    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass

    return value


def _read_template_cell(
    dataframe: pd.DataFrame,
    cell_ref: str | None,
) -> Any:
    if not cell_ref:
        return None

    row, column = _cell_to_indices(
        cell_ref
    )

    if (
        row < 0
        or column < 0
        or row >= dataframe.shape[0]
        or column >= dataframe.shape[1]
    ):
        raise ValueError(
            f"Cellule {cell_ref} hors TemplateSynth."
        )

    return _clean_excel_value(
        dataframe.iat[
            row,
            column,
        ]
    )


def _get_value_by_label(
    dataframe: pd.DataFrame,
    label: str,
    label_col: int,
    value_col: int,
) -> Any:
    if dataframe.shape[1] <= max(
        label_col,
        value_col,
    ):
        return None

    target = norm_text(
        label
    )

    labels = (
        dataframe
        .iloc[:, label_col]
        .astype(str)
        .map(norm_text)
    )

    mask = labels == target

    if not mask.any():
        return None

    row_index = mask[
        mask
    ].index[0]

    return _clean_excel_value(
        dataframe.loc[
            row_index
        ].iloc[
            value_col
        ]
    )


def _extract_tpi(
    thread_size: Any,
) -> int | None:
    if thread_size is None:
        return None

    text = str(
        thread_size
    ).replace(
        ",",
        ".",
    )

    match = re.search(
        r"-\s*(\d+)",
        text,
    )

    if match:
        return int(
            match.group(1)
        )

    return None


def _finite_or_none(
    value: Any,
) -> float | None:
    number = _as_float_fr(
        value
    )

    try:
        number = float(
            number
        )
    except Exception:
        return None

    if not math.isfinite(
        number
    ):
        return None

    return number


def _set_imported_value(
    config: ArctaInputConfig,
    key: str,
    value: Any,
    *,
    source: str,
    source_ref: str,
) -> None:
    field = config.get_field(
        key
    )

    if field is None:
        return

    value = _clean_excel_value(
        value
    )

    if value is None:
        return

    field.value = value
    field.original_value = value
    field.source = source
    field.source_ref = source_ref
    field.original_source = source
    field.original_source_ref = source_ref
    field.status = "TO_CONFIRM"


def import_templatesynth_to_config(
    *,
    campaign_id: str,
    template_path: str | Path | None,
    spec: dict[str, Any] | None = None,
) -> TemplateSynthImportResult:
    """
    Importe le TemplateSynth dans la CONFIG canonique.

    L'absence de TemplateSynth produit une CONFIG initiale
    exploitable par la future saisie manuelle Web.
    """
    config = build_default_campaign_config(
        campaign_id
    )

    if template_path is None:
        return TemplateSynthImportResult(
            config=config,
            template_present=False,
            warnings=(
                "TEMPLATE_SYNTH_NOT_PROVIDED",
            ),
        )

    path = Path(
        template_path
    )

    if not path.is_file():
        raise FileNotFoundError(
            path
        )

    if path.suffix.lower() != ".xlsx":
        raise ValueError(
            "Le TemplateSynth doit être un fichier XLSX."
        )

    import_spec = (
        DEFAULT_TEMPLATESYNTH_IMPORT_SPEC
        if spec is None
        else spec
    )

    excel_file = pd.ExcelFile(
        path,
        engine="openpyxl",
    )

    try:
        configured_sheet = (
            import_spec.get(
                "sheet_name"
            )
        )

        sheet_name = (
            configured_sheet
            or excel_file.sheet_names[0]
        )

        if sheet_name not in excel_file.sheet_names:
            raise ValueError(
                "Feuille TemplateSynth inconnue : "
                f"{sheet_name}"
            )

        dataframe = pd.read_excel(
            excel_file,
            sheet_name=sheet_name,
            header=None,
        )

    finally:
        excel_file.close()

    cell_map = (
        import_spec.get(
            "cell_map",
            {},
        )
        or {}
    )

    label_map = (
        import_spec.get(
            "label_map",
            {},
        )
        or {}
    )

    def read_key(
        key: str,
    ) -> tuple[Any, str]:
        cell_ref = cell_map.get(
            key
        )

        value = _read_template_cell(
            dataframe,
            cell_ref,
        )

        if value is not None:
            return (
                value,
                f"{sheet_name}!{cell_ref}",
            )

        label_spec = label_map.get(
            key
        )

        if not label_spec:
            return None, ""

        label = str(
            label_spec[
                "label"
            ]
        )

        label_col = int(
            label_spec[
                "label_col"
            ]
        )

        value_col = int(
            label_spec[
                "value_col"
            ]
        )

        value = _get_value_by_label(
            dataframe,
            label,
            label_col,
            value_col,
        )

        used_column = value_col

        if (
            value is None
            and "fallback_value_col"
            in label_spec
        ):
            used_column = int(
                label_spec[
                    "fallback_value_col"
                ]
            )

            value = _get_value_by_label(
                dataframe,
                label,
                label_col,
                used_column,
            )

        if value is None:
            return None, ""

        return (
            value,
            (
                f"{sheet_name}:"
                f"label={label!r};"
                f"value_col={used_column}"
            ),
        )

    direct_keys = (
        "thread_size",
        "p_mm",
        "d2_mm",
        "dm_vis_mm",
        "dm_ecrou_mm",
        "d_int_vis_mm",
        "d_ext_vis_mm",
        "d_int_ecrou_mm",
        "d_ext_ecrou_mm",
        "tightening_application",
    )

    values: dict[str, Any] = {}
    refs: dict[str, str] = {}

    for key in direct_keys:
        value, reference = read_key(
            key
        )

        values[key] = value
        refs[key] = reference

        if value is not None:
            normalized_value = value

            if key.endswith(
                "_mm"
            ):
                normalized_value = (
                    _finite_or_none(
                        value
                    )
                )

            if normalized_value is not None:
                _set_imported_value(
                    config,
                    key,
                    normalized_value,
                    source="TEMPLATE_SYNTH",
                    source_ref=reference,
                )

    p_mm = _finite_or_none(
        values.get(
            "p_mm"
        )
    )

    thread_size = values.get(
        "thread_size"
    )

    if p_mm is None:
        tpi = _extract_tpi(
            thread_size
        )

        if tpi:
            p_mm = (
                25.4
                / float(tpi)
            )

            _set_imported_value(
                config,
                "p_mm",
                p_mm,
                source="DERIVED",
                source_ref=(
                    "derived:"
                    "thread_size→TPI→p_mm"
                ),
            )

    dm_vis = _finite_or_none(
        values.get(
            "dm_vis_mm"
        )
    )

    if dm_vis is None:
        d_int_vis = _finite_or_none(
            values.get(
                "d_int_vis_mm"
            )
        )

        d_ext_vis = _finite_or_none(
            values.get(
                "d_ext_vis_mm"
            )
        )

        if (
            d_int_vis is not None
            and d_ext_vis is not None
        ):
            dm_vis = (
                d_int_vis
                + d_ext_vis
            ) / 2.0

            _set_imported_value(
                config,
                "dm_vis_mm",
                dm_vis,
                source="DERIVED",
                source_ref=(
                    "derived:"
                    "d_int_vis_mm+d_ext_vis_mm"
                ),
            )

    dm_ecrou = _finite_or_none(
        values.get(
            "dm_ecrou_mm"
        )
    )

    if dm_ecrou is None:
        d_int_ecrou = _finite_or_none(
            values.get(
                "d_int_ecrou_mm"
            )
        )

        d_ext_ecrou = _finite_or_none(
            values.get(
                "d_ext_ecrou_mm"
            )
        )

        if (
            d_int_ecrou is not None
            and d_ext_ecrou is not None
        ):
            dm_ecrou = (
                d_int_ecrou
                + d_ext_ecrou
            ) / 2.0

            _set_imported_value(
                config,
                "dm_ecrou_mm",
                dm_ecrou,
                source="DERIVED",
                source_ref=(
                    "derived:"
                    "d_int_ecrou_mm+d_ext_ecrou_mm"
                ),
            )

    application_raw = str(
        values.get(
            "tightening_application"
        )
        or ""
    ).strip()

    application = norm_text(
        application_raw
    )

    type_serrage = ""
    db_mm: float | None = None

    if (
        "vis" in application
        or "goujon" in application
    ):
        type_serrage = "vis"
        db_mm = dm_vis

    elif (
        "ecrou" in application
        or "taraud" in application
    ):
        type_serrage = "ecrou"
        db_mm = dm_ecrou

    elif dm_vis is not None:
        type_serrage = "inconnu"
        db_mm = dm_vis

    elif dm_ecrou is not None:
        type_serrage = "inconnu"
        db_mm = dm_ecrou

    if type_serrage:
        _set_imported_value(
            config,
            "type_serrage",
            type_serrage,
            source="DERIVED",
            source_ref=(
                "derived:"
                "tightening_application"
            ),
        )

    if db_mm is not None:
        _set_imported_value(
            config,
            "Db_mm",
            db_mm,
            source="DERIVED",
            source_ref=(
                "derived:"
                "tightening_application"
                "+dm_vis_mm/dm_ecrou_mm"
            ),
        )

    return TemplateSynthImportResult(
        config=config,
        template_present=True,
        template_path=str(
            path
        ),
        template_sheet=str(
            sheet_name
        ),
        warnings=(),
    )