from __future__ import annotations

import threading
import uuid
from dataclasses import replace
from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from arcta.profiles import DEFAULT_ARCTA_RUN_PROFILE
from cta_core.campaign_run import ArctaCampaignRun
from web_common.sessions import SessionNotFoundError

from apps.arcta_web.campaign_execution_service import (
    CampaignRunExecutionError,
    WebCampaignExecutionResult,
    execute_campaign_run,
)
from apps.arcta_web.campaign_run_plan import (
    CampaignRunPrerequisiteError,
    build_campaign_run_plan,
)
from apps.arcta_web.session_campaign_run import (
    SessionCampaignRunError,
    failed_run_after_result_error,
    list_session_campaign_runs,
    load_campaign_result_metadata,
    load_session_campaign_run,
    recover_interrupted_campaign_run,
    resolve_campaign_artifact,
    save_campaign_report_options,
    save_campaign_outputs,
    save_session_campaign_run,
)


from .output_locations import prepare_locations, publish_locations
from . import run_deletion


class CampaignRunRequest(BaseModel):
    source_directory: str | None = None
    profile: str = DEFAULT_ARCTA_RUN_PROFILE
    force: bool = False
    report_options: dict[str, object] | None = None


class RunDeletionRequest(BaseModel):
    token: str
    confirm: bool = False


class CampaignRunManagerError(RuntimeError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = str(code)


class CampaignRunManager:
    """Pilote les threads de calcul, la progression et la persistance."""

    def __init__(
        self,
        *,
        executor=execute_campaign_run,
        result_saver=save_campaign_outputs,
    ) -> None:
        self._executor = executor
        self._result_saver = result_saver
        self._lock = threading.RLock()
        self._active: dict[str, threading.Thread] = {}

    @staticmethod
    def _session_key(session) -> str:
        return str(session.session_id)

    def _thread_alive(self, session) -> bool:
        thread = self._active.get(self._session_key(session))
        return bool(thread is not None and thread.is_alive())

    def current(self, session) -> ArctaCampaignRun | None:
        with self._lock:
            current = load_session_campaign_run(session)
            if (
                current is not None
                and current.status in {"PENDING", "RUNNING"}
                and not self._thread_alive(session)
            ):
                current = recover_interrupted_campaign_run(session, current)
            return current

    def get(self, session, run_id: str) -> ArctaCampaignRun | None:
        """Lit un run sans entrer en concurrence avec sa persistance."""
        with self._lock:
            return load_session_campaign_run(session, run_id)

    def history(self, session) -> tuple[ArctaCampaignRun, ...]:
        with self._lock:
            return list_session_campaign_runs(session)

    def result_metadata(
        self,
        session,
        run_id: str,
    ) -> dict[str, object] | None:
        with self._lock:
            return load_campaign_result_metadata(session, run_id)

    def deletion(self, session, run_id, token=None):
        with self._lock:
            if self._thread_alive(session):
                raise ValueError("Attendez la fin de l'exécution avant de supprimer un run")
            return (run_deletion.preview(session, run_id) if token is None
                    else run_deletion.delete(session, run_id, token))

    def start(
        self,
        session,
        *,
        profile: str,
        force: bool,
        report_options: dict[str, object] | None = None,
        source_directory: str | None = None,
    ) -> ArctaCampaignRun:
        with self._lock:
            if run_deletion.pending(session):
                raise CampaignRunManagerError("Terminez la suppression en cours avant de relancer", code="RUN_DELETE_PENDING")
            current = self.current(session)
            if self._thread_alive(session) and (
                current is None or not current.terminal
            ):
                raise CampaignRunManagerError(
                    "Une exécution ARCTA est déjà active pour cette session.",
                    code="RUN_ALREADY_RUNNING",
                )

            if current is not None and not force:
                raise CampaignRunManagerError(
                    "Un run ARCTA existe déjà. Une relance exige force=true.",
                    code="RUN_RELAUNCH_REQUIRES_FORCE",
                )

            plan = build_campaign_run_plan(session, profile=profile)
            run_id = str(uuid.uuid4())
            prepare_locations(session, run_id, source_directory)
            save_campaign_report_options(
                session,
                run_id,
                report_options,
            )
            run = ArctaCampaignRun(
                run_id=run_id,
                plan=plan,
            ).start()
            save_session_campaign_run(session, run)

            thread = threading.Thread(
                target=self._execute,
                args=(session, plan, run.run_id),
                name=f"arcta-run-{run.run_id}",
                daemon=True,
            )
            self._active[self._session_key(session)] = thread
            thread.start()
            return run

    def _persist_progress(
        self,
        session,
        run_id: str,
        percent: float,
        message: str,
    ) -> None:
        if float(percent) >= 100.0:
            return
        with self._lock:
            stored = load_session_campaign_run(session, run_id)
            if stored is None or stored.status != "RUNNING":
                return
            updated = stored.with_progress(
                max(stored.progress_percent, float(percent)),
                message,
            )
            save_session_campaign_run(session, updated)

    def _unexpected_failure(
        self,
        session,
        run_id: str,
        exc: BaseException,
    ) -> None:
        stored = load_session_campaign_run(session, run_id)
        if stored is None or stored.terminal:
            return
        if stored.status == "PENDING":
            stored = stored.start()
        failed = stored.fail(
            "RUN_WORKER_FAILED",
            "Le worker ARCTA a échoué : " + str(exc),
        )
        save_session_campaign_run(session, failed)

    def _execute(self, session, plan, run_id: str) -> None:
        try:
            execution: WebCampaignExecutionResult = self._executor(
                session,
                plan,
                run_id=run_id,
                progress=lambda percent, message: self._persist_progress(
                    session,
                    run_id,
                    percent,
                    message,
                ),
            )
            try:
                with self._lock:
                    saved = self._result_saver(
                        session,
                        run_id,
                        execution.campaign,
                    )
                    artifacts = (
                        (dict(saved),)
                        if isinstance(saved, dict)
                        else tuple(dict(item) for item in saved)
                    )
                    publish_locations(session, run_id, artifacts)
                    completed = replace(
                        execution.run,
                        artifacts=artifacts,
                    )
                    save_session_campaign_run(session, completed)
            except Exception as exc:
                failed = failed_run_after_result_error(execution.run, exc)
                with self._lock:
                    save_session_campaign_run(session, failed)
        except CampaignRunExecutionError as exc:
            with self._lock:
                save_session_campaign_run(session, exc.run)
        except Exception as exc:
            with self._lock:
                self._unexpected_failure(session, run_id, exc)
        finally:
            with self._lock:
                key = self._session_key(session)
                if self._active.get(key) is threading.current_thread():
                    self._active.pop(key, None)


def _run_response(
    session_id: str,
    run: ArctaCampaignRun,
    *,
    result: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "session_id": session_id,
        "exists": True,
        "terminal": run.terminal,
        "run": run.to_dict(),
        "result": result,
    }


def build_campaign_run_router(
    resolve_session: Callable[[str], Any],
    *,
    manager: CampaignRunManager | None = None,
) -> APIRouter:
    router = APIRouter()
    run_manager = manager or CampaignRunManager()

    def session_or_404(session_id: str):
        try:
            session = resolve_session(session_id)
        except (SessionNotFoundError, KeyError):
            raise HTTPException(
                status_code=404,
                detail=f"Session ARCTA inconnue : {session_id}",
            )
        if session is None:
            raise HTTPException(
                status_code=404,
                detail=f"Session ARCTA inconnue : {session_id}",
            )
        return session

    def run_or_404(session_id: str, session, run_id: str):
        try:
            run = run_manager.get(session, run_id)
        except SessionCampaignRunError as exc:
            raise HTTPException(
                status_code=422,
                detail={"code": exc.code, "message": str(exc)},
            )
        if run is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "RUN_NOT_FOUND",
                    "message": f"Run ARCTA inconnu : {run_id}",
                },
            )
        return run

    @router.get("/api/sessions/{session_id}/campaign/runs/current")
    def get_current_run(session_id: str):
        session = session_or_404(session_id)
        try:
            run = run_manager.current(session)
        except SessionCampaignRunError as exc:
            raise HTTPException(
                status_code=500,
                detail={"code": exc.code, "message": str(exc)},
            )
        if run is None:
            return {
                "session_id": session_id,
                "exists": False,
                "terminal": False,
                "run": None,
                "result": None,
            }
        result = run_manager.result_metadata(session, run.run_id)
        return _run_response(session_id, run, result=result)

    def selflock_message(session, plan):
        from arcta.profiles import require_profile_config
        from arcta.selflock_policy import resolve_selflock, audit_message
        from .session_diag_review import load_session_diag_review
        import pandas as pd
        cfg = require_profile_config(plan.profile)
        if not (cfg.get('do_compute') or cfg.get('do_mu')):
            return ''
        review = load_session_diag_review(session)
        return audit_message(resolve_selflock(
            {'DIAG_SUMMARY': pd.DataFrame(review.review_summary)}, plan.accepted_source_ids))

    @router.get("/api/sessions/{session_id}/campaign/readiness")
    def get_campaign_readiness(
        session_id: str,
        profile: str = DEFAULT_ARCTA_RUN_PROFILE,
    ):
        session = session_or_404(session_id)
        try:
            plan = build_campaign_run_plan(session, profile=profile)
        except CampaignRunPrerequisiteError as exc:
            return {
                "session_id": session_id,
                "ready": False,
                "profile": str(profile or "").strip().upper(),
                "code": exc.code,
                "message": str(exc),
                "plan": None,
            }
        return {
            "session_id": session_id,
            "ready": True,
            "profile": plan.profile,
            "code": None,
            "message": "La campagne est prête pour l'exécution ARCTA.",
            "selflock_message": selflock_message(session, plan),
            "plan": plan.to_dict(),
        }

    @router.get("/api/sessions/{session_id}/campaign/runs")
    def get_run_history(session_id: str):
        session = session_or_404(session_id)
        runs = run_manager.history(session)
        return {
            "session_id": session_id,
            "count": len(runs),
            "runs": [run.to_dict() for run in runs],
            "deletions_pending": run_deletion.pending(session),
        }

    @router.post("/api/sessions/{session_id}/campaign/runs")
    def start_run(
        session_id: str,
        payload: CampaignRunRequest | None = None,
    ):
        session = session_or_404(session_id)
        request = payload or CampaignRunRequest()
        try:
            run = run_manager.start(
                session,
                profile=request.profile,
                force=request.force,
                report_options=request.report_options,
                source_directory=request.source_directory,
            )
        except CampaignRunManagerError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": exc.code, "message": str(exc)},
            )
        except CampaignRunPrerequisiteError as exc:
            raise HTTPException(
                status_code=422,
                detail={"code": exc.code, "message": str(exc)},
            )
        except (SessionCampaignRunError, TypeError, ValueError) as exc:
            code = getattr(exc, "code", "RUN_START_INVALID")
            raise HTTPException(
                status_code=422,
                detail={"code": code, "message": str(exc)},
            )
        return JSONResponse(
            status_code=202,
            content=_run_response(session_id, run),
        )

    @router.get("/api/sessions/{session_id}/campaign/runs/{run_id}")
    def get_run(session_id: str, run_id: str):
        session = session_or_404(session_id)
        run = run_or_404(session_id, session, run_id)
        result = run_manager.result_metadata(session, run.run_id)
        return _run_response(session_id, run, result=result)

    @router.get(
        "/api/sessions/{session_id}/campaign/runs/{run_id}/result"
    )
    def get_run_result(session_id: str, run_id: str):
        session = session_or_404(session_id)
        run = run_or_404(session_id, session, run_id)
        result = run_manager.result_metadata(session, run.run_id)
        if result is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "RUN_RESULT_NOT_FOUND",
                    "message": "Le résultat du run ARCTA n'est pas disponible.",
                },
            )
        return _run_response(session_id, run, result=result)

    @router.get(
        "/api/sessions/{session_id}/campaign/runs/{run_id}/artifacts/{kind}"
    )
    def get_run_artifact(session_id: str, run_id: str, kind: str):
        session = session_or_404(session_id)
        run = run_or_404(session_id, session, run_id)
        try:
            path = resolve_campaign_artifact(session, run, kind)
        except SessionCampaignRunError as exc:
            raise HTTPException(
                status_code=404,
                detail={"code": exc.code, "message": str(exc)},
            )
        artifact = next(
            item for item in run.artifacts
            if str(item.get("kind", "")).upper() == str(kind).upper()
        )
        media_type = str(
            artifact.get("media_type") or "application/octet-stream"
        )
        return FileResponse(
            path,
            media_type=media_type,
            filename=(
                None
                if media_type.startswith("image/")
                else str(artifact.get("filename") or path.name)
            ),
        )

    def deletion_guard(request):
        from urllib.parse import urlsplit
        source = request.headers.get("origin") or request.headers.get("referer")
        origin = urlsplit(source or "")
        same_origin = ((origin.scheme, origin.netloc) == (request.url.scheme, request.url.netloc)
                       if source else request.headers.get("sec-fetch-site") == "same-origin")
        if request.headers.get("x-arcta-delete") != "1" or not same_origin:
            raise HTTPException(403, "Origine de la demande de suppression refusée")

    @router.get("/api/sessions/{session_id}/campaign/runs/{run_id}/deletion")
    def preview_deletion(session_id: str, run_id: str, request: Request):
        deletion_guard(request)
        session = session_or_404(session_id)
        try:
            return run_manager.deletion(session, run_id)
        except (OSError, ValueError, SessionCampaignRunError) as exc:
            raise HTTPException(409, str(exc))

    @router.delete("/api/sessions/{session_id}/campaign/runs/{run_id}")
    def delete_run(session_id: str, run_id: str, request: Request, payload: RunDeletionRequest):
        deletion_guard(request)
        if not payload.confirm:
            raise HTTPException(422, "Confirmation explicite requise")
        session = session_or_404(session_id)
        try:
            return run_manager.deletion(session, run_id, payload.token)
        except (OSError, ValueError, SessionCampaignRunError) as exc:
            raise HTTPException(409, str(exc))

    return router
