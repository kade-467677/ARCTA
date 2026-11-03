from __future__ import annotations
from collections.abc import Mapping, Sequence
import pandas as pd

DIAG_SHORT_GROUPS = {
    "Serrage — tension / angle": [
        ("A_contact_Y_eff", "A_contact tension — début de montée en charge"),
        ("A_snug_eff", "A_snug — début de zone de serrage utile"),
        ("Aeff_Ymax", "Angle effectif à Ymax"),
        ("Ymax", "Tension maximale Ymax"),
        ("R2_A0_fit", "Qualité linéaire du fit A0 sur Y=f(A)"),
        ("K_YA_20_50", "Raideur tension/angle sur fenêtre 20–50 %"),
        ("Order_OK_expected_contact_lt_snug_lt_A0", "Ordre attendu A_contact < A_snug < A0"),
    ],
    "Inversion — course morte / torsion résiduelle": [
        ("DeadTravel_DeltaA_deg", "Course morte après inversion — amplitude angulaire"),
        ("Residual_Thread_Torque_Median_Nm", "Couple filet résiduel Xt — médiane sur course morte"),
        ("Residual_Torsional_Stress_Nominal_MPa", "Contrainte nominale de torsion résiduelle"),
        ("Reverse_Pickup_Aeff_deg", "Reprise du couple global en sens inverse"),
        ("Effective_Loosening_Aeff_deg", "Début du desserrage effectif détecté par Y"),
    ],
    "Serrage — couple / angle": [
        ("A0_snug_from_Xg_threshold_eff", "A_snug estimé depuis seuil Xg"),
        ("A0_elastic_from_Xg_eff", "A0 élastique estimé depuis Xg=f(A)"),
        ("A0_shift_Xg_vs_Y", "Décalage A0 couple vs A0 tension"),
        ("K_XgA_20_50", "Raideur couple/angle sur fenêtre 20–50 %"),
        ("A_cross_Xh_Xt_eff", "Croisement Xh / Xt"),
    ],
    "Autofrein pré-A0": [
        ("Autofrein_Xg_preA0_med", "Autofrein Xg médian avant A0"),
        ("Autofrein_Xt_preA0_med", "Autofrein Xt médian avant A0"),
        ("Autofrein_Xg_minus_Xt_preA0_med", "Écart autofrein Xg - Xt avant A0"),
    ],
}

# Contrat partagé par le Desktop historique et le Web pour l'analyse
# robuste ISO 16269-4 des scalaires produits par le DIAG.
DIAG_ISO16269_4_SCALARS = (
    ("DIAG_SUMMARY", "A0_elastic_Y", "Origine élastique brute A0 issue du fit Y=f(A)", "deg"),
    ("DIAG_SUMMARY", "A_contact_Y_eff", "Début de tension mesurable en angle recalé", "deg"),
    ("DIAG_SUMMARY", "A_snug_eff", "Début estimé de mise en tension stabilisée", "deg"),
    ("DIAG_SUMMARY", "Aeff_Ymax", "Angle recalé au maximum de tension", "deg"),
    ("DIAG_SUMMARY", "Ymax", "Maximum de tension", "N"),
    ("DIAG_SUMMARY", "Xgmax", "Maximum du couple global", "Nm"),
    ("DIAG_SUMMARY", "R2_A0_fit", "Qualité R² du fit linéaire A0", "-"),
    ("DIAG_SUMMARY", "K_YA_20_50", "Pente linéaire du fit A0 : dY/dA sur 20–50% Ymax", "N/deg"),
    (
        "DIAG_SUMMARY",
        "A0_snug_from_Xg_threshold_eff",
        "Angle recalé de franchissement du seuil Xg robuste, recherché à rebours depuis A0",
        "deg",
    ),
    (
        "DIAG_SUMMARY",
        "A0_elastic_from_Xg_eff",
        "Origine élastique équivalente issue du fit Xg=f(A_eff), en repère recalé Y",
        "deg",
    ),
    (
        "DIAG_SUMMARY",
        "A0_shift_Xg_vs_Y",
        "Décalage entre l'origine élastique Xg et l'origine élastique Y",
        "deg",
    ),
    (
        "DIAG_SUMMARY",
        "K_XgA_20_50",
        "Pente du fit linéaire Xg=f(A_eff) sur la fenêtre élastique Y 20-50% Ymax",
        "Nm/deg",
    ),
    (
        "DIAG_SUMMARY",
        "R2_XgA_20_50",
        "R² du fit linéaire Xg=f(A_eff) sur la fenêtre élastique Y 20-50% Ymax",
        "-",
    ),
    (
        "DIAG_SUMMARY",
        "Xg_threshold_Nm",
        "Seuil robuste Xg utilisé pour A0_snug_from_Xg_threshold et A0_elastic_from_Xg",
        "Nm",
    ),
    ("DIAG_SUMMARY", "A_elastic_start_eff", "Début de fenêtre de fit A0 en angle recalé", "deg"),
    ("DIAG_SUMMARY", "A_elastic_end_eff", "Fin de fenêtre de fit A0 en angle recalé", "deg"),
    (
        "DIAG_SUMMARY",
        "Unwind_Plateau_DeltaA_deg",
        "Durée angulaire du palier de dévrillage : Amax_eff - A_fin_eff",
        "deg",
    ),
    (
        "DIAG_SUMMARY",
        "Unwind_Plateau_Xt_mean_Nm",
        "Moyenne du couple filets Xt pendant le palier de dévrillage",
        "Nm",
    ),
    (
        "DIAG_SUMMARY",
        "Unwind_Plateau_Xt_median_Nm",
        "Médiane du couple filets Xt pendant le palier de dévrillage",
        "Nm",
    ),
    (
        "DIAG_SUMMARY",
        "Unwind_Plateau_Y_delta_rel",
        "Variation relative de tension pendant le palier de dévrillage",
        "-",
    ),
    (
        "DIAG_SUMMARY",
        "DeadTravel_DeltaA_deg",
        "Course morte de la chaîne d'entraînement après Xg≈0",
        "deg",
    ),
    (
        "DIAG_SUMMARY",
        "Residual_Thread_Torque_Median_Nm",
        "Couple filet Xt résiduel médian sur la course morte",
        "Nm",
    ),
    (
        "DIAG_SUMMARY",
        "Residual_Torsional_Stress_Nominal_MPa",
        "Contrainte de cisaillement nominale maximale due à la torsion résiduelle",
        "MPa",
    ),
    (
        "DIAG_SUMMARY",
        "Reverse_Pickup_Aeff_deg",
        "Angle recalé de reprise du couple global en sens inverse",
        "deg",
    ),
    (
        "DIAG_SUMMARY",
        "Effective_Loosening_Aeff_deg",
        "Angle recalé du début de desserrage effectif détecté par la baisse durable de Y",
        "deg",
    ),
    ("DIAG_PRE_CLEAN", "Intercept_YA_20_50", "Intercept du fit linéaire Y=f(A) utilisé pour A0", "N"),
    ("DIAG_PRE_CLEAN", "N_A0_fit", "Nombre de points utilisés pour le fit A0", "points"),
    ("DIAG_PRE_CLEAN", "Aeff_min", "Borne basse du domaine pré-DIAG recalé", "deg"),
    ("DIAG_PRE_CLEAN", "Aeff_max", "Borne haute du domaine pré-DIAG recalé", "deg"),
    ("DIAG_COUPLE_CROSS", "A_cross_Xh_Xt_eff", "Angle recalé de croisement Xh=Xt", "deg"),
    ("DIAG_COUPLE_CROSS", "Y_cross_Xh_Xt", "Tension au croisement Xh=Xt", "N"),
    ("DIAG_COUPLE_CROSS", "Xg_cross_Xh_Xt", "Couple global au croisement Xh=Xt", "Nm"),
    ("DIAG_COUPLE_CROSS", "Xh_cross_Xh_Xt", "Couple sous tête au croisement Xh=Xt", "Nm"),
    ("DIAG_COUPLE_CROSS", "Xt_cross_Xh_Xt", "Couple filets au croisement Xh=Xt", "Nm"),
    ("DIAG_AUTOFREIN", "Autofrein_Xg_preA0_med", "Autofrein médian T sur [A0−1080° ; A0−360°], fenêtre validée", "Nm"),
    ("DIAG_AUTOFREIN", "Autofrein_Xg_preA0_mean", "Autofrein direct pré-A0, moyenne Xg", "Nm"),
    ("DIAG_AUTOFREIN", "Autofrein_Xg_preA0_std", "Dispersion Xg pré-A0", "Nm"),
    ("DIAG_AUTOFREIN", "Autofrein_Xg_preA0_MAD", "MAD Xg pré-A0", "Nm"),
    ("DIAG_AUTOFREIN", "Autofrein_Xt_preA0_med", "Autofrein direct pré-A0, médiane Xt", "Nm"),
    (
        "DIAG_AUTOFREIN",
        "Autofrein_Xg_minus_Xt_preA0_med",
        "Médiane Xg-Xt pré-A0",
        "Nm",
    ),
    (
        "DIAG_AUTOFREIN",
        "Autofrein_Xg_over_Xt_preA0_med",
        "Médiane Xg/Xt pré-A0",
        "-",
    ),
    (
        "DIAG_BALANCE",
        "TBR_Mean_Nm",
        "Torque Balance Residual signé moyen : R_X = Xg - (Xh + Xt)",
        "Nm",
    ),
    ("DIAG_BALANCE", "TBR_RMS_Nm", "RMS du Torque Balance Residual", "Nm"),
    ("DIAG_BALANCE", "TBR_MaxAbs_Nm", "Maximum absolu du Torque Balance Residual", "Nm"),
    (
        "DIAG_BALANCE",
        "mean_abs_delta_rel",
        "Résidu relatif moyen |Xg-(Xh+Xt)|/|Xg|",
        "-",
    ),
    (
        "DIAG_BALANCE",
        "max_abs_delta_rel",
        "Résidu relatif max |Xg-(Xh+Xt)|/|Xg|",
        "-",
    ),
    ("DIAG_BALANCE", "mean_Xh_over_Xg", "Part moyenne Xh/Xg", "-"),
    ("DIAG_BALANCE", "mean_Xt_over_Xg", "Part moyenne Xt/Xg", "-"),
    (
        "DIAG_BALANCE",
        "TBR_MeanAbsRel_Xg",
        "Résidu moyen absolu rapporté à |Xg|",
        "-",
    ),
    (
        "DIAG_BALANCE",
        "TBR_MaxAbsRel_Xg",
        "Résidu maximal absolu rapporté à |Xg|",
        "-",
    ),
    (
        "DIAG_BALANCE",
        "TBR_MeanAbs_per_Y_Nm_per_N",
        "Résidu moyen absolu rapporté à la tension Y",
        "Nm/N",
    ),
    (
        "DIAG_BALANCE",
        "TBR_Energy_J",
        "Intégrale signée du résidu sur l'angle recalé, en Nm.rad",
        "J",
    ),
    (
        "DIAG_BALANCE",
        "TBR_AbsEnergy_J",
        "Intégrale absolue du résidu sur l'angle recalé, en Nm.rad",
        "J",
    ),
)

DIAG_ISO16269_4_MIN_N = 5
DIAG_ISO16269_4_IQR_WARN_K = 1.5
DIAG_ISO16269_4_IQR_FAIL_K = 3.0
DIAG_ISO16269_4_ROBUST_Z_WARN = 3.5
DIAG_ISO16269_4_ROBUST_Z_FAIL = 5.0

def _flatten_diag_short_groups() -> list[str]:
    out = []
    for _group, items in DIAG_SHORT_GROUPS.items():
        for key, _label in items:
            if key not in out:
                out.append(key)
    return out

DIAG_ISO16269_4_SHORT_VARS = _flatten_diag_short_groups()
DIAG_SHORT_LABELS = {
    key: label
    for _group, items in DIAG_SHORT_GROUPS.items()
    for key, label in items
}
DIAG_REPORT_SHORT_META_COLS = [
    "Trial_ID",
    "Status",
    "Use_For_ARCTA",
    "Main_Flags_FR",
]
DIAG_REPORT_SHORT_ISO_COLS = [
    "ISO16269_4_Max_Severity",
    "ISO16269_4_Outlier_Count",
    "ISO16269_4_Main_Variables",
]
DIAG_REPORT_SHORT_COLS = (
    DIAG_REPORT_SHORT_META_COLS
    + DIAG_ISO16269_4_SHORT_VARS
    + DIAG_REPORT_SHORT_ISO_COLS
)

def normalize_diag_short_vars(vars_in: Sequence[str] | None = None) -> list[str]:
    """Normalise la sélection des indicateurs DIAG Short."""
    allowed = list(DIAG_ISO16269_4_SHORT_VARS)
    if vars_in is None:
        return allowed
    selected = []
    for value in vars_in:
        key = str(value).strip()
        if key in allowed and key not in selected:
            selected.append(key)
    return selected if selected else allowed

def build_diag_report_short_cols(
    selected_vars: Sequence[str] | None = None,
    include_iso: bool = True,
) -> list[str]:
    """Construit les colonnes de la synthèse DIAG courte."""
    vars_clean = normalize_diag_short_vars(selected_vars)
    cols = []
    cols.extend(DIAG_REPORT_SHORT_META_COLS)
    cols.extend(vars_clean)
    if include_iso:
        cols.extend(DIAG_REPORT_SHORT_ISO_COLS)
    out = []
    for col in cols:
        if col not in out:
            out.append(col)
    return out

def build_diag_short_selection_sheet(
    selected_vars: Sequence[str] | None = None,
) -> pd.DataFrame:
    """Feuille d'audit de la sélection DIAG Short."""
    selected = set(normalize_diag_short_vars(selected_vars))
    rows = []
    for group, items in DIAG_SHORT_GROUPS.items():
        for key, label in items:
            rows.append({
                "Group": group,
                "Variable": key,
                "Label_FR": label,
                "Selected": key in selected,
            })
    return pd.DataFrame(rows)

def get_diag_short_vars_from_diag(
    diag: Mapping[str, pd.DataFrame],
) -> list[str]:
    """Récupère la sélection DIAG Short mémorisée dans le run."""
    df = diag.get("DIAG_SHORT_SELECTION", pd.DataFrame())
    if (
        isinstance(df, pd.DataFrame)
        and not df.empty
        and "Variable" in df.columns
        and "Selected" in df.columns
    ):
        selected = []
        for _, row in df.iterrows():
            variable = str(row.get("Variable", "")).strip()
            raw = row.get("Selected", False)
            is_selected = (
                raw is True
                or str(raw).strip().lower() in ("true", "1", "yes", "oui", "x")
            )
            if is_selected:
                selected.append(variable)
        return normalize_diag_short_vars(selected)
    return normalize_diag_short_vars(None)

def build_diag_synthesis(
    diag: Mapping[str, pd.DataFrame],
    selected_vars: Sequence[str] | None = None,
) -> pd.DataFrame:
    """Construit la synthèse DIAG métier courte d'une campagne."""
    summary = diag.get("DIAG_SUMMARY", pd.DataFrame()).copy()
    if summary.empty or "Trial_ID" not in summary.columns:
        return summary
    summary["Trial_ID"] = summary["Trial_ID"].astype(str)

    def merge_missing(sheet_name: str, cols: list[str], suffix: str) -> None:
        nonlocal summary
        df = diag.get(sheet_name, pd.DataFrame()).copy()
        if df.empty or "Trial_ID" not in df.columns:
            return
        df["Trial_ID"] = df["Trial_ID"].astype(str)
        keep = ["Trial_ID"] + [
            col
            for col in cols
            if col in df.columns and col not in summary.columns
        ]
        if len(keep) > 1:
            summary = summary.merge(
                df[keep],
                on="Trial_ID",
                how="left",
                suffixes=("", suffix),
            )

    merge_missing(
        "DIAG_COUPLE_CROSS",
        ["A_cross_Xh_Xt_eff"],
        "_cross",
    )
    merge_missing(
        "DIAG_AUTOFREIN",
        [
            "Autofrein_Xg_preA0_med",
            "Autofrein_Xt_preA0_med",
            "Autofrein_Xg_minus_Xt_preA0_med",
        ],
        "_autofrein",
    )
    merge_missing(
        "DIAG_UNWIND",
        [
            "Unwind_Plateau_Found",
            "Unwind_End_Trigger",
            "Unwind_Amax_eff",
            "Unwind_Xg_negative_Aeff",
            "Unwind_Y_drop_Aeff",
            "Unwind_Plateau_A_start_eff",
            "Unwind_Plateau_A_end_eff",
            "Unwind_Plateau_DeltaA_deg",
            "Unwind_Plateau_Xt_mean_Nm",
            "Unwind_Plateau_Xt_median_Nm",
            "Unwind_Plateau_N_points",
            "Unwind_Plateau_Y_delta_rel",
        ],
        "_unwind",
    )

    iso4 = diag.get(
        "DIAG_ISO16269_4_SUMMARY",
        pd.DataFrame(),
    ).copy()

    if not iso4.empty and "Trial_ID" in iso4.columns:
        iso4["Trial_ID"] = iso4["Trial_ID"].astype(str)
        keep_iso4 = [
            col
            for col in [
                "Trial_ID",
                "ISO16269_4_Outlier_Count",
                "ISO16269_4_Warning_Count",
                "ISO16269_4_Fail_Count",
                "ISO16269_4_Max_Severity",
                "ISO16269_4_Main_Variables",
                "ISO16269_4_Comments_FR",
            ]
            if col in iso4.columns
        ]
        for col in keep_iso4:
            if col != "Trial_ID" and col in summary.columns:
                summary = summary.drop(columns=[col])
        if len(keep_iso4) > 1:
            summary = summary.merge(
                iso4[keep_iso4],
                on="Trial_ID",
                how="left",
            )

    selected_vars = normalize_diag_short_vars(
        selected_vars
        or get_diag_short_vars_from_diag(diag)
    )

    final_cols = [
        col
        for col in build_diag_report_short_cols(
            selected_vars,
            include_iso=True,
        )
        if col in summary.columns
    ]

    if final_cols:
        summary = summary[final_cols].copy()

    return summary
