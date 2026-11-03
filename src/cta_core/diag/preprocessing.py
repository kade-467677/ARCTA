from __future__ import annotations

from typing import Any, Mapping

import numpy as np

from .tightening import tightening_peak

from .primitives import (
    first_consecutive,
    linear_fit,
    rolling_median,
)


def preclean_and_fit_a0(
        a_raw: np.ndarray,
        y_raw: np.ndarray,
        cfg: Mapping[str, Any],
        torque_raw: np.ndarray | None = None,
) -> dict[str, Any]:
    """
    Pré-nettoyage DIAG et détermination de A0 élastique.

    Important :
        cette fonction ne lit aucune variable globale.

    Toute la configuration nécessaire est fournie explicitement
    par ``cfg``.

    Cela rend la fonction :
        - testable indépendamment ;
        - utilisable depuis Tkinter ;
        - utilisable depuis une API Web ;
        - sûre vis-à-vis de plusieurs runs simultanés.
    """

    a = np.asarray(
        a_raw,
        dtype=float,
    )

    y = np.asarray(
        y_raw,
        dtype=float,
    )

    mask_valid = (
        np.isfinite(a)
        & np.isfinite(y)
    )

    out: dict[str, Any] = {
        "N_raw_valid": int(
            mask_valid.sum()
        )
    }

    if int(mask_valid.sum()) < 10:
        out["error"] = "TOO_FEW_POINTS"
        return out

    y_s = rolling_median(
        y,
        7,
    )

    try:
        peak = tightening_peak(y, torque_raw, a, cfg)
    except ValueError as exc:
        out["error"] = str(exc)
        return out
    out.update(peak)
    idx_ymax, ymax = peak["idx_ymax"], peak["Ymax"]
    # Le lissage du fit A0 ne doit pas emprunter des points au desserrage.
    y_s = y_s.copy()
    y_s[:idx_ymax + 1] = rolling_median(y[:idx_ymax + 1], 7)

    if (
        not np.isfinite(ymax)
        or ymax <= 0
    ):
        out["error"] = "NO_POSITIVE_TENSION"
        return out

    unload_drop_ratio = float(
        cfg[
            "prediag_unload_drop_ratio"
        ]
    )

    unload_consecutive = int(
        cfg[
            "prediag_unload_consecutive"
        ]
    )

    keep_before_a0_deg = float(
        cfg[
            "prediag_keep_before_a0_deg"
        ]
    )

    a0_fit_windows = cfg[
        "a0_fit_windows"
    ]

    a0_min_points = int(
        cfg[
            "a0_min_points"
        ]
    )

    threshold_down = (
        1.0
        - unload_drop_ratio
    ) * ymax

    post = y_s[
        idx_ymax + 1:
    ]

    idx_unload = None

    if len(post):
        j = first_consecutive(
            post <= threshold_down,
            unload_consecutive,
        )

        if j is not None:
            idx_unload = (
                idx_ymax
                + 1
                + j
            )

    idx_stop_initial = (
        int(idx_unload)
        if idx_unload is not None
        else len(a) - 1
    )

    a_up = a[
        :idx_ymax + 1
    ]

    y_up = y_s[
        :idx_ymax + 1
    ]

    a0 = np.nan

    fit = (
        np.nan,
        np.nan,
        np.nan,
        0,
        None,
        np.nan,
        np.nan,
    )

    for k, window in enumerate(
        a0_fit_windows
    ):
        lo, hi = window

        mf = (
            (y_up >= lo * ymax)
            & (y_up <= hi * ymax)
            & np.isfinite(a_up)
            & np.isfinite(y_up)
        )

        if int(
            mf.sum()
        ) < a0_min_points:
            continue

        aa, bb, rr, nn = linear_fit(
            a_up[mf],
            y_up[mf],
        )

        if (
            np.isfinite(aa)
            and aa > 0
        ):
            a0_candidate = (
                -bb / aa
            )

            if np.isfinite(
                a0_candidate
            ):
                a0 = float(
                    a0_candidate
                )

                a_fit_window = a_up[
                    mf
                ]

                a_start_fit = float(
                    np.nanmin(
                        a_fit_window
                    )
                )

                a_end_fit = float(
                    np.nanmax(
                        a_fit_window
                    )
                )

                fit = (
                    aa,
                    bb,
                    rr,
                    nn,
                    (
                        lo,
                        hi,
                        (
                            "nominal"
                            if k == 0
                            else "fallback"
                        ),
                    ),
                    a_start_fit,
                    a_end_fit,
                )

                break

    if not np.isfinite(
        a0
    ):
        out["error"] = "A0_NOT_FOUND"
        return out

    aeff = (
        a - a0
    )

    candidates = np.where(
        aeff[
            :idx_stop_initial + 1
        ]
        >= -keep_before_a0_deg
    )[0]

    idx_start = (
        int(
            candidates[0]
        )
        if len(candidates)
        else 0
    )

    idx_stop = (
        idx_stop_initial
    )

    (
        aa,
        bb,
        rr,
        nn,
        fw,
        a_el_start_raw,
        a_el_end_raw,
    ) = fit

    out.update(
        {
            "A0_elastic_Y": a0,
            "Ymax": ymax,

            "A_raw_Ymax": float(
                a[idx_ymax]
            ),

            "Aeff_Ymax": float(
                aeff[idx_ymax]
            ),

            "idx_ymax":
                idx_ymax,

            "idx_unload_5pct":
                idx_unload,

            "unload_5pct_detected":
                idx_unload is not None,

            "idx_start":
                idx_start,

            "idx_stop":
                idx_stop,

            "Aeff_min": float(
                aeff[idx_start]
            ),

            "Aeff_max": float(
                aeff[idx_stop]
            ),

            "K_YA_20_50":
                aa,

            "Intercept_YA_20_50":
                bb,

            "R2_A0_fit":
                rr,

            "N_A0_fit":
                nn,

            "A0_fit_window":
                fw,

            "A_elastic_start_raw":
                a_el_start_raw,

            "A_elastic_end_raw":
                a_el_end_raw,

            "A_elastic_start_eff": (
                float(
                    a_el_start_raw
                    - a0
                )
                if np.isfinite(
                    a_el_start_raw
                )
                else np.nan
            ),

            "A_elastic_end_eff": (
                float(
                    a_el_end_raw
                    - a0
                )
                if np.isfinite(
                    a_el_end_raw
                )
                else np.nan
            ),

            "Prediag_keep_before_A0_deg":
                keep_before_a0_deg,

            "Aeff_clean":
                aeff[
                    idx_start:
                    idx_stop + 1
                ],

            "A_clean":
                a[
                    idx_start:
                    idx_stop + 1
                ],

            "Y_clean":
                y[
                    idx_start:
                    idx_stop + 1
                ],
        }
    )

    return out