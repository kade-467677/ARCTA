"""Options de rapport indépendantes de la couche Web."""

from __future__ import annotations
from arcta.notation import iso_text, LABELS, nomenclature_rows

import re
import unicodedata
from collections.abc import Mapping, Sequence


REPORT_OPTIONS_SCHEMA_VERSION = "1.0"
REPORT_PRESET_SYNTHETIC = "SYNTHETIC"
REPORT_PRESET_COMPLETE = "COMPLETE"
REPORT_PRESET_CUSTOM = "CUSTOM"
REPORT_PRESETS = frozenset({
    REPORT_PRESET_SYNTHETIC,
    REPORT_PRESET_COMPLETE,
    REPORT_PRESET_CUSTOM,
})

REPORT_GRAPH_OPTIONS = (
    ("exp_yfxg", "Essais expérimentaux Y=f(Xg)"),
    ("exp_yfa", "Essais expérimentaux Y=f(A_eff)"),
    ("exp_xgfa", "Essais expérimentaux Xg=f(A_eff)"),
    ("compute_yfxg", "Courbes recalculées Y=f(Xg)"),
    ("compute_xgfy", "Courbes recalculées Xg=f(Y)"),
    ("nrmse_yfxg", "Écart à la moyenne Y=f(Xg)"),
    ("nrmse_xgfy", "Écart à la moyenne Xg=f(Y)"),
    ("overlay_yfxg", "Overlay Y=f(Xg)"),
    ("overlay_xgfy", "Overlay Xg=f(Y) affiché en Y=f(Xg)"),
    ("overlay_yfa", "Overlay Y=f(A_eff)"),
    ("overlay_xgfa", "Overlay Xg=f(A_eff)"),
    ("friction_mug", "Coefficient de frottement global µg"),
    ("friction_muh", "Coefficient de frottement sous-tête µh"),
    ("friction_mut", "Coefficient de frottement filet µt"),
    (
        "diag_boxplots_short",
        "12 boîtes à moustaches DIAG — synthèse courte (3 planches)",
    ),
    ("diag_boxplots_full", "Boîtes à moustaches DIAG complètes"),
    ("self_lock", "SelfLock / autofrein issu du DIAG"),
)
REPORT_GRAPH_OPTIONS = tuple((key, iso_text(label)) for key, label in REPORT_GRAPH_OPTIONS)
REPORT_GRAPH_KEYS = frozenset(key for key, _label in REPORT_GRAPH_OPTIONS)

SYNTHETIC_GRAPH_KEYS = (
    "exp_yfxg",
    "exp_yfa",
    "exp_xgfa",
    "compute_yfxg",
    "compute_xgfy",
    "nrmse_yfxg",
    "nrmse_xgfy",
    "overlay_yfxg",
    "overlay_xgfy",
    "overlay_yfa",
    "overlay_xgfa",
    "friction_mug",
    "friction_muh",
    "friction_mut",
    "diag_boxplots_short",
    "self_lock",
)
COMPLETE_GRAPH_KEYS = tuple(key for key, _label in REPORT_GRAPH_OPTIONS)

POLY_TYPE_OPTIONS = (
    ("TEST_YfXg", "Tension Y = f(Couple global Xg)"),
    ("TEST_XgfY", "Couple global Xg = f(Tension Y)"),
    ("TEST_YfA", "Tension Y = f(Angle recalé A_eff)"),
    ("TEST_XgfA", "Couple global Xg = f(Angle recalé A_eff)"),
    ("µg_fXg", "µg = f(Couple global Xg)"),
    ("µg_fY", "µg = f(Tension Y)"),
    ("µg_fA", "µg = f(Angle recalé A_eff)"),
    ("µh_fXg", "µh = f(Couple global Xg)"),
    ("µh_fY", "µh = f(Tension Y)"),
    ("µh_fA", "µh = f(Angle recalé A_eff)"),
    ("µt_fXg", "µt = f(Couple global Xg)"),
    ("µt_fY", "µt = f(Tension Y)"),
    ("µt_fA", "µt = f(Angle recalé A_eff)"),
)
POLY_TYPE_OPTIONS = tuple((key, iso_text(label)) for key, label in POLY_TYPE_OPTIONS)
POLY_TYPE_KEYS = frozenset(key for key, _label in POLY_TYPE_OPTIONS)

POLY_STAT_OPTIONS = (
    ("MEAN", "Moyenne"),
    ("MEDIAN", "Médiane"),
    ("MIN", "Minimum"),
    ("MAX", "Maximum"),
    ("STD", "Écart-type"),
    ("Q1", "Premier quartile Q1"),
    ("Q3", "Troisième quartile Q3"),
    ("MAD", "Écart absolu médian MAD"),
    ("MEAN_PLUS_2S", "Moyenne + 2σ"),
    ("MEAN_MINUS_2S", "Moyenne - 2σ"),
    ("MEAN_CI_LOW", "IC moyenne - borne basse"),
    ("MEAN_CI_HIGH", "IC moyenne - borne haute"),
    ("MEDIAN_CI_LOW", "IC médiane ISO 16269-7 - borne basse"),
    ("MEDIAN_CI_HIGH", "IC médiane ISO 16269-7 - borne haute"),
    ("TOL_LOW", "Tolérance ISO retenue - borne basse"),
    ("TOL_HIGH", "Tolérance ISO retenue - borne haute"),
)
POLY_STAT_KEYS = frozenset(key for key, _label in POLY_STAT_OPTIONS)

DEFAULT_POLY_TYPES = (
    "TEST_YfXg",
    "TEST_XgfY",
    "µg_fXg",
    "µg_fY",
    "µh_fXg",
    "µh_fY",
    "µt_fXg",
    "µt_fY",
)
DEFAULT_POLY_STATS = (
    "MEAN",
    "MEDIAN",
    "MEAN_PLUS_2S",
    "MEAN_MINUS_2S",
    "MEAN_CI_LOW",
    "MEAN_CI_HIGH",
    "TOL_LOW",
    "TOL_HIGH",
)

REPORT_SECTION_OPTIONS = (
    ("include_summary", "Synthèse de campagne"),
    ("include_diag_principle", "Figure de principe du DIAG"),
    ("include_decisions", "Décisions par essai"),
    ("include_diag_summary", "Synthèse DIAG"),
    ("include_curve_deviation_summary", "Synthèse des écarts aux moyennes"),
    ("include_polynomial_tables", "Tableaux des polynômes sélectionnés"),
    ("include_self_lock_summary", "Synthèse SelfLock / autofrein"),
)
REPORT_SECTION_KEYS = frozenset(key for key, _label in REPORT_SECTION_OPTIONS)


class CampaignReportOptionsError(ValueError):
    def __init__(self, message: str, *, code: str = "REPORT_OPTIONS_INVALID") -> None:
        super().__init__(message)
        self.code = str(code)


def _unique_allowed(
    values: object,
    *,
    allowed: frozenset[str],
    field: str,
) -> list[str]:
    if isinstance(values, str) or not isinstance(values, Sequence):
        raise CampaignReportOptionsError(f"{field} doit être une liste.")
    output: list[str] = []
    invalid: list[str] = []
    for value in values:
        normalized = str(value).strip()
        if field == "poly_stats":
            normalized = {"CI95_LOW": "MEAN_CI_LOW",
                          "CI95_HIGH": "MEAN_CI_HIGH"}.get(normalized, normalized)
        if normalized not in allowed:
            invalid.append(normalized)
        elif normalized not in output:
            output.append(normalized)
    if invalid:
        raise CampaignReportOptionsError(
            f"{field} contient des valeurs inconnues : {', '.join(invalid)}"
        )
    return output


def default_report_options(
    *,
    title: str = "Rapport ARCTA - essais couple tension",
    preset: str = REPORT_PRESET_SYNTHETIC,
) -> dict[str, object]:
    normalized_preset = str(preset).strip().upper()
    if normalized_preset not in REPORT_PRESETS:
        normalized_preset = REPORT_PRESET_SYNTHETIC
    graphs = (
        COMPLETE_GRAPH_KEYS
        if normalized_preset == REPORT_PRESET_COMPLETE
        else SYNTHETIC_GRAPH_KEYS
    )
    return {
        "schema_version": REPORT_OPTIONS_SCHEMA_VERSION,
        "report_title": str(title).strip() or "Rapport ARCTA - essais couple tension",
        "preset": normalized_preset,
        "graph_keys": list(graphs),
        **{key: True for key, _label in REPORT_SECTION_OPTIONS},
        "poly_types": list(DEFAULT_POLY_TYPES),
        "poly_stats": list(DEFAULT_POLY_STATS),
        "poly_columns_mode": "complete",
    }


def normalize_report_options(
    payload: Mapping[str, object] | None,
    *,
    fallback_title: str = "Rapport ARCTA - essais couple tension",
    default_preset: str = REPORT_PRESET_COMPLETE,
) -> dict[str, object]:
    if payload is None:
        return default_report_options(title=fallback_title, preset=default_preset)
    if not isinstance(payload, Mapping):
        raise CampaignReportOptionsError("report_options doit être un objet JSON.")

    preset = str(payload.get("preset", REPORT_PRESET_CUSTOM)).strip().upper()
    if preset not in REPORT_PRESETS:
        raise CampaignReportOptionsError(f"Préréglage PDF inconnu : {preset}")

    title = re.sub(r"[\x00-\x1f\x7f]+", " ", str(
        payload.get("report_title", fallback_title)
    )).strip()
    if not title:
        title = str(fallback_title).strip() or "Rapport ARCTA - essais couple tension"
    if len(title) > 180:
        raise CampaignReportOptionsError(
            "Le titre du rapport ne peut pas dépasser 180 caractères.",
            code="REPORT_TITLE_TOO_LONG",
        )

    defaults = default_report_options(title=title, preset=preset)
    if "graph_keys" in payload:
        graph_keys = _unique_allowed(
            payload["graph_keys"], allowed=REPORT_GRAPH_KEYS, field="graph_keys"
        )
    else:
        graph_keys = list(defaults["graph_keys"])

    if "poly_types" in payload:
        poly_types = _unique_allowed(
            payload["poly_types"], allowed=POLY_TYPE_KEYS, field="poly_types"
        )
    else:
        poly_types = list(defaults["poly_types"])
    if "poly_stats" in payload:
        poly_stats = _unique_allowed(
            payload["poly_stats"], allowed=POLY_STAT_KEYS, field="poly_stats"
        )
    else:
        poly_stats = list(defaults["poly_stats"])

    columns_mode = str(payload.get(
        "poly_columns_mode", defaults["poly_columns_mode"]
    )).strip().lower()
    if columns_mode not in {"compact", "complete"}:
        raise CampaignReportOptionsError(
            "poly_columns_mode doit valoir 'compact' ou 'complete'."
        )

    normalized: dict[str, object] = {
        "schema_version": REPORT_OPTIONS_SCHEMA_VERSION,
        "report_title": title,
        "preset": preset,
        "graph_keys": graph_keys,
        "poly_types": poly_types,
        "poly_stats": poly_stats,
        "poly_columns_mode": columns_mode,
    }
    for key, _label in REPORT_SECTION_OPTIONS:
        # Une configuration déjà persistée avant 63E1 ne connaissait pas la
        # figure de principe : préserver alors sa pagination historique.
        # Les nouveaux formulaires et les préréglages explicites transmettent
        # le champ et le sélectionnent par défaut.
        fallback = False if key == "include_diag_principle" else defaults[key]
        normalized[key] = bool(payload.get(key, fallback))
    return normalized


def report_filename(title: object) -> str:
    visible = str(title or "").strip() or "Rapport ARCTA"
    ascii_text = unicodedata.normalize("NFKD", visible).encode(
        "ascii", "ignore"
    ).decode("ascii")
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", ascii_text).strip(" ._")
    safe = safe[:100].rstrip(" ._") or "Rapport_ARCTA"
    return f"{safe}.pdf"


def report_options_rows(options: Mapping[str, object]) -> list[dict[str, object]]:
    rows = [{
        "Category": "report",
        "Key": "report_title",
        "Selected": True,
        "Value": options.get("report_title", ""),
    }, {
        "Category": "report",
        "Key": "preset",
        "Selected": True,
        "Value": options.get("preset", ""),
    }]
    graph_labels = dict(REPORT_GRAPH_OPTIONS)
    selected_graphs = set(options.get("graph_keys", ()))
    for key, _label in REPORT_GRAPH_OPTIONS:
        rows.append({
            "Category": "graph",
            "Key": key,
            "Selected": key in selected_graphs,
            "Value": graph_labels[key],
        })
    for key, label in REPORT_SECTION_OPTIONS:
        rows.append({
            "Category": "section",
            "Key": key,
            "Selected": bool(options.get(key, False)),
            "Value": label,
        })
    for category, field, choices in (
        ("poly_type", "poly_types", POLY_TYPE_OPTIONS),
        ("poly_stat", "poly_stats", POLY_STAT_OPTIONS),
    ):
        selected = set(options.get(field, ()))
        for key, label in choices:
            rows.append({
                "Category": category,
                "Key": key,
                "Selected": key in selected,
                "Value": label,
            })
    rows.append({
        "Category": "poly_columns",
        "Key": "poly_columns_mode",
        "Selected": True,
        "Value": options.get("poly_columns_mode", "complete"),
    })
    return rows

# 64G3A_MEAN_CI_NAMES
