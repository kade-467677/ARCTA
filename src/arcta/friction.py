from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from cta_core.parsing import coerce_numeric_series

from .columns import group_concat_columns_by_trial, pick_first


DEFAULT_TORQUE_UNIT = "Nm"


def torque_to_nmm(
    torque,
    torque_unit: str = DEFAULT_TORQUE_UNIT,
) -> np.ndarray:
    arr = pd.to_numeric(
        pd.Series(torque),
        errors="coerce",
    ).to_numpy(dtype=float)

    if str(torque_unit).lower() in (
        "nm",
        "n.m",
        "n*m",
    ):
        return arr * 1000.0

    return arr


def mu_kellerman_klein(
    torque,
    force,
    p_mm,
    d_mm,
    torque_unit: str = DEFAULT_TORQUE_UNIT,
    subtract_geom: bool = True,
    is_thread_friction: bool = False,
) -> np.ndarray:
    torque_nmm = torque_to_nmm(
        torque,
        torque_unit=torque_unit,
    )

    force_n = pd.to_numeric(
        pd.Series(force),
        errors="coerce",
    ).to_numpy(dtype=float)

    n = min(
        len(torque_nmm),
        len(force_n),
    )

    torque_nmm = torque_nmm[:n]
    force_n = force_n[:n]

    if subtract_geom:
        geometric_torque = (
            force_n
            * (
                float(p_mm)
                / (2.0 * np.pi)
            )
        )
    else:
        geometric_torque = 0.0

    numerator = (
        torque_nmm
        - geometric_torque
    )

    if is_thread_friction:
        denominator = (
            force_n
            * (0.577 * float(d_mm))
        )
    else:
        denominator = (
            force_n
            * (float(d_mm) / 2.0)
        )

    mu = np.full(
        n,
        np.nan,
        dtype=float,
    )

    valid = (
        (denominator > 0)
        & np.isfinite(numerator)
        & np.isfinite(denominator)
    )

    mu[valid] = (
        numerator[valid]
        / denominator[valid]
    )

    return mu


def build_mu_df_from_clean(df_clean, constants, torque_unit=DEFAULT_TORQUE_UNIT):
    """K&K : le couple filet mesuré inclut le terme d'avance géométrique."""
    from .run_mechanics import geometry
    lead, gt, gh = geometry(constants)
    blocks = []
    for tid, cols in group_concat_columns_by_trial(df_clean).items():
        role = {key: pick_first(cols, key+'_') for key in ('Xg','Xt','Xh','Y','A')}
        if not role['Xg'] or not role['Y']:
            continue
        block = {col: coerce_numeric_series(df_clean[col]).to_numpy(dtype=float)
                 for col in role.values() if col}
        force = block[role['Y']]
        for key, factor, geometric, name in (('Xg',gt+gh,True,'µg'),('Xt',gt,True,'µt'),('Xh',gh,False,'µh')):
            if not role[key]:
                continue
            numerator = torque_to_nmm(block[role[key]], torque_unit)
            if geometric:
                numerator = numerator - force*lead/(2*np.pi)
            valid = np.isfinite(numerator) & np.isfinite(force) & (force>0)
            mu = np.full(len(force), np.nan)
            mu[valid] = numerator[valid]/(force[valid]*factor)
            block[name+'_'+str(tid)] = mu
        blocks.append(pd.DataFrame(block))
    return pd.concat(blocks, axis=1) if blocks else pd.DataFrame()