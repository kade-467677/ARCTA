from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

import pandas as pd

from ..models import ColumnSelection
from .trial import analyze_diag_trial

ProgressCallback = Callable[[float, str], None]


def analyze_diag_batch(
    import_sheets: Mapping[str, pd.DataFrame],
    sel: ColumnSelection,
    cfg: Mapping[str, Any],
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """
    Analyse DIAG headless d'une campagne complète.

    Aucun graphe, aucun fichier et aucune UI ne sont produits.
    Les DataFrames retournés correspondent aux sorties scientifiques
    historiques du pré-DIAG.
    """
    rows_summary = []
    rows_pre = []
    rows_balance = []
    rows_cross = []
    rows_autofrein = []
    rows_unwind = []
    trial_results: dict[str, dict[str, Any]] = {}

    items = list(import_sheets.items())

    for i, (trial_id, df) in enumerate(items, start=1):
        trial_id = str(trial_id)

        if progress:
            progress(
                100.0 * i / max(len(items), 1),
                f"DIAG essai {i}/{len(items)} : {trial_id}",
            )

        result = analyze_diag_trial(trial_id, df, sel, cfg)
        trial_results[trial_id] = result

        rows_summary.append(result["summary"])

        if result.get("pre"):
            rows_pre.append(result["pre"])
        if result.get("balance"):
            rows_balance.append(result["balance"])
        if result.get("cross"):
            rows_cross.append(result["cross"])
        if result.get("autofrein"):
            rows_autofrein.append(result["autofrein"])
        if result.get("unwind"):
            rows_unwind.append(result["unwind"])

    diag = {
        "DIAG_SUMMARY": pd.DataFrame(rows_summary),
        "DIAG_PRE_CLEAN": pd.DataFrame(rows_pre),
        "DIAG_BALANCE": pd.DataFrame(rows_balance),
        "DIAG_COUPLE_CROSS": pd.DataFrame(rows_cross),
        "DIAG_AUTOFREIN": pd.DataFrame(rows_autofrein),
        "DIAG_EVENTS": pd.DataFrame(),
        "DIAG_UNWIND": pd.DataFrame(rows_unwind),
    }

    return {
        "diag": diag,
        "trial_results": trial_results,
    }