from __future__ import annotations

from typing import Any, Mapping

import numpy as np


def torque_balance(
        xg,
        xh,
        xt,
        y,
        ymax,
        cfg: Mapping[str, Any],
        aeff=None,
) -> dict[str, Any]:
    """
    Torque Balance Residual DIAG.

    Définition :
        R_X(A) = Xg(A) - [Xh(A) + Xt(A)]

    La configuration est fournie explicitement par ``cfg``.
    La fonction ne dépend donc d'aucune variable globale ARCTA.

    Indicateurs calculés :
        - résidu signé ;
        - résidu absolu ;
        - RMS ;
        - résidu relatif à Xg ;
        - résidu rapporté à Y ;
        - énergie résiduelle intégrée sur l'angle ;
        - flag exploratoire OK / WARNING / FAIL.
    """

    y_min_ratio = float(
        cfg.get(
            "tbr_y_min_ratio",
            0.05,
        )
    )

    out = {
        # ----------------------------------------------------------
        # Compatibilité historique
        # ----------------------------------------------------------
        "Balance_Flag": "NA",
        "mean_abs_delta_rel": np.nan,
        "max_abs_delta_rel": np.nan,
        "mean_delta_Xg_minus_XhXt_Nm": np.nan,
        "max_abs_delta_Xg_minus_XhXt_Nm": np.nan,
        "mean_Xh_over_Xg": np.nan,
        "mean_Xt_over_Xg": np.nan,

        # ----------------------------------------------------------
        # Torque Balance Residual
        # ----------------------------------------------------------
        "TBR_Method": "R_X = Xg - (Xh + Xt)",
        "TBR_N_valid": 0,
        "TBR_Mask_Y_min_ratio": y_min_ratio,

        "TBR_Mean_Nm": np.nan,
        "TBR_Median_Nm": np.nan,
        "TBR_MeanAbs_Nm": np.nan,
        "TBR_MaxAbs_Nm": np.nan,
        "TBR_RMS_Nm": np.nan,

        "TBR_MeanSignedRel_Xg": np.nan,
        "TBR_MeanAbsRel_Xg": np.nan,
        "TBR_MaxAbsRel_Xg": np.nan,

        "TBR_MeanAbs_per_Y_Nm_per_N": np.nan,
        "TBR_MaxAbs_per_Y_Nm_per_N": np.nan,

        "TBR_Energy_Nm_deg": np.nan,
        "TBR_AbsEnergy_Nm_deg": np.nan,
        "TBR_Energy_J": np.nan,
        "TBR_AbsEnergy_J": np.nan,

        "TBR_Aeff_min": np.nan,
        "TBR_Aeff_max": np.nan,
    }

    if (
        xg is None
        or xh is None
        or xt is None
    ):
        return out

    xg = np.asarray(
        xg,
        dtype=float,
    )

    xh = np.asarray(
        xh,
        dtype=float,
    )

    xt = np.asarray(
        xt,
        dtype=float,
    )

    y = np.asarray(
        y,
        dtype=float,
    )

    if aeff is not None:
        aeff = np.asarray(
            aeff,
            dtype=float,
        )

    n = min(
        len(xg),
        len(xh),
        len(xt),
        len(y),
    )

    if aeff is not None:
        n = min(
            n,
            len(aeff),
        )

    tbr_min_points = int(
        cfg.get(
            "tbr_min_points",
            5,
        )
    )

    if n < tbr_min_points:
        return out

    xg = xg[:n]
    xh = xh[:n]
    xt = xt[:n]
    y = y[:n]

    if aeff is not None:
        aeff = aeff[:n]

    xg_min = float(
        cfg.get(
            "tbr_xg_min_abs_Nm",
            1e-9,
        )
    )

    y_min_abs = float(
        cfg.get(
            "tbr_y_min_abs_N",
            1e-9,
        )
    )

    mask = (
        np.isfinite(xg)
        & np.isfinite(xh)
        & np.isfinite(xt)
        & np.isfinite(y)
        & (np.abs(xg) > xg_min)
        & (np.abs(y) > y_min_abs)
    )

    if (
        np.isfinite(ymax)
        and ymax > 0
    ):
        mask &= (
            y
            > y_min_ratio
            * float(ymax)
        )

    if int(
        np.sum(mask)
    ) < tbr_min_points:
        return out

    rx = (
        xg[mask]
        - (
            xh[mask]
            + xt[mask]
        )
    )

    xg_m = xg[
        mask
    ]

    y_m = y[
        mask
    ]

    xh_m = xh[
        mask
    ]

    xt_m = xt[
        mask
    ]

    abs_rx = np.abs(
        rx
    )

    rel_signed_xg = (
        rx
        / np.maximum(
            np.abs(xg_m),
            xg_min,
        )
    )

    rel_abs_xg = (
        abs_rx
        / np.maximum(
            np.abs(xg_m),
            xg_min,
        )
    )

    abs_per_y = (
        abs_rx
        / np.maximum(
            np.abs(y_m),
            y_min_abs,
        )
    )

    out.update(
        {
            "TBR_N_valid":
                int(
                    np.sum(mask)
                ),

            "TBR_Mean_Nm":
                float(
                    np.nanmean(rx)
                ),

            "TBR_Median_Nm":
                float(
                    np.nanmedian(rx)
                ),

            "TBR_MeanAbs_Nm":
                float(
                    np.nanmean(
                        abs_rx
                    )
                ),

            "TBR_MaxAbs_Nm":
                float(
                    np.nanmax(
                        abs_rx
                    )
                ),

            "TBR_RMS_Nm":
                float(
                    np.sqrt(
                        np.nanmean(
                            rx ** 2
                        )
                    )
                ),

            "TBR_MeanSignedRel_Xg":
                float(
                    np.nanmean(
                        rel_signed_xg
                    )
                ),

            "TBR_MeanAbsRel_Xg":
                float(
                    np.nanmean(
                        rel_abs_xg
                    )
                ),

            "TBR_MaxAbsRel_Xg":
                float(
                    np.nanmax(
                        rel_abs_xg
                    )
                ),

            "TBR_MeanAbs_per_Y_Nm_per_N":
                float(
                    np.nanmean(
                        abs_per_y
                    )
                ),

            "TBR_MaxAbs_per_Y_Nm_per_N":
                float(
                    np.nanmax(
                        abs_per_y
                    )
                ),

            "mean_Xh_over_Xg":
                float(
                    np.nanmean(
                        xh_m
                        / np.maximum(
                            np.abs(xg_m),
                            xg_min,
                        )
                    )
                ),

            "mean_Xt_over_Xg":
                float(
                    np.nanmean(
                        xt_m
                        / np.maximum(
                            np.abs(xg_m),
                            xg_min,
                        )
                    )
                ),
        }
    )

    # --------------------------------------------------------------
    # Compatibilité historique
    # --------------------------------------------------------------
    out[
        "mean_delta_Xg_minus_XhXt_Nm"
    ] = out[
        "TBR_Mean_Nm"
    ]

    out[
        "max_abs_delta_Xg_minus_XhXt_Nm"
    ] = out[
        "TBR_MaxAbs_Nm"
    ]

    out[
        "mean_abs_delta_rel"
    ] = out[
        "TBR_MeanAbsRel_Xg"
    ]

    out[
        "max_abs_delta_rel"
    ] = out[
        "TBR_MaxAbsRel_Xg"
    ]

    # --------------------------------------------------------------
    # Énergie résiduelle
    #
    # Nm.deg :
    # intégrale dans l'espace angle en degrés.
    #
    # J :
    # Nm.rad.
    # --------------------------------------------------------------
    if aeff is not None:

        a_m = aeff[
            mask
        ]

        ok_angle = (
            np.isfinite(a_m)
            & np.isfinite(rx)
        )

        if int(
            np.sum(ok_angle)
        ) >= 2:

            a_valid = a_m[
                ok_angle
            ]

            rx_valid = rx[
                ok_angle
            ]

            order = np.argsort(
                a_valid
            )

            a_valid = a_valid[
                order
            ]

            rx_valid = rx_valid[
                order
            ]

            out[
                "TBR_Aeff_min"
            ] = float(
                np.nanmin(
                    a_valid
                )
            )

            out[
                "TBR_Aeff_max"
            ] = float(
                np.nanmax(
                    a_valid
                )
            )

            try:
                # NumPy moderne :
                # np.trapezoid remplace np.trapz.
                e_nm_deg = float(
                    np.trapezoid(
                        rx_valid,
                        a_valid,
                    )
                )

                e_abs_nm_deg = float(
                    np.trapezoid(
                        np.abs(
                            rx_valid
                        ),
                        a_valid,
                    )
                )

                angle_rad = np.deg2rad(
                    a_valid
                )

                e_j = float(
                    np.trapezoid(
                        rx_valid,
                        angle_rad,
                    )
                )

                e_abs_j = float(
                    np.trapezoid(
                        np.abs(
                            rx_valid
                        ),
                        angle_rad,
                    )
                )

                out[
                    "TBR_Energy_Nm_deg"
                ] = e_nm_deg

                out[
                    "TBR_AbsEnergy_Nm_deg"
                ] = e_abs_nm_deg

                out[
                    "TBR_Energy_J"
                ] = e_j

                out[
                    "TBR_AbsEnergy_J"
                ] = e_abs_j

            except Exception:
                pass

    # --------------------------------------------------------------
    # Flag exploratoire
    # --------------------------------------------------------------
    balance_rel_fail = float(
        cfg.get(
            "balance_rel_fail",
            0.15,
        )
    )

    balance_rel_warn = float(
        cfg.get(
            "balance_rel_warn",
            0.08,
        )
    )

    if (
        out[
            "TBR_MeanAbsRel_Xg"
        ]
        > balance_rel_fail
    ):
        out[
            "Balance_Flag"
        ] = "FAIL"

    elif (
        out[
            "TBR_MeanAbsRel_Xg"
        ]
        > balance_rel_warn
    ):
        out[
            "Balance_Flag"
        ] = "WARNING"

    else:
        out[
            "Balance_Flag"
        ] = "OK"

    return out