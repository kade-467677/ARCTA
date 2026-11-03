from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import replace
from pathlib import Path
from typing import Mapping

import pandas as pd

from arcta.campaign import ArctaCampaignResult
from arcta.profiles import require_profile_config
from arcta.reporting.excel import write_workbook_file
from arcta.reporting.pdf import (
    CAMPAIGN_PDF_FILENAME,
    generate_campaign_pdf,
)
from cta_core.campaign_run import (
    RUN_STATUS_PENDING,
    RUN_STATUS_RUNNING,
    ArctaCampaignRun,
    campaign_run_from_dict,
)

from apps.arcta_web.campaign_export_identity import (
    build_export_sheets_with_trial_identity,
)
from apps.arcta_web.campaign_graphics import generate_campaign_graphics
from arcta.reporting.options import (
    REPORT_OPTIONS_SCHEMA_VERSION,
    normalize_report_options,
    report_filename,
    report_options_rows,
)
from apps.arcta_web.session_config import load_session_config
from apps.arcta_web.session_canonical_config import load_session_canonical_config


SESSION_CAMPAIGN_RUN_SCHEMA_VERSION = "1.0"
SESSION_CAMPAIGN_RUNS_DIRNAME = "campaign_runs"
CAMPAIGN_RUN_STATE_FILENAME = "run.json"
CAMPAIGN_RUN_RESULT_FILENAME = "result.json"
CAMPAIGN_RUN_XLSX_FILENAME = "result.xlsx"
CAMPAIGN_RUN_PDF_FILENAME = CAMPAIGN_PDF_FILENAME
CAMPAIGN_RUN_REPORT_OPTIONS_FILENAME = "report_options.json"
CURRENT_CAMPAIGN_RUN_FILENAME = "current.json"

_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9._-]+$")
_WINDOWS_IO_RETRY_DELAYS = (0.02, 0.05, 0.1, 0.2, 0.4)


class SessionCampaignRunError(ValueError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = str(code)


def _replace_file_with_retry(
    source: Path,
    destination: Path,
) -> None:
    for attempt in range(
        len(_WINDOWS_IO_RETRY_DELAYS) + 1
    ):
        try:
            os.replace(source, destination)
            return
        except PermissionError:
            if attempt >= len(
                _WINDOWS_IO_RETRY_DELAYS
            ):
                raise

            time.sleep(
                _WINDOWS_IO_RETRY_DELAYS[attempt]
            )


def _read_json_with_retry(
    path: Path,
) -> dict[str, object]:
    for attempt in range(
        len(_WINDOWS_IO_RETRY_DELAYS) + 1
    ):
        try:
            return json.loads(
                path.read_text(
                    encoding="utf-8"
                )
            )
        except PermissionError:
            if attempt >= len(
                _WINDOWS_IO_RETRY_DELAYS
            ):
                raise

            time.sleep(
                _WINDOWS_IO_RETRY_DELAYS[attempt]
            )

    raise AssertionError(
        "Boucle de lecture JSON incohérente."
    )


def _require_run_id(run_id: str) -> str:
    normalized = str(run_id or "").strip()
    if not normalized or not _SAFE_RUN_ID.fullmatch(normalized):
        raise SessionCampaignRunError(
            "Identifiant de run ARCTA invalide.",
            code="RUN_ID_INVALID",
        )
    return normalized


def _atomic_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".part")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        _replace_file_with_retry(
            temporary,
            path,
        )
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def session_campaign_runs_dir(session) -> Path:
    return Path(session.storage_dir) / SESSION_CAMPAIGN_RUNS_DIRNAME


def session_campaign_run_dir(session, run_id: str) -> Path:
    return session_campaign_runs_dir(session) / _require_run_id(run_id)


def session_campaign_run_path(session, run_id: str) -> Path:
    return session_campaign_run_dir(session, run_id) / CAMPAIGN_RUN_STATE_FILENAME


def current_campaign_run_path(session) -> Path:
    return session_campaign_runs_dir(session) / CURRENT_CAMPAIGN_RUN_FILENAME


def session_campaign_report_options_path(session, run_id: str) -> Path:
    return (
        session_campaign_run_dir(session, run_id)
        / CAMPAIGN_RUN_REPORT_OPTIONS_FILENAME
    )


def save_campaign_report_options(
    session,
    run_id: str,
    options: Mapping[str, object] | None,
) -> dict[str, object]:
    normalized = normalize_report_options(
        options,
        fallback_title=_campaign_pdf_label(session),
    )
    _atomic_json(
        session_campaign_report_options_path(session, run_id),
        normalized,
    )
    return normalized


def load_campaign_report_options(
    session,
    run_id: str,
) -> dict[str, object]:
    path = session_campaign_report_options_path(session, run_id)
    if not path.is_file():
        return normalize_report_options(
            None,
            fallback_title=_campaign_pdf_label(session),
        )
    payload = _read_json_with_retry(path)
    if payload.get("schema_version") != REPORT_OPTIONS_SCHEMA_VERSION:
        raise SessionCampaignRunError(
            "Version de configuration du rapport PDF non supportée.",
            code="REPORT_OPTIONS_SCHEMA_UNSUPPORTED",
        )
    return normalize_report_options(
        payload,
        fallback_title=_campaign_pdf_label(session),
    )


def save_session_campaign_run(
    session,
    run: ArctaCampaignRun,
    *,
    make_current: bool = True,
) -> ArctaCampaignRun:
    if not isinstance(run, ArctaCampaignRun):
        raise TypeError("run doit être un ArctaCampaignRun.")
    if run.plan.session_id != str(session.session_id):
        raise SessionCampaignRunError(
            "Le run ARCTA n'appartient pas à cette session.",
            code="RUN_SESSION_MISMATCH",
        )

    _atomic_json(
        session_campaign_run_path(session, run.run_id),
        {
            "schema_version": SESSION_CAMPAIGN_RUN_SCHEMA_VERSION,
            "run": run.to_dict(),
        },
    )
    if make_current:
        _atomic_json(
            current_campaign_run_path(session),
            {
                "schema_version": SESSION_CAMPAIGN_RUN_SCHEMA_VERSION,
                "run_id": run.run_id,
            },
        )
    return run


def _read_run_file(path: Path) -> ArctaCampaignRun:
    payload = _read_json_with_retry(path)
    if payload.get("schema_version") != SESSION_CAMPAIGN_RUN_SCHEMA_VERSION:
        raise SessionCampaignRunError(
            "Version de persistance du run ARCTA non supportée.",
            code="RUN_STORAGE_SCHEMA_UNSUPPORTED",
        )
    raw_run = payload.get("run")
    if not isinstance(raw_run, Mapping):
        raise SessionCampaignRunError(
            "État de run ARCTA absent ou invalide.",
            code="RUN_STORAGE_INVALID",
        )
    return campaign_run_from_dict(raw_run)


def current_campaign_run_id(session) -> str | None:
    path = current_campaign_run_path(session)
    if not path.is_file():
        return None
    payload = _read_json_with_retry(path)
    if payload.get("schema_version") != SESSION_CAMPAIGN_RUN_SCHEMA_VERSION:
        raise SessionCampaignRunError(
            "Version du pointeur de run ARCTA non supportée.",
            code="RUN_STORAGE_SCHEMA_UNSUPPORTED",
        )
    return _require_run_id(payload.get("run_id", ""))


def load_session_campaign_run(
    session,
    run_id: str | None = None,
) -> ArctaCampaignRun | None:
    explicit = run_id is not None
    selected = _require_run_id(run_id) if explicit else current_campaign_run_id(session)
    if selected is None:
        return None
    path = session_campaign_run_path(session, selected)
    if not path.is_file():
        if explicit:
            return None
        raise SessionCampaignRunError(
            "Le pointeur de run ARCTA désigne un état absent.",
            code="RUN_STORAGE_INVALID",
        )
    return _read_run_file(path)


def list_session_campaign_runs(session) -> tuple[ArctaCampaignRun, ...]:
    root = session_campaign_runs_dir(session)
    if not root.is_dir():
        return ()
    runs = []
    for child in root.iterdir():
        path = child / CAMPAIGN_RUN_STATE_FILENAME
        if child.is_dir() and path.is_file():
            runs.append(_read_run_file(path))
    return tuple(sorted(runs, key=lambda item: item.plan.created_at, reverse=True))


def recover_interrupted_campaign_run(
    session,
    run: ArctaCampaignRun,
) -> ArctaCampaignRun:
    if run.status == RUN_STATUS_PENDING:
        run = run.start()
    if run.status != RUN_STATUS_RUNNING:
        return run
    recovered = run.fail(
        "RUN_INTERRUPTED",
        "Le processus Web a été interrompu pendant l'exécution ARCTA.",
    )
    return save_session_campaign_run(session, recovered)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _campaign_pdf_label(session) -> str:
    state = load_session_config(session)
    if state is None:
        return str(session.session_id)
    fields = state.config.fields
    for key in (
        "report_title",
        "campaign_name",
        "campaign_reference",
        "test_reference",
        "configuration_reference",
        "assembly_reference",
    ):
        field = fields.get(key)
        value = getattr(field, "value", None)
        if value is not None and str(value).strip():
            return str(value).strip()
    return str(state.config.campaign_id or session.session_id)


def _pdf_report_sheets(
    *,
    result,
    relative_path: str,
    profile: str,
    mode: str,
    filename: str,
    report_options: Mapping[str, object],
) -> dict[str, pd.DataFrame]:
    return {
        "ARCTA_PDF_INVENTORY": pd.DataFrame(list(result.inventory)),
        "ARCTA_PDF_SELECTION": pd.DataFrame(
            report_options_rows(report_options)
        ),
        "ARCTA_PDF_REPORT": pd.DataFrame([{
            "PDF_Report_Status": "GENERATED",
            "PDF_Report_Path": relative_path,
            "PDF_Report_Filename": filename,
            "PDF_Report_Title": report_options.get("report_title", ""),
            "PDF_Page_Count": result.page_count,
            "Profile": profile,
            "Mode": mode,
        }]),
    }


def _save_campaign_outputs(
    session,
    run_id: str,
    campaign: ArctaCampaignResult,
    *,
    include_plots: bool,
    include_pdf: bool,
    output_subdir: str = "",
) -> tuple[dict[str, object], ...]:
    if not isinstance(campaign, ArctaCampaignResult):
        raise TypeError("campaign doit être un ArctaCampaignResult.")

    if campaign.mechanical_results:
        from .dual_outputs import save_dual_outputs
        return save_dual_outputs(session, run_id, campaign,
                                 include_plots=include_plots, include_pdf=include_pdf)
    if output_subdir not in ("", "TOTAL", "EFFECTIVE"):
        raise ValueError("Sous-dossier mécanique invalide")
    export_sheets = build_export_sheets_with_trial_identity(
        session,
        campaign.result_sheets,
    )
    export_sheets["ARCTA_RUN_METADATA"] = pd.DataFrame([{
        "Run_ID": _require_run_id(run_id),
    }])
    run_dir = session_campaign_run_dir(session, run_id) / output_subdir
    run_dir.mkdir(parents=True, exist_ok=True)
    report_options = load_campaign_report_options(session, run_id)
    canonical_state = load_session_canonical_config(session)
    canonical_config = (
        canonical_state.config.to_dict()
        if canonical_state is not None and canonical_state.config is not None
        else None
    )
    from .config_export_summary import build_config_summary
    export_sheets["ARCTA_CONFIG_SYNTHESIS"] = build_config_summary(
        canonical_config, campaign.constants, export_sheets.get("ARCTA_SETTINGS")
    )
    from .dabcta_arcta_bridge import export_lineage
    export_lineage(session, export_sheets)
    plot_artifacts: tuple[dict[str, object], ...] = ()
    if include_plots:
        export_sheets, plot_artifacts = generate_campaign_graphics(
            session_root=Path(session.storage_dir),
            run_dir=run_dir,
            sheets=export_sheets,
            report_options=report_options if include_pdf else None,
        )
    pdf_artifact: dict[str, object] | None = None
    if include_pdf:
        pdf_filename = (output_subdir + "_" if output_subdir else "") + report_filename(report_options.get("report_title"))
        pdf_path = run_dir / pdf_filename
        pdf_temporary = run_dir / "report.part.pdf"
        try:
            pdf_result = generate_campaign_pdf(
                output_path=pdf_temporary,
                session_root=Path(session.storage_dir),
                sheets=export_sheets,
                plot_artifacts=plot_artifacts,
                campaign_label=_campaign_pdf_label(session),
                profile=campaign.profile,
                mode=campaign.mode,
                constants=campaign.constants,
                canonical_config=canonical_config,
                report_options=report_options,
            )
            _replace_file_with_retry(pdf_temporary, pdf_path)
        except Exception:
            pdf_temporary.unlink(missing_ok=True)
            raise
        pdf_relative_path = pdf_path.relative_to(
            Path(session.storage_dir)
        ).as_posix()
        pdf_artifact = {
            "kind": "PDF",
            "filename": pdf_path.name,
            "relative_path": pdf_relative_path,
            "media_type": "application/pdf",
            "size_bytes": pdf_path.stat().st_size,
            "sha256": _sha256_file(pdf_path),
            "page_count": pdf_result.page_count,
            "title": str(report_options.get("report_title", "Rapport ARCTA")),
        }
        export_sheets.update(_pdf_report_sheets(
            result=pdf_result,
            relative_path=pdf_relative_path,
            profile=campaign.profile,
            mode=campaign.mode,
            filename=pdf_filename,
            report_options=report_options,
        ))
    output_path = run_dir / CAMPAIGN_RUN_XLSX_FILENAME
    temporary = run_dir / "result.part.xlsx"
    try:
        write_workbook_file(str(temporary), export_sheets)
        _replace_file_with_retry(
            temporary,
            output_path,
        )
    except Exception:
        temporary.unlink(missing_ok=True)
        raise

    relative_path = output_path.relative_to(Path(session.storage_dir)).as_posix()
    workbook_artifact = {
        "kind": "XLSX",
        "filename": output_path.name,
        "relative_path": relative_path,
        "media_type": (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        "size_bytes": output_path.stat().st_size,
        "sha256": _sha256_file(output_path),
        "sheet_names": [str(name) for name in export_sheets],
    }
    _atomic_json(
        run_dir / CAMPAIGN_RUN_RESULT_FILENAME,
        {
            "schema_version": SESSION_CAMPAIGN_RUN_SCHEMA_VERSION,
            "run_id": _require_run_id(run_id),
            "profile": campaign.profile,
            "mode": campaign.mode,
            "constants": dict(campaign.constants),
            "report_options": report_options,
            "sheet_names": [str(name) for name in export_sheets],
            "artifacts": [
                workbook_artifact,
                *plot_artifacts,
                *(() if pdf_artifact is None else (pdf_artifact,)),
            ],
        },
    )
    return (
        workbook_artifact,
        *plot_artifacts,
        *(() if pdf_artifact is None else (pdf_artifact,)),
    )


def save_campaign_result(
    session,
    run_id: str,
    campaign: ArctaCampaignResult,
) -> dict[str, object]:
    """Compatibilité 62C : persiste seulement le classeur et retourne son descripteur."""
    return _save_campaign_outputs(
        session,
        run_id,
        campaign,
        include_plots=False,
        include_pdf=False,
    )[0]


def save_campaign_outputs(
    session,
    run_id: str,
    campaign: ArctaCampaignResult,
) -> tuple[dict[str, object], ...]:
    """Persiste le XLSX, les graphes 62G1 et le rapport PDF 62G2 demandés."""
    profile = require_profile_config(campaign.profile)
    return _save_campaign_outputs(
        session,
        run_id,
        campaign,
        include_plots=bool(profile.get("do_plots")),
        include_pdf=bool(profile.get("do_pdf")),
    )


def load_campaign_result_metadata(
    session,
    run_id: str,
) -> dict[str, object] | None:
    path = session_campaign_run_dir(session, run_id) / CAMPAIGN_RUN_RESULT_FILENAME
    if not path.is_file():
        return None
    payload = _read_json_with_retry(path)
    if payload.get("schema_version") != SESSION_CAMPAIGN_RUN_SCHEMA_VERSION:
        raise SessionCampaignRunError(
            "Version du résultat ARCTA non supportée.",
            code="RUN_STORAGE_SCHEMA_UNSUPPORTED",
        )
    return dict(payload)


def resolve_campaign_artifact(
    session,
    run: ArctaCampaignRun,
    kind: str,
) -> Path:
    wanted = str(kind or "").strip().upper()
    artifact = next(
        (
            item for item in run.artifacts
            if str(item.get("kind", "")).upper() == wanted
        ),
        None,
    )
    if artifact is None:
        raise SessionCampaignRunError(
            f"Artefact ARCTA absent : {wanted}",
            code="RUN_ARTIFACT_NOT_FOUND",
        )
    relative = Path(str(artifact.get("relative_path", "")))
    root = Path(session.storage_dir).resolve()
    candidate = (root / relative).resolve()
    if root not in candidate.parents or not candidate.is_file():
        from .output_locations import published_artifact
        published = published_artifact(session, run.run_id, artifact)
        if published is not None:
            return published
        raise SessionCampaignRunError(
            "Chemin d'artefact ARCTA invalide ou absent.",
            code="RUN_ARTIFACT_INVALID",
        )
    return candidate


def failed_run_after_result_error(
    run: ArctaCampaignRun,
    exc: BaseException,
) -> ArctaCampaignRun:
    return replace(
        run,
        status="FAILED",
        progress_percent=min(run.progress_percent, 99.0),
        message="Persistance du résultat ARCTA en échec.",
        error_code="RUN_RESULT_PERSISTENCE_FAILED",
        error_message=str(exc),
        artifacts=(),
    )
