from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd


def rolling_median(
        y: np.ndarray,
        window: int = 7,
) -> np.ndarray:
    """
    Médiane glissante centrée.

    La taille de fenêtre est forcée :
      - à au moins 3 points ;
      - à une valeur impaire.
    """

    window = max(
        3,
        int(window) | 1,
    )

    return (
        pd.Series(y)
        .rolling(
            window=window,
            center=True,
            min_periods=1,
        )
        .median()
        .to_numpy(dtype=float)
    )


def safe_gradient_by_angle(
        y,
        a,
        smooth_window: int = 7,
        min_unique_points: int = 3,
) -> np.ndarray:
    """
    Calcule dY/dA de manière robuste lorsque l'angle
    contient éventuellement des doublons.

    Le résultat possède la même longueur que les entrées.

    Si le gradient n'est pas calculable, les valeurs
    retournées sont NaN.
    """

    y = np.asarray(
        y,
        dtype=float,
    )

    a = np.asarray(
        a,
        dtype=float,
    )

    out = np.full(
        len(y),
        np.nan,
        dtype=float,
    )

    if (
        len(y) != len(a)
        or len(y) < min_unique_points
    ):
        return out

    mask = (
        np.isfinite(y)
        & np.isfinite(a)
    )

    if int(
        np.sum(mask)
    ) < min_unique_points:
        return out

    y_s = rolling_median(
        y,
        smooth_window,
    )

    df = (
        pd.DataFrame(
            {
                "A": a[mask],
                "Y": y_s[mask],
            }
        )
        .dropna()
    )

    if df.empty:
        return out

    grouped = (
        df
        .groupby(
            "A",
            sort=True,
            as_index=False,
        )["Y"]
        .median()
    )

    a_unique = grouped[
        "A"
    ].to_numpy(dtype=float)

    y_unique = grouped[
        "Y"
    ].to_numpy(dtype=float)

    order = np.argsort(
        a_unique
    )

    a_unique = a_unique[
        order
    ]

    y_unique = y_unique[
        order
    ]

    keep = (
        np.concatenate(
            [
                [True],
                np.diff(a_unique) > 0,
            ]
        )
        if len(a_unique)
        else np.array(
            [],
            dtype=bool,
        )
    )

    a_unique = a_unique[
        keep
    ]

    y_unique = y_unique[
        keep
    ]

    if len(
        a_unique
    ) < min_unique_points:
        return out

    with np.errstate(
        divide="ignore",
        invalid="ignore",
    ):
        gradient_unique = np.gradient(
            y_unique,
            a_unique,
        )

    gradient_unique[
        ~np.isfinite(
            gradient_unique
        )
    ] = np.nan

    idx = np.where(
        mask
    )[0]

    out[idx] = np.interp(
        a[mask],
        a_unique,
        gradient_unique,
        left=np.nan,
        right=np.nan,
    )

    return out


def linear_fit(
        x: np.ndarray,
        y: np.ndarray,
) -> tuple[
    float,
    float,
    float,
    int,
]:
    """
    Régression linéaire y = a*x + b.

    Retour :
        pente,
        intercept,
        R²,
        nombre de points valides.
    """

    mask = (
        np.isfinite(x)
        & np.isfinite(y)
    )

    x = x[
        mask
    ]

    y = y[
        mask
    ]

    if len(x) < 2:
        return (
            np.nan,
            np.nan,
            np.nan,
            len(x),
        )

    a, b = np.polyfit(
        x,
        y,
        deg=1,
    )

    y_hat = (
        a * x
        + b
    )

    ss_res = float(
        np.sum(
            (y - y_hat) ** 2
        )
    )

    ss_tot = float(
        np.sum(
            (y - np.mean(y)) ** 2
        )
    )

    r2 = (
        1.0
        - ss_res / ss_tot
        if ss_tot > 0
        else np.nan
    )

    return (
        float(a),
        float(b),
        float(r2),
        len(x),
    )


def first_consecutive(
        mask: np.ndarray,
        n: int,
) -> Optional[int]:
    """
    Retourne l'indice de début de la première
    séquence de n valeurs True consécutives.
    """

    count = 0

    for i, value in enumerate(
        mask
    ):
        if bool(value):
            count += 1

            if count >= n:
                return (
                    i - n + 1
                )

        else:
            count = 0

    return None


def robust_sigma_mad(
        vals: np.ndarray,
) -> float:
    """
    Estimation robuste de sigma à partir du MAD.

    Si le MAD est nul :
      - utilise l'écart-type échantillon si possible ;
      - retourne 0 pour un singleton.
    """

    values = np.asarray(
        vals,
        dtype=float,
    )

    values = values[
        np.isfinite(values)
    ]

    if len(values) == 0:
        return np.nan

    median = float(
        np.nanmedian(values)
    )

    mad = float(
        np.nanmedian(
            np.abs(
                values - median
            )
        )
    )

    if (
        np.isfinite(mad)
        and mad > 0
    ):
        return float(
            1.4826 * mad
        )

    if len(values) > 1:
        std = float(
            np.nanstd(
                values,
                ddof=1,
            )
        )

        return (
            std
            if np.isfinite(std)
            else np.nan
        )

    return 0.0


def compute_contact_threshold_y(
        base_med: float,
        base_sig: float,
        ymax: float,
        cfg: dict,
) -> dict:
    """
    Calcule le seuil de détection A_contact_Y.

    Modes :
      - max
      - hybrid_backward
      - mean

    Toutes les informations nécessaires sont fournies
    par cfg : cette fonction ne dépend donc d'aucune
    configuration globale ARCTA.
    """

    base_med = (
        float(base_med)
        if np.isfinite(base_med)
        else 0.0
    )

    base_sig = (
        float(base_sig)
        if np.isfinite(base_sig)
        else 0.0
    )

    ymax = (
        float(ymax)
        if np.isfinite(ymax)
        else np.nan
    )

    k_noise = float(
        cfg.get(
            "contact_sigma_k",
            5.0,
        )
    )

    k_floor = float(
        cfg.get(
            "contact_sigma_floor_k",
            2.0,
        )
    )

    ratio = float(
        cfg.get(
            "contact_min_ratio_ymax",
            0.005,
        )
    )

    abs_thr = float(
        cfg.get(
            "contact_min_abs_N",
            0.0,
        )
    )

    mode = str(
        cfg.get(
            "contact_threshold_mode",
            "max",
        )
    ).strip().lower()

    noise_thr = (
        base_med
        + k_noise * base_sig
    )

    floor_thr = (
        base_med
        + k_floor * base_sig
    )

    rel_thr = (
        ratio * ymax
        if np.isfinite(ymax)
        else np.nan
    )

    candidates_finite = [
        value
        for value in (
            noise_thr,
            floor_thr,
            rel_thr,
            abs_thr,
        )
        if np.isfinite(value)
    ]

    if not candidates_finite:
        return {
            "threshold": np.nan,
            "mode": mode,
            "noise_threshold": np.nan,
            "relative_threshold": np.nan,
            "absolute_threshold": abs_thr,
            "floor_threshold": np.nan,
            "hybrid_mean_threshold": np.nan,
        }

    if (
        np.isfinite(noise_thr)
        and np.isfinite(rel_thr)
    ):
        hybrid_mean_thr = (
            0.5
            * (
                noise_thr
                + rel_thr
            )
        )

    elif np.isfinite(
        noise_thr
    ):
        hybrid_mean_thr = (
            noise_thr
        )

    elif np.isfinite(
        rel_thr
    ):
        hybrid_mean_thr = (
            rel_thr
        )

    else:
        hybrid_mean_thr = (
            abs_thr
        )

    if mode == "hybrid_backward":

        threshold = max(
            abs_thr,
            (
                floor_thr
                if np.isfinite(
                    floor_thr
                )
                else abs_thr
            ),
            (
                hybrid_mean_thr
                if np.isfinite(
                    hybrid_mean_thr
                )
                else abs_thr
            ),
        )

    elif mode == "mean":

        threshold = max(
            abs_thr,
            (
                hybrid_mean_thr
                if np.isfinite(
                    hybrid_mean_thr
                )
                else abs_thr
            ),
        )

    else:
        mode = "max"

        threshold = max(
            (
                noise_thr
                if np.isfinite(
                    noise_thr
                )
                else abs_thr
            ),
            (
                rel_thr
                if np.isfinite(
                    rel_thr
                )
                else abs_thr
            ),
            abs_thr,
        )

    return {
        "threshold": (
            float(threshold)
            if np.isfinite(threshold)
            else np.nan
        ),
        "mode": mode,
        "noise_threshold": (
            float(noise_thr)
            if np.isfinite(noise_thr)
            else np.nan
        ),
        "relative_threshold": (
            float(rel_thr)
            if np.isfinite(rel_thr)
            else np.nan
        ),
        "absolute_threshold": (
            float(abs_thr)
            if np.isfinite(abs_thr)
            else np.nan
        ),
        "floor_threshold": (
            float(floor_thr)
            if np.isfinite(floor_thr)
            else np.nan
        ),
        "hybrid_mean_threshold": (
            float(hybrid_mean_thr)
            if np.isfinite(
                hybrid_mean_thr
            )
            else np.nan
        ),
    }


def _first_index_at_or_after_a0(
        aeff: np.ndarray,
) -> Optional[int]:
    """
    Retourne le premier indice pour lequel A_eff >= 0.

    Si aucun point n'est positif, retourne le point fini
    le plus proche de zéro.
    """

    angle = np.asarray(
        aeff,
        dtype=float,
    )

    finite = np.where(
        np.isfinite(angle)
    )[0]

    if len(finite) == 0:
        return None

    after = finite[
        angle[finite] >= 0
    ]

    if len(after):
        return int(
            after[0]
        )

    return int(
        finite[
            np.nanargmin(
                np.abs(
                    angle[finite]
                )
            )
        ]
    )


def backward_threshold_crossing_from_a0(
        aeff: np.ndarray,
        values: np.ndarray,
        threshold: float,
        min_consecutive_below: int = 4,
) -> tuple[
    float,
    Optional[int],
    str,
]:
    """
    Recherche un franchissement de seuil à rebours depuis A0.

    Retour :
        angle_eff,
        index du premier point au-dessus,
        méthode.
    """

    angle = np.asarray(
        aeff,
        dtype=float,
    )

    values = np.asarray(
        values,
        dtype=float,
    )

    n = min(
        len(angle),
        len(values),
    )

    angle = angle[
        :n
    ]

    values = values[
        :n
    ]

    if n < max(
        3,
        min_consecutive_below + 1,
    ):
        return (
            np.nan,
            None,
            "TOO_FEW_POINTS",
        )

    if not np.isfinite(
        threshold
    ):
        return (
            np.nan,
            None,
            "INVALID_THRESHOLD",
        )

    idx_ref = (
        _first_index_at_or_after_a0(
            angle
        )
    )

    if idx_ref is None:
        return (
            np.nan,
            None,
            "NO_A0_REFERENCE",
        )

    if (
        not np.isfinite(
            values[idx_ref]
        )
        or values[idx_ref]
        < threshold
    ):
        return (
            np.nan,
            None,
            "REF_BELOW_THRESHOLD",
        )

    above = (
        np.isfinite(values)
        & (
            values >= threshold
        )
    )

    below_count = 0

    for i in range(
        idx_ref,
        -1,
        -1,
    ):
        if not above[i]:

            below_count += 1

            if (
                below_count
                >= int(
                    min_consecutive_below
                )
            ):
                idx_below = (
                    i
                    + int(
                        min_consecutive_below
                    )
                    - 1
                )

                idx_above = (
                    idx_below + 1
                )

                if (
                    idx_above <= idx_ref
                    and idx_above < n
                ):
                    try:
                        a1 = angle[
                            idx_below
                        ]

                        v1 = values[
                            idx_below
                        ]

                        a2 = angle[
                            idx_above
                        ]

                        v2 = values[
                            idx_above
                        ]

                        if (
                            np.isfinite(a1)
                            and np.isfinite(a2)
                            and np.isfinite(v1)
                            and np.isfinite(v2)
                            and abs(
                                v2 - v1
                            ) > 1e-12
                        ):
                            t = (
                                threshold - v1
                            ) / (
                                v2 - v1
                            )

                            angle_crossing = float(
                                a1
                                + t
                                * (
                                    a2 - a1
                                )
                            )

                        else:
                            angle_crossing = float(
                                angle[
                                    idx_above
                                ]
                            )

                        return (
                            angle_crossing,
                            int(
                                idx_above
                            ),
                            "BACKWARD_FROM_A0_INTERP",
                        )

                    except Exception:
                        return (
                            float(
                                angle[
                                    idx_above
                                ]
                            ),
                            int(
                                idx_above
                            ),
                            "BACKWARD_FROM_A0_INDEX",
                        )

                return (
                    np.nan,
                    None,
                    "NO_ABOVE_AFTER_BELOW_RUN",
                )

        else:
            below_count = 0

    return (
        np.nan,
        None,
        "NO_STABLE_BELOW_BEFORE_A0",
    )