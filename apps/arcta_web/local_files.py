"""Sélection native locale et provenance distincte de la destination."""
from pathlib import Path
from urllib.parse import urlsplit
import ipaddress
import io
import json
import os
import subprocess
import sys
import threading
from fastapi import APIRouter, HTTPException, Request, UploadFile
from starlette.concurrency import run_in_threadpool
from .output_locations import _storage, source_directory
from .local_storage import central_root

router = APIRouter()
_dialog_lock = threading.Lock()


def is_local(request):
    try:
        return (ipaddress.ip_address(request.client.host).is_loopback
                and request.url.hostname in ("localhost", "127.0.0.1", "::1"))
    except (ValueError, AttributeError):
        return False


def available(request):
    return os.name == "nt" and not getattr(sys, "frozen", False) and is_local(request)


def guard(request):
    if not available(request):
        raise HTTPException(403, "Sélection native réservée à ARCTA Windows sur ce poste.")
    origin = urlsplit(request.headers.get("origin", ""))
    if (origin.scheme, origin.netloc) != (request.url.scheme, request.url.netloc) or request.headers.get("x-arcta-local") != "1":
        raise HTTPException(403, "Sélection native : origine de la requête refusée.")


def read_state(session):
    path = Path(session.storage_dir) / "output_directory.json"
    return _storage()._read_json_with_retry(path) if path.exists() else {}


def write_state(session, state):
    _storage()._atomic_json(Path(session.storage_dir) / "output_directory.json", state)


def dialog(mode, initial):
    result = subprocess.run(
        [sys.executable, str(Path(__file__).with_name("native_dialog.py")), mode, initial],
        capture_output=True, encoding="utf-8", timeout=600,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    if result.returncode:
        raise RuntimeError("Ouverture de la fenêtre Windows impossible. Vérifiez que tkinter est installé.")
    paths = json.loads(result.stdout)
    if not isinstance(paths, list) or not all(isinstance(p, str) for p in paths):
        raise ValueError("Réponse de sélection invalide.")
    return paths


def session_for(request, session_id):
    from .routes import _get_session_or_404
    return _get_session_or_404(request, session_id)


@router.get("/api/sessions/{session_id}/local-files")
def information(session_id: str, request: Request):
    session = session_for(request, session_id)
    state = read_state(session)
    return {"native_available": available(request),
            "origin_directory": state.get("origin_directory", ""),
            "destination_directory": source_directory(session),
            "source_paths": state.get("source_paths", {}),
            "central_root": str(central_root(session))}


@router.post("/api/sessions/{session_id}/local-files/{mode}")
async def select_local(session_id: str, mode: str, request: Request):
    guard(request)
    session = session_for(request, session_id)
    if mode not in ("TRIAL", "CONFIG", "directory"):
        raise HTTPException(400, "Choix invalide")
    if not _dialog_lock.acquire(blocking=False):
        raise HTTPException(409, "Une fenêtre de sélection est déjà ouverte.")
    try:
        state = read_state(session)
        paths = await run_in_threadpool(dialog, mode, source_directory(session))
        if not paths:
            return {"cancelled": True, "imported": 0, "errors": []}
        selected = [Path(p).resolve() for p in paths]
        if mode == "directory":
            directory = selected[0]
            if not directory.is_dir():
                raise ValueError("Dossier inaccessible.")
            state["destination_directory"] = str(directory)
            state["source_directory"] = str(directory)
            write_state(session, state)
            return {"cancelled": False, "destination_directory": str(directory)}
        from .routes import upload_source
        from .settings import ARCTA_WEB_MAX_UPLOAD_BYTES
        imported, errors = 0, []
        for path in selected:
            try:
                if path.suffix.lower() not in ((".xlsx",) if mode == "CONFIG" else (".xlsx", ".csv", ".txt")):
                    raise ValueError("Extension non prise en charge.")
                with path.open("rb") as stream:
                    content = stream.read(ARCTA_WEB_MAX_UPLOAD_BYTES + 1)
                if len(content) > ARCTA_WEB_MAX_UPLOAD_BYTES:
                    raise ValueError("Fichier trop volumineux.")
                result = await upload_source(request, session_id, UploadFile(filename=path.name, file=io.BytesIO(content)), mode)
                imported += 1
                state.setdefault("source_paths", {})[result["source"]["source_id"]] = str(path)
                if mode == "TRIAL" and not state.get("origin_directory"):
                    state["origin_directory"] = str(path.parent)
                    state.setdefault("destination_directory", str(path.parent))
                    state["source_directory"] = state["destination_directory"]
                write_state(session, state)
            except (OSError, ValueError, HTTPException) as exc:
                errors.append(f"{path.name} : {getattr(exc, 'detail', str(exc))}")
        return {"cancelled": False, "imported": imported, "errors": errors}
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        raise HTTPException(422, str(exc)) from exc
    finally:
        _dialog_lock.release()
