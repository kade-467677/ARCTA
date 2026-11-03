from __future__ import annotations
from arcta.notation import iso_text, LABELS, nomenclature_rows

import hashlib
import math
import os
import re
import threading
import warnings
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path

import numpy as np
import pandas as pd

from arcta.diag_summary import DIAG_ISO16269_4_SHORT_VARS
from arcta.statistical_titles import statistical_caption
from arcta.tolerance import tolerance_notice
from arcta.tolerance_explanations import graph_explanation


PLOTS_DIRNAME = "plots"
PLOTS_ZIP_FILENAME = "graphs.zip"
PLOT_INVENTORY_COLUMNS = (
    "Kind",
    "Title",
    "Category",
    "Report_Key",
    "Page_Group",
    "Sort_Order",
    "Scope",
    "Filename",
    "Relative_Path",
    "Variables",
)

_PLOT_LOCK = threading.RLock()
_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")

_AXIS_LABELS = LABELS


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_filename(value: str) -> str:
    cleaned = _SAFE_FILENAME.sub("_", str(value)).strip("._")
    return cleaned or "plot"


def _numeric(values) -> np.ndarray:
    return pd.to_numeric(
        pd.Series(values),
        errors="coerce",
    ).to_numpy(dtype=float)


def _normalized_role(value: str) -> str:
    return str(value).strip().replace("μ", "µ")


def _axis_label(role: str) -> str:
    normalized = _normalized_role(role)
    label, unit = _AXIS_LABELS.get(normalized, (normalized, ""))
    return f"{label} ({unit})" if unit else label


def _compute_relation(sheet_name: str) -> tuple[str, str] | None:
    """Retourne (abscisse, ordonnée) depuis le contrat de nommage V5."""
    name = _normalized_role(sheet_name)
    match = re.fullmatch(r"TEST_COMPUTE_([^f]+)f(.+)", name)
    if match:
        return _normalized_role(match.group(2)), _normalized_role(match.group(1))
    match = re.fullmatch(r"(.+)_COMPUTE_f(.+)", name)
    if match:
        return _normalized_role(match.group(2)), _normalized_role(match.group(1))
    return None


def _plotting():
    import matplotlib

    matplotlib.use("Agg", force=True)
    matplotlib.rcParams.update({
        "font.size": 12.0,
        "axes.titlesize": 16.0,
        "axes.labelsize": 14.0,
        "xtick.labelsize": 12.0,
        "ytick.labelsize": 12.0,
        "legend.fontsize": 9.5,
        "figure.titlesize": 17.0,
        "axes.formatter.limits": (-2, 5),
        "axes.formatter.use_mathtext": True,
    })
    from matplotlib import pyplot as plt

    return plt


def _mechanical_labels(ax, frame):
    label = frame.attrs.get("mechanical_caption", "")
    if not label:
        return
    title = ax.get_title()
    if label.startswith("Couple effectif"):
        title = title.replace("expérimentales", "issues des mesures corrigées").replace("EXP", "MESURES CORRIGÉES")
        for get, set_label in ((ax.get_xlabel, ax.set_xlabel),(ax.get_ylabel, ax.set_ylabel)):
            text = get().replace("Couple de serrage T", "Couple effectif T").replace("Couple transmis par le filetage T_th", "Couple effectif dans le filetage T_th").replace("Couple global", "Couple effectif").replace("Couple T", "Couple effectif T").replace("Couple filet", "Couple filet effectif")
            set_label(text)
    ax.set_title(title+"\n"+label, fontsize=10)


def _save_figure(fig, path: Path) -> None:
    temporary = path.with_name(path.name + ".part")
    try:
        fig.savefig(
            temporary,
            format="png",
            dpi=190,
            bbox_inches="tight",
            facecolor="white",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _artifact(
    path: Path,
    *,
    session_root: Path,
    kind: str,
    title: str,
    category: str,
    report_key: str,
    page_group: str,
    sort_order: int,
    scope: str = "",
    variables: Sequence[str] = (),
) -> dict[str, object]:
    return {
        "kind": str(kind),
        "filename": path.name,
        "relative_path": path.relative_to(session_root).as_posix(),
        "media_type": "image/png",
        "size_bytes": path.stat().st_size,
        "sha256": _sha256_file(path),
        "title": iso_text(title),
        "category": str(category),
        "report_key": str(report_key),
        "page_group": str(page_group),
        "sort_order": int(sort_order),
        "scope": str(scope),
        "variables": [str(item) for item in variables],
    }


def _record_error(
    errors: list[dict[str, str]],
    *,
    plot: str,
    exc: BaseException,
) -> None:
    errors.append({
        "Plot": str(plot),
        "Error_Type": type(exc).__name__,
        "Error_Message": str(exc),
    })


def _trial_columns(dataframe: pd.DataFrame) -> dict[str, dict[str, str]]:
    trials: dict[str, dict[str, str]] = {}
    for column in dataframe.columns:
        match = re.fullmatch(r"(Xg|Xh|Xt|Y|A)_(.+)", str(column))
        if match:
            trials.setdefault(match.group(2), {})[match.group(1)] = str(column)
    return trials


def _experimental_plot_limits(
    dataframe: pd.DataFrame,
    *,
    x_role: str,
    y_role: str,
    margin: float = 0.05,
) -> tuple[tuple[float, float], tuple[float, float]] | None:
    """Fenêtre X/Y calculée uniquement sur les points expérimentaux tracés."""
    x_parts: list[np.ndarray] = []
    y_parts: list[np.ndarray] = []
    for columns in _trial_columns(dataframe).values():
        if x_role not in columns or y_role not in columns:
            continue
        x = _numeric(dataframe[columns[x_role]])
        y = _numeric(dataframe[columns[y_role]])
        n = min(len(x), len(y))
        mask = np.isfinite(x[:n]) & np.isfinite(y[:n])
        if mask.any():
            x_parts.append(x[:n][mask])
            y_parts.append(y[:n][mask])
    if not x_parts:
        return None

    def padded(values: np.ndarray) -> tuple[float, float]:
        lower = float(np.min(values))
        upper = float(np.max(values))
        span = upper - lower
        padding = (
            span * max(float(margin), 0.0)
            if span > 0.0
            else max(abs(lower) * max(float(margin), 0.0), 1.0)
        )
        return lower - padding, upper + padding

    return padded(np.concatenate(x_parts)), padded(np.concatenate(y_parts))


def _plot_concat_overlay(
    dataframe: pd.DataFrame,
    *,
    x_role: str,
    y_role: str,
    title: str,
    xlabel: str,
    ylabel: str,
    path: Path,
    xlim: tuple[float, float] | None = None,
    ylim: tuple[float, float] | None = None,
    peak_rows: pd.DataFrame | None = None,
) -> bool:
    # 63D2: fenêtres EXP / TEST_COMPUTE communes
    if xlim is None and ylim is None and x_role == "A":
        limits = _experimental_plot_limits(
            dataframe, x_role=x_role, y_role=y_role
        )
        if limits is not None:
            xlim, ylim = limits

    plt = _plotting()
    fig, ax = plt.subplots(figsize=(11, 6.5))
    plotted = 0
    try:
        for trial_id, columns in _trial_columns(dataframe).items():
            if x_role not in columns or y_role not in columns:
                continue
            x = _numeric(dataframe[columns[x_role]])
            y = _numeric(dataframe[columns[y_role]])
            n = min(len(x), len(y))
            mask = np.isfinite(x[:n]) & np.isfinite(y[:n])
            if int(mask.sum()) < 2:
                continue
            order = np.argsort(x[:n][mask])
            ax.plot(
                x[:n][mask],
                y[:n][mask],
                linewidth=1.25,
                label=trial_id,
            )
            if x_role == "Xg" and y_role == "Y":
                j = int(np.argmax(y[:n][mask]))
                px, py = x[:n][mask][j], y[:n][mask][j]
                if isinstance(peak_rows, pd.DataFrame) and {"Trial_ID", "T_at_Fmax_Nm", "Ymax"}.issubset(peak_rows.columns):
                    rows = peak_rows[peak_rows["Trial_ID"].astype(str) == str(trial_id)]
                    if len(rows) == 1:
                        tx, fy = float(rows.iloc[0]["T_at_Fmax_Nm"]), float(rows.iloc[0]["Ymax"])
                        if np.isfinite(tx) and np.isfinite(fy):
                            px = tx - dataframe.attrs.get("autofrein_offsets", {}).get(str(trial_id), 0)
                            py = fy
                # Sans repère DIAG, px est déjà lu dans les coordonnées affichées.
                ax.scatter([px], [py],
                           marker="D", s=34, facecolors="white",
                           edgecolors=ax.lines[-1].get_color(), zorder=5)
            plotted += 1

        if not plotted:
            return False
        if x_role == "Xg" and y_role == "Y":
            title += " — losanges : Fmax au serrage"
        ax.set_title(iso_text(title))
        ax.set_xlabel(iso_text(xlabel))
        ax.set_ylabel(iso_text(ylabel))
        if xlim is not None:
            ax.set_xlim(*xlim)
        if ylim is not None:
            ax.set_ylim(*ylim)
        ax.grid(True, alpha=0.28)
        ax.legend(
            loc="best",
            fontsize=8 if plotted <= 15 else 7,
            ncol=1 if plotted <= 15 else 2,
        )
        _mechanical_labels(ax, dataframe)
        _save_figure(fig, path)
        return True
    finally:
        plt.close(fig)


def _compute_trial_columns(dataframe: pd.DataFrame) -> list[str]:
    columns = [str(column) for column in dataframe.columns]
    if not columns:
        return []
    output = []
    for column in columns[1:]:
        if not column or column.startswith("STAT_"):
            continue
        values = _numeric(dataframe[column])
        if np.isfinite(values).any():
            output.append(column)
    return output


def _nrmse_percent(values, reference) -> float:
    values = _numeric(values)
    reference = _numeric(reference)
    count = min(len(values), len(reference))
    values = values[:count]
    reference = reference[:count]
    finite = np.isfinite(values) & np.isfinite(reference)
    if int(finite.sum()) < 2:
        return float("nan")
    rmse = float(np.sqrt(np.mean((values[finite] - reference[finite]) ** 2)))
    amplitude = float(np.max(reference[finite]) - np.min(reference[finite]))
    if not np.isfinite(amplitude) or amplitude <= 0:
        return float("nan")
    return 100.0 * rmse / amplitude


def _nrmse_class(value: float) -> str:
    if not np.isfinite(value):
        return "NON_CALCULABLE"
    if value <= 1.0:
        return "≤ 1 %"
    if value <= 2.5:
        return "]1 ; 2,5] %"
    if value <= 5.0:
        return "]2,5 ; 5] %"
    if value <= 10.0:
        return "]5 ; 10] %"
    return "> 10 %"


def _curve_deviation_rows(
    dataframe: pd.DataFrame,
    *,
    relation: str,
) -> list[dict[str, object]]:
    if dataframe.empty or "STAT_MEAN" not in dataframe.columns:
        return []
    reference = _numeric(dataframe["STAT_MEAN"])
    rows = []
    for trial_id in _compute_trial_columns(dataframe):
        value = _nrmse_percent(dataframe[trial_id], reference)
        rows.append({
            "Relation": relation,
            "Trial_ID": str(trial_id),
            "nRMSE_Percent": value,
            "Threshold_Class": _nrmse_class(value),
            "Within_1pct": bool(np.isfinite(value) and value <= 1.0),
            "Within_2_5pct": bool(np.isfinite(value) and value <= 2.5),
            "Within_5pct": bool(np.isfinite(value) and value <= 5.0),
            "Within_10pct": bool(np.isfinite(value) and value <= 10.0),
        })
    rows.sort(
        key=lambda row: (
            np.isfinite(float(row["nRMSE_Percent"])),
            float(row["nRMSE_Percent"])
            if np.isfinite(float(row["nRMSE_Percent"])) else -np.inf,
        ),
        reverse=True,
    )
    for rank, row in enumerate(rows, start=1):
        row["Rank_Worst_First"] = rank
    return rows


def _plot_nrmse_bars(
    dataframe: pd.DataFrame,
    *,
    relation: str,
    title: str,
    path: Path,
) -> bool:
    subset = dataframe[dataframe["Relation"].astype(str) == relation].copy()
    if subset.empty:
        return False
    subset["nRMSE_Percent"] = pd.to_numeric(
        subset["nRMSE_Percent"], errors="coerce"
    )
    subset = subset.sort_values("nRMSE_Percent", ascending=False, na_position="last")
    values = subset["nRMSE_Percent"].to_numpy(dtype=float)
    trials = subset["Trial_ID"].astype(str).tolist()

    def color(value: float) -> str:
        if not np.isfinite(value):
            return "#b8bec5"
        if value <= 1.0:
            return "#008c33"
        if value <= 2.5:
            return "#59bf40"
        if value <= 5.0:
            return "#f2d12e"
        if value <= 10.0:
            return "#f28c2e"
        return "#d93636"

    plt = _plotting()
    fig, ax = plt.subplots(figsize=(12, max(5.8, 0.34 * max(len(trials), 1))))
    try:
        positions = np.arange(len(trials))
        bars = ax.barh(
            positions,
            np.where(np.isfinite(values), values, 0.0),
            color=[color(value) for value in values],
        )
        ax.set_yticks(positions)
        ax.set_yticklabels(trials, fontsize=8)
        ax.invert_yaxis()
        for threshold, label, color_value in (
            (1.0, "1 %", "#008c33"),
            (2.5, "2,5 %", "#59bf40"),
            (5.0, "5 %", "#f2b82e"),
            (10.0, "10 %", "#f28c2e"),
        ):
            ax.axvline(threshold, color=color_value, linestyle=":", linewidth=1.0)
            ax.text(threshold, -0.65, label, color=color_value, fontsize=7, ha="center")
        for bar, value in zip(bars, values):
            label = "NC" if not np.isfinite(value) else f"{value:.2g} %"
            finite_values = values[np.isfinite(values)]
            offset_scale = float(np.max(finite_values)) if len(finite_values) else 1.0
            ax.text(
                bar.get_width() + max(0.08, 0.01 * max(offset_scale, 1.0)),
                bar.get_y() + bar.get_height() / 2.0,
                label,
                va="center",
                fontsize=8,
            )
        ax.set_title(iso_text(title))
        ax.set_xlabel("nRMSE normalisée par l’étendue de la courbe moyenne (%)")
        ax.grid(True, axis="x", alpha=0.25)
        _save_figure(fig, path)
        return True
    finally:
        plt.close(fig)


def _plot_compute_sheet(
    dataframe: pd.DataFrame,
    *,
    sheet_name: str,
    path: Path,
    experimental: pd.DataFrame | None = None,
) -> bool:
    if dataframe.empty or len(dataframe.columns) < 2:
        return False
    x_column = str(dataframe.columns[0])
    x = _numeric(dataframe[x_column])
    trial_columns = _compute_trial_columns(dataframe)
    if not trial_columns:
        return False
    invert_display = _normalized_role(sheet_name) == "TEST_COMPUTE_XgfY"
    experimental_limits = None
    relation_for_limits = _compute_relation(sheet_name)
    if (
        isinstance(experimental, pd.DataFrame)
        and not experimental.empty
        and relation_for_limits is not None
        and relation_for_limits[0] == "A"
        and relation_for_limits[1] in {"Y", "Xg"}
    ):
        experimental_limits = _experimental_plot_limits(
            experimental,
            x_role=relation_for_limits[0],
            y_role=relation_for_limits[1],
        )

    plt = _plotting()
    fig, ax = plt.subplots(figsize=(11, 6.5))
    plotted = 0
    try:
        for column in trial_columns:
            y = _numeric(dataframe[column])
            n = min(len(x), len(y))
            mask = np.isfinite(x[:n]) & np.isfinite(y[:n])
            if int(mask.sum()) < 2:
                continue
            plot_x = y[:n][mask] if invert_display else x[:n][mask]
            plot_y = x[:n][mask] if invert_display else y[:n][mask]
            order = np.argsort(plot_x)
            ax.plot(
                plot_x[order],
                plot_y[order],
                linewidth=1.0,
                alpha=0.72,
                label=column,
            )
            plotted += 1

        for stat, label, color, style in (
            ("STAT_MEAN", "Moyenne", "#0b3b69", "-"),
            ("STAT_MEDIAN", "Médiane", "#111111", "--"),
            ("STAT_TOL_SELECTED_LOW", "Tolérance basse", "#c23b22", ":"),
            ("STAT_TOL_SELECTED_HIGH", "Tolérance haute", "#c23b22", ":"),
        ):
            if stat not in dataframe.columns:
                continue
            y = _numeric(dataframe[stat])
            n = min(len(x), len(y))
            mask = np.isfinite(x[:n]) & np.isfinite(y[:n])
            if int(mask.sum()) >= 2:
                plot_x = y[:n][mask] if invert_display else x[:n][mask]
                plot_y = x[:n][mask] if invert_display else y[:n][mask]
                order = np.argsort(plot_x)
                ax.plot(
                    plot_x[order],
                    plot_y[order],
                    linewidth=2.0 if stat in {"STAT_MEAN", "STAT_MEDIAN"} else 1.3,
                    color=color,
                    linestyle=style,
                    label=label,
                )

        if not plotted:
            return False
        relation = _compute_relation(sheet_name)
        x_role, y_role = relation if relation is not None else (x_column, sheet_name)
        if invert_display:
            x_role, y_role = y_role, x_role
            title = f"ARCTA — {sheet_name} — représentation Y=f(Xg)"
        else:
            title = f"ARCTA — {sheet_name} — {y_role}=f({x_role})"
        caption = statistical_caption(dataframe, statistics=["TOL_SELECTED_LOW"] if "STAT_TOL_SELECTED_LOW" in dataframe else [])
        ax.set_title(iso_text(title) + ("\n" + caption if caption else ""), fontsize=11)
        ax.set_xlabel(_axis_label(x_role))
        ax.set_ylabel(_axis_label(y_role))
        if experimental_limits is not None:
            ax.set_xlim(*experimental_limits[0])
            ax.set_ylim(*experimental_limits[1])
        elif _normalized_role(y_role).startswith("µ"):
            ax.set_ylim(bottom=0)
        ax.grid(True, alpha=0.28)
        ax.legend(
            loc="best",
            fontsize=7 if plotted > 12 else 8,
            ncol=2 if plotted > 12 else 1,
        )
        _mechanical_labels(ax, dataframe)
        _save_figure(fig, path)
        return True
    finally:
        plt.close(fig)


def _stat_values(dataframe: pd.DataFrame, *names: str) -> np.ndarray:
    for name in names:
        if name in dataframe.columns:
            return _numeric(dataframe[name])
    return np.full(len(dataframe), np.nan, dtype=float)


def _plot_v5_overlay(
    clean: pd.DataFrame,
    compute: pd.DataFrame,
    *,
    x_role: str,
    y_role: str,
    title: str,
    path: Path,
    invert_display: bool = False,
) -> bool:
    """Overlay V5 : EXP + Mean ±2σ + IC95 + tolérance ISO retenue."""
    if compute.empty or len(compute.columns) < 2:
        return False
    mean = _stat_values(compute, "STAT_MEAN")
    if not np.isfinite(mean).any():
        return False

    abscissa = _numeric(compute.iloc[:, 0])
    plus_2s = _stat_values(compute, "STAT_MEAN_PLUS_2S")
    minus_2s = _stat_values(compute, "STAT_MEAN_MINUS_2S")
    levels = _stat_values(compute, "STAT_MEAN_CI_CONF_TARGET")
    finite_levels = levels[np.isfinite(levels)]
    ci_label = (f"IC moyenne {100 * finite_levels[0]:g} %" if len(finite_levels) else "IC moyenne — niveau non archivé")
    ci_low = _stat_values(compute, "STAT_MEAN_CI_LOW", "STAT_CI95_LOW")
    ci_high = _stat_values(compute, "STAT_MEAN_CI_HIGH", "STAT_CI95_HIGH")
    tol_low = _stat_values(
        compute,
        "STAT_TOL_LOW",
        "STAT_TOL_SELECTED_LOW",
    )
    tol_high = _stat_values(
        compute,
        "STAT_TOL_HIGH",
        "STAT_TOL_SELECTED_HIGH",
    )

    plt = _plotting()
    fig, ax = plt.subplots(figsize=(12, 6.5))
    plotted = 0
    try:
        for _trial_id, columns in _trial_columns(clean).items():
            if x_role not in columns or y_role not in columns:
                continue
            x = _numeric(clean[columns[x_role]])
            y = _numeric(clean[columns[y_role]])
            n = min(len(x), len(y))
            mask = np.isfinite(x[:n]) & np.isfinite(y[:n])
            if int(mask.sum()) < 2:
                continue
            order = np.argsort(x[:n][mask])
            ax.plot(
                x[:n][mask][order],
                y[:n][mask][order],
                linewidth=1.0,
                alpha=0.35,
                label="_nolegend_",
            )
            plotted += 1
        if not plotted:
            return False
        ax.plot(
            [],
            [],
            color="gray",
            linewidth=1.2,
            alpha=0.4,
            label="EXP (données)",
        )

        def finite(*arrays) -> np.ndarray:
            mask = np.ones(len(abscissa), dtype=bool)
            for values in (abscissa, *arrays):
                mask &= np.isfinite(values)
            return mask

        if invert_display:
            mask = finite(mean)
            ax.plot(mean[mask], abscissa[mask], color="black", linewidth=2.2, label="Moyenne")
            for values, label in ((plus_2s, "Moyenne + 2σ"), (minus_2s, "Moyenne − 2σ")):
                m = finite(values)
                if m.any():
                    ax.plot(values[m], abscissa[m], color="black", linewidth=1.1, linestyle="--", label=label)
            m = finite(ci_low, ci_high)
            if m.any():
                ax.fill_betweenx(abscissa[m], ci_low[m], ci_high[m], color="#7861A8", alpha=0.32, edgecolor="#5B4385", linewidth=0.8, zorder=1.8, label=ci_label)
            m = finite(tol_low, tol_high)
            if m.any():
                ax.fill_betweenx(abscissa, tol_low, tol_high, where=m, color="darkorange", alpha=0.20, label="Tolérance ponctuelle retenue")
                ax.plot(tol_low, abscissa, color="darkorange", linewidth=1.2, linestyle=":")
                ax.plot(tol_high, abscissa, color="darkorange", linewidth=1.2, linestyle=":")
        else:
            mask = finite(mean)
            ax.plot(abscissa[mask], mean[mask], color="black", linewidth=2.2, label="Moyenne")
            for values, label in ((plus_2s, "Moyenne + 2σ"), (minus_2s, "Moyenne − 2σ")):
                m = finite(values)
                if m.any():
                    ax.plot(abscissa[m], values[m], color="black", linewidth=1.1, linestyle="--", label=label)
            m = finite(ci_low, ci_high)
            if m.any():
                ax.fill_between(abscissa[m], ci_low[m], ci_high[m], color="#7861A8", alpha=0.32, edgecolor="#5B4385", linewidth=0.8, zorder=1.8, label=ci_label)
            m = finite(tol_low, tol_high)
            if m.any():
                ax.fill_between(abscissa, tol_low, tol_high, where=m, color="darkorange", alpha=0.20, label="Tolérance ponctuelle retenue")
                ax.plot(abscissa, tol_low, color="darkorange", linewidth=1.2, linestyle=":")
                ax.plot(abscissa, tol_high, color="darkorange", linewidth=1.2, linestyle=":")

        notice = tolerance_notice(compute)
        caption = statistical_caption(compute, statistics=["MEAN_CI_LOW", "TOL_LOW"])
        ax.set_title(iso_text(title) + "\n" + caption + ("\n" + notice if notice else ""), fontsize=11)
        explanation = graph_explanation(compute, _axis_label(x_role))
        if explanation:
            # Keep the original plot height; grow the canvas for the explanation.
            extra = 0.19 * len(explanation.splitlines()) + 0.4
            height = 6.5 + extra
            fig.set_size_inches(12, height)
            fig.subplots_adjust(bottom=(0.8 + extra) / height, top=1 - 1.25 / height)
            fig.text(0.08, 0.03, explanation, fontsize=10, va="bottom", ha="left")
        ax.set_xlabel(_axis_label(x_role))
        ax.set_ylabel(_axis_label(y_role))
        if x_role != "A":
            ax.set_xlim(left=0)
        if y_role != "A":
            ax.set_ylim(bottom=0)
        ax.grid(True, alpha=0.25)
        ax.legend(loc="best", fontsize=8)
        _mechanical_labels(ax, compute)
        _save_figure(fig, path)
        return True
    finally:
        plt.close(fig)


def _selected_short_variables(sheets: Mapping[str, pd.DataFrame]) -> list[str]:
    selection = sheets.get("DIAG_SHORT_SELECTION")
    if (
        isinstance(selection, pd.DataFrame)
        and not selection.empty
        and {"Variable", "Selected"}.issubset(selection.columns)
    ):
        selected = []
        for _, row in selection.iterrows():
            raw = row.get("Selected", False)
            if raw is True or str(raw).strip().lower() in {
                "true", "1", "yes", "oui", "x"
            }:
                selected.append(str(row.get("Variable", "")))
        if selected:
            return selected
    return list(DIAG_ISO16269_4_SHORT_VARS)


def _finite_number(row: pd.Series, *names: str) -> float:
    for name in names:
        try:
            value = float(row.get(name, np.nan))
        except (TypeError, ValueError):
            continue
        if np.isfinite(value):
            return value
    return float("nan")


def _plot_iso_boxplot_page(
    dataframe: pd.DataFrame,
    *,
    variables: Sequence[str],
    title: str,
    path: Path,
    ncols: int = 2,
    compact: bool = False,
) -> bool:
    plt = _plotting()
    count = len(variables)
    if count == 0:
        return False
    ncols = max(1, min(int(ncols), count))
    nrows = int(math.ceil(count / ncols))
    fig, axes = plt.subplots(
        nrows,
        ncols,
        figsize=(18, 11.5) if compact else (14, max(4.5 * nrows, 5.5)),
        squeeze=False,
    )
    flat_axes = list(axes.flatten())
    try:
        for ax, variable in zip(flat_axes, variables):
            subset = dataframe[
                dataframe["Variable"].astype(str) == str(variable)
            ].copy()
            subset["Value"] = pd.to_numeric(
                subset["Value"],
                errors="coerce",
            )
            subset = subset[np.isfinite(subset["Value"])].copy()
            if subset.empty:
                ax.axis("off")
                continue
            values = subset["Value"].to_numpy(dtype=float)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", PendingDeprecationWarning)
                ax.boxplot(
                    values,
                    vert=False,
                    widths=0.30,
                    showmeans=True,
                    patch_artist=True,
                    boxprops={"facecolor": "#dceeff", "color": "#4a76a8"},
                    medianprops={"color": "navy", "linewidth": 1.4},
                    meanprops={
                        "marker": "o",
                        "markerfacecolor": "white",
                        "markeredgecolor": "black",
                        "markersize": 5,
                    },
                )
            jitter = (
                np.linspace(-0.10, 0.10, len(values))
                if len(values) > 1 else np.array([0.0])
            )
            severity_colors = {
                "OK": "#4f6f52",
                "WARNING": "#d97706",
                "FAIL": "#b42318",
            }
            levels = subset.get(
                "Outlier_Level",
                pd.Series(["OK"] * len(subset), index=subset.index),
            )
            colors = [
                severity_colors.get(str(value).upper(), "#5b6570")
                for value in levels
            ]
            ax.scatter(
                values,
                1.0 + jitter,
                s=18 if compact else 28,
                c=colors,
                zorder=3,
            )
            for x_value, y_value, trial_id in zip(
                values,
                1.0 + jitter,
                subset.get("Trial_ID", pd.Series([""] * len(subset))),
            ):
                ax.annotate(
                    str(trial_id),
                    (x_value, y_value),
                    xytext=(3, 4),
                    textcoords="offset points",
                    fontsize=5 if compact else 6,
                    alpha=0.8,
                )

            first = subset.iloc[0]
            for value, color, style, label in (
                (_finite_number(first, "Median"), "navy", "-", "Médiane"),
                (_finite_number(first, "Lower_Fence_Warn", "IQR_Low_Warn"), "#d97706", "--", "Seuil WARNING"),
                (_finite_number(first, "Upper_Fence_Warn", "IQR_High_Warn"), "#d97706", "--", ""),
                (_finite_number(first, "Lower_Fence_Fail", "IQR_Low_Fail"), "#b42318", ":", "Seuil FAIL"),
                (_finite_number(first, "Upper_Fence_Fail", "IQR_High_Fail"), "#b42318", ":", ""),
            ):
                if np.isfinite(value):
                    ax.axvline(
                        value,
                        color=color,
                        linestyle=style,
                        linewidth=1.0,
                        label=label or None,
                    )
            description = str(first.get("Description_FR", variable))
            unit = str(first.get("Unit", "")).strip()
            ax.set_title(iso_text(description), fontsize=8 if compact else 10)
            ax.set_xlabel(
                unit if unit and unit != "nan" else str(variable),
                fontsize=7 if compact else None,
            )
            if compact:
                ax.tick_params(axis="x", labelsize=6.5)
            ax.set_yticks([])
            ax.grid(True, axis="x", alpha=0.25)

        for ax in flat_axes[count:]:
            ax.axis("off")
        handles, labels = flat_axes[0].get_legend_handles_labels()
        if handles:
            unique = dict(zip(labels, handles))
            fig.legend(
                unique.values(),
                unique.keys(),
                loc="lower center",
                ncol=min(4, len(unique)),
                fontsize=6.5 if compact else 8,
            )
        fig.suptitle(iso_text(title), fontsize=13 if compact else 14, fontweight="bold")
        fig.tight_layout(rect=(0, 0.05, 1, 0.96))
        _save_figure(fig, path)
        return True
    finally:
        plt.close(fig)


def _self_lock_frames(
    sheets: Mapping[str, pd.DataFrame],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    comparison = sheets.get("AUTOFREIN_COMPARISON")
    if not isinstance(comparison, pd.DataFrame) or comparison.empty:
        comparison = sheets.get("DIAG_AUTOFREIN")
    if not isinstance(comparison, pd.DataFrame) or comparison.empty:
        return pd.DataFrame(), pd.DataFrame()

    # Le Web persiste la synthèse DIAG entre la revue et l'exécution, mais pas
    # nécessairement la feuille DIAG_AUTOFREIN détaillée. On réinjecte ici les
    # scalaires pré-A0 disponibles afin que le rapport ne perde ni le graphe
    # ni la synthèse SelfLock.
    comparison = comparison.copy()
    value_columns = (
        "Autofrein_Xg_preA0_med",
        "Autofrein_Xg_preA0_mean",
        "Autofrein_Xg_preA0_std",
        "Autofrein_Xg_preA0_MAD",
    )
    for sheet_name in ("DIAG_AUTOFREIN", "DIAG_SUMMARY"):
        candidate = sheets.get(sheet_name)
        if (
            not isinstance(candidate, pd.DataFrame)
            or candidate.empty
            or "Trial_ID" not in candidate.columns
            or "Trial_ID" not in comparison.columns
        ):
            continue
        available = [column for column in value_columns if column in candidate.columns]
        if not available:
            continue
        lookup = candidate[["Trial_ID", *available]].drop_duplicates("Trial_ID")
        merged = comparison.merge(
            lookup,
            on="Trial_ID",
            how="left",
            suffixes=("", "__diag"),
        )
        for column in available:
            fallback = f"{column}__diag"
            if column not in merged.columns:
                merged[column] = merged[fallback]
            elif fallback in merged.columns:
                merged[column] = merged[column].combine_first(merged[fallback])
            if fallback in merged.columns:
                merged = merged.drop(columns=[fallback])
        comparison = merged

    detail_columns = [
        column for column in (
            "Trial_ID",
            "Source_Name",
            "Autofrein_Xg_preA0_med",
            "Autofrein_Xg_preA0_mean",
            "Autofrein_Xg_preA0_std",
            "Autofrein_Xg_preA0_MAD",
        )
        if column in comparison.columns
    ]
    detail = comparison[detail_columns].copy()
    rows = []
    for column, label in (("Autofrein_Xg_preA0_med", "DIAG pré-A0"),):
        if column not in comparison.columns:
            continue
        values = _numeric(comparison[column])
        values = values[np.isfinite(values)]
        if not len(values):
            continue
        rows.append({
            "Method": label,
            "Variable": column,
            "N": int(len(values)),
            "Mean_Nm": float(np.mean(values)),
            "Median_Nm": float(np.median(values)),
            "Std_Nm": float(np.std(values, ddof=1)) if len(values) > 1 else np.nan,
            "Q1_Nm": float(np.percentile(values, 25)),
            "Q3_Nm": float(np.percentile(values, 75)),
            "Min_Nm": float(np.min(values)),
            "Max_Nm": float(np.max(values)),
        })
    return detail, pd.DataFrame(rows)


def _plot_self_lock_boxplot(
    detail: pd.DataFrame,
    *,
    path: Path,
) -> bool:
    data = []
    labels = []
    for column, label in (("Autofrein_Xg_preA0_med", "DIAG pré-A0"),):
        if column not in detail.columns:
            continue
        values = _numeric(detail[column])
        values = values[np.isfinite(values)]
        if len(values):
            data.append(values)
            labels.append(label)
    if not data:
        return False

    plt = _plotting()
    fig, ax = plt.subplots(figsize=(10, 5.8))
    try:
        try:
            boxplot = ax.boxplot(
                data, tick_labels=labels, patch_artist=True, showmeans=True
            )
        except TypeError:
            boxplot = ax.boxplot(
                data, labels=labels, patch_artist=True, showmeans=True
            )
        for patch, color in zip(boxplot["boxes"], ("#f28c2e",)):
            patch.set_facecolor(color)
            patch.set_alpha(0.32)
        ax.set_title("SelfLock / autofrein — évaluation DIAG pré-Θ₀")
        ax.set_ylabel("Couple d’autofrein (N·m)")
        ax.grid(True, axis="y", alpha=0.25)
        _save_figure(fig, path)
        return True
    finally:
        plt.close(fig)


def _plot_self_lock_trials(
    detail: pd.DataFrame,
    *,
    path: Path,
) -> bool:
    if "Trial_ID" not in detail.columns or "Autofrein_Xg_preA0_med" not in detail.columns:
        return False
    values = _numeric(detail["Autofrein_Xg_preA0_med"])
    trials = detail["Trial_ID"].astype(str).tolist()
    finite = np.isfinite(values)
    if not finite.any():
        return False
    values = values[finite]
    trials = [trial for trial, keep in zip(trials, finite) if keep]
    order = np.argsort(values)[::-1]
    values = values[order]
    trials = [trials[index] for index in order]

    plt = _plotting()
    fig, ax = plt.subplots(figsize=(11, max(5.5, 0.32 * len(trials))))
    try:
        positions = np.arange(len(trials))
        ax.barh(positions, values, color="#f28c2e", alpha=0.85)
        ax.set_yticks(positions)
        ax.set_yticklabels(trials, fontsize=8)
        ax.invert_yaxis()
        median = float(np.median(values))
        ax.axvline(
            median,
            color="#24364b",
            linestyle="--",
            linewidth=1.4,
            label=f"Médiane campagne = {median:.4g} N·m",
        )
        ax.set_title("SelfLock issu du DIAG pré-Θ₀ — détail par essai")
        ax.set_xlabel("Couple T médian avant Θ₀ (N·m)")
        ax.grid(True, axis="x", alpha=0.25)
        ax.legend(loc="best", fontsize=8)
        _save_figure(fig, path)
        return True
    finally:
        plt.close(fig)


def _compute_report_key(sheet_name: str) -> tuple[str, str, int] | None:
    normalized = _normalized_role(sheet_name)
    direct = {
        "TEST_COMPUTE_YfXg": ("compute_yfxg", "CORE_CURVES", 20),
        "TEST_COMPUTE_XgfY": ("compute_xgfy", "CORE_CURVES", 30),
        "TEST_COMPUTE_YfA": ("overlay_yfa", "ANGLE_CURVES", 10),
        "TEST_COMPUTE_XgfA": ("overlay_xgfa", "ANGLE_CURVES", 20),
    }
    if normalized in direct:
        return direct[normalized]
    if normalized.startswith("µg_COMPUTE_"):
        return "friction_mug", "FRICTION_MUG", 10
    if normalized.startswith("µh_COMPUTE_"):
        return "friction_muh", "FRICTION_MUH", 10
    if normalized.startswith("µt_COMPUTE_"):
        return "friction_mut", "FRICTION_MUT", 10
    return None


def generate_campaign_graphics(
    *,
    session_root: Path,
    run_dir: Path,
    sheets: Mapping[str, pd.DataFrame],
    report_options: Mapping[str, object] | None = None,
) -> tuple[dict[str, pd.DataFrame], tuple[dict[str, object], ...]]:
    """Génère les PNG 62G1 sans modifier les DataFrames scientifiques reçus."""
    output_sheets = {
        str(name): dataframe.copy(deep=True)
        for name, dataframe in sheets.items()
    }
    from arcta.run_mechanics import caption
    mechanical_caption = caption(output_sheets)
    for frame in output_sheets.values():
        frame.attrs["mechanical_caption"] = mechanical_caption
    if "CONCAT_EFFECTIVE" in output_sheets:
        # Raw measurements still exported separately; all plotted overlays share a basis.
        output_sheets["CONCAT_CLEAN"].attrs["mechanical_caption"] = "Couple total mesuré (données originales)"
    if "CONCAT_EFFECTIVE" in output_sheets:
        correction = output_sheets.get("ARCTA_SELFLOCK_CORRECTION", pd.DataFrame())
        output_sheets["CONCAT_EFFECTIVE"].attrs["autofrein_offsets"] = dict(zip(
            correction.get("Trial_ID", []), correction.get("Autofrein_Nm", [])))
    plot_dir = run_dir / PLOTS_DIRNAME
    plot_dir.mkdir(parents=True, exist_ok=True)
    artifacts: list[dict[str, object]] = []
    errors: list[dict[str, str]] = []
    selected_graphs = (
        None
        if report_options is None
        else {str(value) for value in report_options.get("graph_keys", ())}
    )

    def add_plot(
        *,
        stem: str,
        title: str,
        category: str,
        plotter,
        report_key: str,
        page_group: str,
        sort_order: int,
        scope: str = "",
        variables: Sequence[str] = (),
    ) -> None:
        if selected_graphs is not None and report_key not in selected_graphs:
            return
        index = len(artifacts) + 1
        kind = f"PNG_{index:03d}"
        path = plot_dir / f"{_safe_filename(stem)}.png"
        try:
            if plotter(path):
                artifacts.append(_artifact(
                    path,
                    session_root=session_root,
                    kind=kind,
                    title=title,
                    category=category,
                    report_key=report_key,
                    page_group=page_group,
                    sort_order=sort_order,
                    scope=scope,
                    variables=variables,
                ))
        except Exception as exc:
            _record_error(errors, plot=title, exc=exc)

    with _PLOT_LOCK:
        concat = output_sheets.get("CONCAT_EFFECTIVE", output_sheets.get("CONCAT_CLEAN"))
        if not isinstance(concat, pd.DataFrame) or concat.empty:
            concat = output_sheets.get("CONCAT")
        deviation_rows: list[dict[str, object]] = []
        for relation, sheet_name in (
            ("Y=f(Xg)", "TEST_COMPUTE_YfXg"),
            ("Xg=f(Y)", "TEST_COMPUTE_XgfY"),
        ):
            compute = output_sheets.get(sheet_name)
            if isinstance(compute, pd.DataFrame) and not compute.empty:
                deviation_rows.extend(_curve_deviation_rows(
                    compute,
                    relation=relation,
                ))
        deviations = pd.DataFrame(deviation_rows)
        if not deviations.empty:
            sources = output_sheets.get("ARCTA_SOURCES")
            if (
                isinstance(sources, pd.DataFrame)
                and {"Trial_ID", "Source_Name"}.issubset(sources.columns)
            ):
                deviations = deviations.merge(
                    sources[["Trial_ID", "Source_Name"]].drop_duplicates("Trial_ID"),
                    on="Trial_ID",
                    how="left",
                )
            output_sheets["ARCTA_CURVE_DEVIATIONS"] = deviations
            summary_rows = []
            for relation, group in deviations.groupby("Relation", sort=False):
                values = pd.to_numeric(group["nRMSE_Percent"], errors="coerce")
                finite = values[np.isfinite(values)]
                summary_rows.append({
                    "Relation": relation,
                    "N": int(len(finite)),
                    "Mean_nRMSE_Percent": float(finite.mean()) if len(finite) else np.nan,
                    "Median_nRMSE_Percent": float(finite.median()) if len(finite) else np.nan,
                    "Max_nRMSE_Percent": float(finite.max()) if len(finite) else np.nan,
                    "Count_Within_1pct": int((finite <= 1.0).sum()),
                    "Count_Within_2_5pct": int((finite <= 2.5).sum()),
                    "Count_Within_5pct": int((finite <= 5.0).sum()),
                    "Count_Within_10pct": int((finite <= 10.0).sum()),
                    "Count_Above_10pct": int((finite > 10.0).sum()),
                })
            output_sheets["ARCTA_CURVE_DEVIATION_SUMMARY"] = pd.DataFrame(summary_rows)
            for relation, report_key, order in (
                ("Y=f(Xg)", "nrmse_yfxg", 40),
                ("Xg=f(Y)", "nrmse_xgfy", 50),
            ):
                add_plot(
                    stem=f"G_NRMSE_{report_key.upper()}",
                    title=f"Écart des essais à la moyenne — {relation}",
                    category="CURVE_DEVIATION",
                    report_key=report_key,
                    page_group="CORE_CURVES",
                    sort_order=order,
                    variables=(relation,),
                    plotter=lambda path, rel=relation, ti=f"Écart des essais à la moyenne — {relation}": _plot_nrmse_bars(
                        deviations,
                        relation=rel,
                        title=ti,
                        path=path,
                    ),
                )
        else:
            output_sheets["ARCTA_CURVE_DEVIATIONS"] = pd.DataFrame(columns=(
                "Relation", "Trial_ID", "Source_Name", "nRMSE_Percent",
                "Threshold_Class", "Within_1pct", "Within_2_5pct",
                "Within_5pct", "Within_10pct", "Rank_Worst_First",
            ))
            output_sheets["ARCTA_CURVE_DEVIATION_SUMMARY"] = pd.DataFrame()

        if isinstance(concat, pd.DataFrame) and not concat.empty:
            for stem, x_role, y_role, title, report_key, page_group, order in (
                ("G_EXP_YfXg", "Xg", "Y", "Courbes expérimentales nettoyées — Y=f(Xg)", "exp_yfxg", "CORE_CURVES", 10),
                ("G_EXP_YfA", "A", "Y", "Courbes expérimentales nettoyées — Y=f(A_eff)", "exp_yfa", "ANGLE_CURVES", 5),
                ("G_EXP_XgfA", "A", "Xg", "Courbes expérimentales nettoyées — Xg=f(A_eff)", "exp_xgfa", "ANGLE_CURVES", 6),
            ):
                add_plot(
                    stem=stem,
                    title=title,
                    category="CAMPAIGN_CURVES",
                    report_key=report_key,
                    page_group=page_group,
                    sort_order=order,
                    variables=(x_role, y_role),
                    plotter=lambda path, xr=x_role, yr=y_role, ti=title: _plot_concat_overlay(
                        concat,
                        x_role=xr,
                        y_role=yr,
                        title=ti,
                        xlabel=_axis_label(xr),
                        ylabel=_axis_label(yr),
                        path=path,
                        peak_rows=output_sheets.get("DIAG_SUMMARY"),
                    ),
                )

        for sheet_name, dataframe in output_sheets.items():
            if "_COMPUTE_" not in sheet_name:
                continue
            if not isinstance(dataframe, pd.DataFrame) or dataframe.empty:
                continue
            report_contract = _compute_report_key(sheet_name)
            if report_contract is None and selected_graphs is not None:
                continue
            report_key, page_group, order = report_contract or (
                "compute_yfxg", "COMPUTE_OTHER", 100
            )
            graph_title = f"Courbes calculées et statistiques — {sheet_name}"
            if _normalized_role(sheet_name) == "TEST_COMPUTE_XgfY":
                graph_title += " — représentation Y=f(Xg)"
            add_plot(
                stem=f"G_{sheet_name}",
                title=graph_title,
                category="COMPUTE",
                report_key=report_key,
                page_group=page_group,
                sort_order=order,
                variables=(sheet_name,),
                plotter=lambda path, df=dataframe, name=sheet_name: _plot_compute_sheet(
                    df,
                    sheet_name=name,
                    path=path,
                experimental=concat if isinstance(concat, pd.DataFrame) else None,
                ),
            )

        if isinstance(concat, pd.DataFrame) and not concat.empty:
            for stem, sheet_name, x_role, y_role, invert_display, title, report_key, page_group, order in (
                (
                    "G_OVERLAY_CONCATCLEAN_STATS_YfXg",
                    "TEST_COMPUTE_YfXg",
                    "Xg",
                    "Y",
                    False,
                    "Overlay V5 — Y=f(Xg) — EXP + statistiques + tolérance ISO",
                    "overlay_yfxg",
                    "OVERLAY_TORQUE_TENSION",
                    10,
                ),
                (
                    "G_OVERLAY_CONCATCLEAN_STATS_XgfY",
                    "TEST_COMPUTE_XgfY",
                    "Xg",
                    "Y",
                    True,
                    "Overlay V5 — Xg=f(Y) affiché en Y=f(Xg) — EXP + statistiques + tolérance ISO",
                    "overlay_xgfy",
                    "OVERLAY_TORQUE_TENSION",
                    20,
                ),
                (
                    "G_OVERLAY_CONCATCLEAN_STATS_YfA",
                    "TEST_COMPUTE_YfA",
                    "A",
                    "Y",
                    False,
                    "Overlay V5 — Y=f(A) — EXP + statistiques + tolérance ISO",
                    "overlay_yfa",
                    "OVERLAY_ANGLE",
                    10,
                ),
                (
                    "G_OVERLAY_CONCATCLEAN_STATS_XgfA",
                    "TEST_COMPUTE_XgfA",
                    "A",
                    "Xg",
                    False,
                    "Overlay V5 — Xg=f(A) — EXP + statistiques + tolérance ISO",
                    "overlay_xgfa",
                    "OVERLAY_ANGLE",
                    20,
                ),
            ):
                compute = output_sheets.get(sheet_name)
                if not isinstance(compute, pd.DataFrame) or compute.empty:
                    continue
                add_plot(
                    stem=stem,
                    title=title,
                    category="OVERLAY_V5",
                    report_key=report_key,
                    page_group=page_group,
                    sort_order=order,
                    variables=(x_role, y_role),
                    plotter=lambda path, df=compute, xr=x_role, yr=y_role, ti=title, inv=invert_display: _plot_v5_overlay(
                        concat,
                        df,
                        x_role=xr,
                        y_role=yr,
                        title=ti,
                        path=path,
                        invert_display=inv,
                    ),
                )

        iso = output_sheets.get("DIAG_ISO16269_4_OUTLIERS")
        if (
            isinstance(iso, pd.DataFrame)
            and not iso.empty
            and {"Variable", "Value"}.issubset(iso.columns)
        ):
            from .diag_presentation import HIDDEN_DIAG
            available = [v for v in dict.fromkeys(iso["Variable"].astype(str)) if v not in HIDDEN_DIAG]
            short_selected = _selected_short_variables(output_sheets)
            short_available = [
                item for item in short_selected if item in available
            ]
            # Le rapport synthétique rassemble les trois premières planches
            # DIAG (12 indicateurs) sur une unique page A4 paysage. Les
            # planches historiques de 4 indicateurs restent disponibles dans
            # les PNG et le ZIP pour l'inspection détaillée.
            if (
                selected_graphs is not None
                and "diag_boxplots_short" in selected_graphs
                and short_available
            ):
                report_variables = short_available[:12]
                report_title = (
                    "DIAG — 12 boîtes à moustaches décisionnelles "
                    "(ISO 16269-4)"
                )
                add_plot(
                    stem="DIAG_ISO16269_4_SHORT_REPORT",
                    title=report_title,
                    category="DIAG_ISO16269_4",
                    report_key="diag_boxplots_short",
                    page_group="DIAG_BOXPLOTS_SHORT_REPORT",
                    sort_order=0,
                    scope="SHORT_REPORT",
                    variables=report_variables,
                    plotter=lambda path, values=tuple(report_variables), ti=report_title: _plot_iso_boxplot_page(
                        iso,
                        variables=values,
                        title=ti,
                        path=path,
                        ncols=4,
                        compact=True,
                    ),
                )
            scopes = (
                ("SHORT", short_available),
                ("FULL", available),
            )
            for scope, variables_scope in scopes:
                for page, start in enumerate(range(0, len(variables_scope), 4), start=1):
                    chunk = variables_scope[start:start + 4]
                    title = (
                        "DIAG — Boîtes à moustaches ISO 16269-4 "
                        f"({scope}, page {page})"
                    )
                    add_plot(
                        stem=f"DIAG_ISO16269_4_{scope}_{page:02d}",
                        title=title,
                        category="DIAG_ISO16269_4",
                        report_key=(
                            "diag_boxplots_short"
                            if scope == "SHORT" else "diag_boxplots_full"
                        ),
                        page_group=f"DIAG_BOXPLOTS_{scope}",
                        sort_order=page,
                        scope=scope,
                        variables=chunk,
                        plotter=lambda path, values=tuple(chunk), ti=title: _plot_iso_boxplot_page(
                            iso,
                            variables=values,
                            title=ti,
                            path=path,
                        ),
                    )

        self_lock_detail, self_lock_summary = _self_lock_frames(output_sheets)
        output_sheets["ARCTA_SELF_LOCK"] = self_lock_detail
        output_sheets["ARCTA_SELF_LOCK_STATS"] = self_lock_summary
        if not self_lock_detail.empty:
            add_plot(
                stem="G_SELF_LOCK_BOXPLOT",
                title="SelfLock / autofrein — évaluation DIAG pré-Θ₀",
                category="SELF_LOCK",
                report_key="self_lock",
                page_group="SELF_LOCK",
                sort_order=10,
                variables=("Autofrein_Xg_preA0_med",),
                plotter=lambda path: _plot_self_lock_boxplot(
                    self_lock_detail,
                    path=path,
                ),
            )

    inventory_rows = [
        {
            "Kind": item["kind"],
            "Title": item["title"],
            "Category": item["category"],
            "Report_Key": item["report_key"],
            "Page_Group": item["page_group"],
            "Sort_Order": item["sort_order"],
            "Scope": item["scope"],
            "Filename": item["filename"],
            "Relative_Path": item["relative_path"],
            "Variables": "; ".join(item["variables"]),
        }
        for item in artifacts
    ]
    output_sheets["ARCTA_PLOTS"] = pd.DataFrame(
        inventory_rows,
        columns=PLOT_INVENTORY_COLUMNS,
    )
    output_sheets["ARCTA_PLOTS_ERRORS"] = pd.DataFrame(
        errors,
        columns=("Plot", "Error_Type", "Error_Message"),
    )

    if artifacts:
        zip_path = run_dir / PLOTS_ZIP_FILENAME
        temporary = zip_path.with_name(zip_path.name + ".part")
        try:
            with zipfile.ZipFile(
                temporary,
                "w",
                compression=zipfile.ZIP_DEFLATED,
            ) as archive:
                for item in artifacts:
                    path = session_root / str(item["relative_path"])
                    archive.write(path, arcname=path.name)
            os.replace(temporary, zip_path)
        finally:
            temporary.unlink(missing_ok=True)
        artifacts.append({
            "kind": "PLOTS_ZIP",
            "filename": zip_path.name,
            "relative_path": zip_path.relative_to(session_root).as_posix(),
            "media_type": "application/zip",
            "size_bytes": zip_path.stat().st_size,
            "sha256": _sha256_file(zip_path),
            "title": "Tous les graphes PNG",
            "category": "PLOTS_BUNDLE",
            "scope": "",
            "variables": [],
        })

    return output_sheets, tuple(artifacts)

# 64G3A_MEAN_CI_NAMES
