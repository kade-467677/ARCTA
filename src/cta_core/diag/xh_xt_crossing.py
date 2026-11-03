from __future__ import annotations

from typing import Any, Mapping

import numpy as np


def _interp_linear(
        x1,
        y1,
        x2,
        y2,
        xq,
) -> float:
    """
    Interpolation linéaire robuste entre deux points.
    """

    try:
        values = (
            x1,
            y1,
            x2,
            y2,
            xq,
        )

        if not all(
            np.isfinite(v)
            for v in values
        ):
            return np.nan

        if abs(
            x2 - x1
        ) < 1e-12:
            return np.nan

        t = (
            xq - x1
        ) / (
            x2 - x1
        )

        return float(
            y1
            + t
            * (
                y2 - y1
            )
        )

    except Exception:
        return np.nan


def detect_xh_xt_crossing(
        aeff,
        y,
        signals: Mapping[str, Any],
        a_contact_eff=np.nan,
) -> dict[str, Any]:
    """
    Détecte le premier croisement Xh = Xt
    dans la zone pré-A0.

    Recherche :
        - domaine préférentiel :
          A_contact <= A_eff <= 0
          si A_contact est disponible ;

        - fallback :
          tout le domaine pré-A0 disponible.

    La fonction est pure :
        - aucune configuration globale ;
        - aucune dépendance UI ;
        - aucun état partagé.
    """

    out = {
        "Xh_Xt_cross_found": False,
        "A_cross_Xh_Xt_eff": np.nan,
        "Y_cross_Xh_Xt": np.nan,
        "Xg_cross_Xh_Xt": np.nan,
        "Xh_cross_Xh_Xt": np.nan,
        "Xt_cross_Xh_Xt": np.nan,
        "Cross_Search_Window": "NA",
    }

    xh = signals.get(
        "Xh"
    )

    xt = signals.get(
        "Xt"
    )

    if (
        xh is None
        or xt is None
    ):
        return out

    A = np.asarray(
        aeff,
        dtype=float,
    )

    Y = np.asarray(
        y,
        dtype=float,
    )

    Xh = np.asarray(
        xh,
        dtype=float,
    )

    Xt = np.asarray(
        xt,
        dtype=float,
    )

    Xg = signals.get(
        "Xg"
    )

    Xg = (
        np.asarray(
            Xg,
            dtype=float,
        )
        if Xg is not None
        else None
    )

    n = min(
        len(A),
        len(Y),
        len(Xh),
        len(Xt),
        (
            len(Xg)
            if Xg is not None
            else len(A)
        ),
    )

    A = A[:n]
    Y = Y[:n]
    Xh = Xh[:n]
    Xt = Xt[:n]

    if Xg is not None:
        Xg = Xg[:n]

    base_mask = (
        np.isfinite(A)
        & np.isfinite(Y)
        & np.isfinite(Xh)
        & np.isfinite(Xt)
        & (A <= 0)
    )

    if np.isfinite(
        a_contact_eff
    ):
        mask = (
            base_mask
            & (
                A
                >= float(
                    a_contact_eff
                )
            )
        )

        out[
            "Cross_Search_Window"
        ] = "A_contact_to_A0"

    else:
        mask = (
            base_mask
        )

        out[
            "Cross_Search_Window"
        ] = "pre_A0_full"

    idx = np.where(
        mask
    )[0]

    if len(idx) < 2:
        return out

    # --------------------------------------------------------------
    # Premier changement de signe de :
    #
    #     D = Xh - Xt
    #
    # dans le domaine de recherche.
    # --------------------------------------------------------------
    for k in range(
        len(idx) - 1
    ):
        i = idx[k]
        j = idx[k + 1]

        d1 = (
            Xh[i]
            - Xt[i]
        )

        d2 = (
            Xh[j]
            - Xt[j]
        )

        if not (
            np.isfinite(d1)
            and np.isfinite(d2)
        ):
            continue

        if d1 == 0:

            a_cross = A[i]

        elif (
            d1 * d2
            <= 0
        ):

            # Interpolation de D=0
            # entre A[i] et A[j].
            if abs(
                d2 - d1
            ) < 1e-12:

                a_cross = A[i]

            else:

                a_cross = (
                    A[i]
                    - d1
                    * (
                        A[j]
                        - A[i]
                    )
                    / (
                        d2 - d1
                    )
                )

        else:
            continue

        out.update(
            {
                "Xh_Xt_cross_found":
                    True,

                "A_cross_Xh_Xt_eff":
                    float(
                        a_cross
                    ),

                "Y_cross_Xh_Xt":
                    _interp_linear(
                        A[i],
                        Y[i],
                        A[j],
                        Y[j],
                        a_cross,
                    ),

                "Xh_cross_Xh_Xt":
                    _interp_linear(
                        A[i],
                        Xh[i],
                        A[j],
                        Xh[j],
                        a_cross,
                    ),

                "Xt_cross_Xh_Xt":
                    _interp_linear(
                        A[i],
                        Xt[i],
                        A[j],
                        Xt[j],
                        a_cross,
                    ),
            }
        )

        if Xg is not None:
            out[
                "Xg_cross_Xh_Xt"
            ] = _interp_linear(
                A[i],
                Xg[i],
                A[j],
                Xg[j],
                a_cross,
            )

        return out

    return out