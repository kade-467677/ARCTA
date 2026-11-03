from __future__ import annotations

import math
import re
import statistics
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

from cta_core.parsing import norm_text

from .canonical import (
    CANONICAL_FIELD_SPEC_BY_ID,
    CanonicalCampaignConfig,
)


PROFILE_TEMPLATE_SYNTH_V1 = "TEMPLATE_SYNTH_V1"
PROFILE_INTERNAL_REQUEST_V1 = "DEMANDE_ESSAIS_INTERNE_V1"


class UnsupportedConfigSourceError(ValueError):
    pass


@dataclass(frozen=True)
class CanonicalExtractionResult:
    config: CanonicalCampaignConfig
    source_path: str
    source_profile: str
    source_sheet: str = ""
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "source_path": self.source_path,
            "source_profile": self.source_profile,
            "source_sheet": self.source_sheet,
            "warnings": list(self.warnings),
            "config": self.config.to_dict(),
        }


def _clean(value: Any) -> Any:
    if value is None:
        return None

    if isinstance(value, str):
        value = value.strip()
        return value or None

    return value


def _as_text(value: Any) -> str | None:
    value = _clean(value)
    return None if value is None else str(value).strip()


def _as_float(value: Any) -> float | None:
    value = _clean(value)

    if value is None or isinstance(value, bool):
        return None

    if isinstance(value, (int, float)):
        result = float(value)
    else:
        text = (
            str(value)
            .strip()
            .replace("\u00a0", "")
            .replace("\u202f", "")
            .replace(" ", "")
            .replace(",", ".")
        )

        try:
            result = float(text)
        except Exception:
            return None

    return result if math.isfinite(result) else None


def _as_int(value: Any) -> int | None:
    number = _as_float(value)

    if number is None or not number.is_integer():
        return None

    return int(number)


def _as_bool(value: Any) -> bool | None:
    value = _clean(value)

    if value is None:
        return None

    if isinstance(value, bool):
        return value

    if isinstance(value, (int, float)):
        return bool(value)

    normalized = norm_text(str(value))

    if normalized in {"1", "oui", "vrai", "true", "avec", "yes"}:
        return True

    if normalized in {"0", "non", "faux", "false", "sans", "no"}:
        return False

    return None


def _as_date_iso(value: Any) -> str | None:
    value = _clean(value)

    if isinstance(value, datetime):
        return value.date().isoformat()

    if isinstance(value, date):
        return value.isoformat()

    if value is None:
        return None

    text = str(value).strip()

    for pattern in (
        r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$",
        r"^(\d{1,2})[-/](\d{1,2})[-/](\d{4})$",
    ):
        match = re.match(pattern, text)

        if not match:
            continue

        parts = [int(part) for part in match.groups()]

        if pattern.startswith(r"^(\d{4})"):
            year, month, day = parts
        else:
            day, month, year = parts

        try:
            return date(year, month, day).isoformat()
        except ValueError:
            return None

    return text


def _normalize_tightening_component(value: Any) -> str | None:
    normalized = norm_text(str(value or ""))

    if "ecrou" in normalized or "taraud" in normalized:
        return "écrou"

    if "vis" in normalized or "tete" in normalized or "goujon" in normalized:
        return "vis"

    return _as_text(value)


def _normalize_bearing_geometry(value: Any) -> str | None:
    normalized = norm_text(str(value or ""))

    if "plat" in normalized:
        return "plate"

    if "coniqu" in normalized:
        return "conique"

    if "spher" in normalized:
        return "sphérique"

    return _as_text(value)


def _thread_dimensions(designation: Any) -> tuple[float | None, float | None]:
    text = str(designation or "").strip().replace(",", ".")
    normalized = text.lower().replace("×", "x")

    metric = re.search(
        r"\bm\s*(\d+(?:\.\d+)?)\s*(?:x\s*(\d+(?:\.\d+)?))?",
        normalized,
    )

    if metric:
        diameter = float(metric.group(1))
        pitch = float(metric.group(2)) if metric.group(2) else None
        return diameter, pitch

    fraction = re.search(
        r"(\d+)\s*/\s*(\d+)\s*-\s*(\d+)",
        normalized,
    )

    if fraction:
        diameter = (
            float(fraction.group(1))
            / float(fraction.group(2))
            * 25.4
        )
        pitch = 25.4 / float(fraction.group(3))
        return diameter, pitch

    imperial = re.search(
        r"(?<![/\d.])(\d+(?:\.\d+)?)\s*-\s*(\d+)",
        normalized,
    )

    if imperial:
        diameter = float(imperial.group(1)) * 25.4
        pitch = 25.4 / float(imperial.group(2))
        return diameter, pitch

    return None, None


def _tightening_endpoint(value: Any) -> tuple[float | None, str | None]:
    text = str(value or "").strip().replace(",", ".")

    with_parenthesized_unit = re.search(
        r"\(\s*([A-Za-zµ°/]+)\s*\)\s*-\s*\(\s*"
        r"([+-]?\d+(?:\.\d+)?)",
        text,
    )

    if with_parenthesized_unit:
        return (
            float(with_parenthesized_unit.group(2)),
            with_parenthesized_unit.group(1),
        )

    trailing_value = re.search(
        r"([+-]?\d+(?:\.\d+)?)\s*([A-Za-zµ°/]+)\s*$",
        text,
    )

    if trailing_value:
        return float(trailing_value.group(1)), trailing_value.group(2)

    parenthesized_value = re.search(
        r"-\s*\(\s*([+-]?\d+(?:\.\d+)?)\s*\)\s*$",
        text,
    )

    if parenthesized_value:
        return float(parenthesized_value.group(1)), None

    return None, None


def _normalized_for_field(field_id: str, raw_value: Any) -> Any:
    spec = CANONICAL_FIELD_SPEC_BY_ID[field_id]

    if field_id == "tightening_component":
        return _normalize_tightening_component(raw_value)

    if field_id == "bearing_geometry":
        return _normalize_bearing_geometry(raw_value)

    if spec.value_type == "float":
        return _as_float(raw_value)

    if spec.value_type == "int":
        return _as_int(raw_value)

    if spec.value_type == "bool":
        return _as_bool(raw_value)

    if spec.value_type == "date":
        return _as_date_iso(raw_value)

    return _as_text(raw_value)


def _put(
    config: CanonicalCampaignConfig,
    field_id: str,
    raw_value: Any,
    *,
    source_file: str,
    source_sheet: str,
    source_cell: str,
    normalized_value: Any = None,
    transformation: str = "",
    status: str = "EXTRACTED",
    message: str = "",
) -> None:
    raw_value = _clean(raw_value)

    if raw_value is None and normalized_value is None:
        return

    if normalized_value is None:
        normalized_value = _normalized_for_field(field_id, raw_value)

    if normalized_value is None:
        status = "AMBIGUOUS"
        message = message or "Valeur extraite mais non normalisable."

    spec = CANONICAL_FIELD_SPEC_BY_ID[field_id]
    unit = spec.type_unit if spec.value_type == "float" else ""

    config.set_field(
        field_id,
        raw_value=raw_value,
        normalized_value=normalized_value,
        unit=unit,
        source_file=source_file,
        source_sheet=source_sheet,
        source_cell=source_cell,
        transformation=transformation,
        status=status,
        message=message,
    )


def _sheet_map(workbook) -> dict[str, str]:
    return {
        norm_text(name): name
        for name in workbook.sheetnames
    }


def _worksheet_values(worksheet, max_row: int = 120, max_col: int = 12):
    rows = []

    for row in worksheet.iter_rows(
        min_row=1,
        max_row=min(worksheet.max_row, max_row),
        min_col=1,
        max_col=min(worksheet.max_column, max_col),
        values_only=True,
    ):
        rows.append(list(row))

    return rows


_TEMPLATE_ANCHORS = {
    norm_text("ID Programme"),
    norm_text("Configuration"),
    norm_text("Taille et pas (mm)"),
    norm_text("Application du serrage"),
}


def _is_templatesynth_sheet(worksheet) -> bool:
    found = set()

    for row in _worksheet_values(worksheet, max_row=80, max_col=10):
        for value in row:
            normalized = norm_text(value)

            if normalized in _TEMPLATE_ANCHORS:
                found.add(normalized)

    return found == _TEMPLATE_ANCHORS


def _find_templatesynth_sheet(workbook):
    preferred = (
        "configuration testee",
        "templatesynth",
        "template synth",
        "sheet 1",
    )
    mapped = _sheet_map(workbook)

    for normalized_name in preferred:
        actual = mapped.get(normalized_name)

        if actual and _is_templatesynth_sheet(workbook[actual]):
            return workbook[actual]

    for worksheet in workbook.worksheets:
        if _is_templatesynth_sheet(worksheet):
            return worksheet

    return None


def _is_internal_request_workbook(workbook) -> bool:
    mapped = _sheet_map(workbook)
    required = {
        norm_text("à remplir(demandeur)"),
        norm_text("caractéristiques pièces(labo)"),
        norm_text("ARCTA"),
    }

    if not required.issubset(mapped):
        return False

    worksheet = workbook[mapped[norm_text("ARCTA")]]

    return (
        norm_text(worksheet["C19"].value) == "arcta"
        and norm_text(worksheet["C20"].value) == "serrage"
    )


def detect_config_source_profile(path: str | Path) -> str:
    source = Path(path)

    if not source.is_file():
        raise FileNotFoundError(source)

    if source.suffix.lower() != ".xlsx":
        raise UnsupportedConfigSourceError(
            "La source CONFIG canonique doit être XLSX."
        )

    workbook = load_workbook(
        source,
        read_only=True,
        data_only=False,
        keep_links=False,
    )

    try:
        if _is_internal_request_workbook(workbook):
            return PROFILE_INTERNAL_REQUEST_V1

        if _find_templatesynth_sheet(workbook) is not None:
            return PROFILE_TEMPLATE_SYNTH_V1
    finally:
        workbook.close()

    raise UnsupportedConfigSourceError(
        "Format CONFIG non reconnu : ni TEMPLATE_SYNTH_V1 "
        "ni DEMANDE_ESSAIS_INTERNE_V1."
    )


class _LabelIndex:
    def __init__(self, worksheet) -> None:
        self.worksheet = worksheet
        self.by_label: dict[str, list[tuple[int, int]]] = {}

        for row in worksheet.iter_rows(
            min_row=1,
            max_row=min(worksheet.max_row, 140),
            min_col=1,
            max_col=min(worksheet.max_column, 12),
        ):
            for cell in row:
                normalized = norm_text(cell.value)

                if normalized:
                    self.by_label.setdefault(normalized, []).append(
                        (cell.row, cell.column)
                    )

    def row(
        self,
        label: str,
        *,
        label_col: int | None = None,
        occurrence: int = 0,
    ) -> int | None:
        matches = self.by_label.get(norm_text(label), [])

        if label_col is not None:
            matches = [item for item in matches if item[1] == label_col]

        if occurrence < 0 or occurrence >= len(matches):
            return None

        return matches[occurrence][0]

    def value(
        self,
        label: str,
        value_col: int,
        *,
        label_col: int | None = None,
        occurrence: int = 0,
    ) -> tuple[Any, str]:
        row = self.row(
            label,
            label_col=label_col,
            occurrence=occurrence,
        )

        if row is None:
            return None, ""

        cell = self.worksheet.cell(row=row, column=value_col)
        return (
            cell.value,
            f"{get_column_letter(value_col)}{row}",
        )


def _extract_templatesynth(
    path: Path,
    campaign_id: str,
    source_name: str | None = None,
) -> CanonicalExtractionResult:
    workbook = load_workbook(
        path,
        read_only=True,
        data_only=True,
        keep_links=False,
    )

    try:
        worksheet = _find_templatesynth_sheet(workbook)

        if worksheet is None:
            raise UnsupportedConfigSourceError(
                "Feuille TemplateSynth introuvable."
            )

        config = CanonicalCampaignConfig(
            campaign_id=campaign_id,
            source_profile=PROFILE_TEMPLATE_SYNTH_V1,
        )
        index = _LabelIndex(worksheet)
        source_file = str(source_name or path.name)
        source_sheet = worksheet.title

        direct_rules: tuple[
            tuple[str, str, int, int | None, Callable[[Any], Any] | None],
            ...,
        ] = (
            ("entity", "Division SAFRAN", 8, 5, None),
            ("program_id", "ID Programme", 3, 2, None),
            ("configuration_id", "Configuration", 3, 2, None),
            ("report_number", "ID CETIM", 3, 2, None),
            ("test_date", "Date de réalisation", 8, 5, _as_date_iso),
            ("sample_count", "Nombre d'échantillons", 3, 2, _as_int),
            ("tightening_component", "Application du serrage", 3, 2, _normalize_tightening_component),
            ("tightening_speed_rpm", "Vitesse de serrage (tr/mn)", 3, 2, _as_float),
            ("thread_designation", "Taille et pas (mm)", 3, 2, None),
            ("thread_pitch_diameter_mm", "Diamètre au flanc des filets (mm)", 8, 5, _as_float),
            ("bearing_mean_diameter_mm", "Diamètre moyen de frottement(Øb)", 8, 5, _as_float),
            ("lubricant_reference", "Type et référence du lubrifiant", 3, 2, None),
            ("bench_reference", "Référence du banc d'essai", 3, 2, None),
            ("sensor_reference", "Référence du capteur de mesure", 3, 2, None),
            ("operator_name", "Nom de l'opérateur", 3, 2, None),
            ("tightening_method", "Consigne de serrage", 3, 2, None),
        )

        for field_id, label, value_col, label_col, normalizer in direct_rules:
            raw_value, source_cell = index.value(
                label,
                value_col,
                label_col=label_col,
            )

            normalized_value = (
                normalizer(raw_value)
                if normalizer is not None
                else None
            )

            _put(
                config,
                field_id,
                raw_value,
                normalized_value=normalized_value,
                source_file=source_file,
                source_sheet=source_sheet,
                source_cell=source_cell,
            )

        tightening_method = config.get_field("tightening_method")

        if not tightening_method.missing:
            endpoint_value, endpoint_unit = _tightening_endpoint(
                tightening_method.value
            )

            for field_id, normalized_value in (
                ("tightening_endpoint_value", endpoint_value),
                ("tightening_endpoint_unit", endpoint_unit),
            ):
                _put(
                    config,
                    field_id,
                    tightening_method.raw_value,
                    normalized_value=normalized_value,
                    source_file=source_file,
                    source_sheet=source_sheet,
                    source_cell=tightening_method.source_cell,
                    transformation="parse tightening_method",
                    status="DERIVED",
                )

        component_columns = {
            "screw": 3,
            "nut": 5,
            "washer": 7,
            "support": 9,
        }
        component_rules = {
            "P/N": {
                "screw": "screw_part_number",
                "nut": "nut_part_number",
                "washer": "washer_part_number",
                "support": "support_plan_reference",
            },
            "Numéro(s) de lot(s)": {
                "screw": "screw_lot",
                "nut": "nut_lot",
                "washer": "washer_lot",
            },
            "Forme de l'entrainement": {
                "screw": "screw_drive_form",
                "nut": "nut_drive_form",
            },
            "Diamètre intérieur (mm)": {
                "screw": "screw_bearing_inner_diameter_mm",
                "nut": "nut_bearing_inner_diameter_mm",
                "washer": "washer_inner_diameter_mm",
                "support": "support_hole_diameter_mm",
            },
            "Diamètre extérieur (mm)": {
                "screw": "screw_bearing_outer_diameter_mm",
                "nut": "nut_bearing_outer_diameter_mm",
                "washer": "washer_outer_diameter_mm",
            },
            "Désignation matériaux": {
                "screw": "screw_material",
                "nut": "nut_material",
                "washer": "washer_material",
                "support": "support_material",
            },
            "Résistance à rupture (Rm)": {
                "screw": "screw_rm_mpa",
                "nut": "nut_rm_mpa",
                "washer": "washer_rm_mpa",
            },
            "Résistance à la limite d'élasticité (Rp0,2)": {
                "screw": "screw_re_mpa",
                "nut": "nut_re_mpa",
                "washer": "washer_re_mpa",
            },
            "Dureté (HV)": {
                "screw": "screw_hardness_hv",
                "nut": "nut_hardness_hv",
                "washer": "washer_hardness_hv",
                "support": "support_hardness",
            },
            "Désignation ou référence": {
                "screw": "screw_surface_treatment",
                "nut": "nut_surface_treatment",
                "washer": "washer_surface_treatment",
            },
            "Rugosité (Ra)": {
                "support": "support_roughness_ra_um",
            },
        }

        for label, by_component in component_rules.items():
            row = index.row(label, label_col=2)

            if row is None:
                continue

            for component, field_id in by_component.items():
                column = component_columns[component]
                cell = worksheet.cell(row=row, column=column)
                message = ""
                status = "EXTRACTED"

                if field_id in {"screw_material", "nut_material"}:
                    message = (
                        "La valeur brute peut contenir matériau et "
                        "spécification/DMD ; séparation à confirmer."
                    )
                    status = "AMBIGUOUS"

                _put(
                    config,
                    field_id,
                    cell.value,
                    source_file=source_file,
                    source_sheet=source_sheet,
                    source_cell=(
                        f"{get_column_letter(column)}{row}"
                    ),
                    status=status,
                    message=message,
                )

        type_row = index.row("Informations types de pièces", label_col=2)

        if type_row is not None:
            washer_cell = worksheet.cell(row=type_row, column=7)
            _put(
                config,
                "washer_description",
                washer_cell.value,
                source_file=source_file,
                source_sheet=source_sheet,
                source_cell=f"G{type_row}",
            )

            support_cell = worksheet.cell(row=type_row, column=9)
            contact_value = None
            contact_cell = ""

            if _clean(washer_cell.value) is not None:
                contact_value = "rondelle"
                contact_cell = f"G{type_row}"
            elif _clean(support_cell.value) is not None:
                contact_value = "plaque d'appui"
                contact_cell = f"I{type_row}"

            _put(
                config,
                "contact_part_type",
                contact_value,
                normalized_value=contact_value,
                source_file=source_file,
                source_sheet=source_sheet,
                source_cell=contact_cell,
                transformation="derive from component columns",
                status="DERIVED",
            )

        inner_active, inner_cell = index.value(
            "Diamètre intérieur (mm)",
            3,
            label_col=2,
            occurrence=1,
        )
        outer_active, outer_cell = index.value(
            "Diamètre extérieur (mm)",
            3,
            label_col=2,
            occurrence=1,
        )
        _put(
            config,
            "bearing_inner_active_mm",
            inner_active,
            source_file=source_file,
            source_sheet=source_sheet,
            source_cell=inner_cell,
        )
        _put(
            config,
            "bearing_outer_active_mm",
            outer_active,
            source_file=source_file,
            source_sheet=source_sheet,
            source_cell=outer_cell,
        )

        mean_diameter = config.get_field("bearing_mean_diameter_mm")

        if not mean_diameter.missing:
            _put(
                config,
                "bearing_mean_radius_mm",
                mean_diameter.raw_value,
                normalized_value=float(mean_diameter.value) / 2.0,
                source_file=source_file,
                source_sheet=source_sheet,
                source_cell=mean_diameter.source_cell,
                transformation="bearing_mean_diameter_mm / 2",
                status="DERIVED",
            )

        thread_designation = config.get_field("thread_designation")

        if not thread_designation.missing:
            nominal, pitch = _thread_dimensions(thread_designation.value)

            _put(
                config,
                "thread_nominal_diameter_mm",
                thread_designation.raw_value,
                normalized_value=nominal,
                source_file=source_file,
                source_sheet=source_sheet,
                source_cell=thread_designation.source_cell,
                transformation="parse thread_designation",
                status="DERIVED",
            )

            designation_normalized = norm_text(thread_designation.value)
            half_angle = (
                30.0
                if any(
                    marker in designation_normalized
                    for marker in ("unj", "unf", "unc", "metric", "m ")
                )
                or designation_normalized.startswith("m")
                else None
            )
            _put(
                config,
                "thread_half_angle_deg",
                thread_designation.raw_value,
                normalized_value=half_angle,
                source_file=source_file,
                source_sheet=source_sheet,
                source_cell=thread_designation.source_cell,
                transformation="ISO/UN thread profile: 60° included angle / 2",
                status="DERIVED",
            )
            _put(
                config,
                "thread_pitch_mm",
                thread_designation.raw_value,
                normalized_value=pitch,
                source_file=source_file,
                source_sheet=source_sheet,
                source_cell=thread_designation.source_cell,
                transformation="parse thread_designation / TPI",
                status="DERIVED",
            )

        lubrication_rules = (
            ("lube_screw_bearing", "Application sur la surface d'appui", 3),
            ("lube_nut_bearing", "Application sur la surface d'appui", 5),
            ("lube_washer_bearing", "Application sur la surface d'appui", 7),
            ("lube_screw_thread", "Application sur le filetage", 3),
            ("lube_nut_thread", "Application sur le filetage", 5),
        )

        any_lubricated = False

        for field_id, label, column in lubrication_rules:
            raw_value, source_cell = index.value(label, column, label_col=2)
            normalized_value = _as_bool(raw_value)
            any_lubricated = any_lubricated or normalized_value is True
            _put(
                config,
                field_id,
                raw_value,
                normalized_value=normalized_value,
                source_file=source_file,
                source_sheet=source_sheet,
                source_cell=source_cell,
            )

        lubricant = config.get_field("lubricant_reference")
        lubrication_present = any_lubricated or not lubricant.missing
        _put(
            config,
            "lubrication_present",
            lubrication_present,
            normalized_value=lubrication_present,
            source_file=source_file,
            source_sheet=source_sheet,
            source_cell=lubricant.source_cell,
            transformation="lubricant_reference or localization flags",
            status="DERIVED",
        )

        results_row = index.row("Résultats des essais", label_col=2)
        selflock_values: list[float] = []
        result_cells: list[str] = []

        if results_row is not None:
            for row in range(results_row + 1, min(worksheet.max_row, 5000) + 1):
                first_value = worksheet.cell(row=row, column=2).value

                if norm_text(first_value).startswith("moyenne"):
                    break

                value = _as_float(worksheet.cell(row=row, column=10).value)

                if value is not None:
                    selflock_values.append(value)
                    result_cells.append(f"J{row}")

        if selflock_values:
            source_range = (
                f"{result_cells[0]}:{result_cells[-1]}"
                if len(result_cells) > 1
                else result_cells[0]
            )
            statistics_values = {
                "selflock_mean_nm": statistics.fmean(selflock_values),
                "selflock_median_nm": statistics.median(selflock_values),
                "selflock_std_nm": (
                    statistics.stdev(selflock_values)
                    if len(selflock_values) > 1
                    else 0.0
                ),
                "selflock_min_nm": min(selflock_values),
                "selflock_max_nm": max(selflock_values),
                "selflock_valid_count": len(selflock_values),
            }

            for field_id, value in statistics_values.items():
                _put(
                    config,
                    field_id,
                    selflock_values,
                    normalized_value=value,
                    source_file=source_file,
                    source_sheet=source_sheet,
                    source_cell=source_range,
                    transformation="statistics over valid self-lock values",
                    status="DERIVED",
                )

        warnings = []

        if config.get_field("tightening_component").missing:
            warnings.append("TIGHTENING_COMPONENT_MISSING")

        return CanonicalExtractionResult(
            config=config,
            source_path=str(path),
            source_profile=PROFILE_TEMPLATE_SYNTH_V1,
            source_sheet=source_sheet,
            warnings=tuple(warnings),
        )
    finally:
        workbook.close()


def _worksheet_by_normalized_name(workbook, wanted: str):
    actual = _sheet_map(workbook).get(norm_text(wanted))

    if actual is None:
        raise UnsupportedConfigSourceError(
            f"Feuille interne introuvable : {wanted}"
        )

    return workbook[actual]


def _combine(*values: Any) -> str | None:
    cleaned = [str(value).strip() for value in values if _clean(value) is not None]
    return " — ".join(cleaned) if cleaned else None


def _extract_internal_request(
    path: Path,
    campaign_id: str,
    source_name: str | None = None,
) -> CanonicalExtractionResult:
    workbook = load_workbook(
        path,
        read_only=True,
        data_only=True,
        keep_links=False,
    )

    try:
        request = _worksheet_by_normalized_name(workbook, "à remplir(demandeur)")
        parts = _worksheet_by_normalized_name(workbook, "caractéristiques pièces(labo)")
        arcta = _worksheet_by_normalized_name(workbook, "ARCTA")
        config = CanonicalCampaignConfig(
            campaign_id=campaign_id,
            source_profile=PROFILE_INTERNAL_REQUEST_V1,
        )
        source_file = str(source_name or path.name)

        request_rules = {
            "configuration_id": "B6",
            "assembly_plan_reference": "C6",
            "sample_count": "D6",
            "tightening_speed_rpm": "E6",
            "tightening_endpoint_value": "H6",
            "tightening_endpoint_unit": "I6",
            "tightening_component": "J6",
            "grip_or_threads": "K6",
            "contact_part_type": "L6",
            "screw_plan_reference": "M6",
            "nut_plan_reference": "N6",
            "washer_description": "O6",
            "washer_plan_reference": "P6",
            "support_plan_reference": "Q6",
            "lubrication_present": "B15",
            "lubricant_reference": "C15",
            "lubricant_wrs_listed": "D15",
            "lubricant_wrs_reference": "E15",
            "lube_screw_bearing": "F15",
            "lube_screw_thread": "G15",
            "lube_nut_bearing": "H15",
            "lube_nut_thread": "I15",
            "lube_washer_bearing": "J15",
            "lubricant_application_method": "K15",
            "lubrication_comment": "L15",
        }

        for field_id, cell_ref in request_rules.items():
            _put(
                config,
                field_id,
                request[cell_ref].value,
                source_file=source_file,
                source_sheet=request.title,
                source_cell=cell_ref,
            )

        method = _clean(request["F6"].value)
        other_method = _clean(request["G6"].value)
        method_text = _combine(method, other_method) if other_method else method
        _put(
            config,
            "tightening_method",
            method_text,
            source_file=source_file,
            source_sheet=request.title,
            source_cell="F6:G6",
        )

        part_rules = {
            "thread_designation": "C6",
            "thread_nominal_diameter_mm": "D6",
            "thread_pitch_mm": "F6",
            "thread_half_angle_deg": "H6",
            "bearing_geometry": "I6",
            "bearing_angle_deg": "J6",
            "screw_bearing_inner_diameter_mm": "N6",
            "screw_bearing_outer_diameter_mm": "O6",
            "screw_rm_mpa": "V6",
            "nut_bearing_inner_diameter_mm": "Y6",
            "nut_bearing_outer_diameter_mm": "Z6",
            "nut_rm_mpa": "AG6",
            "washer_inner_diameter_mm": "B15",
            "washer_outer_diameter_mm": "C15",
            "washer_thickness_mm": "D15",
            "support_hole_diameter_mm": "H15",
            "support_thickness_mm": "I15",
            "support_material": "K15",
            "support_material_spec": "L15",
            "support_roughness_ra_um": "M15",
            "support_hardness": "N15",
            "measured_m_mm": "Q15",
            "contact_summary": "S15",
            "bearing_inner_active_mm": "U15",
            "bearing_outer_active_mm": "V15",
            "effective_grip_mm": "X15",
            "full_thread_length_mm": "Y15",
            "shim_thickness_m_method_mm": "Z15",
            "shim_thickness_grip_method_mm": "AA15",
            "shim_thickness_tooling_method_mm": "AB15",
        }

        for field_id, cell_ref in part_rules.items():
            _put(
                config,
                field_id,
                parts[cell_ref].value,
                source_file=source_file,
                source_sheet=parts.title,
                source_cell=cell_ref,
            )

        for field_id, cell_ref in (
            ("screw_material", "U6"),
            ("nut_material", "AF6"),
        ):
            _put(
                config,
                field_id,
                parts[cell_ref].value,
                source_file=source_file,
                source_sheet=parts.title,
                source_cell=cell_ref,
                status="AMBIGUOUS",
                message=(
                    "La cellule contient actuellement matériau + "
                    "spécification/DMD ; séparation à confirmer."
                ),
            )

        screw_drive = _combine(parts["Q6"].value, parts["R6"].value)
        nut_drive = _combine(parts["AB6"].value, parts["AC6"].value)
        _put(
            config,
            "screw_drive_form",
            screw_drive,
            source_file=source_file,
            source_sheet=parts.title,
            source_cell="Q6:R6",
        )
        _put(
            config,
            "nut_drive_form",
            nut_drive,
            source_file=source_file,
            source_sheet=parts.title,
            source_cell="AB6:AC6",
        )

        radius = _as_float(arcta["C13"].value)

        if radius is None:
            inner = _as_float(parts["U15"].value)
            outer = _as_float(parts["V15"].value)
            geometry = _normalize_bearing_geometry(parts["I6"].value)

            if inner is not None and outer is not None and geometry == "plate":
                radius = (inner + outer) / 4.0
                radius_source_sheet = parts.title
                radius_source_cell = "U15:V15"
                radius_transformation = "(Di + Dw) / 4 for flat bearing"
            else:
                radius_source_sheet = arcta.title
                radius_source_cell = "C13"
                radius_transformation = ""
        else:
            radius_source_sheet = arcta.title
            radius_source_cell = "C13"
            radius_transformation = "ARCTA mean bearing radius"

        _put(
            config,
            "bearing_mean_radius_mm",
            radius,
            normalized_value=radius,
            source_file=source_file,
            source_sheet=radius_source_sheet,
            source_cell=radius_source_cell,
            transformation=radius_transformation,
            status="DERIVED",
        )

        if radius is not None:
            _put(
                config,
                "bearing_mean_diameter_mm",
                radius,
                normalized_value=2.0 * radius,
                source_file=source_file,
                source_sheet=radius_source_sheet,
                source_cell=radius_source_cell,
                transformation="2 * bearing_mean_radius_mm",
                status="DERIVED",
            )

        warnings = []

        if config.get_field("thread_pitch_diameter_mm").missing:
            warnings.append("THREAD_PITCH_DIAMETER_MISSING")

        if config.get_field("screw_part_number").missing:
            warnings.append("PART_NUMBERS_DISTINCT_FROM_PLANS_MISSING")

        return CanonicalExtractionResult(
            config=config,
            source_path=str(path),
            source_profile=PROFILE_INTERNAL_REQUEST_V1,
            source_sheet=request.title,
            warnings=tuple(warnings),
        )
    finally:
        workbook.close()


def extract_canonical_campaign_config(
    *,
    campaign_id: str,
    source_path: str | Path,
    source_profile: str | None = None,
    source_name: str | None = None,
) -> CanonicalExtractionResult:
    path = Path(source_path)
    profile = (
        detect_config_source_profile(path)
        if source_profile is None
        else str(source_profile).strip().upper()
    )

    if profile == PROFILE_TEMPLATE_SYNTH_V1:
        return _extract_templatesynth(path, campaign_id, source_name)

    if profile == PROFILE_INTERNAL_REQUEST_V1:
        return _extract_internal_request(path, campaign_id, source_name)

    raise UnsupportedConfigSourceError(
        f"Profil CONFIG canonique non supporté : {profile}"
    )
