from __future__ import annotations

from typing import Any, Mapping, Optional

import numpy as np

from .primitives import (
    backward_threshold_crossing_from_a0,
    linear_fit,
    robust_sigma_mad,
    rolling_median,
)


def compute_xg_based_a0_indicators(
        aeff,
        y,
        signals: Mapping[str, Any],
        pre: Mapping[str, Any],
        cfg: Mapping[str, Any],
        a_contact_eff=np.nan,
        autofrein_payload: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """
    Calcule les indicateurs DIAG basés sur Xg.

    La configuration est fournie explicitement via ``cfg``.
    La fonction ne dépend donc d'aucune configuration globale ARCTA.

    Indicateurs principaux :
        - seuil Xg basé sur l'autofrein robuste ;
        - A0_snug_from_Xg_threshold_eff ;
        - tangente élastique Xg=f(A_eff) ;
        - A0_elastic_from_Xg_eff ;
        - décalage A0_Xg par rapport à A0_Y.
    """

    out = {
        "A0_snug_from_Xg_threshold": np.nan,
        "A0_snug_from_Xg_threshold_eff": np.nan,
        "A0_snug_from_Xg_threshold_method": "NA",

        "A0_elastic_from_Xg": np.nan,
        "A0_elastic_from_Xg_eff": np.nan,
        "A0_elastic_from_Xg_eff_raw": np.nan,
        "A0_elastic_from_Xg_method": "NA",

        "A0_shift_Xg_vs_Y": np.nan,

        "K_XgA_20_50": np.nan,
        "Intercept_XgA_20_50": np.nan,
        "R2_XgA_20_50": np.nan,
        "N_XgA_fit": 0,

        "Xg_autofrein_used_Nm": np.nan,
        "Xg_autofrein_source": "NA",
        "Xg_baseline_preA0_Nm": np.nan,
        "Xg_baseline_sigma_preA0_Nm": np.nan,

        "Xg_threshold_Nm": np.nan,

        "Xg_threshold_factor": float(
            cfg.get(
                "xg_threshold_from_autofrein_factor",
                1.05,
            )
        ),

        "Xg_threshold_method":
            "AUTOFRICTION_MEDIAN_X_FACTOR",

        "Xg_at_A0_from_fit_Nm": np.nan,
    }

    Xg = signals.get(
        "Xg"
    )

    if Xg is None:
        return out

    A = np.asarray(
        aeff,
        dtype=float,
    )

    Y = np.asarray(
        y,
        dtype=float,
    )

    Xg = np.asarray(
        Xg,
        dtype=float,
    )

    n = min(
        len(A),
        len(Y),
        len(Xg),
    )

    A = A[:n]
    Y = Y[:n]
    Xg = Xg[:n]

    if n < 10:
        return out

    Xg_s = rolling_median(
        Xg,
        7,
    )

    a0_y_raw = float(
        pre.get(
            "A0_elastic_Y",
            np.nan,
        )
    )

    ymax = float(
        pre.get(
            "Ymax",
            np.nan,
        )
    )

    # --------------------------------------------------------------
    # 1. Autofrein robuste fourni par le DIAG
    # --------------------------------------------------------------
    xg_autofrein = np.nan
    xg_sigma = np.nan
    source = "NA"

    if isinstance(
        autofrein_payload,
        Mapping,
    ):
        for key in (
            "Autofrein_Xg_preA0_med",
            "Autofrein_Xg_preA0_median",
            "Autofrein_Xg_med",
        ):
            try:
                value = float(
                    autofrein_payload.get(
                        key,
                        np.nan,
                    )
                )

                if np.isfinite(
                    value
                ):
                    xg_autofrein = (
                        value
                    )

                    source = key
                    break

            except Exception:
                pass

        # MAD robuste -> sigma équivalent
        for key in (
            "Autofrein_Xg_preA0_MAD",
            "Autofrein_Xg_MAD",
        ):
            try:
                mad = float(
                    autofrein_payload.get(
                        key,
                        np.nan,
                    )
                )

                if np.isfinite(
                    mad
                ):
                    xg_sigma = (
                        1.4826 * mad
                    )
                    break

            except Exception:
                pass

    # --------------------------------------------------------------
    # 2. Fallback si l'autofrein n'est pas fourni
    # --------------------------------------------------------------
    if not np.isfinite(
        xg_autofrein
    ):
        if np.isfinite(
            a_contact_eff
        ):
            base_mask = (
                np.isfinite(A)
                & np.isfinite(Xg_s)
                & (
                    A
                    <= float(
                        a_contact_eff
                    )
                )
            )

        else:
            base_mask = (
                np.isfinite(A)
                & np.isfinite(Xg_s)
                & (A < -60.0)
            )

        if (
            np.isfinite(ymax)
            and ymax > 0
        ):
            base_mask &= (
                np.isfinite(Y)
                & (
                    Y
                    < float(
                        cfg.get(
                            "autofrein_y_max_ratio",
                            0.03,
                        )
                    ) * ymax
                )
            )

        if int(
            np.sum(base_mask)
        ) < 5:
            pre_a0_idx = np.where(
                np.isfinite(A)
                & np.isfinite(Xg_s)
                & (A < 0)
            )[0]

            if len(
                pre_a0_idx
            ):
                n_base = max(
                    5,
                    min(
                        25,
                        (
                            len(pre_a0_idx) // 4
                            if len(pre_a0_idx) >= 20
                            else len(pre_a0_idx)
                        ),
                    ),
                )

                base_vals = Xg_s[
                    pre_a0_idx[
                        :n_base
                    ]
                ]

            else:
                base_vals = Xg_s[
                    :max(
                        5,
                        min(
                            25,
                            n // 10,
                        ),
                    )
                ]

        else:
            base_vals = Xg_s[
                base_mask
            ]

        base_vals = np.asarray(
            base_vals,
            dtype=float,
        )

        base_vals = base_vals[
            np.isfinite(
                base_vals
            )
        ]

        if len(base_vals):
            xg_autofrein = float(
                np.nanmedian(
                    base_vals
                )
            )

            xg_sigma = (
                robust_sigma_mad(
                    base_vals
                )
            )

            source = (
                "FALLBACK_MEDIAN_PREA0"
            )

        else:
            return out

    if not np.isfinite(
        xg_sigma
    ):
        xg_sigma = np.nan

    out[
        "Xg_autofrein_used_Nm"
    ] = float(
        xg_autofrein
    )

    out[
        "Xg_autofrein_source"
    ] = source

    out[
        "Xg_baseline_preA0_Nm"
    ] = float(
        xg_autofrein
    )

    out[
        "Xg_baseline_sigma_preA0_Nm"
    ] = (
        float(
            xg_sigma
        )
        if np.isfinite(
            xg_sigma
        )
        else np.nan
    )

    # --------------------------------------------------------------
    # 3. Seuil Xg = autofrein × facteur
    # --------------------------------------------------------------
    factor = float(
        cfg.get(
            "xg_threshold_from_autofrein_factor",
            1.05,
        )
    )

    xg_threshold = float(
        xg_autofrein
        * factor
    )

    out[
        "Xg_threshold_Nm"
    ] = xg_threshold

    out[
        "Xg_threshold_factor"
    ] = factor

    out[
        "Xg_threshold_method"
    ] = (
        "AUTOFRICTION_MEDIAN_X_FACTOR"
    )

    # --------------------------------------------------------------
    # 4. A_snug Xg :
    #    franchissement backward depuis A0
    # --------------------------------------------------------------
    (
        a_snug_xg_eff,
        _idx_xg,
        method,
    ) = (
        backward_threshold_crossing_from_a0(
            A,
            Xg_s,
            xg_threshold,
            min_consecutive_below=int(
                cfg.get(
                    "contact_min_consecutive",
                    4,
                )
            ),
        )
    )

    if (
        np.isfinite(
            a_snug_xg_eff
        )
        and a_snug_xg_eff > 0
    ):
        a_snug_xg_eff = 0.0

        method = (
            str(method)
            + "_CAPPED_AT_A0"
        )

    out[
        "A0_snug_from_Xg_threshold_eff"
    ] = (
        float(
            a_snug_xg_eff
        )
        if np.isfinite(
            a_snug_xg_eff
        )
        else np.nan
    )

    out[
        "A0_snug_from_Xg_threshold_method"
    ] = method

    if (
        np.isfinite(
            a_snug_xg_eff
        )
        and np.isfinite(
            a0_y_raw
        )
    ):
        out[
            "A0_snug_from_Xg_threshold"
        ] = float(
            a0_y_raw
            + a_snug_xg_eff
        )

    # --------------------------------------------------------------
    # 5. Fit branche élastique Xg=f(A_eff)
    # --------------------------------------------------------------
    a_start = float(
        pre.get(
            "A_elastic_start_eff",
            np.nan,
        )
    )

    a_end = float(
        pre.get(
            "A_elastic_end_eff",
            np.nan,
        )
    )

    fit_mask = (
        np.isfinite(A)
        & np.isfinite(Xg_s)
        & np.isfinite(Y)
        & (A >= a_start)
        & (A <= a_end)
    )

    xg_a0_min_points = int(
        cfg.get(
            "xg_a0_min_points",
            8,
        )
    )

    if int(
        np.sum(fit_mask)
    ) < xg_a0_min_points:

        if (
            np.isfinite(ymax)
            and ymax > 0
        ):
            fit_mask = (
                np.isfinite(A)
                & np.isfinite(Y)
                & np.isfinite(Xg_s)
                & (Y >= 0.20 * ymax)
                & (Y <= 0.50 * ymax)
            )

    if int(
        np.sum(fit_mask)
    ) < xg_a0_min_points:
        return out

    (
        axg,
        bxg,
        r2xg,
        nxg,
    ) = linear_fit(
        A[
            fit_mask
        ],
        Xg_s[
            fit_mask
        ],
    )

    out[
        "K_XgA_20_50"
    ] = axg

    out[
        "Intercept_XgA_20_50"
    ] = bxg

    out[
        "R2_XgA_20_50"
    ] = r2xg

    out[
        "N_XgA_fit"
    ] = int(
        nxg
    )

    if not (
        np.isfinite(axg)
        and abs(axg) > 1e-12
        and np.isfinite(bxg)
    ):
        return out

    out[
        "Xg_at_A0_from_fit_Nm"
    ] = float(
        bxg
    )

    # --------------------------------------------------------------
    # 6. Intersection tangente Xg / autofrein
    # --------------------------------------------------------------
    a0_xg_eff_raw = (
        xg_autofrein
        - bxg
    ) / axg

    out[
        "A0_elastic_from_Xg_eff_raw"
    ] = (
        float(
            a0_xg_eff_raw
        )
        if np.isfinite(
            a0_xg_eff_raw
        )
        else np.nan
    )

    if not np.isfinite(
        a0_xg_eff_raw
    ):
        return out

    if (
        bool(
            cfg.get(
                "xg_a0_reject_positive_eff",
                False,
            )
        )
        and a0_xg_eff_raw > 0
    ):
        out[
            "A0_elastic_from_Xg_method"
        ] = (
            "REJECTED_INTERSECTION_AFTER_A0_Y"
        )

        return out

    out[
        "A0_elastic_from_Xg_eff"
    ] = float(
        a0_xg_eff_raw
    )

    out[
        "A0_elastic_from_Xg_method"
    ] = (
        "INTERSECTION_ELASTIC_XG_WITH_AUTOFRICTION_LEVEL"
        if a0_xg_eff_raw <= 0
        else
        "INTERSECTION_ELASTIC_XG_WITH_AUTOFRICTION_LEVEL_AFTER_A0_Y"
    )

    if np.isfinite(
        a0_y_raw
    ):
        out[
            "A0_elastic_from_Xg"
        ] = float(
            a0_y_raw
            + a0_xg_eff_raw
        )

        out[
            "A0_shift_Xg_vs_Y"
        ] = float(
            a0_xg_eff_raw
        )

    return out