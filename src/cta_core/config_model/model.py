from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from .schema_version import (
    ARCTA_INPUT_CONFIG_SCHEMA_VERSION,
)


CONFIG_FIELD_STATUSES = frozenset({
    "VALID",
    "TO_CONFIRM",
    "MISSING",
    "INVALID",
})

CONFIG_FIELD_SOURCES = frozenset({
    "TEMPLATE_SYNTH",
    "MANUAL",
    "DEFAULT",
    "DERIVED",
    "IMPORTED_CONFIG",
    "UNKNOWN",
})


@dataclass
class ArctaConfigField:
    """
    Champ élémentaire de la configuration d'une campagne ARCTA.

    Un champ représente une information de campagne, jamais une valeur
    spécifique à un essai individuel.
    """

    key: str
    value: Any = None
    label: str = ""
    category: str = "general"
    unit: str = ""
    value_type: str = "text"
    source: str = "UNKNOWN"
    source_ref: str = ""
    original_value: Any = None
    original_source: str = ""
    original_source_ref: str = ""
    required: bool = False
    status: str = "TO_CONFIRM"
    comment: str = ""

    def __post_init__(self) -> None:
        self.key = str(
            self.key
        ).strip()

        if not self.key:
            raise ValueError(
                "La clé CONFIG ne peut pas être vide."
            )

        self.label = (
            str(self.label).strip()
            or self.key
        )

        self.category = (
            str(self.category).strip()
            or "general"
        )

        self.unit = str(
            self.unit or ""
        ).strip()

        self.value_type = (
            str(self.value_type).strip().lower()
            or "text"
        )

        self.source = (
            str(self.source).strip().upper()
            or "UNKNOWN"
        )

        if self.source not in CONFIG_FIELD_SOURCES:
            raise ValueError(
                "Source CONFIG inconnue : "
                f"{self.source}"
            )

        self.source_ref = str(
            self.source_ref or ""
        ).strip()

        self.original_source = str(
            self.original_source or ""
        ).strip().upper()

        if (
                self.original_source
                and self.original_source
                not in CONFIG_FIELD_SOURCES
        ):
            raise ValueError(
                "Source CONFIG d'origine inconnue : "
                f"{self.original_source}"
            )

        self.original_source_ref = str(
            self.original_source_ref or ""
        ).strip()

        self.status = (
            str(self.status).strip().upper()
            or "TO_CONFIRM"
        )

        if self.status not in CONFIG_FIELD_STATUSES:
            raise ValueError(
                "Statut CONFIG inconnu : "
                f"{self.status}"
            )

        self.comment = str(
            self.comment or ""
        ).strip()

    @property
    def modified(self) -> bool:
        return (
            self.original_value is not None
            and self.value != self.original_value
        )

    @property
    def missing(self) -> bool:
        if self.value is None:
            return True

        if isinstance(
            self.value,
            str,
        ):
            return not self.value.strip()

        return False

    def to_dict(
        self,
    ) -> dict[str, object]:
        return {
            "key": self.key,
            "value": self.value,
            "label": self.label,
            "category": self.category,
            "unit": self.unit,
            "value_type": self.value_type,
            "source": self.source,
            "source_ref": self.source_ref,
            "original_value":
                self.original_value,
            "original_source":
                self.original_source,
            "original_source_ref":
                self.original_source_ref,
            "modified":
                self.modified,
            "required":
                self.required,
            "status":
                self.status,
            "comment":
                self.comment,
        }


@dataclass
class ArctaInputConfig:
    """
    Configuration canonique d'une campagne ARCTA.

    Invariant métier :
    tous les essais d'une campagne partagent cette même configuration.
    """

    campaign_id: str
    fields: dict[
        str,
        ArctaConfigField,
    ] = field(
        default_factory=dict
    )
    schema_version: str = (
        ARCTA_INPUT_CONFIG_SCHEMA_VERSION
    )

    def __post_init__(self) -> None:
        self.campaign_id = str(
            self.campaign_id
        ).strip()

        if not self.campaign_id:
            raise ValueError(
                "campaign_id ne peut pas être vide."
            )

        normalized: dict[
            str,
            ArctaConfigField,
        ] = {}

        for key, config_field in self.fields.items():
            if not isinstance(
                config_field,
                ArctaConfigField,
            ):
                raise TypeError(
                    "fields doit contenir uniquement "
                    "des ArctaConfigField."
                )

            if str(key) != config_field.key:
                raise ValueError(
                    "La clé du dictionnaire CONFIG "
                    "doit correspondre à field.key."
                )

            if config_field.key in normalized:
                raise ValueError(
                    "Clé CONFIG dupliquée : "
                    f"{config_field.key}"
                )

            normalized[
                config_field.key
            ] = config_field

        self.fields = normalized

    def add_field(
        self,
        config_field: ArctaConfigField,
        *,
        replace: bool = False,
    ) -> None:
        if not isinstance(
            config_field,
            ArctaConfigField,
        ):
            raise TypeError(
                "config_field doit être un "
                "ArctaConfigField."
            )

        if (
            config_field.key in self.fields
            and not replace
        ):
            raise ValueError(
                "Clé CONFIG déjà présente : "
                f"{config_field.key}"
            )

        self.fields[
            config_field.key
        ] = config_field

    def get_field(
        self,
        key: str,
    ) -> ArctaConfigField | None:
        return self.fields.get(
            str(key).strip()
        )

    def set_value(
        self,
        key: str,
        value: Any,
        *,
        source: str = "MANUAL",
        comment: str | None = None,
    ) -> ArctaConfigField:
        config_field = self.get_field(
            key
        )

        if config_field is None:
            raise KeyError(
                str(key)
            )

        if (
                config_field.original_value is None
                and config_field.value is not None
        ):
            config_field.original_value = (
                config_field.value
            )

        if (
                not config_field.original_source
                and config_field.value is not None
        ):
            config_field.original_source = (
                config_field.source
            )

            config_field.original_source_ref = (
                config_field.source_ref
            )

        config_field.value = value
        config_field.source = (
            str(source).strip().upper()
            or "MANUAL"
        )

        if (
            config_field.source
            not in CONFIG_FIELD_SOURCES
        ):
            raise ValueError(
                "Source CONFIG inconnue : "
                f"{config_field.source}"
            )

        if comment is not None:
            config_field.comment = str(
                comment
            ).strip()

        return config_field

    def remove_field(
        self,
        key: str,
    ) -> None:
        normalized_key = str(
            key
        ).strip()

        if normalized_key not in self.fields:
            raise KeyError(
                normalized_key
            )

        del self.fields[
            normalized_key
        ]

    def categories(
        self,
    ) -> tuple[str, ...]:
        result: list[str] = []

        for config_field in self.fields.values():
            if (
                config_field.category
                not in result
            ):
                result.append(
                    config_field.category
                )

        return tuple(
            result
        )

    def fields_in_category(
        self,
        category: str,
    ) -> tuple[
        ArctaConfigField,
        ...,
    ]:
        wanted = str(
            category
        ).strip()

        return tuple(
            config_field
            for config_field
            in self.fields.values()
            if config_field.category == wanted
        )

    def validation_summary(
        self,
    ) -> dict[str, object]:
        missing_required = [
            config_field.key
            for config_field
            in self.fields.values()
            if (
                config_field.required
                and config_field.missing
            )
        ]

        invalid = [
            config_field.key
            for config_field
            in self.fields.values()
            if config_field.status == "INVALID"
        ]

        to_confirm = [
            config_field.key
            for config_field
            in self.fields.values()
            if config_field.status == "TO_CONFIRM"
        ]

        valid = (
            not missing_required
            and not invalid
        )

        return {
            "valid": valid,
            "field_count":
                len(self.fields),
            "missing_required":
                missing_required,
            "invalid":
                invalid,
            "to_confirm":
                to_confirm,
        }

    def to_dict(
        self,
    ) -> dict[str, object]:
        return {
            "schema_version":
                self.schema_version,
            "campaign_id":
                self.campaign_id,
            "scope":
                "campaign",
            "fields": [
                config_field.to_dict()
                for config_field
                in self.fields.values()
            ],
            "validation":
                self.validation_summary(),
        }


def build_arcta_input_config(
    *,
    campaign_id: str,
    fields: Iterable[
        ArctaConfigField
    ] = (),
) -> ArctaInputConfig:
    config = ArctaInputConfig(
        campaign_id=campaign_id
    )

    for config_field in fields:
        config.add_field(
            config_field
        )

    return config


def arcta_input_config_from_dict(
    payload: Mapping[
        str,
        Any,
    ],
) -> ArctaInputConfig:
    schema_version = str(
        payload.get(
            "schema_version",
            "",
        )
    ).strip()

    if (
        schema_version
        != ARCTA_INPUT_CONFIG_SCHEMA_VERSION
    ):
        raise ValueError(
            "Version CONFIG ARCTA non supportée : "
            f"{schema_version or '(absente)'}"
        )

    campaign_id = str(
        payload.get(
            "campaign_id",
            "",
        )
    ).strip()

    raw_fields = payload.get(
        "fields",
        [],
    )

    if not isinstance(
        raw_fields,
        list,
    ):
        raise ValueError(
            "CONFIG.fields doit être une liste."
        )

    fields: list[
        ArctaConfigField
    ] = []

    for raw in raw_fields:
        if not isinstance(
            raw,
            Mapping,
        ):
            raise ValueError(
                "Chaque champ CONFIG doit être "
                "un objet."
            )

        fields.append(
            ArctaConfigField(
                key=raw.get(
                    "key",
                    "",
                ),
                value=raw.get(
                    "value"
                ),
                label=raw.get(
                    "label",
                    "",
                ),
                category=raw.get(
                    "category",
                    "general",
                ),
                unit=raw.get(
                    "unit",
                    "",
                ),
                value_type=raw.get(
                    "value_type",
                    "text",
                ),
                source=raw.get(
                    "source",
                    "UNKNOWN",
                ),
                source_ref=raw.get(
                    "source_ref",
                    "",
                ),
                original_value=raw.get(
                    "original_value"
                ),
                original_source=raw.get(
                    "original_source",
                    "",
                ),
                original_source_ref=raw.get(
                    "original_source_ref",
                    "",
                ),
                required=bool(
                    raw.get(
                        "required",
                        False,
                    )
                ),
                status=raw.get(
                    "status",
                    "TO_CONFIRM",
                ),
                comment=raw.get(
                    "comment",
                    "",
                ),
            )
        )

    return build_arcta_input_config(
        campaign_id=campaign_id,
        fields=fields,
    )