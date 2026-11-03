import json
import math

import pandas as pd

from arcta.diag_summary import get_diag_short_vars_from_diag

def pack_curves(results):
    """Persist the actual DIAG arrays, with nulls for non-finite values."""
    def numbers(values):
        if values is None:
            return []
        output = []
        for value in values:
            try:
                number = float(value)
            except (TypeError, ValueError):
                number = float("nan")
            output.append(number if math.isfinite(number) else None)
        return output
    output = []
    for source_id, result in results.items():
        if not result.get("_plot_ready"):
            continue
        x = numbers(result.get("_aeff_clean"))
        signals = {"Y": result.get("_y_clean")}
        signals.update(result.get("_signals") or {})
        series = {}
        for key in ("Y", "Xg", "Xh", "Xt"):
            y = numbers(signals.get(key))
            if len(x) == len(y) and any(
                a is not None and b is not None for a, b in zip(x, y)
            ):
                series[key] = y
        if series:
            summary = result.get("summary") or {}
            marker_sources = (
                ("fmax", "Aeff_Ymax"),
                ("contact", "A_contact_Y_eff"),
                ("snug", "A_snug_eff"),
                ("elastic_start", "A_elastic_start_eff"),
                ("a0", None),
                ("elastic_end", "A_elastic_end_eff"),
            )
            markers = {}
            for marker, summary_key in marker_sources:
                value = 0.0 if summary_key is None else summary.get(summary_key)
                try:
                    value = float(value)
                except (TypeError, ValueError):
                    continue
                if math.isfinite(value):
                    markers[marker] = value
            output.append({
                "source_id": str(source_id),
                "x": x,
                "series": series,
                "markers": markers,
            })
    return tuple(output)


def pack_iso_boxplots(diag):
    """Persiste les données ISO 16269-4 nécessaires à la page DIAG."""
    dataframe = diag.get("DIAG_ISO16269_4_OUTLIERS")
    if not isinstance(dataframe, pd.DataFrame) or dataframe.empty:
        return ()
    if not {"Variable", "Value"}.issubset(dataframe.columns):
        return ()
    short_variables = set(get_diag_short_vars_from_diag(diag))
    packed = dataframe.copy(deep=True)
    packed["Short_Selected"] = packed["Variable"].astype(str).isin(short_variables)
    rows = json.loads(
        packed.to_json(orient="records", date_format="iso", force_ascii=False)
    )
    return tuple(dict(row) for row in rows)
