from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


ARCTA_DABCTA_CANONICAL_SCHEMA_VERSION = "1.1"
ARCTA_DABCTA_SUPPORTED_SCHEMA_VERSIONS = frozenset({"1.0", "1.1"})

CANONICAL_FIELD_STATUSES = frozenset({
    "EXTRACTED",
    "DERIVED",
    "CONFIRMED",
    "MISSING",
    "AMBIGUOUS",
})

CANONICAL_FIELD_REQUIREMENTS = frozenset({
    "OBLIGATOIRE_ID",
    "OBLIGATOIRE_CALCUL",
    "RECOMMANDE",
    "OPTIONNEL",
    "CALCULE",
})

CANONICAL_SOURCE_PROFILES = frozenset({
    "DABCTA_REANALYSIS_V1",
    "TEMPLATE_SYNTH_V1",
    "DEMANDE_ESSAIS_INTERNE_V1",
})


@dataclass(frozen=True)
class CanonicalFieldSpec:
    field_id: str
    label: str
    category: str
    type_unit: str = "texte"
    requirement: str = "RECOMMANDE"
    dabcta_column: str = ""

    def __post_init__(self) -> None:
        if not str(self.field_id).strip():
            raise ValueError("field_id canonique vide.")

        if self.requirement not in CANONICAL_FIELD_REQUIREMENTS:
            raise ValueError(
                "Niveau canonique inconnu : "
                f"{self.requirement}"
            )

    @property
    def value_type(self) -> str:
        normalized = str(self.type_unit).lower()

        if "bool" in normalized:
            return "bool"

        if "entier" in normalized:
            return "int"

        if normalized in {
            "mm",
            "hv",
            "mpa",
            "rpm",
            "degré",
            "nm",
            "µm",
            "nombre",
        }:
            return "float"

        if "date" in normalized:
            return "date"

        return "text"


_FIELD_ROWS = (
    ("entity", "Entité Safran", "Identification", "texte", "OBLIGATOIRE_ID", "SAFRAN_Entity"),
    ("program_id", "Programme", "Identification", "texte", "OBLIGATOIRE_ID", "ID_Prog"),
    ("configuration_id", "Identifiant de configuration", "Identification", "texte", "OBLIGATOIRE_ID", "ID_Conf"),
    ("report_number", "Numéro de rapport", "Identification", "texte", "OBLIGATOIRE_ID", "Num_Rapport"),
    ("test_date", "Date de réalisation", "Identification", "date ISO", "OBLIGATOIRE_ID", "Date_Réal"),
    ("sample_count", "Nombre d'échantillons", "Conditions", "entier", "OBLIGATOIRE_ID", "Nb._Ech"),
    ("tightening_component", "Pièce entraînée au serrage", "Conditions", "enum vis|écrou", "OBLIGATOIRE_CALCUL", "Vissage_Par"),
    ("tightening_speed_rpm", "Vitesse de serrage", "Conditions", "rpm", "RECOMMANDE", "Vit._Serrage (RPM)"),
    ("thread_designation", "Taille et pas normalisés", "Filetage", "texte", "OBLIGATOIRE_CALCUL", "Taille_&_Pas_(mm)"),
    ("bearing_mean_diameter_mm", "Diamètre moyen de frottement", "Géométrie", "mm", "OBLIGATOIRE_CALCUL", "Dia._Moy_Frott"),
    ("screw_part_number", "P/N vis", "Vis", "texte", "OBLIGATOIRE_ID", "PN_Vis"),
    ("screw_material", "Matériau vis", "Vis", "texte", "OBLIGATOIRE_ID", "Mat._Vis"),
    ("screw_material_spec", "Spécification matériau vis / DMD", "Vis", "texte", "RECOMMANDE", ""),
    ("screw_hardness_hv", "Dureté vis", "Vis", "HV", "RECOMMANDE", "Dureté_Mat._Vis_(HV)"),
    ("screw_rm_mpa", "Résistance à rupture vis", "Vis", "MPa", "RECOMMANDE", "Rm_Mat._Vis"),
    ("screw_re_mpa", "Limite d'élasticité vis", "Vis", "MPa", "RECOMMANDE", "Re_Mat._Vis"),
    ("screw_bearing_inner_diameter_mm", "Diamètre intérieur appui vis", "Vis", "mm", "OBLIGATOIRE_CALCUL", "Dia._Inter_Vis"),
    ("screw_bearing_outer_diameter_mm", "Diamètre extérieur appui vis", "Vis", "mm", "OBLIGATOIRE_CALCUL", "Dia._Exter_Vis"),
    ("screw_surface_treatment", "Traitement de surface vis", "Vis", "texte", "RECOMMANDE", "TS_Vis"),
    ("nut_part_number", "P/N écrou", "Écrou", "texte", "OBLIGATOIRE_ID", "PN_Ecrou"),
    ("nut_material", "Matériau écrou", "Écrou", "texte", "OBLIGATOIRE_ID", "Mat._Ecrou"),
    ("nut_material_spec", "Spécification matériau écrou / DMD", "Écrou", "texte", "RECOMMANDE", ""),
    ("nut_hardness_hv", "Dureté écrou", "Écrou", "HV", "RECOMMANDE", "Dureté_Mat._Ecrou_(HV)"),
    ("nut_rm_mpa", "Résistance à rupture écrou", "Écrou", "MPa", "RECOMMANDE", "Rm_Mat._Ecrou"),
    ("nut_re_mpa", "Limite d'élasticité écrou", "Écrou", "MPa", "RECOMMANDE", "Re_Mat._Ecrou"),
    ("nut_bearing_inner_diameter_mm", "Diamètre intérieur appui écrou", "Écrou", "mm", "OBLIGATOIRE_CALCUL", "Dia._Inter_Ecrou"),
    ("nut_bearing_outer_diameter_mm", "Diamètre extérieur appui écrou", "Écrou", "mm", "OBLIGATOIRE_CALCUL", "Dia._Exter_Ecrou"),
    ("nut_surface_treatment", "Traitement de surface écrou", "Écrou", "texte", "RECOMMANDE", "TS_Ecrou"),
    ("washer_part_number", "P/N rondelle", "Rondelle", "texte", "RECOMMANDE", "PN_Rondelle"),
    ("washer_material", "Matériau rondelle", "Rondelle", "texte", "RECOMMANDE", "Mat._Rondelle"),
    ("washer_material_spec", "Spécification matériau rondelle / DMD", "Rondelle", "texte", "OPTIONNEL", ""),
    ("washer_hardness_hv", "Dureté rondelle", "Rondelle", "HV", "RECOMMANDE", "Dureté_Mat._Rondelle_(HV)"),
    ("washer_rm_mpa", "Résistance à rupture rondelle", "Rondelle", "MPa", "OPTIONNEL", "Rm_Mat._Rondelle"),
    ("washer_re_mpa", "Limite d'élasticité rondelle", "Rondelle", "MPa", "OPTIONNEL", "Re_Mat._Rondelle"),
    ("washer_inner_diameter_mm", "Diamètre intérieur rondelle", "Rondelle", "mm", "RECOMMANDE", "Dia._Inter_Rondelle"),
    ("washer_outer_diameter_mm", "Diamètre extérieur rondelle", "Rondelle", "mm", "RECOMMANDE", "Dia._Exter_Rondelle"),
    ("washer_surface_treatment", "Traitement de surface rondelle", "Rondelle", "texte", "RECOMMANDE", "TS_Rondelle"),
    ("lubricant_reference", "Lubrifiant additionnel type/référence", "Lubrification", "texte", "RECOMMANDE", "Lub_Add"),
    ("lube_screw_bearing", "Lubrification appui vis", "Lubrification", "booléen", "RECOMMANDE", "Lub_Vis_ST"),
    ("lube_nut_bearing", "Lubrification appui écrou", "Lubrification", "booléen", "RECOMMANDE", "Lub_Ecou_ST"),
    ("lube_washer_bearing", "Lubrification appui rondelle/plaque", "Lubrification", "booléen", "RECOMMANDE", "Lub_Rondelle_ST"),
    ("lube_screw_thread", "Lubrification filet vis", "Lubrification", "booléen", "RECOMMANDE", "Lub_Vis_TH"),
    ("lube_nut_thread", "Lubrification filet écrou", "Lubrification", "booléen", "RECOMMANDE", "Lub_Ecrou_TH"),
    ("selflock_mean_nm", "Autofrein moyenne", "Résultats", "Nm", "CALCULE", "SelfLock_Moyenne"),
    ("selflock_median_nm", "Autofrein médiane", "Résultats", "Nm", "CALCULE", "SelfLock_Médiane"),
    ("selflock_std_nm", "Autofrein écart-type", "Résultats", "Nm", "CALCULE", "SelfLock_EcartType"),
    ("selflock_min_nm", "Autofrein minimum", "Résultats", "Nm", "CALCULE", "SelfLock_Min"),
    ("selflock_max_nm", "Autofrein maximum", "Résultats", "Nm", "CALCULE", "SelfLock_Max"),
    ("selflock_valid_count", "Nombre d'autofreins valides", "Résultats", "entier", "CALCULE", "SelfLock_Nvalides"),
    ("thread_nominal_diameter_mm", "Diamètre nominal", "Filetage", "mm", "OBLIGATOIRE_CALCUL", ""),
    ("thread_pitch_mm", "Pas", "Filetage", "mm", "OBLIGATOIRE_CALCUL", ""),
    ("thread_lead_mm", "Avance axiale par tour (vide : un filet, avance = pas)", "Filetage", "mm", "OPTIONNEL", ""),
    ("bearing_cone_half_angle_deg", "Demi-angle du cône d’appui depuis l’axe (90° = plan)", "Géométrie", "degré", "OPTIONNEL", ""),
    ("thread_half_angle_deg", "Demi-angle du flanc chargé", "Filetage", "degré", "OBLIGATOIRE_CALCUL", ""),
    ("thread_pitch_diameter_mm", "Diamètre au flanc d2", "Filetage", "mm", "OBLIGATOIRE_CALCUL", ""),
    (
        "screw_torsion_diameter_mm",
        "Diamètre résistant en torsion de la vis",
        "Vis",
        "mm",
        "RECOMMANDE",
        "",
    ),
    ("bearing_inner_active_mm", "Diamètre intérieur actif Di", "Géométrie", "mm", "OBLIGATOIRE_CALCUL", ""),
    ("bearing_outer_active_mm", "Diamètre extérieur actif Dw", "Géométrie", "mm", "OBLIGATOIRE_CALCUL", ""),
    ("bearing_geometry", "Géométrie surface d'appui", "Géométrie", "enum plate|conique|sphérique", "RECOMMANDE", ""),
    ("bearing_angle_deg", "Angle surface d'appui alpha_b", "Géométrie", "degré", "RECOMMANDE", ""),
    ("bearing_mean_radius_mm", "Rayon moyen d'appui", "Géométrie", "mm", "CALCULE", ""),
    ("assembly_plan_reference", "Référence plan assemblage", "Identification", "texte", "RECOMMANDE", ""),
    ("screw_plan_reference", "Référence plan vis", "Vis", "texte", "OPTIONNEL", ""),
    ("nut_plan_reference", "Référence plan écrou", "Écrou", "texte", "OPTIONNEL", ""),
    ("washer_plan_reference", "Référence plan rondelle/entretoise", "Rondelle", "texte", "OPTIONNEL", ""),
    ("tightening_method", "Méthode de serrage", "Conditions", "texte/enum", "OBLIGATOIRE_ID", ""),
    ("tightening_endpoint_value", "Valeur de fin de serrage", "Conditions", "nombre", "OBLIGATOIRE_ID", ""),
    ("tightening_endpoint_unit", "Unité de fin de serrage", "Conditions", "unité", "OBLIGATOIRE_ID", ""),
    ("grip_or_threads", "Épaisseur serrée ou deux filets", "Conditions", "mm/texte", "RECOMMANDE", ""),
    ("contact_part_type", "Pièce de contact soumise au frottement", "Conditions", "texte/enum", "OBLIGATOIRE_CALCUL", ""),
    ("washer_description", "Description rondelle/entretoise/coupelle", "Rondelle", "texte", "RECOMMANDE", ""),
    ("washer_thickness_mm", "Épaisseur rondelle", "Rondelle", "mm", "RECOMMANDE", ""),
    ("support_plan_reference", "Référence plan plaque d'appui", "Plaque d'appui", "texte", "RECOMMANDE", ""),
    ("support_hole_diameter_mm", "Diamètre trou plaque", "Plaque d'appui", "mm", "RECOMMANDE", ""),
    ("support_thickness_mm", "Épaisseur plaque", "Plaque d'appui", "mm", "RECOMMANDE", ""),
    ("support_material", "Matériau plaque", "Plaque d'appui", "texte", "RECOMMANDE", ""),
    ("support_material_spec", "Spécification matériau plaque DMD", "Plaque d'appui", "texte", "RECOMMANDE", ""),
    ("support_roughness_ra_um", "Rugosité plaque Ra", "Plaque d'appui", "µm", "RECOMMANDE", ""),
    ("support_hardness", "Dureté plaque", "Plaque d'appui", "texte/valeur", "OPTIONNEL", ""),
    ("lubrication_present", "Présence de graisse/produit", "Lubrification", "booléen", "RECOMMANDE", ""),
    ("lubricant_wrs_listed", "Produit référencé", "Lubrification", "booléen", "OPTIONNEL", ""),
    ("lubricant_wrs_reference", "Référence", "Lubrification", "texte", "OPTIONNEL", ""),
    ("lubricant_application_method", "Moyen d'application", "Lubrification", "texte", "OPTIONNEL", ""),
    ("lubrication_comment", "Commentaire lubrification", "Lubrification", "texte", "OPTIONNEL", ""),
    ("bench_reference", "Référence banc d'essai", "Moyens", "texte", "RECOMMANDE", ""),
    ("sensor_reference", "Référence capteur", "Moyens", "texte", "RECOMMANDE", ""),
    ("operator_name", "Opérateur", "Traçabilité", "texte", "OPTIONNEL", ""),
    ("screw_lot", "Lot vis", "Vis", "texte", "RECOMMANDE", ""),
    ("nut_lot", "Lot écrou", "Écrou", "texte", "RECOMMANDE", ""),
    ("washer_lot", "Lot rondelle", "Rondelle", "texte", "RECOMMANDE", ""),
    ("screw_drive_form", "Forme d'entraînement vis", "Vis", "texte", "RECOMMANDE", ""),
    ("nut_drive_form", "Forme d'entraînement écrou", "Écrou", "texte", "RECOMMANDE", ""),
    ("contact_summary", "Résumé pièce serrée / pièce frottante", "Calcul", "texte", "CALCULE", ""),
    ("measured_m_mm", "Mesure M", "Outillage", "mm", "OPTIONNEL", ""),
    ("effective_grip_mm", "Épaisseur de serrage effective Eserrer", "Calcul", "mm", "CALCULE", ""),
    ("full_thread_length_mm", "Longueur filet complet entre appuis Lt", "Calcul", "mm", "CALCULE", ""),
    ("shim_thickness_m_method_mm", "Épaisseur cale méthode M", "Outillage", "mm", "CALCULE", ""),
    ("shim_thickness_grip_method_mm", "Épaisseur cale méthode Eserrer", "Outillage", "mm", "CALCULE", ""),
    ("shim_thickness_tooling_method_mm", "Épaisseur cale méthode outillage", "Outillage", "mm", "CALCULE", ""),
)

CANONICAL_FIELD_SPECS = tuple(
    CanonicalFieldSpec(*row)
    for row in _FIELD_ROWS
)

CANONICAL_FIELD_SPEC_BY_ID = {
    spec.field_id: spec
    for spec in CANONICAL_FIELD_SPECS
}

if len(CANONICAL_FIELD_SPEC_BY_ID) != len(CANONICAL_FIELD_SPECS):
    raise RuntimeError("Field_ID canonique dupliqué.")


def _is_missing(value: Any) -> bool:
    if value is None:
        return True

    if isinstance(value, str):
        return not value.strip()

    return False


@dataclass
class CanonicalFieldValue:
    field_id: str
    raw_value: Any = None
    normalized_value: Any = None
    unit: str = ""
    source_profile: str = ""
    source_file: str = ""
    source_sheet: str = ""
    source_cell: str = ""
    transformation: str = ""
    status: str = "MISSING"
    message: str = ""

    def __post_init__(self) -> None:
        self.field_id = str(self.field_id).strip()

        if self.field_id not in CANONICAL_FIELD_SPEC_BY_ID:
            raise ValueError(
                "Field_ID canonique inconnu : "
                f"{self.field_id}"
            )

        self.status = str(self.status).strip().upper() or "MISSING"

        if self.status not in CANONICAL_FIELD_STATUSES:
            raise ValueError(
                "Statut canonique inconnu : "
                f"{self.status}"
            )

        self.source_profile = str(self.source_profile or "").strip().upper()

        if (
            self.source_profile
            and self.source_profile not in CANONICAL_SOURCE_PROFILES
        ):
            raise ValueError(
                "Profil source canonique inconnu : "
                f"{self.source_profile}"
            )

        for attribute in (
            "unit",
            "source_file",
            "source_sheet",
            "source_cell",
            "transformation",
            "message",
        ):
            setattr(self, attribute, str(getattr(self, attribute) or "").strip())

        if _is_missing(self.raw_value) and _is_missing(self.normalized_value):
            self.status = "MISSING"

    @property
    def value(self) -> Any:
        if self.status == "MISSING":
            return None

        if not _is_missing(self.normalized_value):
            return self.normalized_value

        return self.raw_value

    @property
    def missing(self) -> bool:
        return _is_missing(self.value)

    def to_dict(self) -> dict[str, object]:
        spec = CANONICAL_FIELD_SPEC_BY_ID[self.field_id]

        return {
            "field_id": self.field_id,
            "label": spec.label,
            "category": spec.category,
            "type_unit": spec.type_unit,
            "value_type": spec.value_type,
            "requirement": spec.requirement,
            "dabcta_column": spec.dabcta_column,
            "raw_value": self.raw_value,
            "normalized_value": self.normalized_value,
            "value": self.value,
            "unit": self.unit,
            "source_profile": self.source_profile,
            "source_file": self.source_file,
            "source_sheet": self.source_sheet,
            "source_cell": self.source_cell,
            "transformation": self.transformation,
            "status": self.status,
            "message": self.message,
        }


@dataclass
class CanonicalCampaignConfig:
    campaign_id: str
    source_profile: str
    fields: dict[str, CanonicalFieldValue] = field(default_factory=dict)
    schema_version: str = ARCTA_DABCTA_CANONICAL_SCHEMA_VERSION

    def __post_init__(self) -> None:
        self.campaign_id = str(self.campaign_id).strip()
        self.source_profile = str(self.source_profile).strip().upper()

        if not self.campaign_id:
            raise ValueError("campaign_id canonique vide.")

        if self.source_profile not in CANONICAL_SOURCE_PROFILES:
            raise ValueError(
                "Profil source canonique inconnu : "
                f"{self.source_profile}"
            )

        unknown = set(self.fields) - set(CANONICAL_FIELD_SPEC_BY_ID)

        if unknown:
            raise ValueError(
                "Field_ID canoniques inconnus : "
                + ", ".join(sorted(unknown))
            )

        for field_id, value in self.fields.items():
            if value.field_id != field_id:
                raise ValueError(
                    "La clé canonique doit correspondre à field_id."
                )

        for spec in CANONICAL_FIELD_SPECS:
            if spec.field_id not in self.fields:
                self.fields[spec.field_id] = CanonicalFieldValue(
                    field_id=spec.field_id,
                    unit=spec.type_unit if spec.value_type == "float" else "",
                    source_profile=self.source_profile,
                )

    def get_field(self, field_id: str) -> CanonicalFieldValue:
        return self.fields[str(field_id).strip()]

    def set_field(
        self,
        field_id: str,
        *,
        raw_value: Any,
        normalized_value: Any = None,
        unit: str = "",
        source_file: str = "",
        source_sheet: str = "",
        source_cell: str = "",
        transformation: str = "",
        status: str = "EXTRACTED",
        message: str = "",
    ) -> CanonicalFieldValue:
        value = CanonicalFieldValue(
            field_id=field_id,
            raw_value=raw_value,
            normalized_value=normalized_value,
            unit=unit,
            source_profile=self.source_profile,
            source_file=source_file,
            source_sheet=source_sheet,
            source_cell=source_cell,
            transformation=transformation,
            status=status,
            message=message,
        )
        self.fields[field_id] = value
        return value

    def validation_summary(self) -> dict[str, object]:
        missing_calculation = []
        missing_identity = []
        ambiguous = []
        ambiguous_calculation = []
        ambiguous_identity = []

        for spec in CANONICAL_FIELD_SPECS:
            value = self.fields[spec.field_id]

            if value.status == "AMBIGUOUS":
                ambiguous.append(spec.field_id)

                if spec.requirement == "OBLIGATOIRE_CALCUL":
                    ambiguous_calculation.append(spec.field_id)
                elif spec.requirement == "OBLIGATOIRE_ID":
                    ambiguous_identity.append(spec.field_id)

            if not value.missing:
                continue

            if spec.requirement == "OBLIGATOIRE_CALCUL":
                missing_calculation.append(spec.field_id)
            elif spec.requirement == "OBLIGATOIRE_ID":
                missing_identity.append(spec.field_id)

        return {
            "calculation_ready": not (
                missing_calculation or ambiguous_calculation
            ),
            "dabcta_identity_ready": not (
                missing_identity or ambiguous_identity
            ),
            "field_count": len(self.fields),
            "missing_calculation": missing_calculation,
            "missing_identity": missing_identity,
            "ambiguous": ambiguous,
            "ambiguous_calculation": ambiguous_calculation,
            "ambiguous_identity": ambiguous_identity,
        }

    def dabcta_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}

        for spec in CANONICAL_FIELD_SPECS:
            if not spec.dabcta_column:
                continue

            value = self.fields[spec.field_id]
            payload[spec.dabcta_column] = None if value.missing else value.value

        return payload

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "campaign_id": self.campaign_id,
            "scope": "campaign",
            "source_profile": self.source_profile,
            "fields": [
                self.fields[spec.field_id].to_dict()
                for spec in CANONICAL_FIELD_SPECS
            ],
            "validation": self.validation_summary(),
        }


def canonical_campaign_config_from_dict(
    payload: Mapping[str, Any],
) -> CanonicalCampaignConfig:
    schema_version = str(payload.get("schema_version", "")).strip()

    if schema_version not in ARCTA_DABCTA_SUPPORTED_SCHEMA_VERSIONS:
        raise ValueError(
            "Version canonique ARCTA/DABCTA non supportée : "
            f"{schema_version or '(absente)'}"
        )

    raw_fields = payload.get("fields", [])

    if not isinstance(raw_fields, list):
        raise ValueError("canonical.fields doit être une liste.")

    fields: dict[str, CanonicalFieldValue] = {}

    for raw in raw_fields:
        if not isinstance(raw, Mapping):
            raise ValueError("Chaque champ canonique doit être un objet.")

        field_id = str(raw.get("field_id", "")).strip()

        if field_id in fields:
            raise ValueError(
                f"Champ canonique dupliqué dans le JSON : {field_id or '(vide)'}"
            )

        fields[field_id] = CanonicalFieldValue(
            field_id=field_id,
            raw_value=raw.get("raw_value"),
            normalized_value=raw.get("normalized_value"),
            unit=raw.get("unit", ""),
            source_profile=raw.get("source_profile", ""),
            source_file=raw.get("source_file", ""),
            source_sheet=raw.get("source_sheet", ""),
            source_cell=raw.get("source_cell", ""),
            transformation=raw.get("transformation", ""),
            status=raw.get("status", "MISSING"),
            message=raw.get("message", ""),
        )

    return CanonicalCampaignConfig(
        campaign_id=payload.get("campaign_id", ""),
        source_profile=payload.get("source_profile", ""),
        fields=fields,
        # Lecture transparente du contrat 1.0 : le champ 63E2 absent est
        # complété par CanonicalCampaignConfig puis la prochaine sauvegarde
        # sérialise le contrat courant 1.1.
        schema_version=ARCTA_DABCTA_CANONICAL_SCHEMA_VERSION,
    )
