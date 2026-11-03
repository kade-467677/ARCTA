from __future__ import annotations

import re
import unicodedata
from typing import Any, Sequence

import numpy as np
import pandas as pd


def make_unique_columns(
        columns: Sequence[Any],
) -> list[str]:
    """
    Rend les noms de colonnes uniques et non vides.

    Exemple :
        ["Angle", "Couple", "Couple", ""]

    devient :
        ["Angle", "Couple", "Couple_2", "COL_004"]
    """

    used = {}
    out = []

    for i, c in enumerate(
            columns,
            start=1,
    ):
        s = (
            ""
            if c is None
            else str(c).strip()
        )

        if s.lower() in (
            "",
            "nan",
            "none",
            "null",
        ):
            s = f"COL_{i:03d}"

        base = s

        n = used.get(
            base,
            0,
        )

        if n == 0:
            out.append(
                base
            )
        else:
            out.append(
                f"{base}_{n + 1}"
            )

        used[base] = n + 1

    return out


def strip_accents(
        s: str,
) -> str:
    return "".join(
        ch
        for ch in unicodedata.normalize(
            "NFD",
            str(s),
        )
        if unicodedata.category(ch)
        != "Mn"
    )


def norm_text(
        s: str,
) -> str:
    """
    Normalisation robuste des en-têtes
    pour l'auto-détection ARCTA.
    """

    s = (
        ""
        if s is None
        else str(s)
    )

    s = strip_accents(
        s
    ).lower()

    s = (
        s
        .replace("µ", "mu")
        .replace("μ", "mu")
    )

    s = s.replace(
        "°",
        " deg ",
    )

    s = (
        s
        .replace("\u00a0", " ")
        .replace("\u202f", " ")
    )

    # Séparateurs et ponctuation -> espaces
    s = re.sub(
        r"[^0-9a-zA-Z]+",
        " ",
        s,
    )

    # CH1 -> ch 1
    # M8  -> m 8
    s = re.sub(
        r"([a-zA-Z])([0-9])",
        r"\1 \2",
        s,
    )

    s = re.sub(
        r"([0-9])([a-zA-Z])",
        r"\1 \2",
        s,
    )

    return re.sub(
        r"\s+",
        " ",
        s,
    ).strip()


def coerce_numeric_series(
        s: Any,
) -> pd.Series:
    """
    Conversion robuste vers une série numérique.

    Accepte notamment :
        1234.5
        1 234,5
        1.234,5
    """

    if s is None:
        return pd.Series(
            [],
            dtype=float,
        )

    if (
        hasattr(s, "ndim")
        and s.ndim == 2
    ):
        s = s.iloc[:, 0]

    if not pd.api.types.is_numeric_dtype(
            s
    ):
        ss = s.astype(
            "string"
        )

        ss = ss.str.replace(
            "\u202f",
            "",
            regex=False,
        )

        ss = ss.str.replace(
            "\u00a0",
            "",
            regex=False,
        )

        ss = ss.str.replace(
            " ",
            "",
            regex=False,
        )

        both = ss.str.contains(
            r"\d+\.\d+,\d+",
            regex=True,
            na=False,
        )

        ss.loc[both] = (
            ss.loc[both]
            .str.replace(
                ".",
                "",
                regex=False,
            )
            .str.replace(
                ",",
                ".",
                regex=False,
            )
        )

        comma = (
            ~both
            & ss.str.contains(
                ",",
                na=False,
            )
        )

        ss.loc[comma] = (
            ss.loc[comma]
            .str.replace(
                ",",
                ".",
                regex=False,
            )
        )

        s = ss

    v = (
        pd.to_numeric(
            s,
            errors="coerce",
        )
        .replace(
            [
                np.inf,
                -np.inf,
            ],
            np.nan,
        )
    )

    return v.astype(
        float
    )


def _cell_to_indices(
        cell_ref: str,
) -> tuple[int, int]:
    """
    Convertit une référence Excel A1
    en indices pandas 0-based.

    Exemples :
        A1   -> (0, 0)
        AA12 -> (11, 26)
    """

    m = re.match(
        r"^([A-Za-z]+)(\d+)$",
        str(cell_ref).strip(),
    )

    if not m:
        raise ValueError(
            f"Référence cellule invalide : {cell_ref}"
        )

    letters = m.group(1).upper()
    row = int(
        m.group(2)
    )

    col = 0

    for ch in letters:
        col = (
            col * 26
            + (
                ord(ch)
                - ord("A")
                + 1
            )
        )

    return (
        row - 1,
        col - 1,
    )


def _as_float_fr(
        v,
) -> float:
    """
    Conversion scalaire robuste,
    notamment pour les valeurs françaises.
    """

    if v is None:
        return np.nan

    if isinstance(
        v,
        (
            int,
            float,
            np.integer,
            np.floating,
        ),
    ):
        return float(
            v
        )

    s0 = (
        str(v)
        .strip()
        .replace("\u00a0", "")
        .replace("\u202f", "")
        .replace(" ", "")
        .replace(",", ".")
    )

    try:
        return float(
            s0
        )
    except Exception:
        return np.nan