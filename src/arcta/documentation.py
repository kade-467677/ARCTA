from __future__ import annotations
import pandas as pd
from .analysis_config import ArctaAnalysisConfig, DEFAULT_ARCTA_ANALYSIS_CONFIG

def build_diag_definitions_sheet(
    analysis_config: ArctaAnalysisConfig = DEFAULT_ARCTA_ANALYSIS_CONFIG,
) -> pd.DataFrame:
    """Glossaire documentaire embarqué dans le résultat ARCTA."""
    rows = [
        {"Sheet": "CONCAT_CLEAN", "Parameter": "A_...", "Definition": "Angle recalé A_eff = A_raw - A0_elastic_Y lorsque A0 est disponible ; CONCAT garde l'angle brut.", "Unit": "deg", "Rule/Threshold": "Recalage depuis DIAG_SUMMARY/DIAG_PRE_CLEAN"},
        {"Sheet": "DIAG_SUMMARY", "Parameter": "A0_elastic_Y", "Definition": "Origine élastique brute : intersection à Y=0 de la tangente Y=f(A) calculée sur la montée de tension.", "Unit": "deg brut", "Rule/Threshold": "Fit linéaire nominal sur 20-50% de Ymax, fallback 25-55/30-60/20-60 si nécessaire"},
        {"Sheet": "DIAG_SUMMARY", "Parameter": "A_contact_Y_eff", "Definition": "Premier angle recalé où la tension devient mesurable au-dessus du bruit initial.", "Unit": "deg recalé", "Rule/Threshold": "Y > max(médiane baseline + 5σ, 0.3% Ymax, seuil absolu) sur plusieurs points consécutifs"},
        {"Sheet": "DIAG_SUMMARY", "Parameter": "A_contact_Y_threshold_mode", "Definition": "Mode de calcul du seuil de détection A_contact_Y.", "Unit": "-", "Rule/Threshold": "max = seuil conservatif historique ; hybrid_backward = moyenne bruit/relatif avec plancher robuste ; mean = moyenne bruit/relatif seule."},
        {"Sheet": "DIAG_SUMMARY", "Parameter": "A_contact_noise_threshold_N", "Definition": "Seuil bruit robuste basé sur la baseline pré-A0.", "Unit": "N", "Rule/Threshold": "median(baseline) + contact_sigma_k × sigma_robuste."},
        {"Sheet": "DIAG_SUMMARY", "Parameter": "A_contact_relative_threshold_N", "Definition": "Seuil relatif à l'échelle de l'essai.", "Unit": "N", "Rule/Threshold": "contact_min_ratio_ymax × Ymax."},
        {"Sheet": "DIAG_SUMMARY", "Parameter": "A_contact_floor_threshold_N", "Definition": "Plancher robuste minimal au-dessus de la baseline.", "Unit": "N", "Rule/Threshold": "median(baseline) + contact_sigma_floor_k × sigma_robuste."},
        {"Sheet": "DIAG_SUMMARY", "Parameter": "A_contact_hybrid_mean_threshold_N", "Definition": "Moyenne entre le seuil bruit robuste et le seuil relatif.", "Unit": "N", "Rule/Threshold": "0.5 × (A_contact_noise_threshold_N + A_contact_relative_threshold_N)."},
        {"Sheet": "DIAG_SUMMARY", "Parameter": "A_snug_eff", "Definition": "Début estimé de mise en tension stabilisée dans le repère recalé.", "Unit": "deg recalé", "Rule/Threshold": "dY/dA > 25% de K_YA_20_50 et Y > 3% Ymax sur plusieurs points consécutifs"},
        {"Sheet": "DIAG_SUMMARY", "Parameter": "Aeff_Ymax", "Definition": "Angle recalé du maximum de tension.", "Unit": "deg recalé", "Rule/Threshold": "A_raw_Ymax - A0_elastic_Y"},
        {"Sheet": "DIAG_SUMMARY", "Parameter": "Ymax", "Definition": "Maximum de force mesurée au serrage, avant décharge du couple ; même détection dans DIAG et CONCAT_CLEAN.", "Unit": "N", "Rule/Threshold": "max(F) avant la fin du pic/plateau T positif précédant l’inversion ; T >= Fmax_torque_min_ratio * Tmax (défaut 0.5)"},
        {"Sheet": "DIAG_SUMMARY", "Parameter": "R2_A0_fit", "Definition": "R² du fit linéaire Y=f(A) utilisé pour calculer A0_elastic.", "Unit": "-", "Rule/Threshold": "Alerte si < 0.995"},
        {"Sheet": "DIAG_SUMMARY", "Parameter": "K_YA_20_50", "Definition": "Pente de la tangente Y=f(A) utilisée pour A0_elastic.", "Unit": "N/deg", "Rule/Threshold": "Pente du fit linéaire sur la fenêtre retenue"},
        {"Sheet": "DIAG_SUMMARY", "Parameter": "A0_fit_window", "Definition": "Fenêtre de tension utilisée pour ajuster la tangente A0.", "Unit": "%Ymax", "Rule/Threshold": "Nominal 0.20-0.50 Ymax ; fallback indiqué le cas échéant"},
        {"Sheet": "DIAG_SUMMARY", "Parameter": "A_elastic_start_eff", "Definition": "Début, en angle recalé, de la fenêtre de points effectivement utilisée pour le fit A0.", "Unit": "deg recalé", "Rule/Threshold": "min(A_raw_fit - A0)"},
        {"Sheet": "DIAG_SUMMARY", "Parameter": "A_elastic_end_eff", "Definition": "Fin, en angle recalé, de la fenêtre de points effectivement utilisée pour le fit A0.", "Unit": "deg recalé", "Rule/Threshold": "max(A_raw_fit - A0)"},
        {"Sheet": "DIAG_SUMMARY", "Parameter": "Order_OK_expected_contact_lt_snug_lt_A0", "Definition": "Vérifie l'ordre indicatif attendu : A_contact_Y_eff < A_snug_eff < 0, car A0 est une origine extrapolée.", "Unit": "bool", "Rule/Threshold": "True si contact avant snug et snug avant A0"},
        {"Sheet": "DIAG_SUMMARY", "Parameter": "A0_snug_from_Xg_threshold", "Definition": "Angle brut où le couple global Xg franchit un seuil robuste, recherché à rebours depuis A0 vers les angles négatifs.", "Unit": "deg brut", "Rule/Threshold": "Seuil = Xg_baseline_preA0 + max(k*sigma robuste, ratio*delta élastique Xg, seuil absolu)"},
        {"Sheet": "DIAG_SUMMARY", "Parameter": "A0_snug_from_Xg_threshold_eff", "Definition": "Même indicateur que A0_snug_from_Xg_threshold, mais dans le repère recalé A_eff = A - A0_elastic_Y.", "Unit": "deg recalé", "Rule/Threshold": "Recherche à rebours depuis A_eff≈0."},
        {"Sheet": "DIAG_SUMMARY", "Parameter": "A0_elastic_from_Xg", "Definition": "Origine élastique équivalente obtenue par extrapolation du fit Xg=f(A_eff) au seuil robuste Xg.", "Unit": "deg brut", "Rule/Threshold": "Fit Xg=f(A_eff) sur la fenêtre élastique Y 20-50% Ymax."},
        {"Sheet": "DIAG_SUMMARY", "Parameter": "A0_elastic_from_Xg_eff", "Definition": "Origine élastique Xg exprimée dans le repère recalé Y ; correspond au décalage relatif à A0_elastic_Y.", "Unit": "deg recalé", "Rule/Threshold": "A0_elastic_from_Xg_eff = A0_elastic_from_Xg - A0_elastic_Y."},
        {"Sheet": "DIAG_SUMMARY", "Parameter": "A0_shift_Xg_vs_Y", "Definition": "Décalage entre l'origine élastique issue du couple global Xg et celle issue de la tension Y.", "Unit": "deg", "Rule/Threshold": "A0_shift_Xg_vs_Y = A0_elastic_from_Xg - A0_elastic_Y."},
        {"Sheet": "DIAG_SUMMARY", "Parameter": "K_XgA_20_50", "Definition": "Pente de la tangente Xg=f(A_eff) calculée sur la même fenêtre élastique que A0_elastic_Y.", "Unit": "Nm/deg", "Rule/Threshold": "Fenêtre nominale Y entre 20% et 50% de Ymax."},
        {"Sheet": "DIAG_COUPLE_CROSS", "Parameter": "A_cross_Xh_Xt_eff", "Definition": "Angle recalé du premier croisement Xh = Xt avant A0. Indicateur exploratoire de transition filets/sous-tête.", "Unit": "deg recalé", "Rule/Threshold": "Recherche préférentielle entre A_contact et A0 ; fallback sur pré-A0 complet"},
        {"Sheet": "DIAG_AUTOFREIN", "Parameter": "Autofrein_Xg_preA0_med", "Definition": "Médiane du couple global dans la zone pré-A0 supposée représentative de l'autofrein direct.", "Unit": "Nm", "Rule/Threshold": "Fenêtre fixe [-1080°, -360°] au vissage ; zéro tension contrôlé, sans repli ; méthode A0_MINUS_3_TO_MINUS_1_TURNS_V1"},
        {"Sheet": "DIAG_AUTOFREIN", "Parameter": "Autofrein_Xt_preA0_med", "Definition": "Médiane du couple filets dans la zone pré-A0 ; attendu proche de Xg si Xh est nul/faible avant appui sous tête.", "Unit": "Nm", "Rule/Threshold": "Même fenêtre que Autofrein_Xg_preA0_med"},
        {"Sheet": "DIAG_AUTOFREIN", "Parameter": "Autofrein_Xg_minus_Xt_preA0_med", "Definition": "Médiane de Xg-Xt avant A0 ; proche de 0 si le couple global est essentiellement porté par les filets/autofrein.", "Unit": "Nm", "Rule/Threshold": "Indicateur exploratoire, non pénalisant"},
        {"Sheet": "TEST_COMPUTE_*", "Parameter": "STAT_MEDIAN_CI_LOW / STAT_MEDIAN_CI_HIGH", "Definition": "Bornes de l'intervalle de confiance de la médiane selon ISO 16269-7, calculées par statistiques d'ordre (approche non paramétrique exacte).", "Unit": "selon variable", "Rule/Threshold": f"Confiance cible = {analysis_config.iso_median_conf_level:.3g}; intervalle fini le plus étroit documenté avec confiance effectivement atteinte"},
        {"Sheet": "TEST_COMPUTE_*", "Parameter": "STAT_MEDIAN_CI_CONF_ACTUAL", "Definition": "Niveau de confiance effectivement atteint par l'intervalle de médiane retenu.", "Unit": "-", "Rule/Threshold": "Peut être < confiance cible pour petits effectifs (discrétisation binomiale)"},
        {"Sheet": "TEST_COMPUTE_*", "Parameter": "STAT_MEDIAN_CI_ORDER_LOW / STAT_MEDIAN_CI_ORDER_HIGH", "Definition": "Rangs des statistiques d'ordre utilisées pour l'IC de médiane ISO 16269-7.", "Unit": "indices 1-based", "Rule/Threshold": "Basé sur l'inversion du test des signes / loi binomiale"},
        {"Sheet": "TEST_COMPUTE_*", "Parameter": "STAT_MEDIAN_CI_STATUS", "Definition": "Statut du calcul de l'IC de médiane.", "Unit": "OK/UNDER_TARGET", "Rule/Threshold": "UNDER_TARGET si aucun intervalle fini n'atteint exactement la confiance cible"},
        {"Sheet": "DIAG_ISO16269_4_OUTLIERS", "Parameter": "Outlier_Level", "Definition": "Diagnostic robuste ISO 16269-4 appliqué aux scalaires DIAG par campagne. WARNING/FAIL signale une valeur atypique à revoir, sans exclusion automatique.", "Unit": "OK/WARNING/FAIL", "Rule/Threshold": "MAD robust z : warning >=3.5, fail >=5 ; fences IQR : warning 1.5 IQR, fail 3 IQR"},
        {"Sheet": "DIAG_ISO16269_4_OUTLIERS", "Parameter": "K_YA_20_50", "Definition": "La pente linéaire utilisée pour A0_elastic est incluse dans l'analyse ISO 16269-4 des scalaires.", "Unit": "N/deg", "Rule/Threshold": "Variable expertisée comme scalaire d'essai"},
        {"Sheet": "SELF_LOCK_REFIT", "Parameter": "Autofrein_b_refit_Nm", "Definition": "Autofrein estimé par refit linéaire Xg = aY + b sur le début de montée en tension [5%;10%]Ymax.", "Unit": "Nm", "Rule/Threshold": "b = Xg extrapolé à Y=0 ; fallback [3%;15%] si points insuffisants"},
        {"Sheet": "AUTOFREIN_COMPARISON", "Parameter": "Delta_refit_minus_DIAG_preA0_Nm", "Definition": "Écart entre autofrein par refit linéaire dans CONCAT_CLEAN et autofrein direct DIAG pré-A0.", "Unit": "Nm", "Rule/Threshold": "OK si |delta| <= max(0.5 Nm, 15% du niveau comparé)"},
        {"Sheet": "AUTOFREIN_COMPARISON", "Parameter": "Autofrein_Compatibility_Flag", "Definition": "Compatibilité entre l'autofrein refit et l'autofrein DIAG pré-A0.", "Unit": "OK/WARNING/NO_DIAG_COMPARISON", "Rule/Threshold": "Tolérance V0 paramétrée dans build_autofrein_comparison"},
        {"Sheet": "DIAG_BALANCE", "Parameter": "Balance_Flag", "Definition": "Indicateur exploratoire de résidu Xg-(Xh+Xt). Attention : Xg contient une part géométrique dans Kellermann & Klein, donc ce flag n'est pas pénalisant.", "Unit": "OK/WARNING/FAIL", "Rule/Threshold": "OK si mean_abs_delta_rel <= 8%; WARNING si >8%; FAIL si >15%"},
        {"Sheet": "DIAG_BALANCE", "Parameter": "mean_abs_delta_rel", "Definition": "Moyenne de |Xg-(Xh+Xt)|/|Xg| sur zone valide.", "Unit": "-", "Rule/Threshold": "Zone valide : points finis avec Y > 5%Ymax et |Xg|>0"},
        {"Sheet": "DIAG_BALANCE", "Parameter": "max_abs_delta_rel", "Definition": "Maximum de |Xg-(Xh+Xt)|/|Xg| sur zone valide.", "Unit": "-", "Rule/Threshold": "Indicateur d'événement local, non utilisé seul pour Balance_Flag"},
        {"Sheet": "DIAG_BALANCE", "Parameter": "mean_delta_Xg_minus_XhXt_Nm", "Definition": "Écart moyen signé Xg-(Xh+Xt).", "Unit": "Nm", "Rule/Threshold": "Signe positif : Xg mesuré > somme composantes"},
        {"Sheet": "DIAG_BALANCE", "Parameter": "max_abs_delta_Xg_minus_XhXt_Nm", "Definition": "Écart absolu maximal entre Xg et Xh+Xt.", "Unit": "Nm", "Rule/Threshold": "Indicateur de pic ou incohérence locale"},
        {"Sheet": "DIAG_BALANCE", "Parameter": "mean_Xh_over_Xg", "Definition": "Part moyenne du couple sous-tête dans le couple global.", "Unit": "-", "Rule/Threshold": "Calculée sur la même zone valide que le bilan"},
        {"Sheet": "DIAG_BALANCE", "Parameter": "mean_Xt_over_Xg", "Definition": "Part moyenne du couple filets dans le couple global.", "Unit": "-", "Rule/Threshold": "Calculée sur la même zone valide que le bilan"},
        {"Sheet": "DIAG_BALANCE", "Parameter": "Torque Balance Residual / TBR", "Definition": "Résidu de bilan couple défini par R_X(A) = Xg(A) - [Xh(A) + Xt(A)].", "Unit": "Nm", "Rule/Threshold": "Indicateur exploratoire ; ne doit pas exclure seul un essai."},
        {"Sheet": "DIAG_BALANCE", "Parameter": "TBR_Mean_Nm", "Definition": "Moyenne signée du résidu R_X sur la zone valide.", "Unit": "Nm", "Rule/Threshold": "Zone valide : points finis avec Y > tbr_y_min_ratio × Ymax et |Xg| > tbr_xg_min_abs_Nm."},
        {"Sheet": "DIAG_BALANCE", "Parameter": "TBR_RMS_Nm", "Definition": "RMS du résidu R_X, sensible aux écarts persistants et aux pics.", "Unit": "Nm", "Rule/Threshold": "Indicateur scalaire expertisé par ISO16269-4."},
        {"Sheet": "DIAG_BALANCE", "Parameter": "TBR_MaxAbs_Nm", "Definition": "Maximum absolu de |R_X| sur la zone valide.", "Unit": "Nm", "Rule/Threshold": "Indicateur d'événement local ou d'incohérence ponctuelle."},
        {"Sheet": "DIAG_BALANCE", "Parameter": "TBR_MeanAbsRel_Xg", "Definition": "Moyenne de |R_X| / |Xg| sur la zone valide.", "Unit": "-", "Rule/Threshold": "Utilisé pour Balance_Flag : OK/WARNING/FAIL selon balance_rel_warn / balance_rel_fail."},
        {"Sheet": "DIAG_BALANCE", "Parameter": "TBR_MeanAbs_per_Y_Nm_per_N", "Definition": "Moyenne de |R_X| / Y. Permet de rapporter le résidu couple à la tension générée.", "Unit": "Nm/N", "Rule/Threshold": "Indicateur exploratoire de rendement mécanique apparent du résidu."},
        {"Sheet": "DIAG_BALANCE", "Parameter": "TBR_Energy_J / TBR_AbsEnergy_J", "Definition": "Intégrale signée / absolue du résidu R_X sur l'angle recalé converti en radians.", "Unit": "J", "Rule/Threshold": "Calculé seulement si A_eff est disponible ; reflète l'accumulation angulaire du résidu."},
    ]
    rows.append({
        "Sheet": "*_COMPUTE_*",
        "Parameter": "STAT_TOL_NP_* / STAT_TOL_STATUS",
        "Definition": "Tolérance bilatérale non paramétrique par rangs centraux fixes (Wilks). "
        "CONF_ACTUAL : confiance atteinte ; CONF_MAX : confiance avec les extrêmes ; "
        "MIN_N_REQUIRED : effectif minimal. INSUFFICIENT_N : bornes absentes, "
        "min/max descriptifs conservés. P et CONF restent des objectifs.",
        "Unit": "selon variable / probabilités / effectifs",
        "Rule/Threshold": "Observations indépendantes de même population continue. "
        "Contrôle ponctuel à chaque abscisse, sans garantie simultanée de courbe. "
        "Rangs choisis selon N, proportion et confiance, jamais selon la largeur observée. "
        "Les polynômes ajustés aux bornes restent des approximations graphiques.",
    })
    return pd.DataFrame(rows)
