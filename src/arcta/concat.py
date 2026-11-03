from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np
import pandas as pd

from cta_core.diag.tightening import tightening_peak
from cta_core.config import DEFAULT_DIAG_NUMERICAL_CONFIG
from cta_core.models import ColumnSelection
from cta_core.parsing import coerce_numeric_series

from .analysis_config import DEFAULT_ARCTA_ANALYSIS_CONFIG
from .columns import group_concat_columns_by_trial, pick_first


def build_concat_df(
    import_sheets: Mapping[str, pd.DataFrame],
    sel: ColumnSelection,
    accepted: Sequence[str],
) -> pd.DataFrame:
    """
    Construit CONCAT en mémoire.

    Les colonnes source sont renommées selon la convention :
        <Role>_<Trial_ID>

    Les noms source restent tracés séparément dans ARCTA_COLUMN_MAP.
    """
    blocks = []
    accepted_set = set(map(str, accepted))

    for trial_id, df in import_sheets.items():
        trial_id = str(trial_id)

        if trial_id not in accepted_set:
            continue

        block = {}

        for role in ("Xg", "Xh", "Xt", "A", "Y"):
            col = sel.roles.get(role)

            if col and col in df.columns:
                block[f"{role}_{trial_id}"] = (
                    coerce_numeric_series(df[col])
                    .reset_index(drop=True)
                )

        if block:
            blocks.append(
                pd.DataFrame(block)
            )

    if not blocks:
        raise RuntimeError(
            "Aucun essai accepté exploitable."
        )

    return pd.concat(
        blocks,
        axis=1,
    )


def build_column_map_sheet(
    sel: ColumnSelection,
    accepted: Sequence[str],
) -> pd.DataFrame:
    rows = []

    for trial_id in accepted:
        for role, source in sel.roles.items():
            if source:
                rows.append({
                    "Trial_ID": str(trial_id),
                    "Role": role,
                    "Source_Column": source,
                    "Output_Column":
                        f"{role}_{trial_id}",
                })

    return pd.DataFrame(rows)


def _build_a0_lookup_from_diag(
    diag: Mapping[
        str,
        pd.DataFrame,
    ] | None,
) -> dict[str, float]:
    """
    Récupère A0_elastic_Y par Trial_ID depuis les feuilles DIAG.

    L'ordre historique est conservé :
        DIAG_SUMMARY puis DIAG_PRE_CLEAN.

    Si les deux feuilles contiennent le même Trial_ID,
    la dernière valeur valide rencontrée est conservée.
    """
    out: dict[str, float] = {}

    if not diag:
        return out

    for sheet_name in (
        "DIAG_SUMMARY",
        "DIAG_PRE_CLEAN",
    ):
        df = diag.get(sheet_name)

        if (
            not isinstance(df, pd.DataFrame)
            or df.empty
        ):
            continue

        if (
            "Trial_ID" not in df.columns
            or "A0_elastic_Y" not in df.columns
        ):
            continue

        for _, row in df.iterrows():
            trial_id = str(
                row.get(
                    "Trial_ID",
                    "",
                )
            )

            a0 = pd.to_numeric(
                pd.Series([
                    row.get(
                        "A0_elastic_Y"
                    )
                ]),
                errors="coerce",
            ).iloc[0]

            if (
                trial_id
                and np.isfinite(a0)
            ):
                out[trial_id] = float(a0)

    return out


def build_concat_clean_df(
    df_concat: pd.DataFrame,
    thr_ratio: float = DEFAULT_ARCTA_ANALYSIS_CONFIG.thr_ratio,
    diag: Mapping[
        str,
        pd.DataFrame,
    ] | None = None,
) -> pd.DataFrame:
    """
    Construit CONCAT_CLEAN.

    Pour chaque essai :
      - recherche Ymax ;
      - conserve la montée depuis le premier point
        Y >= thr_ratio * Ymax ;
      - s'arrête au point Ymax ;
      - recale A en A_eff = A_raw - A0_elastic_Y
        lorsque A0 est disponible.
    """
    groups = group_concat_columns_by_trial(
        df_concat
    )

    a0_lookup = (
        _build_a0_lookup_from_diag(
            diag
        )
    )

    blocks = []

    for trial_id, cols in groups.items():
        y_col = pick_first(
            cols,
            "Y_",
        )

        if not y_col:
            continue

        y = coerce_numeric_series(
            df_concat[y_col]
        ).to_numpy(dtype=float)

        if (
            len(y) < 5
            or not np.isfinite(y).any()
        ):
            continue

        def channel(role):
            name = pick_first(cols, role + "_")
            return coerce_numeric_series(df_concat[name]).to_numpy(dtype=float) if name else None

        peak_cfg = DEFAULT_DIAG_NUMERICAL_CONFIG.to_dict()
        # Rejoue exactement le seuil archivé par le DIAG de cet essai.
        summary = diag.get("DIAG_SUMMARY") if diag else None
        if isinstance(summary, pd.DataFrame) and {"Trial_ID", "Fmax_torque_min_ratio"}.issubset(summary.columns):
            rows = summary[summary["Trial_ID"].astype(str) == str(trial_id)]
            if len(rows) == 1:
                peak_cfg["fmax_torque_min_ratio"] = float(rows.iloc[0]["Fmax_torque_min_ratio"])
        try:
            peak = tightening_peak(y, channel("Xg"), channel("A"), peak_cfg)
        except ValueError as exc:
            raise ValueError(f"Essai {trial_id} : maximum au serrage indéterminé ({exc})") from exc
        ymax, idx_ymax = peak["Ymax"], peak["idx_ymax"]

        y_rising = y[
            :idx_ymax + 1
        ]

        valid = np.where(
            (y_rising >= thr_ratio * ymax)
            & np.isfinite(y_rising)
        )[0]

        if not len(valid):
            continue

        i0 = int(valid[0])
        i1 = idx_ymax

        a0 = a0_lookup.get(
            str(trial_id),
            np.nan,
        )

        block = {}

        for col in cols:
            series = (
                coerce_numeric_series(
                    df_concat[col]
                )
                .iloc[i0:i1 + 1]
                .reset_index(drop=True)
            )

            if (
                str(col).startswith("A_")
                and np.isfinite(a0)
            ):
                series = (
                    series
                    - float(a0)
                )

            block[col] = series

        blocks.append(
            pd.DataFrame(block)
        )

    if not blocks:
        raise RuntimeError(
            "CONCAT_CLEAN mémoire vide."
        )

    return pd.concat(
        blocks,
        axis=1,
    )