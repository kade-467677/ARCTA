from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

import pandas as pd


SUPPORTED_PREVIEW_EXTENSIONS = frozenset({
    ".xlsx",
    ".csv",
    ".txt",
})

HEADER_ANCHOR_ROW_1BASED = 20
HEADER_FALLBACK_MAX_SCAN = 80
HEADER_UNIT_MAX_GAP = 2


def _cell_text(
    value: object,
) -> str:
    if value is None:
        return ""

    try:
        if pd.isna(value):
            return ""
    except (
        TypeError,
        ValueError,
    ):
        pass

    return str(value).strip()


def _row_non_empty_values(
    row: pd.Series,
) -> list[str]:
    values = []

    for value in row.tolist():
        text = _cell_text(value)

        if not text:
            continue

        if text.lower() in {
            "nan",
            "none",
            "null",
        }:
            continue

        values.append(text)

    return values


def _is_numeric_like_cell(
    value: object,
) -> bool:
    if value is None:
        return False

    if isinstance(
        value,
        bool,
    ):
        return False

    if isinstance(
        value,
        (
            int,
            float,
        ),
    ):
        try:
            return math.isfinite(
                float(value)
            )
        except (
            TypeError,
            ValueError,
        ):
            return False

    text = _cell_text(
        value
    )

    if not text:
        return False

    normalized = (
        text
        .replace("\u00a0", "")
        .replace("\u202f", "")
        .replace(" ", "")
        .replace(",", ".")
    )

    if normalized.endswith("%"):
        normalized = (
            normalized[:-1]
        )

    try:
        float(normalized)
        return True
    except ValueError:
        return False


def _row_is_header_candidate(
    row: pd.Series,
    *,
    min_non_empty: int = 2,
    min_non_numeric: int = 1,
    max_numeric_ratio: float = 0.60,
) -> bool:
    """
    Recherche une ligne textuelle réaliste située
    juste au-dessus du bloc de données.

    Le principe reste celui d'ARCTA V5 :
    on ne cherche pas la ligne la plus "jolie"
    du fichier, mais la dernière ligne
    non numérique réaliste avant les données.
    """
    values = _row_non_empty_values(
        row
    )

    if len(values) < min_non_empty:
        return False

    numeric_count = sum(
        _is_numeric_like_cell(
            value
        )
        for value in values
    )

    non_numeric_count = (
        len(values)
        - numeric_count
    )

    if (
        non_numeric_count
        < min_non_numeric
    ):
        return False

    numeric_ratio = (
        numeric_count
        / max(
            len(values),
            1,
        )
    )

    if (
        numeric_ratio
        > max_numeric_ratio
    ):
        return False

    return any(
        re.search(
            r"[A-Za-zÀ-ÿ_µμ°]",
            value,
        )
        for value in values
    )


def _normalize_unit_text(
    value: object,
) -> str:
    text = _cell_text(
        value
    ).lower()

    text = (
        text
        .replace("μ", "µ")
        .replace("\u00a0", "")
        .replace("\u202f", "")
        .replace(" ", "")
        .replace("·", ".")
        .replace("*", ".")
    )

    text = text.strip(
        "[](){}"
    )

    return text


def _is_unit_like_cell(
    value: object,
) -> bool:
    text = _normalize_unit_text(
        value
    )

    if not text:
        return False

    exact_units = {
        "n",
        "kn",
        "mn",
        "nm",
        "n.m",
        "nmm",
        "n.mm",
        "deg",
        "°",
        "°c",
        "c",
        "rad",
        "mm",
        "cm",
        "m",
        "µm",
        "um",
        "s",
        "ms",
        "min",
        "h",
        "hz",
        "khz",
        "rpm",
        "tr/min",
        "v",
        "mv",
        "a",
        "ma",
        "pa",
        "kpa",
        "mpa",
        "bar",
        "%",
    }

    if text in exact_units:
        return True

    unit_patterns = (
        r"^n/?mm2$",
        r"^n/mm²$",
        r"^mm/s$",
        r"^mm/min$",
        r"^deg/s$",
        r"^°/s$",
        r"^rad/s$",
    )

    return any(
        re.fullmatch(
            pattern,
            text,
        )
        is not None
        for pattern in unit_patterns
    )


def _row_looks_like_units(
    row: pd.Series,
    *,
    min_non_empty: int = 2,
    min_unit_ratio: float = 0.60,
) -> bool:
    values = _row_non_empty_values(
        row
    )

    if (
        len(values)
        < min_non_empty
    ):
        return False

    unit_count = sum(
        _is_unit_like_cell(
            value
        )
        for value in values
    )

    unit_ratio = (
        unit_count
        / len(values)
    )

    return (
        unit_count >= 2
        and unit_ratio
        >= min_unit_ratio
    )


def detect_source_header(
    dataframe_raw: pd.DataFrame,
    *,
    anchor_row_1based: int =
        HEADER_ANCHOR_ROW_1BASED,
    fallback_max_scan: int =
        HEADER_FALLBACK_MAX_SCAN,
) -> tuple[int, int | None]:
    """
    Retourne :

        (
            header_row_index,
            units_row_index | None,
        )

    Règle ARCTA :

    1. partir de la ligne d'ancrage
       (historiquement ligne 20) ;
    2. remonter vers le haut ;
    3. prendre la première ligne
       non numérique réaliste ;
    4. si cette ligne ressemble à une
       ligne d'unités, continuer vers
       la ligne textuelle précédente,
       qui devient l'en-tête réel.

    Les index retournés sont des index
    Python, donc 0-based.
    """
    if (
        dataframe_raw is None
        or dataframe_raw.empty
    ):
        return 0, None

    start_index = min(
        max(
            int(
                anchor_row_1based
            ) - 1,
            0,
        ),
        len(
            dataframe_raw
        ) - 1,
    )

    units_index: int | None = None

    for index in range(
        start_index,
        -1,
        -1,
    ):
        row = (
            dataframe_raw.iloc[
                index
            ]
        )

        if not _row_is_header_candidate(
            row
        ):
            continue

        if _row_looks_like_units(
            row
        ):
            units_index = index
            continue

        if units_index is not None:
            gap = (
                units_index
                - index
            )

            if (
                gap
                <= HEADER_UNIT_MAX_GAP
            ):
                return (
                    int(index),
                    int(units_index),
                )

            units_index = None

        return int(index), None

    best_index = 0
    best_score = -10**9

    scan_count = min(
        len(
            dataframe_raw
        ),
        int(
            fallback_max_scan
        ),
    )

    for index in range(
        scan_count
    ):
        values = (
            _row_non_empty_values(
                dataframe_raw.iloc[
                    index
                ]
            )
        )

        if not values:
            continue

        text_count = sum(
            bool(
                re.search(
                    r"[A-Za-zÀ-ÿ_µμ°]",
                    value,
                )
            )
            for value in values
        )

        numeric_count = sum(
            _is_numeric_like_cell(
                value
            )
            for value in values
        )

        score = (
            text_count * 3
            - numeric_count
        )

        if (
            _row_looks_like_units(
                dataframe_raw.iloc[
                    index
                ]
            )
        ):
            score -= 5

        if score > best_score:
            best_score = score
            best_index = index

    return int(best_index), None


def _deduplicate_headers(
    headers: list[str],
) -> list[str]:
    counts: dict[
        str,
        int,
    ] = {}

    result = []

    for header in headers:
        count = counts.get(
            header,
            0,
        )

        if count == 0:
            result.append(
                header
            )
        else:
            result.append(
                f"{header}.{count}"
            )

        counts[header] = (
            count + 1
        )

    return result


def _dataframe_from_detected_header(
    dataframe_raw: pd.DataFrame,
    *,
    header_index: int,
    units_index: int | None,
    max_rows: int | None,
) -> pd.DataFrame:
    if dataframe_raw.empty:
        return dataframe_raw.copy()

    raw_headers = [
        _cell_text(
            value
        )
        for value
        in dataframe_raw.iloc[
            header_index
        ].tolist()
    ]

    selected_positions = [
        position
        for position, header
        in enumerate(
            raw_headers
        )
        if header
    ]

    if not selected_positions:
        return pd.DataFrame()

    headers = [
        raw_headers[
            position
        ]
        for position
        in selected_positions
    ]

    headers = (
        _deduplicate_headers(
            headers
        )
    )

    first_data_index = (
        header_index + 1
    )

    if (
        units_index is not None
        and units_index
        > header_index
    ):
        first_data_index = (
            units_index + 1
        )

    dataframe = (
        dataframe_raw.iloc[
            first_data_index:,
            selected_positions,
        ]
        .copy()
    )

    dataframe.columns = headers

    dataframe = (
        dataframe
        .dropna(
            how="all"
        )
        .reset_index(
            drop=True
        )
    )

    if (
        max_rows is not None
        and len(dataframe)
        > max_rows
    ):
        dataframe = (
            dataframe.iloc[
                :max_rows
            ]
            .copy()
        )

    return dataframe


def _dataframe_preview(
    dataframe: pd.DataFrame,
) -> tuple[
    list[str],
    list[dict[str, Any]],
]:
    dataframe = (
        dataframe.copy()
    )

    dataframe.columns = [
        str(column)
        for column
        in dataframe.columns
    ]

    rows = json.loads(
        dataframe.to_json(
            orient="records",
            date_format="iso",
            force_ascii=False,
        )
    )

    return (
        list(
            dataframe.columns
        ),
        rows,
    )


def _raw_read_limit(
    max_rows: int,
) -> int:
    return max(
        HEADER_FALLBACK_MAX_SCAN,
        (
            HEADER_ANCHOR_ROW_1BASED
            + max_rows
            + 5
        ),
    )


def _read_delimited_raw(
    path: Path,
    max_rows: int | None,
) -> pd.DataFrame:
    last_error: (
        Exception
        | None
    ) = None

    read_limit = (
        _raw_read_limit(
            max_rows
        )
        if max_rows is not None
        else None
    )

    for encoding in (
        "utf-8-sig",
        "utf-8",
        "cp1252",
        "latin-1",
    ):
        try:
            return pd.read_csv(
                path,
                sep=None,
                engine="python",
                encoding=encoding,
                header=None,
                nrows=read_limit,
                on_bad_lines="skip",
            )

        except Exception as exc:
            last_error = exc

    if last_error is not None:
        raise last_error

    raise ValueError(
        "Lecture du fichier "
        "délimité impossible."
    )


def _build_detected_preview(
    dataframe_raw: pd.DataFrame,
    *,
    max_rows: int,
) -> tuple[
    pd.DataFrame,
    int,
    int | None,
]:
    header_index, units_index = (
        detect_source_header(
            dataframe_raw
        )
    )

    dataframe = (
        _dataframe_from_detected_header(
            dataframe_raw,
            header_index=header_index,
            units_index=units_index,
            max_rows=max_rows,
        )
    )

    return (
        dataframe,
        header_index,
        units_index,
    )


def read_source_preview(
    path: str | Path,
    *,
    sheet_name: str | None = None,
    max_rows: int = 20,
) -> dict[str, object]:
    """
    Lit un aperçu de source ARCTA
    en détectant automatiquement la
    vraie ligne d'en-tête.

    Le contrat JSON historique reste
    conservé. Deux informations de
    traçabilité sont ajoutées :

        header_row_1based
        units_row_1based
    """
    source_path = Path(
        path
    )

    if not source_path.is_file():
        raise FileNotFoundError(
            source_path
        )

    extension = (
        source_path.suffix.lower()
    )

    if (
        extension
        not in
        SUPPORTED_PREVIEW_EXTENSIONS
    ):
        raise ValueError(
            "Format non supporté : "
            f"{extension}"
        )

    if max_rows < 1:
        raise ValueError(
            "max_rows doit être >= 1."
        )

    read_limit = (
        _raw_read_limit(
            max_rows
        )
    )

    if extension == ".xlsx":
        excel_file = pd.ExcelFile(
            source_path,
            engine="openpyxl",
        )

        try:
            sheet_names = list(
                excel_file.sheet_names
            )

            if not sheet_names:
                raise ValueError(
                    "Le classeur ne contient "
                    "aucune feuille."
                )

            selected_sheet = (
                sheet_name
                if sheet_name
                is not None
                else sheet_names[0]
            )

            if (
                selected_sheet
                not in sheet_names
            ):
                raise ValueError(
                    "Feuille inconnue : "
                    f"{selected_sheet}"
                )

            dataframe_raw = (
                pd.read_excel(
                    excel_file,
                    sheet_name=
                        selected_sheet,
                    header=None,
                    nrows=read_limit,
                )
            )

        finally:
            excel_file.close()

        (
            dataframe,
            header_index,
            units_index,
        ) = _build_detected_preview(
            dataframe_raw,
            max_rows=max_rows,
        )

        columns, rows = (
            _dataframe_preview(
                dataframe
            )
        )

        return {
            "file_type": "xlsx",
            "sheet_names":
                sheet_names,
            "selected_sheet":
                selected_sheet,
            "columns": columns,
            "rows": rows,
            "preview_row_count":
                len(rows),
            "header_row_1based":
                header_index + 1,
            "units_row_1based":
                (
                    units_index + 1
                    if units_index
                    is not None
                    else None
                ),
        }

    dataframe_raw = (
        _read_delimited_raw(
            source_path,
            max_rows,
        )
    )

    (
        dataframe,
        header_index,
        units_index,
    ) = _build_detected_preview(
        dataframe_raw,
        max_rows=max_rows,
    )

    columns, rows = (
        _dataframe_preview(
            dataframe
        )
    )

    return {
        "file_type":
            extension.lstrip("."),
        "sheet_names": [],
        "selected_sheet": None,
        "columns": columns,
        "rows": rows,
        "preview_row_count":
            len(rows),
        "header_row_1based":
            header_index + 1,
        "units_row_1based":
            (
                units_index + 1
                if units_index
                is not None
                else None
            ),
    }


def read_source_dataframe(
    path: str | Path,
    *,
    sheet_name: str | None = None,
) -> dict[str, object]:
    """
    Relit intégralement une source ARCTA avec la même détection
    d'en-tête que l'aperçu Web.

    Le DataFrame retourné ne contient ni le préambule, ni la ligne
    d'unités. Les métadonnées de lecture permettent au service DIAG
    de conserver la traçabilité exacte de la préparation de source.
    """
    preview = read_source_preview(
        path,
        sheet_name=sheet_name,
        max_rows=1,
    )

    source_path = Path(path)
    extension = source_path.suffix.lower()

    if extension == ".xlsx":
        dataframe_raw = pd.read_excel(
            source_path,
            sheet_name=preview["selected_sheet"],
            header=None,
            engine="openpyxl",
        )
    else:
        dataframe_raw = _read_delimited_raw(
            source_path,
            None,
        )

    header_index = int(
        preview["header_row_1based"]
    ) - 1

    units_row_1based = preview.get(
        "units_row_1based"
    )

    units_index = (
        int(units_row_1based) - 1
        if units_row_1based is not None
        else None
    )

    dataframe = _dataframe_from_detected_header(
        dataframe_raw,
        header_index=header_index,
        units_index=units_index,
        max_rows=None,
    )

    return {
        "dataframe": dataframe,
        "file_type": preview["file_type"],
        "selected_sheet": preview["selected_sheet"],
        "columns": list(dataframe.columns),
        "row_count": len(dataframe),
        "header_row_1based": header_index + 1,
        "units_row_1based": units_row_1based,
    }
