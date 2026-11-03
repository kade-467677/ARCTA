"""Destinations lisibles, figées avant calcul, publication indépendante par copie."""
from datetime import datetime
from pathlib import Path
import hashlib
import re
import shutil

from fastapi import APIRouter, HTTPException, Request
from .local_storage import central_root

router = APIRouter()


def _storage():
    from . import session_campaign_run
    return session_campaign_run


def source_directory(session):
    path = Path(session.storage_dir) / "output_directory.json"
    state = _storage()._read_json_with_retry(path) if path.exists() else {}
    return str(state.get("destination_directory", state.get("source_directory", "")))


def _label(text):
    clean = re.sub(r'[<>:"/\\|?*\x00-\x1f\s]+', "_", text).strip(" ._") or "dossier"
    if len(clean) > 32:
        clean = clean[:23] + "_" + hashlib.sha256(text.encode()).hexdigest()[:8]
    return clean


def prepare_locations(session, run_id, source, now=None):
    """Le dossier source doit exister ; aucune inférence à partir du navigateur."""
    if source is None:
        return  # Compatibilité des anciens appels sans destination explicite.
    if not isinstance(source, str) or not source.strip():
        raise ValueError("Renseignez le dossier source des essais.")
    directory = Path(source.strip()).expanduser()
    if not directory.is_absolute() or not directory.is_dir():
        raise ValueError("Le dossier source doit être un chemin absolu existant, accessible au serveur ARCTA.")
    directory = directory.resolve()
    root = central_root(session)
    root.mkdir(parents=True, exist_ok=True)
    if directory == root or root in directory.parents or directory in root.parents:
        raise ValueError("Choisissez un dossier source distinct du stockage ARCTA_OUTPUTS.")
    token = re.sub(r"[^a-zA-Z0-9]", "", run_id)[:8]
    if not token:
        raise ValueError("Identifiant de run invalide.")
    date = now or datetime.now().astimezone()
    name = date.strftime("%Y%m%d-%H%M") + "_RUN_" + token
    state_path = Path(session.storage_dir) / "output_directory.json"
    state = _storage()._read_json_with_retry(state_path) if state_path.exists() else {}
    origin = Path(state.get("origin_directory") or directory)
    tail = [part for part in origin.parts if part != origin.anchor][-3:]
    central = name + "_" + "_".join(_label(part) for part in tail)
    destinations = [directory / name, root / central]
    for target in destinations:
        if len(str(target)) > 220:
            raise ValueError("Chemin de sortie trop long : choisissez un dossier source ou une racine ARCTA plus courte.")
    plan = {"run_id": run_id, "created_at": date.isoformat(),
            "source_directory": str(origin), "destination_directory": str(directory),
            "source_paths": state.get("source_paths", {}), "source_tail": tail,
            "destinations": [{"kind": kind, "path": str(path)} for kind, path in
                             zip(("SOURCE", "CENTRAL"), destinations)]}
    from .dabcta_arcta_bridge import lineage
    parentage = lineage(session)
    if parentage is not None:
        plan['arcta_rework' if parentage.get('operation') == 'REWORK' else 'arcta_reanalysis'] = parentage
    storage = _storage()
    run_dir = storage.session_campaign_run_dir(session, run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    storage._atomic_json(run_dir / "output_locations.json", plan)
    state.update(source_directory=str(directory), destination_directory=str(directory))
    storage._atomic_json(state_path, state)


def publish_locations(session, run_id, artifacts):
    storage = _storage()
    run_dir = storage.session_campaign_run_dir(session, run_id)
    plan_path = run_dir / "output_locations.json"
    if not plan_path.exists():
        return
    plan = storage._read_json_with_retry(plan_path)
    statuses = []
    for destination in plan["destinations"]:
        target = Path(destination["path"])
        owned = False
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            base = target
            for index in range(1000):
                target = base if index == 0 else base.with_name(base.name + f"_{index:02d}")
                try:
                    target.mkdir()  # Réservation exclusive, aucun écrasement.
                    owned = True
                    break
                except FileExistsError:
                    continue
            if not owned:
                raise OSError("Impossible de réserver un dossier de sortie unique.")
            (target / ".publication_en_cours").touch()
            manifest = {}
            session_root = Path(session.storage_dir).resolve()
            for item in artifacts:
                source = (session_root / str(item["relative_path"])).resolve()
                relative = source.relative_to(run_dir.resolve())
                if not source.is_file():
                    raise OSError(f"Livrable absent : {source.name}")
                output = target / relative
                output.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, output)
                original_hash = hashlib.sha256(source.read_bytes()).hexdigest()
                if hashlib.sha256(output.read_bytes()).hexdigest() != original_hash:
                    raise OSError(f"Copie incorrecte : {source.name}")
                manifest[relative.as_posix()] = original_hash
            storage._atomic_json(target / "ARCTA_RUN_MANIFEST.json", {
                **plan, "published_directory": str(target), "files_sha256": manifest,
            })
            (target / ".publication_en_cours").unlink()
            statuses.append({"kind": destination["kind"], "path": str(target), "status": "OK"})
        except Exception as exc:
            if owned:
                shutil.rmtree(target, ignore_errors=True)
            statuses.append({"kind": destination["kind"], "path": str(target),
                             "status": "ERROR", "message": str(exc)})
    result_path = run_dir / storage.CAMPAIGN_RUN_RESULT_FILENAME
    result = storage._read_json_with_retry(result_path)
    result["output_locations"] = statuses
    storage._atomic_json(result_path, result)
    if any(item["kind"] == "CENTRAL" and item["status"] == "OK" for item in statuses):
        for artifact in artifacts:
            if published_artifact(session, run_id, artifact) is not None:
                original = (Path(session.storage_dir) / str(artifact["relative_path"])).resolve()
                if original.is_relative_to(run_dir.resolve()):
                    try:
                        original.unlink(missing_ok=True)
                    except OSError:
                        pass  # Le résultat central est vérifié ; purge technique différée.



@router.get("/api/sessions/{session_id}/output-directory")
def get_output_directory(session_id: str, request: Request):
    from web_common.sessions import SessionNotFoundError
    try:
        session = request.app.state.session_registry.get_session(session_id)
    except SessionNotFoundError:
        raise HTTPException(404, "Session inconnue")
    if session is None:
        raise HTTPException(404, "Session inconnue")
    return {"source_directory": source_directory(session),
            "central_root": str(central_root(session))}


def published_artifact(session, run_id, artifact):
    """Résout une copie publiée en contrôlant son manifeste et son empreinte."""
    import json
    storage = _storage()
    result_path = storage.session_campaign_run_dir(session, run_id) / storage.CAMPAIGN_RUN_RESULT_FILENAME
    if not result_path.exists():
        return None
    result = storage._read_json_with_retry(result_path)
    relative = Path(str(artifact.get("relative_path", "")))
    try:
        inside = relative.relative_to(Path("campaign_runs") / run_id)
    except ValueError:
        return None
    if ".." in inside.parts:
        return None
    locations = sorted(result.get("output_locations", []), key=lambda item: item.get("kind") != "CENTRAL")
    for item in locations:
        if item.get("status") != "OK":
            continue
        try:
            root = Path(item["path"]).resolve()
            path = (root / inside).resolve()
            if not path.is_relative_to(root) or not path.is_file():
                continue
            manifest = json.loads((root / "ARCTA_RUN_MANIFEST.json").read_text(encoding="utf-8"))
            expected = manifest["files_sha256"][inside.as_posix()]
            if manifest["run_id"] != run_id or (artifact.get("sha256") and artifact["sha256"] != expected):
                continue
            with path.open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() == expected:
                    return path
        except (OSError, ValueError, KeyError):
            continue
    return None
