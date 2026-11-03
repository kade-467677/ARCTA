from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import date
from typing import Any

from cta_core.config_model import (
    CANONICAL_FIELD_SPECS,
    CanonicalCampaignConfig,
    build_default_campaign_config,
)


CALCULATED_REQUIREMENT = "CALCULE"

REQUIREMENT_LABELS = {
    "OBLIGATOIRE_CALCUL": "Obligatoire pour le calcul",
    "OBLIGATOIRE_ID": "Obligatoire pour DABCTA",
    "RECOMMANDE": "Recommandé",
    "OPTIONNEL": "Optionnel",
    "CALCULE": "Calculé par ARCTA",
}

STATUS_LABELS = {
    "EXTRACTED": "Extrait de la source",
    "DERIVED": "Dérivé automatiquement",
    "CONFIRMED": "Confirmé manuellement",
    "MISSING": "À renseigner",
    "AMBIGUOUS": "À confirmer",
}


def parse_canonical_form_value(raw_value: Any, value_type: str) -> Any:
    text = str(raw_value if raw_value is not None else "").strip()

    if not text:
        return None

    kind = str(value_type or "text").strip().lower()

    if kind == "float":
        value = float(
            text.replace("\u00a0", "").replace(" ", "").replace(",", ".")
        )

        if not math.isfinite(value):
            raise ValueError(f"Valeur numérique non finie : {text}")

        return value

    if kind == "int":
        value = float(text.replace("\u00a0", "").replace(" ", "").replace(",", "."))

        if not math.isfinite(value) or not value.is_integer():
            raise ValueError(f"Valeur entière invalide : {text}")

        return int(value)

    if kind == "bool":
        normalized = text.casefold()

        if normalized in {"1", "true", "vrai", "yes", "oui"}:
            return True

        if normalized in {"0", "false", "faux", "no", "non"}:
            return False

        raise ValueError(f"Valeur booléenne invalide : {text}")

    if kind == "date":
        try:
            return date.fromisoformat(text).isoformat()
        except ValueError as exc:
            raise ValueError(
                f"Date invalide : {text}. Format attendu : AAAA-MM-JJ."
            ) from exc

    return text


def apply_canonical_config_form(
    config: CanonicalCampaignConfig,
    form: Mapping[str, Any],
) -> CanonicalCampaignConfig:
    for spec in CANONICAL_FIELD_SPECS:
        if spec.requirement == CALCULATED_REQUIREMENT:
            continue

        value_key = f"value__{spec.field_id}"

        if value_key not in form:
            continue

        field = config.get_field(spec.field_id)
        parsed = parse_canonical_form_value(
            form.get(value_key),
            spec.value_type,
        )
        message = str(form.get(f"message__{spec.field_id}", "")).strip()

        if parsed != field.value:
            field.normalized_value = parsed
            field.status = "MISSING" if parsed is None else "CONFIRMED"
            field.transformation = "saisie manuelle Web 63C2"

        field.message = message

    return config


def canonical_config_categories(
    config: CanonicalCampaignConfig,
) -> list[dict[str, object]]:
    validation = config.validation_summary()
    attention = set(validation["missing_calculation"])
    attention.update(validation["ambiguous_calculation"])
    categories: list[dict[str, object]] = []
    positions: dict[str, int] = {}

    for spec in CANONICAL_FIELD_SPECS:
        if spec.category not in positions:
            positions[spec.category] = len(categories)
            categories.append({
                "name": spec.category,
                "fields": [],
                "open": False,
            })

        field = config.get_field(spec.field_id)
        source_reference = ""

        if field.source_file:
            source_reference = field.source_file

        if field.source_sheet:
            source_reference += f" — {field.source_sheet}"

        if field.source_cell:
            source_reference += f"!{field.source_cell}"

        categories[positions[spec.category]]["fields"].append({
            "spec": spec,
            "field": field,
            "display_value": "" if field.value is None else field.value,
            "source_reference": source_reference,
            "editable": spec.requirement != CALCULATED_REQUIREMENT,
            "requires_attention": spec.field_id in attention,
        })

    for index, category in enumerate(categories):
        category["open"] = index == 0 or any(
            item["requires_attention"]
            for item in category["fields"]
        )

    return categories


def canonical_to_legacy_config(config: CanonicalCampaignConfig):
    legacy = build_default_campaign_config(config.campaign_id)
    mapping = {
        "thread_size": "thread_designation",
        "p_mm": "thread_pitch_mm",
        "d2_mm": "thread_pitch_diameter_mm",
        "d_int_vis_mm": "screw_bearing_inner_diameter_mm",
        "d_ext_vis_mm": "screw_bearing_outer_diameter_mm",
        "d_int_ecrou_mm": "nut_bearing_inner_diameter_mm",
        "d_ext_ecrou_mm": "nut_bearing_outer_diameter_mm",
        "tightening_application": "tightening_component",
        "type_serrage": "tightening_component",
        "Db_mm": "bearing_mean_diameter_mm",
    }

    for legacy_key, canonical_id in mapping.items():
        canonical_field = config.get_field(canonical_id)
        legacy_field = legacy.get_field(legacy_key)
        value = canonical_field.value

        legacy_field.value = value
        legacy_field.original_value = value
        legacy_field.source = "IMPORTED_CONFIG"
        legacy_field.original_source = "IMPORTED_CONFIG"
        legacy_field.source_ref = _canonical_source_ref(canonical_field)
        legacy_field.original_source_ref = legacy_field.source_ref
        legacy_field.status = (
            "VALID"
            if value is not None and canonical_field.status != "AMBIGUOUS"
            else "MISSING"
        )

    _set_legacy_mean(
        legacy,
        "dm_vis_mm",
        config.get_field("screw_bearing_inner_diameter_mm").value,
        config.get_field("screw_bearing_outer_diameter_mm").value,
    )
    _set_legacy_mean(
        legacy,
        "dm_ecrou_mm",
        config.get_field("nut_bearing_inner_diameter_mm").value,
        config.get_field("nut_bearing_outer_diameter_mm").value,
    )

    return legacy


def _canonical_source_ref(field) -> str:
    parts = []

    if field.source_file:
        parts.append(field.source_file)

    location = field.source_sheet

    if field.source_cell:
        location += f"!{field.source_cell}" if location else field.source_cell

    if location:
        parts.append(location)

    return " — ".join(parts) or "CONFIG_CANONIQUE"


def _set_legacy_mean(legacy, key: str, inner: Any, outer: Any) -> None:
    field = legacy.get_field(key)

    try:
        values = (float(inner), float(outer))
    except (TypeError, ValueError):
        field.status = "MISSING"
        return

    if not all(math.isfinite(value) for value in values):
        field.status = "MISSING"
        return

    field.value = sum(values) / 2.0
    field.original_value = field.value
    field.source = "DERIVED"
    field.original_source = "DERIVED"
    field.source_ref = "CONFIG_CANONIQUE:moyenne_diamètres"
    field.original_source_ref = field.source_ref
    field.status = "VALID"
