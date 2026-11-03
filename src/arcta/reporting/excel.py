from __future__ import annotations
import json
import math
from collections.abc import Mapping, Sequence
from typing import Any
import numpy as np
import pandas as pd
from openpyxl import Workbook

def safe_sheet_name(name: str, max_len: int = 31) -> str:
    """Normalise un nom de feuille Excel."""
    import re
    value = str(name).strip() or "Sheet"
    value = re.sub(r"[\[\]\:\*\?\/\\]", "_", value)
    return value[:max_len]

def unique_sheet_name(base: str, used: set[str]) -> str:
    """Retourne un nom de feuille Excel valide et unique."""
    base = safe_sheet_name(base)
    if base not in used:
        used.add(base)
        return base
    i = 2
    while True:
        candidate = safe_sheet_name(f"{base[:27]}_{i}")
        if candidate not in used:
            used.add(candidate)
            return candidate
        i += 1

def excel_safe_value(value: Any) -> Any:
    """Convertit une valeur Python/NumPy/pandas en valeur acceptable par Excel."""
    if value is None:
        return None
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        out = float(value)
        return out if math.isfinite(out) else None
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (int, bool, str)):
        return value
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    if isinstance(value, (tuple, list, dict, set)):
        try:
            return json.dumps(value, ensure_ascii=False, default=str)
        except Exception:
            return str(value)
    return str(value)

def build_workbook(
    sheets: Mapping[str, object],
    order: Sequence[str] | None = None,
) -> Workbook:
    """Construit en mémoire un classeur XLSX à partir des feuilles ARCTA."""
    workbook = Workbook()
    workbook.remove(workbook.active)
    used: set[str] = set()
    ordered_names = list(order or [])
    ordered_names.extend(
        name
        for name in sheets
        if name not in ordered_names
    )
    for name in ordered_names:
        if name not in sheets:
            continue
        data = sheets[name]
        sheet_name = unique_sheet_name(str(name), used)
        worksheet = workbook.create_sheet(sheet_name)
        if data is None:
            continue
        if not isinstance(data, pd.DataFrame):
            data = pd.DataFrame(data)
        worksheet.append([str(column) for column in data.columns])
        for row in data.itertuples(index=False, name=None):
            worksheet.append([
                excel_safe_value(value)
                for value in row
            ])
    return workbook

def write_workbook_file(
    output_path: str,
    sheets: Mapping[str, object],
    order: Sequence[str] | None = None,
) -> str:
    """
    Écrit physiquement un classeur XLSX sans interaction utilisateur.

    Les erreurs d'écriture sont propagées à l'appelant.
    """
    workbook = build_workbook(
        sheets,
        order=order,
    )
    try:
        workbook.save(output_path)
    finally:
        # Indispensable sous Windows : libere explicitement le fichier XLSX.
        workbook.close()
    return str(output_path)