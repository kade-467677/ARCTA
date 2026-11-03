from __future__ import annotations

from typing import Any, Mapping

import numpy as np

from .primitives import (
    _first_index_at_or_after_a0,
    backward_threshold_crossing_from_a0,
    compute_contact_threshold_y,
    first_consecutive,
    robust_sigma_mad,
    rolling_median,
    safe_gradient_by_angle,
)


def detect_contact_and_snug(
        aeff: np.ndarray,
        y: np.ndarray,
        pre: Mapping[str, Any],
        cfg: Mapping[str, Any],
) -> dict[str, float]:
    """
    Détection de A_contact_Y et A_snug.

    La configuration est fournie explicitement par ``cfg``.
    Cette fonction ne dépend donc d'aucune variable globale ARCTA.

    A_contact_Y :
        recherche prioritaire à rebours depuis A0.

    A_snug :
        détection par pente dY/dA après le contact
        et avant A0.
    """

    A = np.asarray(
        aeff,
        dtype=float,
    )

    Y = np.asarray(
        y,
        dtype=float,
    )

    n = min(
        len(A),
        len(Y),
    )

    A = A[:n]
    Y = Y[:n]

    out = {
        "A_contact_Y_eff": np.nan,
        "A_contact_Y_idx": np.nan,
        "A_contact_Y_method": "",
        "A_contact_Y_threshold_N": np.nan,
        "A_contact_Y_threshold_mode": "",
        "A_contact_noise_threshold_N": np.nan,
        "A_contact_relative_threshold_N": np.nan,
        "A_contact_absolute_threshold_N": np.nan,
        "A_contact_floor_threshold_N": np.nan,
        "A_contact_hybrid_mean_threshold_N": np.nan,
        "A_contact_baseline_median_N": np.nan,
        "A_contact_baseline_sigma_N": np.nan,
        "A_contact_search_ref_eff": np.nan,
        "Y_contact_search_ref_N": np.nan,
        "A_snug_eff": np.nan,
        "A_snug_idx": np.nan,
    }

    if n < 10:
        return out

    ymax = float(
        pre.get(
            "Ymax",
            np.nan,
        )
    )

    if (
        not np.isfinite(ymax)
        or ymax <= 0
    ):
        return out

    Y_s = rolling_median(
        Y,
        7,
    )

    # --------------------------------------------------------------
    # Baseline tension : priorité à la zone pré-A0 peu chargée.
    # --------------------------------------------------------------
    pre_a0 = (
        np.isfinite(A)
        & np.isfinite(Y_s)
        & (A < 0)
    )

    base_mask = (
        pre_a0
        & (
            Y_s
            < max(
                0.05 * ymax,
                cfg.get(
                    "contact_min_abs_N",
                    0.0,
                ),
            )
        )
    )

    if int(
        np.sum(base_mask)
    ) < 5:

        idx_pre = np.where(
            pre_a0
        )[0]

        if len(idx_pre):

            n_base = max(
                5,
                min(
                    25,
                    (
                        len(idx_pre) // 4
                        if len(idx_pre) >= 20
                        else len(idx_pre)
                    ),
                ),
            )

            base_idx = idx_pre[
                :n_base
            ]

            base_vals = Y_s[
                base_idx
            ]

        else:

            base_vals = Y_s[
                :max(
                    5,
                    min(
                        25,
                        n // 10,
                    ),
                )
            ]

    else:
        base_vals = Y_s[
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

    base_med = (
        float(
            np.nanmedian(
                base_vals
            )
        )
        if len(base_vals)
        else 0.0
    )

    base_sig = robust_sigma_mad(
        base_vals
    )

    if not np.isfinite(
        base_sig
    ):
        base_sig = 0.0

    thr_info = compute_contact_threshold_y(
        base_med=base_med,
        base_sig=base_sig,
        ymax=ymax,
        cfg=cfg,
    )

    threshold = float(
        thr_info.get(
            "threshold",
            np.nan,
        )
    )

    out[
        "A_contact_Y_threshold_N"
    ] = threshold

    out[
        "A_contact_Y_threshold_mode"
    ] = str(
        thr_info.get(
            "mode",
            "",
        )
    )

    out[
        "A_contact_noise_threshold_N"
    ] = float(
        thr_info.get(
            "noise_threshold",
            np.nan,
        )
    )

    out[
        "A_contact_relative_threshold_N"
    ] = float(
        thr_info.get(
            "relative_threshold",
            np.nan,
        )
    )

    out[
        "A_contact_absolute_threshold_N"
    ] = float(
        thr_info.get(
            "absolute_threshold",
            np.nan,
        )
    )

    out[
        "A_contact_floor_threshold_N"
    ] = float(
        thr_info.get(
            "floor_threshold",
            np.nan,
        )
    )

    out[
        "A_contact_hybrid_mean_threshold_N"
    ] = float(
        thr_info.get(
            "hybrid_mean_threshold",
            np.nan,
        )
    )

    out[
        "A_contact_baseline_median_N"
    ] = float(
        base_med
    )

    out[
        "A_contact_baseline_sigma_N"
    ] = float(
        base_sig
    )

    if not np.isfinite(
        threshold
    ):
        return out

    idx_ref = (
        _first_index_at_or_after_a0(
            A
        )
    )

    if idx_ref is not None:

        out[
            "A_contact_search_ref_eff"
        ] = float(
            A[idx_ref]
        )

        out[
            "Y_contact_search_ref_N"
        ] = (
            float(
                Y_s[idx_ref]
            )
            if np.isfinite(
                Y_s[idx_ref]
            )
            else np.nan
        )

    # --------------------------------------------------------------
    # Recherche à rebours depuis A0.
    # --------------------------------------------------------------
    if cfg.get(
        "contact_backward_from_a0",
        True,
    ):

        (
            a_contact,
            idx_contact,
            method,
        ) = (
            backward_threshold_crossing_from_a0(
                A,
                Y_s,
                threshold,
                min_consecutive_below=int(
                    cfg.get(
                        "contact_min_consecutive",
                        4,
                    )
                ),
            )
        )

        out[
            "A_contact_Y_eff"
        ] = (
            float(
                a_contact
            )
            if np.isfinite(
                a_contact
            )
            else np.nan
        )

        out[
            "A_contact_Y_idx"
        ] = (
            int(
                idx_contact
            )
            if idx_contact is not None
            else np.nan
        )

        out[
            "A_contact_Y_method"
        ] = method

    # --------------------------------------------------------------
    # Fallback forward si la recherche backward échoue.
    # --------------------------------------------------------------
    if not np.isfinite(
        out[
            "A_contact_Y_eff"
        ]
    ):

        above = (
            np.isfinite(Y_s)
            & (
                Y_s >= threshold
            )
        )

        idx_contact = (
            first_consecutive(
                above,
                int(
                    cfg.get(
                        "contact_min_consecutive",
                        4,
                    )
                ),
            )
        )

        if idx_contact is not None:

            out[
                "A_contact_Y_eff"
            ] = float(
                A[
                    idx_contact
                ]
            )

            out[
                "A_contact_Y_idx"
            ] = int(
                idx_contact
            )

            out[
                "A_contact_Y_method"
            ] = (
                "FALLBACK_FORWARD_FIRST_CONSECUTIVE"
            )

    # --------------------------------------------------------------
    # A_snug : pente significative après contact et avant A0.
    # --------------------------------------------------------------
    k = float(
        pre.get(
            "K_YA_20_50",
            np.nan,
        )
    )

    if (
        np.isfinite(k)
        and k > 0
    ):

        dy = safe_gradient_by_angle(
            Y,
            A,
            smooth_window=7,
        )

        mask = (
            np.isfinite(dy)
            & np.isfinite(Y_s)
            & (
                dy
                > float(
                    cfg.get(
                        "snug_slope_fraction",
                        0.25,
                    )
                ) * k
            )
            & (
                Y_s
                > float(
                    cfg.get(
                        "snug_y_min_ratio",
                        0.03,
                    )
                ) * ymax
            )
            & np.isfinite(A)
            & (A <= 0)
        )

        idx_contact = out.get(
            "A_contact_Y_idx",
            np.nan,
        )

        if np.isfinite(
            idx_contact
        ):
            mask[
                :int(
                    idx_contact
                )
            ] = False

        idx_snug = (
            first_consecutive(
                mask,
                int(
                    cfg.get(
                        "contact_min_consecutive",
                        4,
                    )
                ),
            )
        )

        if idx_snug is not None:

            out[
                "A_snug_eff"
            ] = float(
                A[
                    idx_snug
                ]
            )

            out[
                "A_snug_idx"
            ] = int(
                idx_snug
            )

    return out