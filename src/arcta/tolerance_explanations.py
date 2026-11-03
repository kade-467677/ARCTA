"""63F0A: explain existing pointwise decisions without changing calculations."""
import textwrap

import numpy as np
import pandas as pd


REASONS = {
    "NO_DATA": "Aucune valeur d'essai disponible à cette position.",
    "VALID_FRACTION": "Moins de la moitié des essais ont une valeur disponible : calcul de tolérance non effectué.",
    "TOO_FEW_VALUES": "Moins de deux valeurs disponibles : calcul de tolérance non effectué.",
    "CONSTANT_VALUES": "Dispersion nulle : l'intervalle paramétrique n'est pas calculable par la procédure actuelle.",
    "NORMALITY_SAMPLE": "Effectif inférieur au minimum configuré pour le test de normalité : méthode non paramétrique retenue.",
    "NORMALITY_UNAVAILABLE": "Test de normalité indisponible ou non fini : méthode non paramétrique retenue.",
    "NORMALITY_REJECTED": "Normalité rejetée par le test de Shapiro : méthode non paramétrique retenue.",
    "PARAMETRIC_UNAVAILABLE": "Normalité non rejetée, mais calcul des bornes paramétriques indisponible : méthode non paramétrique retenue.",
    "PARAMETRIC": "Normalité non rejetée : méthode paramétrique retenue sous hypothèse de normalité.",
    "UNKNOWN": "Cause du choix de méthode non enregistrée dans cet ancien résultat ; relancer une exécution pour la tracer.",
}


def annotate_tolerance(df, config, total, eligible):
    reasons = []
    for pos, (_, row) in enumerate(df.iterrows()):
        n, pvalue = row["STAT_N"], row["STAT_SHAPIRO_P"]
        if n == 0:
            reason = "NO_DATA"
        elif not eligible[pos]:
            reason = "VALID_FRACTION"
        elif n < 2:
            reason = "TOO_FEW_VALUES"
        elif row["STAT_TOL_KIND"] == "param":
            reason = "PARAMETRIC"
        elif row["STAT_STD"] == 0:
            reason = "CONSTANT_VALUES"
        elif n < config.normality_min_n:
            reason = "NORMALITY_SAMPLE"
        elif not np.isfinite(pvalue):
            reason = "NORMALITY_UNAVAILABLE"
        elif pvalue < config.normality_alpha:
            reason = "NORMALITY_REJECTED"
        else:
            reason = "PARAMETRIC_UNAVAILABLE"
        reasons.append(reason)
    df["STAT_TOL_AUDIT_REASON"] = reasons
    df["STAT_TOL_AUDIT_ALPHA"] = config.normality_alpha
    df["STAT_TOL_AUDIT_NORMALITY_MIN_N"] = config.normality_min_n
    df["STAT_TOL_AUDIT_TOTAL"] = total
    return df


def number(value):
    value = float(value)
    if not np.isfinite(value):
        return "indisponible"
    return (f"{value:.2e}" if value and (abs(value) < .01 or abs(value) >= 1e5)
            else f"{value:.2f}".rstrip("0").rstrip(".")).replace(".", ",")


def span(values, percent=False):
    values = pd.to_numeric(values, errors="coerce").to_numpy(dtype=float)
    values = values[np.isfinite(values)]
    if not len(values):
        return "indisponible"
    scale, suffix = (100, " %") if percent else (1, "")
    low, high = values.min() * scale, values.max() * scale
    return number(low) + (" à " + number(high) if high != low else "") + suffix


def tolerance_details(sheets, warnings_only=False):
    """One row per contiguous grid segment with the same calculation decision."""
    rows = []
    for name, df in sheets.items():
        if not isinstance(df, pd.DataFrame) or df.empty:
            continue
        needed = {"STAT_TOL_KIND", "STAT_N", "STAT_TOL_P", "STAT_TOL_CONF",
                  "STAT_TOL_LOW", "STAT_TOL_HIGH", "STAT_TOL_NP_MIN_N_REQUIRED"}
        if not needed.issubset(df.columns):
            continue
        keys = [c for c in ("STAT_TOL_KIND", "STAT_TOL_STATUS", "STAT_TOL_AUDIT_REASON",
                "STAT_TOL_P", "STAT_TOL_CONF") if c in df]
        # Compare positions, not dataframe index labels; never merge disjoint zones.
        grouping = df[keys].fillna("").copy()
        grouping["available"] = np.isfinite(df[["STAT_TOL_LOW", "STAT_TOL_HIGH"]].to_numpy(dtype=float)).all(axis=1)
        groups = grouping.ne(grouping.shift()).any(axis=1).cumsum()
        for _, group in df.groupby(groups, sort=False):
            first = group.iloc[0]
            available = np.isfinite(group[["STAT_TOL_LOW", "STAT_TOL_HIGH"]].to_numpy(dtype=float)).all()
            if warnings_only and available:
                continue
            kind = first["STAT_TOL_KIND"]
            reason = first.get("STAT_TOL_AUDIT_REASON", "UNKNOWN")
            cause = REASONS.get(reason, REASONS["UNKNOWN"])
            if reason == "NORMALITY_REJECTED":
                cause += " Seuil alpha = " + number(first["STAT_TOL_AUDIT_ALPHA"]) + "."
            if reason == "NORMALITY_SAMPLE":
                cause += " Minimum : " + number(first["STAT_TOL_AUDIT_NORMALITY_MIN_N"]) + " essais."
            target = f"proportion {number(first['STAT_TOL_P'] * 100)} % / confiance {number(first['STAT_TOL_CONF'] * 100)} %"
            required = int(first["STAT_TOL_NP_MIN_N_REQUIRED"])
            n = span(group["STAT_N"])
            axis = str(df.columns[0])
            if axis == "Abscisse" and "COMPUTE_" in str(name):
                role = str(name).split("COMPUTE_", 1)[1].split("f")[-1]
                if role in {"A", "Y", "Xg", "Xt", "Xh"}:
                    axis = role
            axis = {"A": "Angle recalé (°)", "Y": "Tension (N)",
                    "Xg": "Couple global (N·m)", "Xt": "Couple filet (N·m)",
                    "Xh": "Couple sous-tête (N·m)"}.get(axis, axis)
            coordinates = pd.to_numeric(group.iloc[:, 0], errors="coerce")
            zone = span(coordinates) if coordinates.notna().all() else "coordonnées indisponibles"
            maximum = span(group["STAT_TOL_NP_CONF_MAX"], True) if "STAT_TOL_NP_CONF_MAX" in group else "indisponible"
            if available and kind == "param":
                outcome = "Bornes tracées sous hypothèse normale ; le test ne prouve pas cette hypothèse."
            elif available:
                actual = span(group["STAT_TOL_NP_CONF_ACTUAL"], True)
                outcome = f"Objectif atteint par les rangs retenus ; confiance obtenue : {actual}. Bornes tracées."
            elif kind == "nonparam" and first.get("STAT_TOL_NP_STATUS") == "INSUFFICIENT_N":
                outcome = (f"Objectif non atteint : {n} essais disponibles ; au moins {required} requis pour cette méthode. "
                           f"Confiance maximale avec minimum–maximum : {maximum}, pour la proportion demandée. "
                           "Enveloppe de tolérance non tracée sur cette zone.")
            else:
                outcome = "Bornes indisponibles : les conditions de calcul ne sont pas réunies."
            explanation = (cause + " Objectif : " + target + ". " + outcome
                           + " Les courbes et statistiques disponibles sont conservées ; l'absence d'enveloppe ne signifie pas une baisse du signal. "
                           "Évaluation ponctuelle sous hypothèses d'essais indépendants issus d'une même population continue ; sans garantie simultanée de toute la courbe.")
            rows.append({"Feuille": str(name), "Coordonnée": axis, "Plage": zone,
                         "Positions de grille": len(group), "Méthode": kind or "non évaluée",
                         "Cause": cause, "N valides": n, "N requis": required if kind == "nonparam" else "",
                         "Cible proportion / confiance": target,
                         "Confiance max. avec les extrêmes": maximum if kind == "nonparam" else "",
                         "Bornes disponibles": bool(available), "Explication": explanation})
    return pd.DataFrame(rows)


def graph_explanation(df, axis_label):
    details = tolerance_details({"graphe": df}, warnings_only=True)
    if details.empty:
        return ""
    parts = []
    for _, row in details.head(2).iterrows():
        parts.append(f"{axis_label} : {row['Plage']}. {row['Cause']}")
        if row["Méthode"] == "nonparam" and row["N requis"]:
            parts.append(f"Objectif {row['Cible proportion / confiance']} ; {row['N valides']} essais disponibles, {row['N requis']} requis.")
            parts.append(f"Confiance maximale avec minimum–maximum : {row['Confiance max. avec les extrêmes']} pour la proportion demandée.")
    if len(details) > 2:
        parts.append(f"{len(details)} plages au total ; détail complet dans ARCTA_TOLERANCE_DETAILS et le rapport PDF.")
    parts.append("Seule l'enveloppe orange est interrompue ; les données disponibles restent tracées. Les positions de grille ne sont pas des essais.")
    return "\n".join(textwrap.fill(part, width=125) for part in parts)


def pdf_explanations(sheets):
    details = tolerance_details(sheets, warnings_only=True)
    if details.empty:
        return details
    return pd.DataFrame({
        "Zone": details.apply(lambda row: f"{row['Feuille']} — {row['Coordonnée']} : {row['Plage']} ({row['Positions de grille']} positions de grille)", axis=1),
        "Explication": details["Explication"],
    })
