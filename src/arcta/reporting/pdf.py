from __future__ import annotations
from arcta.notation import iso_text, LABELS, nomenclature_rows

import os
import textwrap
from numbers import Number
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from arcta.statistical_titles import statistical_caption
from arcta.reporting.options import normalize_report_options
from arcta.tolerance_explanations import pdf_explanations
from cta_core.config_model import CANONICAL_FIELD_SPECS


CAMPAIGN_PDF_FILENAME = "report.pdf"
COVER_ARTWORK_FILENAME = "AR-DAB-SELE_CTA.png"
SAFRAN_LOGO_FILENAME = "LOGO_SAFRAN_1109x381.png"
DIAG_PRINCIPLE_FILENAME = "diag_principle_arcta.png"
PDF_RESOURCES_ENV = "ARCTA_RESOURCES_DIR"

CONFIDENTIALITY_TEXT = "C2 - confidentiel"
COVER_TITLE = "ESSAIS COUPLE TENSION"
COVER_FOOTER_LINES = (
    "EXPLOITATION ET SYNTHÈSE DE DONNÉES EXPÉRIMENTALES",
    "D’ESSAIS COUPLE TENSION POUR ASSEMBLAGES BOULONNÉS GÉNÉRÉS SELON ISO 16047",
    "—",
    "ANALYSE SOUS FORME POLYNOMIALE ET EXPLOITATION STATISTIQUE SELON ISO 16269",
)

_ORANGE = "#E7662B"
_DARK_BLUE = "#24364B"
_LIGHT_BLUE = "#E9F0F6"
_MID_GREY = "#5B6570"


_CANONICAL_GEOMETRY_FIELDS = (
    "tightening_component",
    "contact_part_type",
    "thread_designation",
    "thread_nominal_diameter_mm",
    "thread_pitch_mm",
    "thread_lead_mm",
    "thread_pitch_diameter_mm",
    "thread_half_angle_deg",
    "bearing_mean_diameter_mm",
    "bearing_inner_active_mm",
    "bearing_outer_active_mm",
    "screw_bearing_inner_diameter_mm",
    "screw_bearing_outer_diameter_mm",
    "nut_bearing_inner_diameter_mm",
    "nut_bearing_outer_diameter_mm",
    "washer_inner_diameter_mm",
    "washer_outer_diameter_mm",
    "washer_thickness_mm",
    "support_hole_diameter_mm",
    "support_thickness_mm",
    "bearing_geometry",
    "bearing_angle_deg",
    "bearing_cone_half_angle_deg",
)

_CANONICAL_LUBRICATION_FIELDS = (
    "lubrication_present",
    "lubricant_reference",
    "lubricant_wrs_listed",
    "lubricant_wrs_reference",
    "lubricant_application_method",
    "lube_screw_thread",
    "lube_nut_thread",
    "lube_screw_bearing",
    "lube_nut_bearing",
    "lube_washer_bearing",
    "lubrication_comment",
)

_CANONICAL_COMPONENT_ROWS = (
    (
        "Vis",
        ("screw_part_number", "screw_plan_reference"),
        ("screw_material", "screw_material_spec"),
        ("screw_surface_treatment", "screw_hardness_hv"),
    ),
    (
        "Écrou",
        ("nut_part_number", "nut_plan_reference"),
        ("nut_material", "nut_material_spec"),
        ("nut_surface_treatment", "nut_hardness_hv"),
    ),
    (
        "Rondelle / entretoise",
        ("washer_part_number", "washer_plan_reference"),
        ("washer_material", "washer_material_spec"),
        ("washer_surface_treatment", "washer_hardness_hv"),
    ),
    (
        "Plaque d'appui",
        ("support_plan_reference",),
        ("support_material", "support_material_spec"),
        ("support_roughness_ra_um", "support_hardness"),
    ),
)

_CANONICAL_LABEL_BY_ID = {
    spec.field_id: spec.label
    for spec in CANONICAL_FIELD_SPECS
}

_CANONICAL_COMPONENT_PREFIXES = {
    "screw_part_number": "P/N",
    "nut_part_number": "P/N",
    "washer_part_number": "P/N",
    "screw_plan_reference": "Plan",
    "nut_plan_reference": "Plan",
    "washer_plan_reference": "Plan",
    "support_plan_reference": "Plan",
    "screw_material": "Matériau",
    "nut_material": "Matériau",
    "washer_material": "Matériau",
    "support_material": "Matériau",
    "screw_material_spec": "Spéc.",
    "nut_material_spec": "Spéc.",
    "washer_material_spec": "Spéc.",
    "support_material_spec": "Spéc.",
    "screw_surface_treatment": "Traitement",
    "nut_surface_treatment": "Traitement",
    "washer_surface_treatment": "Traitement",
    "screw_hardness_hv": "Dureté",
    "nut_hardness_hv": "Dureté",
    "washer_hardness_hv": "Dureté",
    "support_roughness_ra_um": "Rugosité",
    "support_hardness": "Dureté",
}


class CampaignPdfError(RuntimeError):
    """Erreur explicite de composition du rapport PDF ARCTA."""


class CampaignPdfResourceError(CampaignPdfError):
    """Une image obligatoire de la page de garde est absente ou illisible."""


@dataclass(frozen=True)
class CampaignPdfResult:
    output_path: Path
    page_count: int
    inventory: tuple[dict[str, object], ...]
    resources_dir: Path


def default_pdf_resources_dir() -> Path:
    """Retourne le dossier resources du déploiement, surchargeable par env."""
    configured = str(os.environ.get(PDF_RESOURCES_ENV, "")).strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[3] / "resources"


def require_pdf_resources(
    resources_dir: str | Path | None = None,
) -> tuple[Path, Path, Path]:
    root = (
        Path(resources_dir).expanduser().resolve()
        if resources_dir is not None
        else default_pdf_resources_dir().resolve()
    )
    artwork = root / COVER_ARTWORK_FILENAME
    logo = root / SAFRAN_LOGO_FILENAME
    missing = [path.name for path in (artwork, logo) if not path.is_file()]
    if missing:
        raise CampaignPdfResourceError(
            "Ressource(s) PDF obligatoire(s) absente(s) dans "
            f"{root} : {', '.join(missing)}"
        )
    return root, artwork, logo


def _register_fonts() -> tuple[str, str]:
    """Police Unicode livrée avec Matplotlib, identique sous Windows et Linux."""
    import matplotlib
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    root = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
    names = ("ARCTA-DejaVu", "ARCTA-DejaVu-Bold")

    for name, filename in zip(
        names, ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf")
    ):
        if name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(name, str(root / filename)))

    return names


def _safe_text(value: object, *, fallback: str = "—") -> str:
    if isinstance(value, bool):
        return "Oui" if value else "Non"
    if isinstance(value, Number):
        numeric = float(value)
        if pd.isna(numeric):
            return fallback
        magnitude = abs(numeric)
        if numeric == 0:
            return "0"
        if magnitude >= 1.0e5 or magnitude < 1.0e-2:
            return f"{numeric:.2e}".replace(".", ",")
        if numeric.is_integer():
            return str(int(numeric))
        return f"{numeric:.2f}".rstrip("0").rstrip(".").replace(".", ",")
    text = str(value if value is not None else "").strip()
    return text or fallback


_COLUMN_LABELS = {
    "Indicator": "Indicateur",
    "Value": "Valeur",
    "Source_Name": "Fichier source",
    "Automatic_Status": "Statut auto",
    "Review_Decision": "Décision revue",
    "ISO16269_4_Max_Severity": "Sévérité ISO",
    "Score_Comportement_Global": "Comportement /100",
    "Score_Comparatif_Population": "Population /100",
    "K_YA_20_50": "K Y/A",
    "A0_elastic_from_Xg_eff": "A0 recalé (°)",
    "K_XgA_20_50": "K Xg/A",
    "Mean_nRMSE_Percent": "nRMSE moy. (%)",
    "Median_nRMSE_Percent": "nRMSE méd. (%)",
    "Max_nRMSE_Percent": "nRMSE max. (%)",
    "nRMSE_Percent": "nRMSE (%)",
    "Threshold_Class": "Classe",
    "Count_Within_1pct": "≤ 1 %",
    "Count_Within_2_5pct": "≤ 2,5 %",
    "Count_Within_5pct": "≤ 5 %",
    "Count_Within_10pct": "≤ 10 %",
    "Count_Above_10pct": "> 10 %",
    "Within_2_5pct": "≤ 2,5 %",
    "Within_5pct": "≤ 5 %",
    "Within_10pct": "≤ 10 %",
    "Compute_Sheet": "Feuille",
    "Stat": "Stat.",
    "Degree": "Degré",
    "coeff0": "c0",
    "coeff1": "c1",
    "coeff2": "c2",
    "coeff3": "c3",
    "coeff4": "c4",
    "coeff5": "c5",
    "coeff6": "c6",
    "X_min": "X min",
    "X_max": "X max",
    "Mean_Nm": "Moy. (N·m)",
    "Median_Nm": "Méd. (N·m)",
    "Std_Nm": "Écart-type",
    "Q1_Nm": "Q1",
    "Q3_Nm": "Q3",
    "Min_Nm": "Min.",
    "Max_Nm": "Max.",
    "Autofrein_Xg_preA0_med": "Médiane (N·m)",
    "Autofrein_Xg_preA0_mean": "Moyenne (N·m)",
    "Autofrein_Xg_preA0_std": "Écart-type",
    "Autofrein_Xg_preA0_MAD": "MAD",
    "DeadTravel_DeltaA_deg": "Course morte (°)",
    "Residual_Thread_Torque_Median_Nm": "Xt résiduel (N·m)",
    "Residual_Torsional_Stress_Nominal_MPa": "τ torsion (MPa)",
    "DeadTravel_Quality_Flag": "Qualité inversion",
}


def _column_label(column: str) -> str:
    return iso_text(_COLUMN_LABELS.get(column, str(column).replace("_", " ")))


def _analysis_label(mode: str) -> str:
    normalized = str(mode or "").strip().lower()
    return {
        "fine": "Analyse Fine",
        "global": "Analyse Globale",
        "globale": "Analyse Globale",
        "basic": "Analyse Basique",
        "basique": "Analyse Basique",
    }.get(normalized, f"Analyse {_safe_text(mode, fallback='ARCTA')}")


def _canonical_fields(
    canonical_config: Mapping[str, object] | None,
) -> dict[str, Mapping[str, object]]:
    if not isinstance(canonical_config, Mapping):
        return {}
    raw_fields = canonical_config.get("fields", ())
    if not isinstance(raw_fields, Sequence) or isinstance(raw_fields, (str, bytes)):
        return {}
    output: dict[str, Mapping[str, object]] = {}
    for raw in raw_fields:
        if not isinstance(raw, Mapping):
            continue
        field_id = str(raw.get("field_id", "")).strip()
        if field_id:
            output[field_id] = raw
    return output


def _canonical_value(field: Mapping[str, object] | None) -> str:
    if not field:
        return "—"
    value = field.get("value")
    if value is None or str(value).strip() == "":
        return "—"
    rendered = _safe_text(value)
    unit = str(field.get("unit") or field.get("type_unit") or "").strip()
    if unit.lower() in {
        "",
        "texte",
        "texte/enum",
        "booléen",
        "date iso",
        "enum vis|écrou",
        "enum plate|conique|sphérique",
        "nombre",
        "entier",
        "unité",
    }:
        unit = ""
    return f"{rendered} {unit}".strip()


def _canonical_label_value(
    fields: Mapping[str, Mapping[str, object]],
    field_id: str,
) -> tuple[str, str]:
    field = fields.get(field_id, {})
    label = (
        str(field.get("label", "")).strip()
        or _CANONICAL_LABEL_BY_ID.get(field_id, field_id)
    )
    return label, _canonical_value(field)


def _joined_canonical_values(
    fields: Mapping[str, Mapping[str, object]],
    field_ids: Sequence[str],
    *,
    show_labels: bool = False,
) -> str:
    present = []
    for field_id in field_ids:
        value = _canonical_value(fields.get(field_id))
        if value == "—":
            continue
        if show_labels:
            prefix = _CANONICAL_COMPONENT_PREFIXES.get(field_id, "")
            value = f"{prefix} : {value}" if prefix else value
        present.append(value)
    return " / ".join(present) if present else "—"


def _canonical_summary_blocks(
    canonical_config: Mapping[str, object] | None,
) -> dict[str, object]:
    fields = _canonical_fields(canonical_config)
    if not fields:
        return {}

    identity = {
        field_id: _canonical_value(fields.get(field_id))
        for field_id in (
            "entity",
            "program_id",
            "configuration_id",
            "report_number",
            "test_date",
            "sample_count",
            "tightening_speed_rpm",
            "tightening_method",
            "tightening_endpoint_value",
            "tightening_endpoint_unit",
        )
    }
    geometry = [
        _canonical_label_value(fields, field_id)
        for field_id in _CANONICAL_GEOMETRY_FIELDS
    ]
    lubrication = [
        _canonical_label_value(fields, field_id)
        for field_id in _CANONICAL_LUBRICATION_FIELDS
    ]
    components = [
        (
            component,
            _joined_canonical_values(fields, references, show_labels=True),
            _joined_canonical_values(fields, materials, show_labels=True),
            _joined_canonical_values(fields, treatments, show_labels=True),
        )
        for component, references, materials, treatments
        in _CANONICAL_COMPONENT_ROWS
    ]
    endpoint = " / ".join(
        value
        for value in (
            identity["tightening_endpoint_value"],
            identity["tightening_endpoint_unit"],
        )
        if value != "—"
    ) or "—"
    identity["tightening_endpoint"] = endpoint
    conditions = [
        _canonical_label_value(fields, "tightening_speed_rpm"),
        _canonical_label_value(fields, "tightening_method"),
        ("Fin de serrage", endpoint),
    ]
    return {
        "identity": identity,
        "conditions": conditions,
        "geometry": geometry,
        "components": components,
        "lubrication": lubrication,
    }


def _summary_table(
    rows: Sequence[Sequence[object]],
    *,
    width: float,
    regular_font: str,
    bold_font: str,
    column_weights: Sequence[float],
    header: bool = False,
    font_size: float = 6.5,
):
    from html import escape

    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Paragraph, Table, TableStyle

    weights = [float(value) for value in column_weights]
    total = sum(weights)
    widths = [width * value / total for value in weights]
    cell = ParagraphStyle(
        "ARCTA-Config-Cell",
        fontName=regular_font,
        fontSize=font_size,
        leading=font_size + 1.1,
    )
    label_style = ParagraphStyle(
        "ARCTA-Config-Label",
        fontName=bold_font,
        fontSize=font_size,
        leading=font_size + 1.1,
        textColor=colors.HexColor(_MID_GREY),
    )
    header_style = ParagraphStyle(
        "ARCTA-Config-Header",
        fontName=bold_font,
        fontSize=font_size,
        leading=font_size + 1.1,
        textColor=colors.white,
    )
    data = []
    for row_index, row in enumerate(rows):
        data.append([
            Paragraph(
                escape(_safe_text(value)),
                (
                    header_style
                    if header and row_index == 0
                    else label_style if column_index == 0 else cell
                ),
            )
            for column_index, value in enumerate(row)
        ])
    table = Table(data, colWidths=widths)
    styles = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CBD3DB")),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), (colors.white, colors.HexColor("#F6F8FA"))),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 2.2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.2),
    ]
    if header:
        styles.extend([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(_DARK_BLUE)),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), bold_font),
        ])
    table.setStyle(TableStyle(styles))
    return table


def _draw_summary_subtitle(
    canvas,
    text: str,
    *,
    x: float,
    y: float,
    bold_font: str,
) -> None:
    from reportlab.lib import colors

    canvas.setFillColor(colors.HexColor(_DARK_BLUE))
    canvas.setFont(bold_font, 8.5)
    canvas.drawString(x, y, text)


def _draw_canonical_configuration(
    canvas,
    *,
    pagesize,
    canonical_config: Mapping[str, object],
    start_y: float,
    regular_font: str,
    bold_font: str,
) -> None:
    from reportlab.lib.units import cm

    blocks = _canonical_summary_blocks(canonical_config)
    if not blocks:
        return
    width, _height = pagesize
    gap = 0.55 * cm
    column_width = (width - 2.2 * cm - gap) / 2.0
    left_x = 1.1 * cm
    right_x = left_x + column_width + gap

    def draw_stack(x: float, y: float, sections) -> None:
        current_y = y
        for title, table in sections:
            _draw_summary_subtitle(
                canvas,
                title,
                x=x,
                y=current_y,
                bold_font=bold_font,
            )
            current_y -= 0.23 * cm
            _wrapped_width, table_height = table.wrap(
                column_width,
                max(1.0, current_y - 1.3 * cm),
            )
            table.drawOn(canvas, x, current_y - table_height)
            current_y -= table_height + 0.42 * cm

    geometry_table = _summary_table(
        blocks["geometry"],
        width=column_width,
        regular_font=regular_font,
        bold_font=bold_font,
        column_weights=(1.45, 1.0),
        font_size=7.0,
    )
    conditions_table = _summary_table(
        blocks["conditions"],
        width=column_width,
        regular_font=regular_font,
        bold_font=bold_font,
        column_weights=(1.45, 1.0),
        font_size=7.0,
    )
    component_table = _summary_table(
        [
            ("Composant", "Référence", "Matériau / spéc.", "Traitement / dureté"),
            *blocks["components"],
        ],
        width=column_width,
        regular_font=regular_font,
        bold_font=bold_font,
        column_weights=(1.05, 1.15, 1.45, 1.40),
        header=True,
        font_size=6.2,
    )
    lubrication_table = _summary_table(
        blocks["lubrication"],
        width=column_width,
        regular_font=regular_font,
        bold_font=bold_font,
        column_weights=(1.4, 1.0),
        font_size=6.8,
    )
    draw_stack(
        left_x,
        start_y,
        (
            ("Conditions de serrage", conditions_table),
            ("Filetage et géométrie fonctionnelle", geometry_table),
        ),
    )
    draw_stack(
        right_x,
        start_y,
        (
            ("Constitution de l'assemblage", component_table),
            ("Lubrification", lubrication_table),
        ),
    )


def _draw_image_fit(canvas, path: Path, x: float, y: float, width: float, height: float) -> None:
    from reportlab.lib.utils import ImageReader

    try:
        image = ImageReader(str(path))
        image_width, image_height = image.getSize()
        if image_width <= 0 or image_height <= 0:
            raise ValueError("dimensions nulles")
        scale = min(width / image_width, height / image_height)
        draw_width = image_width * scale
        draw_height = image_height * scale
        canvas.drawImage(
            image,
            x + (width - draw_width) / 2.0,
            y + (height - draw_height) / 2.0,
            width=draw_width,
            height=draw_height,
            preserveAspectRatio=True,
            mask="auto",
        )
    except Exception as exc:
        raise CampaignPdfResourceError(
            f"Image PDF obligatoire illisible : {path.name} ({exc})"
        ) from exc


def _draw_centered_wrapped(
    canvas,
    text: str,
    *,
    center_x: float,
    first_y: float,
    max_width: float,
    font_name: str,
    font_size: float,
    leading: float,
) -> float:
    from reportlab.pdfbase.pdfmetrics import stringWidth

    words = str(text).split()
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        candidate = " ".join((*current, word))
        if current and stringWidth(candidate, font_name, font_size) > max_width:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))

    y = first_y
    canvas.setFont(font_name, font_size)
    for line in lines or [""]:
        canvas.drawCentredString(center_x, y, line)
        y -= leading
    return y


def _draw_cover(
    canvas,
    *,
    pagesize,
    artwork: Path,
    logo: Path,
    campaign_label: str,
    mode: str,
    regular_font: str,
    bold_font: str,
    mechanical_label: str = "",
) -> None:
    from reportlab.lib import colors
    from reportlab.lib.units import cm

    width, height = pagesize
    canvas.setPageSize(pagesize)
    canvas.setFillColor(colors.white)
    canvas.rect(0, 0, width, height, stroke=0, fill=1)

    canvas.setFillColor(colors.HexColor(_ORANGE))
    canvas.setFont(bold_font, 6.8)
    canvas.drawCentredString(width / 2.0, height - 0.48 * cm, CONFIDENTIALITY_TEXT)

    _draw_image_fit(
        canvas,
        logo,
        1.15 * cm,
        height - 2.45 * cm,
        4.35 * cm,
        1.50 * cm,
    )

    canvas.setFillColor(colors.black)
    canvas.setFont(bold_font, 22)
    canvas.drawCentredString(width / 2.0, height - 3.40 * cm, COVER_TITLE)

    # Titre personnalisé dans une zone réservée.
    from xml.sax.saxutils import escape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Paragraph, KeepInFrame

    style = ParagraphStyle(
        "CoverTitle",
        fontName=bold_font,
        fontSize=13,
        leading=17,
        alignment=1,
        splitLongWords=True,
    )
    box = KeepInFrame(
        17 * cm,
        2.6 * cm,
        [Paragraph(escape(_safe_text(campaign_label)), style)],
        mode="shrink",
        hAlign="CENTER",
        vAlign="TOP",
    )
    box.wrapOn(canvas, 17 * cm, 2.6 * cm)
    box.drawOn(
        canvas,
        (width - 17 * cm) / 2,
        height - 4.65 * cm - box.height,
    )

    _draw_image_fit(
        canvas,
        artwork,
        3.60 * cm,
        8.05 * cm,
        width - 7.20 * cm,
        13.10 * cm,
    )

    if mechanical_label:
        canvas.setFont(bold_font, 10)
        canvas.drawCentredString(width / 2.0, 6.6 * cm, mechanical_label)

    footer_y = 4.35 * cm
    for index, line in enumerate(COVER_FOOTER_LINES):
        size = 7.2 if index != 2 else 8.0
        font = bold_font if index != 2 else regular_font
        canvas.setFont(font, size)
        canvas.drawCentredString(width / 2.0, footer_y, line)
        footer_y -= 0.48 * cm if index != 2 else 0.42 * cm

    canvas.showPage()


def _draw_body_header_footer(
    canvas,
    *,
    pagesize,
    page_number: int,
    campaign_label: str,
    regular_font: str,
    bold_font: str,
) -> None:
    from reportlab.lib import colors
    from reportlab.lib.units import cm

    width, height = pagesize
    canvas.setPageSize(pagesize)
    canvas.setStrokeColor(colors.HexColor("#D8DEE5"))
    canvas.setLineWidth(0.5)
    canvas.line(1.1 * cm, height - 1.0 * cm, width - 1.1 * cm, height - 1.0 * cm)
    canvas.setFont(bold_font, 6.8)
    canvas.setFillColor(colors.HexColor(_ORANGE))
    canvas.drawString(1.1 * cm, height - 0.72 * cm, CONFIDENTIALITY_TEXT)
    canvas.setFont(regular_font, 6.8)
    canvas.setFillColor(colors.HexColor(_MID_GREY))
    # En-tête abrégé si nécessaire ; titre intégral sur la couverture.
    from reportlab.pdfbase.pdfmetrics import stringWidth

    label = " ".join(_safe_text(campaign_label).split())
    limit = width - 6.0 * cm

    if stringWidth(label, regular_font, 6.8) > limit:
        while label and stringWidth(label + "…", regular_font, 6.8) > limit:
            label = label[:-1]
        label += "…"

    canvas.drawRightString(
        width - 1.1 * cm,
        height - 0.72 * cm,
        label,
    )
    canvas.line(1.1 * cm, 0.9 * cm, width - 1.1 * cm, 0.9 * cm)
    canvas.drawCentredString(width / 2.0, 0.50 * cm, f"Page {page_number}")


def _draw_section_title(
    canvas,
    title: str,
    *,
    pagesize,
    bold_font: str,
) -> None:
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    from reportlab.pdfbase.pdfmetrics import stringWidth

    width, height = pagesize
    available_width = width - 2.2 * cm
    title_text = iso_text(title)
    font_size = 16.0
    while (
        font_size > 9.0
        and stringWidth(title_text, bold_font, font_size) > available_width
    ):
        font_size -= 0.5
    canvas.setFillColor(colors.HexColor(_DARK_BLUE))
    canvas.setFont(bold_font, font_size)
    canvas.drawString(1.1 * cm, height - 1.75 * cm, title_text)
    canvas.setStrokeColor(colors.HexColor(_ORANGE))
    canvas.setLineWidth(2)
    canvas.line(1.1 * cm, height - 1.95 * cm, min(width - 1.1 * cm, 9.0 * cm), height - 1.95 * cm)

def _draw_analysis_settings(canvas, *, pagesize, sheets, regular_font, bold_font):
    """Affiche uniquement les réglages archivés avec les résultats du calcul."""
    import math
    from reportlab.lib.units import cm

    archived = sheets.get("ARCTA_SETTINGS")
    values = {}
    if isinstance(archived, pd.DataFrame) and {"Parameter", "Value"}.issubset(archived.columns):
        for key, group in archived.groupby("Parameter"):
            if len(group) == 1:
                values[key] = group.iloc[0]["Value"]

    def value(key, *, count=False):
        raw = values.get(key)
        try:
            number = float(raw)
            valid = math.isfinite(number) and not isinstance(raw, bool)
            valid = valid and (number >= 3 and number.is_integer() if count else 0 < number < 1)
            if key == "THR_RATIO_DEFAULT" and number == 0:
                valid = not isinstance(raw, bool)
            if not valid:
                raise ValueError
            return str(int(number)) if count else f"{number * 100:.2f}".rstrip("0").rstrip(".").replace(".", ",") + " %"
        except (TypeError, ValueError, OverflowError):
            return "Non renseigné"

    rows = [
        ("Référence de couple", "Effectif" if values.get("TORQUE_BASIS") == "EFFECTIVE" else "Total",
         "Modèle K&K", "Géométrique" if values.get("KK_MODEL") == "KK_GEOMETRY_1" else "Historique"),
        ("Recalculs : seuil bas de tension / Ymax", value("THR_RATIO_DEFAULT"),
         "Méthode IC moyenne", "Student bilatéral"),
        ("ISO 16269-6 : proportion cible", value("ISO_TOL_P_CONTENT"),
         "ISO 16269-6 : confiance cible", value("ISO_TOL_CONF_LEVEL")),
        ("ISO 16269-6 : IC moyenne", value("MEAN_CI_CONF_LEVEL"),
         "ISO 16269-7 : IC médiane", value("ISO_MEDIAN_CONF_LEVEL")),
        ("Shapiro : seuil de normalité", value("NORMALITY_ALPHA"),
         "Shapiro : effectif minimal", value("NORMALITY_MIN_N", count=True)),
    ]
    width, height = pagesize
    y = height - 8.35 * cm
    _draw_summary_subtitle(canvas, "Paramètres mécaniques et statistiques utilisés",
                          x=1.1 * cm, y=y, bold_font=bold_font)
    table = _summary_table(rows, width=width - 2.2 * cm, regular_font=regular_font,
                           bold_font=bold_font, column_weights=(3.7, 1.2, 3.7, 1.2), font_size=8)
    _, table_height = table.wrap(width - 2.2 * cm, height)
    table.drawOn(canvas, 1.1 * cm, y - 0.2 * cm - table_height)
    canvas.setFont(regular_font, 8)
    canvas.drawString(1.1 * cm, y - table_height - 0.65 * cm,
                      "Tolérance : objectifs demandés ; leur atteinte dépend des données et de la méthode.")
    canvas.drawString(1.1 * cm, y - table_height - 1.05 * cm,
                                            "IC de la moyenne (Student) : niveau indiqué dans le tableau. Valeur non archivée : non renseignée.")
    if values.get("TORQUE_BASIS") == "EFFECTIVE":
        from arcta.selflock_policy import audit_message
        note = audit_message(sheets.get("ARCTA_SELFLOCK_CORRECTION", pd.DataFrame()))
        canvas.drawString(1.1 * cm, y - table_height - 1.45 * cm,
                          note or "Autofrein déduit : médiane DIAG entre A0 - 3 tours et A0 - 1 tour ; pas une consigne outil.")
        return table_height + 1.9 * cm
    return table_height + 1.5 * cm

def _draw_summary_page(
    canvas,
    *,
    pagesize,
    page_number: int,
    campaign_label: str,
    profile: str,
    mode: str,
    constants: Mapping[str, object],
    canonical_config: Mapping[str, object] | None,
    sheets: Mapping[str, pd.DataFrame],
    plot_count: int,
    regular_font: str,
    bold_font: str,
) -> None:
    from reportlab.lib import colors
    from reportlab.lib.units import cm

    width, height = pagesize
    _draw_body_header_footer(
        canvas,
        pagesize=pagesize,
        page_number=page_number,
        campaign_label=campaign_label,
        regular_font=regular_font,
        bold_font=bold_font,
    )
    _draw_section_title(
        canvas,
        "Synthèse de campagne",
        pagesize=pagesize,
        bold_font=bold_font,
    )

    sources = sheets.get("ARCTA_SOURCES", pd.DataFrame())
    decisions = sheets.get("DIAG_REVIEW", pd.DataFrame())
    accepted = 0
    rejected = 0
    if isinstance(decisions, pd.DataFrame) and "Decision" in decisions.columns:
        normalized = decisions["Decision"].astype(str).str.upper()
        accepted = int((normalized == "ACCEPTED").sum())
        rejected = int((normalized == "REJECTED").sum())

    canonical = _canonical_summary_blocks(canonical_config)
    identity = canonical.get("identity", {}) if canonical else {}
    entity_program = " / ".join(
        value
        for value in (
            str(identity.get("entity", "—")),
            str(identity.get("program_id", "—")),
        )
        if value != "—"
    ) or "—"
    date_samples = " / ".join(
        value
        for value in (
            str(identity.get("test_date", "—")),
            (
                f"{identity.get('sample_count')} essais"
                if identity.get("sample_count", "—") != "—"
                else "—"
            ),
        )
        if value != "—"
    ) or "—"
    blocks = (
        (
            "Rapport",
            identity.get("report_number", campaign_label)
            if canonical else campaign_label,
        ),
        ("Entité / programme", entity_program if canonical else profile),
        (
            "Configuration",
            identity.get("configuration_id", "—")
            if canonical else _analysis_label(mode),
        ),
        (
            "Date / échantillons",
            date_samples
            if canonical
            else str(len(sources)) if isinstance(sources, pd.DataFrame) else "0",
        ),
        ("Analyse", f"{_analysis_label(mode)} — {profile}"),
        ("Acceptés / rejetés", f"{accepted} / {rejected}"),
    )
    block_width = (width - 3.3 * cm) / 2.0
    block_height = 1.42 * cm
    for index, (label, value) in enumerate(blocks):
        column = index % 2
        row = index // 2
        x = 1.1 * cm + column * (block_width + 1.1 * cm)
        y = height - 4.0 * cm - row * 1.72 * cm
        canvas.setFillColor(colors.HexColor(_LIGHT_BLUE))
        canvas.roundRect(x, y, block_width, block_height, 5, stroke=0, fill=1)
        canvas.setFillColor(colors.HexColor(_MID_GREY))
        canvas.setFont(bold_font, 7.5)
        canvas.drawString(x + 0.28 * cm, y + 0.92 * cm, label.upper())
        canvas.setFillColor(colors.black)
        canvas.setFont(regular_font, 9.2)
        canvas.drawString(x + 0.28 * cm, y + 0.35 * cm, _safe_text(value))

    # Identifiant complet, commun au manifeste et à DABCTA.
    metadata = sheets.get("ARCTA_RUN_METADATA")
    run_id = "Non renseigné"
    if isinstance(metadata, pd.DataFrame) and len(metadata) == 1 and "Run_ID" in metadata:
        run_id = _safe_text(metadata.iloc[0]["Run_ID"], fallback="Non renseigné")

    x = 1.1 * cm
    y = height - 9.16 * cm
    run_width = width - 2.2 * cm
    canvas.setFillColor(colors.HexColor(_LIGHT_BLUE))
    canvas.roundRect(x, y, run_width, block_height, 5, stroke=0, fill=1)
    canvas.setFillColor(colors.HexColor(_MID_GREY))
    canvas.setFont(bold_font, 7.5)
    canvas.drawString(x + 0.28 * cm, y + 0.92 * cm, "IDENTIFIANT DU RUN ARCTA")
    canvas.setFillColor(colors.black)

    # Affichage intégral sur une ligne, sans troncature.
    from reportlab.pdfbase.pdfmetrics import stringWidth
    font_size = min(
        9.2,
        9.2 * (run_width - 0.56 * cm)
        / max(1.0, stringWidth(run_id, regular_font, 9.2)),
    )
    canvas.setFont(regular_font, font_size)
    canvas.drawString(x + 0.28 * cm, y + 0.35 * cm, run_id)

    # Décalage des paramètres statistiques et des tableaux suivants.
    canvas.saveState()
    canvas.translate(0, -1.72 * cm)
    settings_height = _draw_analysis_settings(
        canvas, pagesize=pagesize, sheets=sheets,
        regular_font=regular_font, bold_font=bold_font,
    )
    canvas.restoreState()
    settings_height += 1.72 * cm
    canvas.saveState()
    canvas.translate(0, -settings_height)

    if canonical:
        _draw_canonical_configuration(
            canvas,
            pagesize=pagesize,
            canonical_config=canonical_config or {},
            start_y=height - 8.55 * cm,
            regular_font=regular_font,
            bold_font=bold_font,
        )
    else:
        canvas.setFillColor(colors.HexColor(_DARK_BLUE))
        canvas.setFont(bold_font, 11)
        canvas.drawString(1.1 * cm, height - 9.25 * cm, "Constantes de calcul")
        y = height - 9.85 * cm
        items = list(constants.items())
        if not items:
            canvas.setFont(regular_font, 8.5)
            canvas.setFillColor(colors.HexColor(_MID_GREY))
            canvas.drawString(1.1 * cm, y, "Aucune constante enregistrée.")
        else:
            for index, (key, value) in enumerate(items[:28]):
                column = index // 14
                row = index % 14
                x = 1.1 * cm + column * 9.45 * cm
                yy = y - row * 0.52 * cm
                canvas.setFont(bold_font, 7.2)
                canvas.setFillColor(colors.HexColor(_MID_GREY))
                canvas.drawString(x, yy, f"{key} :")
                canvas.setFont(regular_font, 7.2)
                canvas.setFillColor(colors.black)
                canvas.drawString(x + 3.3 * cm, yy, _safe_text(value))
    canvas.restoreState()
    canvas.showPage()


def _paragraph(value: object, style):
    from html import escape
    from reportlab.platypus import Paragraph

    return Paragraph(escape(_safe_text(value)), style)


def _draw_dataframe_pages(
    canvas,
    *,
    dataframe: pd.DataFrame,
    columns: Sequence[str],
    title: str,
    campaign_label: str,
    page_number: int,
    pagesize,
    regular_font: str,
    bold_font: str,
    rows_per_page: int = 18,
    font_size: float = 7.1,
) -> tuple[int, list[dict[str, object]]]:
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import Table, TableStyle

    selected = [column for column in columns if column in dataframe.columns]
    if dataframe.empty or not selected:
        return page_number, []

    width, height = pagesize
    available_width = width - 2.2 * cm
    page_rows = max(1, int(rows_per_page))
    inventory: list[dict[str, object]] = []
    header_style = ParagraphStyle(
        "ARCTA-PDF-Header",
        fontName=bold_font,
        fontSize=font_size + 0.3,
        leading=font_size + 1.5,
        textColor=colors.white,
    )
    cell_style = ParagraphStyle(
        "ARCTA-PDF-Cell",
        fontName=regular_font,
        fontSize=font_size,
        leading=font_size + 1.4,
    )
    weights = [1.0] * len(selected)
    for index, column in enumerate(selected):
        if column in {"Source_Name", "Comment", "Review_Comment", "Main_Flags_FR"}:
            weights[index] = 2.1
    if selected == ["Zone", "Explication"]:
        weights = [1.0, 3.8]
    total_weight = sum(weights)
    widths = [available_width * weight / total_weight for weight in weights]

    for start in range(0, len(dataframe), page_rows):
        subset = dataframe.iloc[start:start + page_rows]
        canvas.setPageSize(pagesize)
        _draw_body_header_footer(
            canvas,
            pagesize=pagesize,
            page_number=page_number,
            campaign_label=campaign_label,
            regular_font=regular_font,
            bold_font=bold_font,
        )
        page_title = title if start == 0 else f"{title} — suite"
        _draw_section_title(
            canvas,
            page_title,
            pagesize=pagesize,
            bold_font=bold_font,
        )
        data = [[_paragraph(_column_label(column), header_style) for column in selected]]
        for _, row in subset.iterrows():
            data.append([_paragraph(iso_text(row.get(column)) if column in {"Type", "Relation", "Description_FR", "Definition", "Explication"} else row.get(column), cell_style) for column in selected])
        table = Table(data, colWidths=widths, repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(_DARK_BLUE)),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#CBD3DB")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), (colors.white, colors.HexColor("#F6F8FA"))),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        table.wrapOn(canvas, available_width, height - 4.0 * cm)
        table.drawOn(canvas, 1.1 * cm, height - 2.45 * cm - table._height)
        inventory.append({
            "Page": page_number,
            "Section": "TABLE",
            "Title": page_title,
            "Kind": "DATAFRAME",
        })
        canvas.showPage()
        page_number += 1
    return page_number, inventory


def _draw_polynomial_pages(
    canvas,
    *,
    dataframe: pd.DataFrame,
    columns: Sequence[str],
    campaign_label: str,
    page_number: int,
    pagesize,
    regular_font: str,
    bold_font: str,
    rows_per_page: int = 22,
    settings: pd.DataFrame | None = None,
) -> tuple[int, list[dict[str, object]]]:
    """Une page paysage par type, sans retour à la ligne dans les cellules."""
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    from reportlab.platypus import Table, TableStyle

    selected = [column for column in columns if column in dataframe.columns]
    visible_columns = [column for column in selected if column != "Type"]
    if dataframe.empty or not visible_columns:
        return page_number, []

    if "Type" in dataframe.columns:
        type_values = list(dict.fromkeys(dataframe["Type"].astype(str)))
    else:
        type_values = ["Sélection"]

    width, height = pagesize
    available_width = width - 2.2 * cm
    inventory: list[dict[str, object]] = []
    weight_by_column = {
        "Stat": 2.35,
        "R2": 1.05,
        "N": 0.62,
        "Degree": 0.82,
        "X_min": 1.25,
        "X_max": 1.25,
    }
    weights = [weight_by_column.get(column, 1.08) for column in visible_columns]
    total_weight = sum(weights)
    widths = [available_width * value / total_weight for value in weights]

    for type_value in type_values:
        if "Type" in dataframe.columns:
            typed = dataframe[dataframe["Type"].astype(str) == type_value]
        else:
            typed = dataframe
        for start in range(0, len(typed), max(1, int(rows_per_page))):
            subset = typed.iloc[start:start + max(1, int(rows_per_page))]
            suffix = "" if start == 0 else " - suite"
            title = f"Polynômes statistiques - {type_value}{suffix}"
            canvas.setPageSize(pagesize)
            _draw_body_header_footer(
                canvas,
                pagesize=pagesize,
                page_number=page_number,
                campaign_label=campaign_label,
                regular_font=regular_font,
                bold_font=bold_font,
            )
            _draw_section_title(
                canvas,
                title,
                pagesize=pagesize,
                bold_font=bold_font,
            )
            caption = statistical_caption(subset, settings=settings if settings is not None else pd.DataFrame(), statistics=subset.get("Stat", []))
            canvas.setFont(regular_font, 9)
            from arcta.run_mechanics import caption as mechanical_caption
            mechanical = mechanical_caption({"ARCTA_SETTINGS":settings}) if settings is not None else ""
            caption_lines = ([mechanical] if mechanical else []) + caption.splitlines()
            for index, line in enumerate(caption_lines):
                canvas.drawString(1.1 * cm, height - (2.45 + index * 0.4) * cm, line)
            data = [[_column_label(column) for column in visible_columns]]
            data.extend([
                [_safe_text(row.get(column)) for column in visible_columns]
                for _, row in subset.iterrows()
            ])
            table = Table(data, colWidths=widths, repeatRows=1)
            table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(_DARK_BLUE)),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), bold_font),
                ("FONTNAME", (0, 1), (-1, -1), regular_font),
                ("FONTSIZE", (0, 0), (-1, -1), 6.5),
                ("LEADING", (0, 0), (-1, -1), 7.6),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#CBD3DB")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), (colors.white, colors.HexColor("#F6F8FA"))),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]))
            table.wrapOn(canvas, available_width, height - 4.0 * cm)
            table.drawOn(canvas, 1.1 * cm, height - (2.85 + 0.4 * len(caption_lines)) * cm - table._height)
            inventory.append({
                "Page": page_number,
                "Section": "TABLE",
                "Title": title,
                "Kind": "POLYNOMIAL_TYPE",
            })
            canvas.showPage()
            page_number += 1
    return page_number, inventory


def _compact_table(
    dataframe: pd.DataFrame,
    *,
    columns: Sequence[str],
    available_width: float,
    regular_font: str,
    bold_font: str,
    weights: Mapping[str, float] | None = None,
    font_size: float = 7.1,
):
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Table, TableStyle

    selected = [column for column in columns if column in dataframe.columns]
    if dataframe.empty or not selected:
        return None
    header_style = ParagraphStyle(
        "ARCTA-Compact-Header",
        fontName=bold_font,
        fontSize=font_size,
        leading=font_size + 1.2,
        textColor=colors.white,
    )
    cell_style = ParagraphStyle(
        "ARCTA-Compact-Cell",
        fontName=regular_font,
        fontSize=font_size,
        leading=font_size + 1.2,
    )
    weight_values = [float((weights or {}).get(column, 1.0)) for column in selected]
    total_weight = sum(weight_values)
    widths = [available_width * value / total_weight for value in weight_values]
    data = [[_paragraph(_column_label(column), header_style) for column in selected]]
    for _, row in dataframe.iterrows():
        data.append([_paragraph(iso_text(row.get(column)) if column in {"Type", "Relation", "Description_FR", "Definition", "Explication"} else row.get(column), cell_style) for column in selected])
    table = Table(data, colWidths=widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(_DARK_BLUE)),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#CBD3DB")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), (colors.white, colors.HexColor("#F6F8FA"))),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
    ]))
    return table


def _draw_stacked_tables_pages(
    canvas,
    *,
    title: str,
    blocks: Sequence[tuple[str, pd.DataFrame, Sequence[str], Mapping[str, float]]],
    campaign_label: str,
    page_number: int,
    pagesize,
    regular_font: str,
    bold_font: str,
    font_size: float = 7.1,
) -> tuple[int, list[dict[str, object]]]:
    from reportlab.lib import colors
    from reportlab.lib.units import cm

    visible = [block for block in blocks if isinstance(block[1], pd.DataFrame) and not block[1].empty]
    if not visible:
        return page_number, []
    width, height = pagesize
    left = 1.1 * cm
    available_width = width - 2.2 * cm
    bottom_y = 1.45 * cm
    subtitle_gap = 0.28 * cm
    block_gap = 0.52 * cm
    inventory: list[dict[str, object]] = []
    page_open = False
    page_has_content = False
    top_y = 0.0
    current_title = title

    def start_page() -> None:
        nonlocal page_open, page_has_content, top_y, current_title
        canvas.setPageSize(pagesize)
        _draw_body_header_footer(
            canvas,
            pagesize=pagesize,
            page_number=page_number + len(inventory),
            campaign_label=campaign_label,
            regular_font=regular_font,
            bold_font=bold_font,
        )
        current_title = title if not inventory else f"{title} - suite"
        _draw_section_title(
            canvas,
            current_title,
            pagesize=pagesize,
            bold_font=bold_font,
        )
        top_y = height - 2.55 * cm
        page_open = True
        page_has_content = False

    def finish_page() -> None:
        nonlocal page_open, page_has_content
        if not page_open:
            return
        inventory.append({
            "Page": page_number + len(inventory),
            "Section": "TABLE",
            "Title": current_title,
            "Kind": "DATAFRAME_GROUP",
        })
        canvas.showPage()
        page_open = False
        page_has_content = False

    def make_table(
        dataframe: pd.DataFrame,
        columns: Sequence[str],
        weights: Mapping[str, float],
    ):
        table = _compact_table(
            dataframe,
            columns=columns,
            available_width=available_width,
            regular_font=regular_font,
            bold_font=bold_font,
            weights=weights,
            font_size=font_size,
        )
        if table is None:
            return None, 0.0
        _wrapped_width, table_height = table.wrap(
            available_width,
            max(1.0, height),
        )
        return table, float(table_height)

    for subtitle, dataframe, columns, weights in visible:
        start = 0
        total_rows = len(dataframe)
        while start < total_rows:
            if not page_open:
                start_page()

            available_height = top_y - subtitle_gap - bottom_y
            remaining = dataframe.iloc[start:]
            full_table, full_height = make_table(
                remaining,
                columns,
                weights,
            )

            # Si le bloc complet tient sur une page neuve mais plus dans
            # l'espace résiduel, on le bascule entièrement à la page suivante
            # plutôt que d'isoler quelques lignes sous le bloc précédent.
            fresh_height = (
                height - 2.55 * cm - subtitle_gap - bottom_y
            )
            if (
                page_has_content
                and full_table is not None
                and full_height <= fresh_height
                and full_height > available_height
            ):
                finish_page()
                continue

            if full_table is not None and full_height <= available_height:
                row_count = len(remaining)
                table = full_table
                table_height = full_height
            else:
                low = 1
                high = len(remaining)
                best_count = 0
                best_table = None
                best_height = 0.0
                while low <= high:
                    middle = (low + high) // 2
                    candidate, candidate_height = make_table(
                        remaining.iloc[:middle],
                        columns,
                        weights,
                    )
                    if (
                        candidate is not None
                        and candidate_height <= available_height
                    ):
                        best_count = middle
                        best_table = candidate
                        best_height = candidate_height
                        low = middle + 1
                    else:
                        high = middle - 1
                if best_count == 0:
                    if page_has_content:
                        finish_page()
                        continue
                    raise CampaignPdfError(
                        f"Le tableau {subtitle!r} ne tient pas sur une page."
                    )
                row_count = best_count
                table = best_table
                table_height = best_height

            continued = start > 0
            visible_subtitle = (
                f"{subtitle} - suite" if continued else subtitle
            )
            canvas.setFillColor(colors.HexColor(_DARK_BLUE))
            canvas.setFont(bold_font, 10)
            canvas.drawString(left, top_y, visible_subtitle)
            top_y -= subtitle_gap
            table.drawOn(canvas, left, top_y - table_height)
            top_y -= table_height + block_gap
            start += row_count
            page_has_content = True

            if start < total_rows:
                finish_page()

    finish_page()
    return page_number + len(inventory), inventory


def _draw_plot_page(
    canvas,
    *,
    plot_path: Path,
    title: str,
    category: str,
    campaign_label: str,
    page_number: int,
    pagesize,
    regular_font: str,
    bold_font: str,
) -> None:
    from reportlab.lib import colors
    from reportlab.lib.units import cm

    width, height = pagesize
    canvas.setPageSize(pagesize)
    _draw_body_header_footer(
        canvas,
        pagesize=pagesize,
        page_number=page_number,
        campaign_label=campaign_label,
        regular_font=regular_font,
        bold_font=bold_font,
    )
    _draw_section_title(
        canvas,
        textwrap.shorten(str(title), width=105, placeholder="…"),
        pagesize=pagesize,
        bold_font=bold_font,
    )
    canvas.setFillColor(colors.HexColor(_MID_GREY))
    canvas.setFont(regular_font, 7.5)
    canvas.drawString(1.1 * cm, height - 2.35 * cm, _safe_text(category))
    _draw_image_fit(
        canvas,
        plot_path,
        1.0 * cm,
        1.25 * cm,
        width - 2.0 * cm,
        height - 4.05 * cm,
    )
    canvas.showPage()


def _draw_diag_principle_page(
    canvas,
    *,
    campaign_label: str,
    page_number: int,
    pagesize,
    regular_font: str,
    bold_font: str,
) -> None:
    """Insère la figure explicative commune à l'interface et au PDF."""
    from reportlab.lib import colors
    from reportlab.lib.units import cm

    image_path = (
        Path(__file__).resolve().parents[3]
        / "apps" / "arcta_web" / "static" / DIAG_PRINCIPLE_FILENAME
    )
    if not image_path.is_file():
        raise CampaignPdfResourceError(
            "Figure de principe DIAG absente : "
            f"{image_path}"
        )

    width, height = pagesize
    canvas.setPageSize(pagesize)
    _draw_body_header_footer(
        canvas,
        pagesize=pagesize,
        page_number=page_number,
        campaign_label=campaign_label,
        regular_font=regular_font,
        bold_font=bold_font,
    )
    _draw_section_title(
        canvas,
        "Principe physique du DIAG",
        pagesize=pagesize,
        bold_font=bold_font,
    )
    canvas.setFillColor(colors.HexColor(_MID_GREY))
    canvas.setFont(regular_font, 7.8)
    canvas.drawString(
        1.1 * cm,
        height - 2.35 * cm,
        "Figure de principe — correspondance ISO : Y → F ; Xg → T ; Xt → T_th ; Xh → T_b ; A → Θ.",
    )
    _draw_image_fit(
        canvas,
        image_path,
        0.8 * cm,
        1.15 * cm,
        width - 1.6 * cm,
        height - 3.75 * cm,
    )
    canvas.showPage()


_PLOT_GROUP_TITLES = {
    "CORE_CURVES": "Essais - Expérimental, recalculé et écarts à la moyenne",
    "ANGLE_CURVES": "Courbes des essais en fonction de l’angle recalé",
    "OVERLAY_TORQUE_TENSION": "Overlays couple / tension",
    "OVERLAY_ANGLE": "Overlays en fonction de l’angle recalé",
    "FRICTION_MUG": "Coefficient de frottement global µ_tot",
    "FRICTION_MUH": "Coefficient de frottement à l’appui µ_b",
    "FRICTION_MUT": "Coefficient de frottement du filetage µ_th",
    "DIAG_BOXPLOTS_SHORT_REPORT": (
        "Synthèse DIAG et décisions par essai"
    ),
    "DIAG_BOXPLOTS_SHORT": "Boîtes à moustaches DIAG décisionnelles",
    "DIAG_BOXPLOTS_FULL": "Boîtes à moustaches DIAG complètes",
    "SELF_LOCK": "SelfLock / autofrein issu du DIAG pré-A0",
    "COMPUTE_OTHER": "Courbes recalculées complémentaires",
}


def _group_layout(
    count: int,
    width: float,
    height: float,
    cm,
    *,
    arrangement: str = "auto",
) -> list[tuple[float, float, float, float]]:
    left = 0.8 * cm
    right = 0.8 * cm
    bottom = 1.15 * cm
    top = 2.30 * cm
    gap = 0.35 * cm
    usable_w = width - left - right
    usable_h = height - top - bottom
    if count <= 1:
        return [(left, bottom, usable_w, usable_h)]
    if arrangement == "vertical":
        cell_h = (usable_h - gap) / count
        return [
            (left, bottom + (count - index - 1) * (cell_h + gap), usable_w, cell_h)
            for index in range(count)
        ]
    if count == 2:
        cell_w = (usable_w - gap) / 2.0
        return [
            (left, bottom, cell_w, usable_h),
            (left + cell_w + gap, bottom, cell_w, usable_h),
        ]
    if count == 3:
        half_h = (usable_h - gap) / 2.0
        cell_w = (usable_w - gap) / 2.0
        return [
            (left, bottom + half_h + gap, usable_w, half_h),
            (left, bottom, cell_w, half_h),
            (left + cell_w + gap, bottom, cell_w, half_h),
        ]
    if count == 5:
        top_h = usable_h * 0.43
        bottom_h = (usable_h - top_h - 2.0 * gap) / 2.0
        cell_w = (usable_w - gap) / 2.0
        return [
            (left, bottom + 2.0 * bottom_h + 2.0 * gap, usable_w, top_h),
            (left, bottom + bottom_h + gap, cell_w, bottom_h),
            (left + cell_w + gap, bottom + bottom_h + gap, cell_w, bottom_h),
            (left, bottom, cell_w, bottom_h),
            (left + cell_w + gap, bottom, cell_w, bottom_h),
        ]
    half_h = (usable_h - gap) / 2.0
    cell_w = (usable_w - gap) / 2.0
    return [
        (left, bottom + half_h + gap, cell_w, half_h),
        (left + cell_w + gap, bottom + half_h + gap, cell_w, half_h),
        (left, bottom, cell_w, half_h),
        (left + cell_w + gap, bottom, cell_w, half_h),
    ][:count]


def _draw_plot_group_page(
    canvas,
    *,
    plots: Sequence[tuple[Path, Mapping[str, object]]],
    group: str,
    campaign_label: str,
    page_number: int,
    pagesize,
    regular_font: str,
    bold_font: str,
    title_override: str | None = None,
    arrangement: str = "auto",
) -> None:
    from reportlab.lib import colors
    from reportlab.lib.units import cm

    width, height = pagesize
    _draw_body_header_footer(
        canvas,
        pagesize=pagesize,
        page_number=page_number,
        campaign_label=campaign_label,
        regular_font=regular_font,
        bold_font=bold_font,
    )
    title = title_override or _PLOT_GROUP_TITLES.get(
        group, str(group).replace("_", " ").title()
    )
    _draw_section_title(canvas, title, pagesize=pagesize, bold_font=bold_font)
    for (plot_path, item), (x, y, cell_w, cell_h) in zip(
        plots,
        _group_layout(
            len(plots), width, height, cm, arrangement=arrangement
        ),
    ):
        caption_h = 0.52 * cm
        canvas.setFillColor(colors.HexColor(_MID_GREY))
        canvas.setFont(regular_font, 8.0 if len(plots) >= 4 else 9.0)
        canvas.drawString(
            x + 0.05 * cm,
            y + cell_h - 0.28 * cm,
            textwrap.shorten(
                _safe_text(item.get("title"), fallback=plot_path.stem),
                width=68 if len(plots) >= 4 else 96,
                placeholder="…",
            ),
        )
        _draw_image_fit(
            canvas,
            plot_path,
            x,
            y,
            cell_w,
            max(0.5 * cm, cell_h - caption_h),
        )
    canvas.showPage()


def _plot_groups(
    plots: Sequence[tuple[Path, Mapping[str, object]]],
) -> list[tuple[str, list[tuple[Path, Mapping[str, object]]]]]:
    grouped: dict[str, list[tuple[Path, Mapping[str, object]]]] = {}
    order: list[str] = []
    for path, item in plots:
        group = str(item.get("page_group") or item.get("category") or "GRAPHICS")
        if group not in grouped:
            grouped[group] = []
            order.append(group)
        grouped[group].append((path, item))
    output = []
    for group in order:
        items = sorted(
            grouped[group],
            key=lambda value: int(value[1].get("sort_order", 999)),
        )
        output.append((group, items))
    return output


def _draw_self_lock_page(
    canvas,
    *,
    plot: tuple[Path, Mapping[str, object]] | None,
    summary: pd.DataFrame,
    detail: pd.DataFrame,
    campaign_label: str,
    page_number: int,
    pagesize,
    regular_font: str,
    bold_font: str,
) -> dict[str, object] | None:
    from reportlab.lib import colors
    from reportlab.lib.units import cm

    if plot is None and summary.empty and detail.empty:
        return None
    width, height = pagesize
    canvas.setPageSize(pagesize)
    _draw_body_header_footer(
        canvas,
        pagesize=pagesize,
        page_number=page_number,
        campaign_label=campaign_label,
        regular_font=regular_font,
        bold_font=bold_font,
    )
    title = "SelfLock / autofrein - évaluation DIAG pré-A0"
    _draw_section_title(canvas, title, pagesize=pagesize, bold_font=bold_font)

    if plot is not None:
        _draw_image_fit(
            canvas,
            plot[0],
            1.0 * cm,
            height - 11.1 * cm,
            9.4 * cm,
            8.35 * cm,
        )

    if not summary.empty:
        first = summary.iloc[0]
        indicators = (
            ("Effectif N", "N"),
            ("Moyenne (N·m)", "Mean_Nm"),
            ("Médiane (N·m)", "Median_Nm"),
            ("Écart-type (N·m)", "Std_Nm"),
            ("Q1 (N·m)", "Q1_Nm"),
            ("Q3 (N·m)", "Q3_Nm"),
            ("Minimum (N·m)", "Min_Nm"),
            ("Maximum (N·m)", "Max_Nm"),
        )
        summary_long = pd.DataFrame([
            {"Indicator": label, "Value": first.get(column)}
            for label, column in indicators
            if column in summary.columns
        ])
        canvas.setFillColor(colors.HexColor(_DARK_BLUE))
        canvas.setFont(bold_font, 10)
        canvas.drawString(10.8 * cm, height - 2.85 * cm, "Synthèse statistique")
        table = _compact_table(
            summary_long,
            columns=("Indicator", "Value"),
            available_width=9.15 * cm,
            regular_font=regular_font,
            bold_font=bold_font,
            weights={"Indicator": 1.8, "Value": 1.0},
            font_size=7.4,
        )
        if table is not None:
            _w, table_height = table.wrap(9.15 * cm, 8.0 * cm)
            table.drawOn(canvas, 10.8 * cm, height - 3.15 * cm - table_height)

    if not detail.empty:
        canvas.setFillColor(colors.HexColor(_DARK_BLUE))
        canvas.setFont(bold_font, 10)
        canvas.drawString(1.1 * cm, height - 11.55 * cm, "Détail par essai")
        table = _compact_table(
            detail,
            columns=(
                "Trial_ID", "Source_Name", "Autofrein_Xg_preA0_med",
                "Autofrein_Xg_preA0_mean", "Autofrein_Xg_preA0_std",
                "Autofrein_Xg_preA0_MAD",
            ),
            available_width=width - 2.2 * cm,
            regular_font=regular_font,
            bold_font=bold_font,
            weights={
                "Trial_ID": 0.65,
                "Source_Name": 2.3,
                "Autofrein_Xg_preA0_med": 1.0,
                "Autofrein_Xg_preA0_mean": 1.0,
                "Autofrein_Xg_preA0_std": 0.85,
                "Autofrein_Xg_preA0_MAD": 0.75,
            },
            font_size=7.0,
        )
        if table is not None:
            _w, table_height = table.wrap(width - 2.2 * cm, height - 13.0 * cm)
            table.drawOn(canvas, 1.1 * cm, height - 11.85 * cm - table_height)
    canvas.showPage()
    return {
        "Page": page_number,
        "Section": "SELF_LOCK",
        "Title": title,
        "Kind": "GRAPH_AND_TABLES",
    }


def _polyfits_for_report(
    dataframe: pd.DataFrame,
    report_options: Mapping[str, object],
) -> tuple[pd.DataFrame, tuple[str, ...]]:
    if not isinstance(dataframe, pd.DataFrame) or dataframe.empty:
        return pd.DataFrame(), ()
    selected_types = {
        str(value).strip().replace("μ", "µ")
        for value in report_options.get("poly_types", ())
    }
    selected_stats = {
        str(value).strip().upper()
        for value in report_options.get("poly_stats", ())
    }
    output = dataframe.copy()
    if "Type" in output.columns:
        output = output[
            output["Type"].astype(str).str.replace("μ", "µ").isin(selected_types)
        ]
    if "Stat" in output.columns:
        output = output[output["Stat"].astype(str).str.upper().isin(selected_stats)]
    base_columns = ("Type", "Stat", "R2", "N", "Degree", "X_min", "X_max")
    if str(report_options.get("poly_columns_mode", "complete")) == "complete":
        columns = (
            "Type", "Stat", "R2", "N", "Degree",
            "coeff0", "coeff1", "coeff2", "coeff3", "coeff4", "coeff5", "coeff6",
            "X_min", "X_max",
        )
    else:
        columns = base_columns
    return output, tuple(column for column in columns if column in output.columns)


def _plot_items(
    session_root: Path,
    artifacts: Sequence[Mapping[str, object]],
) -> list[tuple[Path, Mapping[str, object]]]:
    root = session_root.resolve()
    output: list[tuple[Path, Mapping[str, object]]] = []
    for item in artifacts:
        if not str(item.get("kind", "")).upper().startswith("PNG_"):
            continue
        relative = Path(str(item.get("relative_path", "")))
        candidate = (root / relative).resolve()
        if root not in candidate.parents or not candidate.is_file():
            raise CampaignPdfError(
                f"Graphe PDF absent ou hors session : {relative.as_posix()}"
            )
        output.append((candidate, item))
    return output


def generate_campaign_pdf(
    *,
    output_path: str | Path,
    session_root: str | Path,
    sheets: Mapping[str, pd.DataFrame],
    plot_artifacts: Sequence[Mapping[str, object]],
    campaign_label: str,
    profile: str,
    mode: str,
    constants: Mapping[str, Any],
    canonical_config: Mapping[str, object] | None = None,
    resources_dir: str | Path | None = None,
    report_options: Mapping[str, object] | None = None,
) -> CampaignPdfResult:
    """Compose le rapport PDF Web depuis les mêmes feuilles et PNG que le XLSX."""
    try:
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.pdfgen import canvas as reportlab_canvas
    except ImportError as exc:
        raise CampaignPdfError(
            "La génération PDF nécessite le paquet Python 'reportlab'."
        ) from exc

    root, artwork, logo = require_pdf_resources(resources_dir)
    options = normalize_report_options(
        report_options,
        fallback_title=campaign_label,
    )
    report_title = _safe_text(
        options.get("report_title"),
        fallback=campaign_label,
    )
    regular_font, bold_font = _register_fonts()
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    plots = _plot_items(Path(session_root), plot_artifacts)
    selected_graphs = {str(value) for value in options.get("graph_keys", ())}
    plots = [
        (path, item)
        for path, item in plots
        if not item.get("report_key")
        or str(item.get("report_key")) in selected_graphs
    ]
    inventory: list[dict[str, object]] = [{
        "Page": 1,
        "Section": "COVER",
        "Title": report_title,
        "Kind": "COVER",
    }]

    canvas = reportlab_canvas.Canvas(
        str(target),
        pagesize=A4,
        pageCompression=1,
    )
    canvas.setTitle(report_title)
    canvas.setAuthor("ARCTA Web")
    canvas.setSubject("Essais couple tension et exploitation statistique ISO 16269")
    try:
        from arcta.run_mechanics import caption
        _draw_cover(
            canvas,
            pagesize=A4,
            artwork=artwork,
            logo=logo,
            campaign_label=report_title,
            mechanical_label=caption(sheets),
            mode=mode,
            regular_font=regular_font,
            bold_font=bold_font,
        )
        page_number = 2
        if bool(options.get("include_summary", True)):
            _draw_summary_page(
                canvas,
                pagesize=A4,
                page_number=page_number,
                campaign_label=report_title,
                profile=profile,
                mode=mode,
                constants=constants,
                canonical_config=canonical_config,
                sheets=sheets,
                plot_count=len(plots),
                regular_font=regular_font,
                bold_font=bold_font,
            )
            inventory.append({
                "Page": page_number,
                "Section": "SUMMARY",
                "Title": "Synthèse de campagne",
                "Kind": "SUMMARY",
            })
            page_number += 1

        consumed: set[tuple[str, str]] = set()

        def plot_token(value: tuple[Path, Mapping[str, object]]) -> tuple[str, str]:
            path, item = value
            return str(path), str(item.get("kind", "PNG"))

        def select_plots(
            *,
            keys: Sequence[str] = (),
            groups: Sequence[str] = (),
            exclude_keys: Sequence[str] = (),
        ) -> list[tuple[Path, Mapping[str, object]]]:
            key_order = {key: index for index, key in enumerate(keys)}
            output = []
            for value in plots:
                _path, item = value
                key = str(item.get("report_key", ""))
                group = str(item.get("page_group", ""))
                if keys and key not in key_order:
                    continue
                if groups and group not in groups:
                    continue
                if key in exclude_keys:
                    continue
                output.append(value)
            output.sort(key=lambda value: (
                key_order.get(str(value[1].get("report_key", "")), 999),
                int(value[1].get("sort_order", 999)),
            ))
            consumed.update(plot_token(value) for value in output)
            return output

        def emit_plot_page(
            selected: Sequence[tuple[Path, Mapping[str, object]]],
            *,
            group: str,
            title: str,
            pagesize,
            arrangement: str = "auto",
        ) -> None:
            nonlocal page_number
            if not selected:
                return
            _draw_plot_group_page(
                canvas,
                plots=selected,
                group=group,
                campaign_label=report_title,
                page_number=page_number,
                pagesize=pagesize,
                regular_font=regular_font,
                bold_font=bold_font,
                title_override=title,
                arrangement=arrangement,
            )
            inventory.append({
                "Page": page_number,
                "Section": "GRAPHICS",
                "Title": title,
                "Kind": ";".join(
                    str(item.get("kind", "PNG")) for _path, item in selected
                ),
            })
            page_number += 1

        # Page 3 standard : deux vues expérimentales en portrait.
        experimental = select_plots(
            keys=("exp_yfxg", "exp_yfa"),
            groups=("CORE_CURVES", "ANGLE_CURVES"),
        )
        emit_plot_page(
            experimental,
            group="EXPERIMENTAL_OVERVIEW",
            title="Données expérimentales — couples corrigés" if "CONCAT_EFFECTIVE" in sheets else "Données expérimentales",
            pagesize=A4,
            arrangement="vertical",
        )


        # La lecture physique du DIAG précède ses indicateurs décisionnels.
        # La même image statique est affichée dans l'interface Web afin de
        # conserver une définition unique du schéma de principe.
        if bool(options.get("include_diag_principle", True)):
            _draw_diag_principle_page(
                canvas,
                campaign_label=report_title,
                page_number=page_number,
                pagesize=landscape(A4),
                regular_font=regular_font,
                bold_font=bold_font,
            )
            inventory.append({
                "Page": page_number,
                "Section": "DIAG_PRINCIPLE",
                "Title": "Principe physique du DIAG",
                "Kind": "DIAG_PRINCIPLE",
            })
            page_number += 1

        # Page 4 standard : les 12 indicateurs des trois premières planches
        # DIAG sont regroupés sur une page paysage. Les planches historiques
        # de 4 indicateurs restent exportées en PNG mais ne sont pas répétées
        # dans le PDF.
        diag_boxplot_report = select_plots(
            groups=("DIAG_BOXPLOTS_SHORT_REPORT",),
        )
        diag_boxplot_pages = select_plots(
            groups=("DIAG_BOXPLOTS_SHORT",),
        )
        if diag_boxplot_report:
            emit_plot_page(
                diag_boxplot_report[:1],
                group="DIAG_BOXPLOTS_SHORT_REPORT",
                title="Synthèse DIAG et décisions par essai",
                pagesize=landscape(A4),
            )
        elif diag_boxplot_pages:
            # Compatibilité avec un run produit avant l'introduction de la
            # planche compacte : les trois premières planches restent
            # intégrables sans faire réapparaître les suivantes.
            emit_plot_page(
                diag_boxplot_pages[:3],
                group="DIAG_BOXPLOTS_SHORT",
                title="Synthèse DIAG et décisions par essai",
                pagesize=landscape(A4),
            )

        # Page 5 standard : synthèse DIAG et décisions sur une seule page.
        decisions = sheets.get("DIAG_REVIEW")
        synthesis = sheets.get("DIAG_SYNTHESIS")
        if not isinstance(synthesis, pd.DataFrame) or synthesis.empty:
            synthesis = sheets.get("DIAG_SUMMARY")
        diag_blocks = []
        if bool(options.get("include_diag_summary", True)) and isinstance(synthesis, pd.DataFrame):
            diag_blocks.append((
                "Synthèse DIAG",
                synthesis,
                (
                    "Trial_ID", "Status", "Ymax", "K_YA_20_50",
                    "DeadTravel_DeltaA_deg",
                    "Residual_Thread_Torque_Median_Nm",
                    "Residual_Torsional_Stress_Nominal_MPa",
                    "ISO16269_4_Max_Severity",
                ),
                {
                    "Trial_ID": 0.7, "Status": 0.7, "Ymax": 1.0,
                    "K_YA_20_50": 0.9, "DeadTravel_DeltaA_deg": 0.9,
                    "Residual_Thread_Torque_Median_Nm": 1.0,
                    "Residual_Torsional_Stress_Nominal_MPa": 1.0,
                    "ISO16269_4_Max_Severity": 1.0,
                },
            ))
        if bool(options.get("include_decisions", True)) and isinstance(decisions, pd.DataFrame):
            diag_blocks.append((
                "Décisions par essai",
                decisions,
                ("Trial_ID", "Score_Comportement_Global", "Score_Comparatif_Population", "Decision", "Comment"),
                {"Trial_ID": 0.7, "Score_Comportement_Global": 1.1,
                 "Score_Comparatif_Population": 1.1, "Decision": 1.35, "Comment": 2.2},
            ))
        page_number, diag_pages = _draw_stacked_tables_pages(
            canvas,
            title="Synthèse DIAG et décisions par essai",
            blocks=diag_blocks,
            campaign_label=report_title,
            page_number=page_number,
            pagesize=A4,
            regular_font=regular_font,
            bold_font=bold_font,
            font_size=6.9,
        )
        inventory.extend(diag_pages)

        # Page 5 standard : expérimental, recalculs et écarts graphiques.
        core = select_plots(
            keys=(
                "exp_yfxg", "compute_yfxg", "compute_xgfy",
                "nrmse_yfxg", "nrmse_xgfy",
            ),
            groups=("CORE_CURVES",),
        )
        emit_plot_page(
            core,
            group="CORE_CURVES",
            title="Expérimental, recalculs et écarts à la moyenne",
            pagesize=A4,
        )

        # Page 6 standard : synthèse et détail nRMSE en portrait.
        if bool(options.get("include_curve_deviation_summary", True)):
            deviation_summary = sheets.get("ARCTA_CURVE_DEVIATION_SUMMARY")
            deviations = sheets.get("ARCTA_CURVE_DEVIATIONS")
            deviation_blocks = []
            if isinstance(deviation_summary, pd.DataFrame):
                deviation_blocks.append((
                    "Écart des courbes recalculées aux courbes moyennes",
                    deviation_summary,
                    (
                        "Relation", "N", "Mean_nRMSE_Percent",
                        "Median_nRMSE_Percent", "Max_nRMSE_Percent",
                        "Count_Within_1pct", "Count_Within_2_5pct",
                        "Count_Within_5pct", "Count_Within_10pct",
                        "Count_Above_10pct",
                    ),
                    {"Relation": 0.8, "N": 0.5},
                ))
            if isinstance(deviations, pd.DataFrame):
                deviation_blocks.append((
                    "Écarts aux moyennes par essai",
                    deviations,
                    (
                        "Relation", "Trial_ID", "nRMSE_Percent",
                        "Threshold_Class", "Within_2_5pct",
                        "Within_5pct", "Within_10pct",
                    ),
                    {"Relation": 0.8, "Trial_ID": 0.7, "Threshold_Class": 1.2},
                ))
            page_number, deviation_pages = _draw_stacked_tables_pages(
                canvas,
                title="Écarts aux courbes moyennes",
                blocks=deviation_blocks,
                campaign_label=report_title,
                page_number=page_number,
                pagesize=A4,
                regular_font=regular_font,
                bold_font=bold_font,
                font_size=6.7,
            )
            inventory.extend(deviation_pages)

        # Page 7 puis pages 8 à 12 standard : angle, frottements et overlays.
        angle_plots = select_plots(
            keys=("exp_yfa", "exp_xgfa", "overlay_yfa", "overlay_xgfa"),
            groups=("ANGLE_CURVES",),
        )
        emit_plot_page(
            angle_plots,
            group="ANGLE_CURVES",
            title="Courbes des essais en fonction de l’angle recalé",
            pagesize=landscape(A4),
        )
        for group, title in (
            ("FRICTION_MUG", "Coefficient de frottement global µ_tot"),
            ("FRICTION_MUH", "Coefficient de frottement à l’appui µ_b"),
            ("FRICTION_MUT", "Coefficient de frottement du filetage µ_th"),
        ):
            emit_plot_page(
                select_plots(groups=(group,)),
                group=group,
                title=title,
                pagesize=landscape(A4),
            )
        emit_plot_page(
            select_plots(groups=("OVERLAY_TORQUE_TENSION",)),
            group="OVERLAY_TORQUE_TENSION",
            title="Overlays couple / tension",
            pagesize=A4,
            arrangement="vertical",
        )
        emit_plot_page(
            select_plots(groups=("OVERLAY_ANGLE",)),
            group="OVERLAY_ANGLE",
            title="Overlays en fonction de l’angle recalé",
            pagesize=A4,
            arrangement="vertical",
        )

        # Réservation de SelfLock : cette section doit rester la dernière.
        self_lock_plots = select_plots(groups=("SELF_LOCK",))

        # Pages graphiques optionnelles non couvertes par la maquette standard.
        remaining = [value for value in plots if plot_token(value) not in consumed]
        for group, grouped_plots in _plot_groups(remaining):
            for offset in range(0, len(grouped_plots), 4):
                emit_plot_page(
                    grouped_plots[offset:offset + 4],
                    group=group,
                    title=_PLOT_GROUP_TITLES.get(group, group),
                    pagesize=landscape(A4),
                )

        # Les polynômes restent optionnels et précèdent toujours SelfLock.
        if bool(options.get("include_polynomial_tables", True)):
            polyfits, poly_columns = _polyfits_for_report(
                sheets.get("POLY_FITS_STATS", pd.DataFrame()),
                options,
            )
            if not polyfits.empty and poly_columns:
                page_number, pages = _draw_polynomial_pages(
                    canvas,
                    dataframe=polyfits,
                    columns=poly_columns,
                    campaign_label=report_title,
                    page_number=page_number,
                    pagesize=landscape(A4),
                    regular_font=regular_font,
                    bold_font=bold_font,
                    rows_per_page=22,
                    settings=sheets.get("ARCTA_SETTINGS", pd.DataFrame()),
                )
                inventory.extend(pages)

        # 63F0: absence de bornes explicite, même si les overlays sont décochés.
        warning_rows = pdf_explanations(sheets)
        if not warning_rows.empty:
            page_number, pages = _draw_dataframe_pages(
                canvas, dataframe=warning_rows, columns=list(warning_rows.columns),
                title="Tolérance : objectif non atteint ou calcul indisponible",
                campaign_label=report_title, page_number=page_number,
                pagesize=A4, regular_font=regular_font, bold_font=bold_font,
                rows_per_page=3, font_size=9.0,
            )
            inventory.extend(pages)

        # SelfLock est volontairement la dernière page du rapport.
        self_lock_stats = sheets.get("ARCTA_SELF_LOCK_STATS", pd.DataFrame())
        self_lock_detail = sheets.get("ARCTA_SELF_LOCK", pd.DataFrame())
        if not bool(options.get("include_self_lock_summary", True)):
            self_lock_stats = pd.DataFrame()
            self_lock_detail = pd.DataFrame()
        self_lock_page = _draw_self_lock_page(
            canvas,
            plot=self_lock_plots[0] if self_lock_plots else None,
            summary=self_lock_stats if isinstance(self_lock_stats, pd.DataFrame) else pd.DataFrame(),
            detail=self_lock_detail if isinstance(self_lock_detail, pd.DataFrame) else pd.DataFrame(),
            campaign_label=report_title,
            page_number=page_number,
            pagesize=A4,
            regular_font=regular_font,
            bold_font=bold_font,
        )
        if self_lock_page is not None:
            inventory.append(self_lock_page)
            page_number += 1
        canvas.save()
    except Exception:
        try:
            canvas.save()
        except Exception:
            pass
        target.unlink(missing_ok=True)
        raise

    if not target.is_file() or target.stat().st_size == 0:
        raise CampaignPdfError("Le rapport PDF n'a pas été créé ou est vide.")
    return CampaignPdfResult(
        output_path=target,
        page_count=len(inventory),
        inventory=tuple(inventory),
        resources_dir=root,
    )
