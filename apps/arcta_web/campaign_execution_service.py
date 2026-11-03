from __future__ import annotations

import math
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from arcta.analysis_config import (
    ArctaAnalysisConfig,
    DEFAULT_ARCTA_ANALYSIS_CONFIG,
)
from arcta.campaign import ArctaCampaignResult
from arcta.dual_campaign import analyze_dual_campaign as analyze_campaign
from arcta.profiles import require_profile_config
from cta_core.campaign_run import (
    ArctaCampaignRun,
    ArctaCampaignRunPlan,
)

from apps.arcta_web.campaign_run_plan import (
    CampaignRunPrerequisiteError,
    build_campaign_run_plan,
)
from apps.arcta_web.session_config import load_session_config
from apps.arcta_web.session_diag_review import load_session_diag_review
from apps.arcta_web.session_mapping import load_session_mapping
from apps.arcta_web.source_preview import read_source_dataframe
from web_common.sessions import is_trial_source


ProgressCallback = Callable[[float, str], None]
CampaignAnalyzer = Callable[..., ArctaCampaignResult]


class CampaignRunExecutionError(RuntimeError):
    """Échec structuré d'une exécution ARCTA Web 62B."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        run: ArctaCampaignRun,
        source_errors: tuple[dict[str, object], ...] = (),
    ) -> None:
        super().__init__(message)
        self.code = str(code)
        self.run = run
        self.source_errors = tuple(dict(item) for item in source_errors)


@dataclass(frozen=True)
class WebCampaignExecutionResult:
    """Résultat mémoire d'un run 62B, avant persistance et API."""

    run: ArctaCampaignRun
    campaign: ArctaCampaignResult
    source_preparation: tuple[dict[str, object], ...]
    accepted_source_ids: tuple[str, ...]
    rejected_source_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.run.terminal or self.run.status != "SUCCEEDED":
            raise ValueError("Le résultat 62B exige un run SUCCEEDED.")
        if not isinstance(self.campaign, ArctaCampaignResult):
            raise TypeError("campaign doit être un ArctaCampaignResult.")


def _fail(
    run: ArctaCampaignRun,
    code: str,
    message: str,
    *,
    cause: BaseException | None = None,
    source_errors: tuple[dict[str, object], ...] = (),
) -> None:
    failed = run.fail(code, message)
    error = CampaignRunExecutionError(
        message,
        code=code,
        run=failed,
        source_errors=source_errors,
    )
    if cause is None:
        raise error
    raise error from cause


def _assert_current_context(session, plan: ArctaCampaignRunPlan) -> None:
    try:
        current = build_campaign_run_plan(
            session, profile=plan.profile, analysis_settings=plan.analysis_settings or None
        )
    except CampaignRunPrerequisiteError as exc:
        raise CampaignRunPrerequisiteError(
            "Le contexte de campagne n'est plus exécutable : " + str(exc),
            code="RUN_CONTEXT_CHANGED",
        ) from exc

    if current.context_signature != plan.context_signature:
        raise CampaignRunPrerequisiteError(
            "Le contexte de campagne a changé depuis la création du plan.",
            code="RUN_CONTEXT_CHANGED",
        )


def _config_values(config) -> dict[str, object]:
    return {
        str(key): field.value
        for key, field in config.fields.items()
        if field.value is not None
    }


def _numeric_value(values: Mapping[str, object], key: str) -> float:
    value = float(values[key])
    if not math.isfinite(value):
        raise ValueError(f"La valeur CONFIG {key!r} n'est pas finie.")
    return value


def _build_constants(config, *, profile: str) -> dict[str, object]:
    values = _config_values(config)
    constants = dict(values)
    aliases = {
        "p": "p_mm",
        "d2": "d2_mm",
        "Db": "Db_mm",
    }
    profile_config = require_profile_config(profile)
    missing: list[str] = []

    for target, source in aliases.items():
        if source not in values:
            if profile_config.get("do_mu"):
                missing.append(source)
            continue
        constants[target] = _numeric_value(values, source)

    if missing:
        raise ValueError(
            "Constantes CONFIG requises pour le calcul des frottements : "
            + ", ".join(missing)
        )

    return constants


def _build_analysis_config(config) -> ArctaAnalysisConfig:
    values = _config_values(config)
    defaults = DEFAULT_ARCTA_ANALYSIS_CONFIG

    def number(key: str, default: float) -> float:
        if key not in values:
            return default
        return _numeric_value(values, key)

    def integer(key: str, default: int) -> int:
        if key not in values:
            return default
        value = _numeric_value(values, key)
        if not value.is_integer():
            raise ValueError(f"La valeur CONFIG {key!r} doit être entière.")
        return int(value)

    return ArctaAnalysisConfig(
        thr_ratio=number("thr_ratio", defaults.thr_ratio),
        iso_tol_p_content=number(
            "iso_tol_p_content", defaults.iso_tol_p_content
        ),
        iso_tol_conf_level=number(
            "iso_tol_conf_level", defaults.iso_tol_conf_level
        ),
        iso_median_conf_level=number(
            "iso_median_conf_level", defaults.iso_median_conf_level
        ),
        normality_alpha=number(
            "normality_alpha", defaults.normality_alpha
        ),
        normality_min_n=integer(
            "normality_min_n", defaults.normality_min_n
        ),
    )


def _build_diag_input(review_state) -> dict[str, pd.DataFrame]:
    summary = pd.DataFrame(
        [dict(item) for item in review_state.review_summary]
    )
    decisions = {
        trial.source_id: trial
        for trial in review_state.review.trials
    }

    if "Trial_ID" in summary.columns:
        summary = summary.copy()
        summary["Review_Decision"] = summary["Trial_ID"].map(
            lambda value: decisions.get(str(value)).decision
            if str(value) in decisions
            else ""
        )
        summary["Review_Comment"] = summary["Trial_ID"].map(
            lambda value: decisions.get(str(value)).comment
            if str(value) in decisions
            else ""
        )
        summary["Review_Decided_At"] = summary["Trial_ID"].map(
            lambda value: decisions.get(str(value)).reviewed_at
            if str(value) in decisions
            else None
        )

    review_rows = [
        {
            "Trial_ID": trial.source_id,
            "Source_Name": trial.source_name,
            "Automatic_Status": trial.automatic_status,
            "Score_Comportement_Global": getattr(trial, "quality_score", None),
            "Score_Comparatif_Population": getattr(review_state, "population", {}).get("scores", {}).get(trial.source_id, {}).get("score"),
            "Decision": trial.decision,
            "Comment": trial.comment,
            "Decided_At": trial.reviewed_at,
        }
        for trial in review_state.review.trials
    ]

    diag = {
        "DIAG_SUMMARY": summary,
        "DIAG_AUTOFREIN": summary[[c for c in summary if c == "Trial_ID" or "autofrein" in c.lower()]].copy(),
        "DIAG_REVIEW": pd.DataFrame(review_rows),
    }

    # La revue DIAG persiste les valeurs ISO 16269-4 nécessaires aux
    # boxplots afin que l'interface puisse les réafficher sans recalcul. Elles
    # doivent aussi suivre la revue jusqu'au run final : sinon la sélection
    # PDF contient bien diag_boxplots_short, mais le générateur de graphes ne
    # reçoit aucune donnée et ne peut produire aucune planche.
    boxplot_rows = tuple(getattr(review_state, "diag_boxplots", ()) or ())
    boxplots = pd.DataFrame([dict(item) for item in boxplot_rows])
    diag["DIAG_POP_VALUES"] = boxplots.copy()
    included = set(getattr(review_state, "population", {}).get("members", []))
    if getattr(review_state, "population", {}) and "Trial_ID" in boxplots:
        boxplots = boxplots[boxplots["Trial_ID"].astype(str).isin(included)].copy()
    diag["DIAG_POP_DETAILS"] = pd.DataFrame([
        {"Trial_ID": tid, **item, "Reference": getattr(review_state, "population", {}).get("reference")}
        for tid, value in getattr(review_state, "population", {}).get("scores", {}).items()
        for item in value.get("details", [])])
    diag["DIAG_POP_RULES"] = pd.DataFrame([
        {"Parameter": key, "Value": str(value)}
        for key, value in getattr(review_state, "population", {}).get("rules", {}).items()])
    if (
        not boxplots.empty
        and {"Variable", "Value"}.issubset(boxplots.columns)
    ):
        if "Short_Selected" in boxplots.columns:
            selection = (
                boxplots[["Variable", "Short_Selected"]]
                .drop_duplicates(subset=["Variable"], keep="first")
                .rename(columns={"Short_Selected": "Selected"})
                .reset_index(drop=True)
            )
            selection["Selected"] = selection["Selected"].fillna(False).astype(bool)
            diag["DIAG_SHORT_SELECTION"] = selection
            boxplots = boxplots.drop(columns=["Short_Selected"])
        diag["DIAG_ISO16269_4_OUTLIERS"] = boxplots.reset_index(drop=True)

    return diag


def _session_sources_by_id(session) -> dict[str, object]:
    raw_sources = getattr(session, "sources", {})
    if isinstance(raw_sources, dict):
        return {
            str(key): value
            for key, value in raw_sources.items()
            if is_trial_source(value)
        }
    return {
        str(getattr(source, "source_id", "")): source
        for source in raw_sources
        if is_trial_source(source)
    }


def _sheet_for_source(source, sheet_name: str | None) -> str | None:
    path = Path(getattr(source, "storage_path", ""))
    return sheet_name if path.suffix.lower() == ".xlsx" else None


def execute_campaign_run(
    session,
    plan: ArctaCampaignRunPlan,
    *,
    run_id: str | None = None,
    progress: ProgressCallback | None = None,
    campaign_analyzer: CampaignAnalyzer = analyze_campaign,
) -> WebCampaignExecutionResult:
    """
    Exécute le pipeline ARCTA headless à partir du plan immuable 62A.

    Aucune persistance et aucun artefact fichier ne sont produits ici : ils
    relèvent du jalon 62C. Le résultat scientifique reste entièrement mémoire.
    """
    if not isinstance(plan, ArctaCampaignRunPlan):
        raise TypeError("plan doit être un ArctaCampaignRunPlan.")

    run = ArctaCampaignRun(
        run_id=run_id or str(uuid.uuid4()),
        plan=plan,
    ).start()

    def advance(percent: float, message: str) -> None:
        nonlocal run
        value = min(99.0, max(run.progress_percent, float(percent)))
        run = run.with_progress(value, message)
        if progress is not None:
            progress(run.progress_percent, run.message)

    advance(1.0, "Vérification du plan ARCTA…")

    if str(getattr(session, "session_id", "")) != plan.session_id:
        _fail(
            run,
            "RUN_SESSION_MISMATCH",
            "Le plan ARCTA n'appartient pas à cette session.",
        )

    try:
        _assert_current_context(session, plan)
    except CampaignRunPrerequisiteError as exc:
        _fail(run, exc.code, str(exc), cause=exc)

    config_state = load_session_config(session)
    mapping_state = load_session_mapping(session)
    review_state = load_session_diag_review(session)
    if config_state is None or mapping_state is None or review_state is None:
        _fail(
            run,
            "RUN_CONTEXT_CHANGED",
            "Un élément du contexte ARCTA a disparu après la création du plan.",
        )

    try:
        constants = _build_constants(
            config_state.config,
            profile=plan.profile,
        )
        if require_profile_config(plan.profile).get("do_mu"):
            from .run_mechanics import complete_constants
            constants = complete_constants(session, constants)
        analysis_config = (ArctaAnalysisConfig(**dict(plan.analysis_settings))
                           if plan.analysis_settings else _build_analysis_config(config_state.config))
        selection = mapping_state.mapping.to_column_selection()
        diag = _build_diag_input(review_state)
    except Exception as exc:
        _fail(
            run,
            "RUN_CONFIG_CONVERSION_FAILED",
            "La CONFIG ou le mapping ne peut pas être converti pour ARCTA : "
            + str(exc),
            cause=exc,
        )

    advance(8.0, "Préparation des essais acceptés…")
    sources = _session_sources_by_id(session)
    import_sheets: dict[str, pd.DataFrame] = {}
    preparation: list[dict[str, object]] = []
    source_errors: list[dict[str, object]] = []

    for source_id in plan.accepted_source_ids:
        source = sources.get(source_id)
        if source is None:
            source_errors.append({
                "source_id": source_id,
                "error_type": "SourceMissing",
                "message": "La source acceptée est absente de la session.",
            })
            continue

        source_name = str(getattr(source, "original_name", source_id))
        source_path = Path(getattr(source, "storage_path", ""))
        sheet_name = _sheet_for_source(
            source,
            mapping_state.mapping.sheet_name,
        )

        try:
            prepared = read_source_dataframe(
                source_path,
                sheet_name=sheet_name,
            )
            dataframe = prepared.get("dataframe")
            if not isinstance(dataframe, pd.DataFrame):
                raise TypeError(
                    "Le lecteur de source n'a pas retourné de DataFrame."
                )
            mapping_state.mapping.validate(dataframe.columns)
            import_sheets[source_id] = dataframe
            preparation.append({
                "source_id": source_id,
                "source_name": source_name,
                "status": "READY",
                "sheet_name": prepared.get("selected_sheet"),
                "header_row_1based": prepared.get("header_row_1based"),
                "units_row_1based": prepared.get("units_row_1based"),
                "row_count": int(prepared.get("row_count", len(dataframe))),
                "columns": list(prepared.get("columns", dataframe.columns)),
            })
        except Exception as exc:
            source_errors.append({
                "source_id": source_id,
                "source_name": source_name,
                "sheet_name": sheet_name,
                "error_type": type(exc).__name__,
                "message": str(exc),
            })

    if source_errors:
        _fail(
            run,
            "RUN_SOURCE_PREPARATION_FAILED",
            "Au moins un essai accepté n'a pas pu être préparé.",
            source_errors=tuple(source_errors),
        )

    advance(20.0, "Lancement du pipeline ARCTA headless…")

    def engine_progress(percent: float, message: str) -> None:
        mapped = 20.0 + min(100.0, max(0.0, float(percent))) * 0.75
        advance(mapped, message)

    try:
        campaign = campaign_analyzer(
            import_sheets,
            selection,
            diag,
            plan.accepted_source_ids,
            constants,
            profile=plan.profile,
            analysis_config=analysis_config,
            progress=engine_progress,
        )
    except Exception as exc:
        _fail(
            run,
            "RUN_PIPELINE_FAILED",
            "Le pipeline ARCTA a échoué : " + str(exc),
            cause=exc,
        )

    if not isinstance(campaign, ArctaCampaignResult):
        _fail(
            run,
            "RUN_PIPELINE_RESULT_INVALID",
            "Le pipeline ARCTA n'a pas retourné ArctaCampaignResult.",
        )

    advance(96.0, "Contrôle final du contexte de campagne…")
    try:
        _assert_current_context(session, plan)
    except CampaignRunPrerequisiteError as exc:
        _fail(run, exc.code, str(exc), cause=exc)

    run = run.succeed()
    if progress is not None:
        progress(run.progress_percent, run.message)

    return WebCampaignExecutionResult(
        run=run,
        campaign=campaign,
        source_preparation=tuple(preparation),
        accepted_source_ids=plan.accepted_source_ids,
        rejected_source_ids=plan.rejected_source_ids,
    )
