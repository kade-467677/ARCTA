from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any
import unicodedata

from cta_core.config_model import (
    CONFIG_FIELD_STATUSES,
    ArctaConfigField,
    ArctaInputConfig,
    arcta_input_config_from_dict,
)


def serialize_config(
    config: ArctaInputConfig,
) -> str:
    return json.dumps(
        config.to_dict(),
        ensure_ascii=False,
    )


def deserialize_config(
    raw: str,
) -> ArctaInputConfig:
    payload = json.loads(
        str(raw)
    )

    return arcta_input_config_from_dict(
        payload
    )


def parse_form_value(
    raw_value: Any,
    value_type: str,
) -> Any:
    text = str(
        raw_value
        if raw_value is not None
        else ""
    ).strip()

    if not text:
        return None

    kind = str(
        value_type or "text"
    ).strip().lower()

    if kind in {
        "float",
        "number",
    }:
        return float(
            text.replace(
                ",",
                ".",
            )
        )

    if kind in {
        "int",
        "integer",
    }:
        return int(
            text
        )

    if kind in {
        "bool",
        "boolean",
    }:
        normalized = text.lower()

        if normalized in {
            "1",
            "true",
            "vrai",
            "yes",
            "oui",
        }:
            return True

        if normalized in {
            "0",
            "false",
            "faux",
            "no",
            "non",
        }:
            return False

        raise ValueError(
            f"Valeur booléenne invalide : {text}"
        )

    return text


def apply_config_form(
    config: ArctaInputConfig,
    form: Mapping[str, Any],
) -> ArctaInputConfig:
    """
    Applique toutes les valeurs présentes dans le formulaire
    à la CONFIG fournie.
    """
    for field in config.fields.values():
        value_key = (
            f"value__{field.key}"
        )

        if value_key in form:
            new_value = parse_form_value(
                form.get(value_key),
                field.value_type,
            )

            if new_value != field.value:
                config.set_value(
                    field.key,
                    new_value,
                    source="MANUAL",
                )

        status_key = (
            f"status__{field.key}"
        )

        if status_key in form:
            status = str(
                form.get(status_key)
                or ""
            ).strip().upper()

            if status not in CONFIG_FIELD_STATUSES:
                raise ValueError(
                    "Statut CONFIG inconnu : "
                    f"{status}"
                )

            field.status = status

        comment_key = (
            f"comment__{field.key}"
        )

        if comment_key in form:
            field.comment = str(
                form.get(comment_key)
                or ""
            ).strip()

    return config


def restore_config_field(
    config: ArctaInputConfig,
    key: str,
) -> ArctaConfigField:
    field = config.get_field(
        key
    )

    if field is None:
        raise KeyError(
            key
        )

    if field.original_value is None:
        raise ValueError(
            "Ce champ ne possède pas de "
            "valeur d'origine restaurable."
        )

    field.value = (
        field.original_value
    )

    field.source = (
        field.original_source
        or "UNKNOWN"
    )

    if field.original_source_ref:
        field.source_ref = (
            field.original_source_ref
        )

    field.status = "TO_CONFIRM"

    return field


def _normalize_custom_key(
    raw: str,
) -> str:
    key = str(
        raw or ""
    ).strip().lower()

    key = unicodedata.normalize(
        "NFKD",
        key,
    )

    key = "".join(
        character
        for character in key
        if not unicodedata.combining(
            character
        )
    )

    key = re.sub(
        r"[^a-z0-9_]+",
        "_",
        key,
    )

    key = re.sub(
        r"_+",
        "_",
        key,
    ).strip("_")

    if not key:
        raise ValueError(
            "La clé du paramètre est vide."
        )

    if key[0].isdigit():
        key = (
            "field_"
            + key
        )

    return key


def add_custom_config_field(
    config: ArctaInputConfig,
    *,
    key: str,
    label: str,
    value: Any,
    category: str = "utilisateur",
    unit: str = "",
    value_type: str = "text",
    required: bool = False,
) -> ArctaConfigField:
    normalized_key = (
        _normalize_custom_key(
            key
        )
    )

    if config.get_field(
        normalized_key
    ) is not None:
        raise ValueError(
            "Clé CONFIG déjà présente : "
            f"{normalized_key}"
        )

    parsed_value = parse_form_value(
        value,
        value_type,
    )

    field = ArctaConfigField(
        key=normalized_key,
        value=parsed_value,
        label=(
            str(label).strip()
            or normalized_key
        ),
        category=(
            str(category).strip()
            or "utilisateur"
        ),
        unit=str(
            unit or ""
        ).strip(),
        value_type=(
            str(value_type).strip().lower()
            or "text"
        ),
        source="MANUAL",
        required=bool(
            required
        ),
        status="TO_CONFIRM",
    )

    config.add_field(
        field
    )

    return field


def remove_custom_config_field(
    config: ArctaInputConfig,
    key: str,
) -> None:
    field = config.get_field(
        key
    )

    if field is None:
        raise KeyError(
            key
        )

    if field.required:
        raise ValueError(
            "Un paramètre obligatoire "
            "ne peut pas être supprimé."
        )

    config.remove_field(
        key
    )


def config_ready_for_continue(
    config: ArctaInputConfig,
) -> bool:
    summary = (
        config.validation_summary()
    )

    return bool(
        summary["valid"]
        and not summary["to_confirm"]
    )