"""Synthèse CONFIG lisible ; réglages exclusivement issus des résultats du run."""
import math
import pandas as pd

SETTINGS = (
    ("MEAN_CI_CONF_LEVEL", "Confiance de l’intervalle de la moyenne", "%"),
    ("THR_RATIO_DEFAULT", "Seuil bas de tension pour les recalculs", "% de Y maximal"),
    ("ISO_TOL_P_CONTENT", "Proportion de population visée — ISO 16269-6", "%"),
    ("ISO_TOL_CONF_LEVEL", "Confiance de la tolérance — ISO 16269-6", "%"),
    ("ISO_MEDIAN_CONF_LEVEL", "Confiance de l’intervalle de la médiane — ISO 16269-7", "%"),
    ("NORMALITY_ALPHA", "Seuil du test de normalité Shapiro", "%"),
    ("NORMALITY_MIN_N", "Effectif minimal pour tester la normalité", "essais"),
)


def build_config_summary(canonical, constants, archived):
    rows = []
    for field in (canonical or {}).get("fields", []):
        rows.append({"Section": "Configuration", "Code": field["field_id"],
                     "Libellé": field.get("label", field["field_id"]),
                     "Valeur": field.get("value"), "Unité": field.get("unit", ""),
                     "Source": field.get("source_file", ""),
                     "Statut": field.get("status", "")})
    for key, value in constants.items():
        rows.append({"Section": "Constantes de calcul", "Code": key,
                     "Libellé": key, "Valeur": value, "Unité": "",
                     "Source": "Constantes du run", "Statut": "Utilisé"})
    values = {}
    if isinstance(archived, pd.DataFrame) and {"Parameter", "Value"}.issubset(archived.columns):
        for key, group in archived.groupby("Parameter"):
            if len(group) == 1:
                values[key] = group.iloc[0]["Value"]
    for key, label in (("TORQUE_BASIS", "Convention du couple : TOTAL mesuré / EFFECTIVE corrigé / DUAL les deux"),
                       ("KK_MODEL", "Modèle de calcul K&K"),
                       ("SELFLOCK_METHOD", "Méthode de correction de l’autofrein")):
        if key in values:
            rows.append({"Section":"Modèle mécanique", "Code":key, "Libellé":label,
                         "Valeur":values[key], "Unité":"", "Source":"ARCTA_SETTINGS du run", "Statut":"Utilisé"})
    for key, label, unit in SETTINGS:
        raw = values.get(key)
        value, status = None, "Non renseigné ou ambigu"
        try:
            number = float(raw)
            valid = math.isfinite(number) and not isinstance(raw, bool)
            if key == "NORMALITY_MIN_N":
                valid = valid and number.is_integer() and 3 <= number <= 5000
                converted = int(number) if valid else None
            else:
                valid = valid and (0 <= number < 1 if key == "THR_RATIO_DEFAULT" else 0 < number < 1)
                converted = round(number * 100, 10) if valid else None
            if valid:
                value, status = converted, "Utilisé"
        except (ValueError, TypeError, OverflowError):
            pass
        rows.append({"Section": "Statistiques et recalculs", "Code": key,
                     "Libellé": label, "Valeur": value, "Unité": unit,
                     "Source": "ARCTA_SETTINGS du run", "Statut": status})
    return pd.DataFrame(rows, columns=["Section", "Code", "Libellé", "Valeur", "Unité", "Source", "Statut"])
