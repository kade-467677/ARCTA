"""Titres scientifiques construits exclusivement depuis les paramètres archivés."""
import math
import pandas as pd


def percentage(values):
    levels = set()
    for raw in values:
        try:
            number = float(raw)
            if isinstance(raw, bool) or not math.isfinite(number) or not 0 < number < 1:
                continue
            levels.add(number)
        except (TypeError, ValueError):
            continue
    if len(levels) != 1:
        return "non renseigné" if not levels else "incohérent"
    return (f"{100 * levels.pop():.2f}".rstrip("0").rstrip(".").replace(".", ",") + " %")


def statistical_caption(frame, *, settings=None, statistics=None):
    """Une ligne par famille présente ; objectifs de tolérance, pas garantie."""
    names = set(str(x).removeprefix("STAT_") for x in (statistics if statistics is not None else frame.columns))
    def level(column, parameter):
        if settings is None:
            return percentage(frame[column]) if column in frame else "non renseigné"
        if not {"Parameter", "Value"}.issubset(settings.columns):
            return "non renseigné"
        return percentage(settings.loc[settings.Parameter == parameter, "Value"])
    lines = []
    if names & {"MEAN_CI_LOW", "MEAN_CI_HIGH", "CI95_LOW", "CI95_HIGH"}:
        lines.append("IC moyenne : confiance " + level("STAT_MEAN_CI_CONF_TARGET", "MEAN_CI_CONF_LEVEL"))
    if names & {"MEDIAN_CI_LOW", "MEDIAN_CI_HIGH"}:
        lines.append("IC médiane : confiance " + level("STAT_MEDIAN_CI_CONF_TARGET", "ISO_MEDIAN_CONF_LEVEL"))
    if any(name.startswith("TOL_") and name.endswith(("LOW", "HIGH")) for name in names):
        lines.append("Tolérance : proportion cible " + level("STAT_TOL_P", "ISO_TOL_P_CONTENT") +
                     " ; confiance cible " + level("STAT_TOL_CONF", "ISO_TOL_CONF_LEVEL"))
    return "\n".join(lines)

# 64G3A_MEAN_CI_NAMES
