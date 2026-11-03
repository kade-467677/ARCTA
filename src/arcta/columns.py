from __future__ import annotations
from collections.abc import Sequence
import pandas as pd

ARCTA_TRIAL_PREFIXES = (
    "Xg_", "Xh_", "Xt_", "Y_", "A_",
    "µg_", "µh_", "µt_",
)

def group_concat_columns_by_trial(df: pd.DataFrame) -> dict[str, list[str]]:
    """Regroupe les colonnes ARCTA par identifiant d'essai."""
    groups: dict[str, list[str]] = {}
    for c in df.columns:
        s = str(c)
        if not s.startswith(ARCTA_TRIAL_PREFIXES):
            continue
        _, suffix = s.split("_", 1)
        if suffix:
            groups.setdefault(suffix, []).append(c)
    return groups

def pick_first(cols: Sequence[str], prefix: str) -> str | None:
    for c in cols:
        if str(c).startswith(prefix):
            return c
    return None

def var_col_for_trial(cols: Sequence[str], var: str) -> str | None:
    return pick_first(cols, f"{var}_")

def detect_analysis_mode(df_clean: pd.DataFrame) -> str:
    """Détermine le niveau de données mécaniques disponible."""
    cols = [str(c) for c in df_clean.columns]
    if any(c.startswith("Xh_") for c in cols) and any(c.startswith("Xt_") for c in cols):
        return "fine"
    if any(c.startswith("Xg_") for c in cols) and any(c.startswith("Y_") for c in cols):
        return "global"
    return "basic"