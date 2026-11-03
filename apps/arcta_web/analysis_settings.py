"""Campaign analysis settings, independently persisted from CONFIG and DIAG."""
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import threading
import time

from fastapi import APIRouter, HTTPException, Request
from arcta.analysis_config import ArctaAnalysisConfig
from arcta.tolerance import minimum_sample_size
from apps.arcta_web.session_config import load_session_config
from web_common.sessions import SessionNotFoundError


DEFAULTS = asdict(ArctaAnalysisConfig())
FIELDS = [
    ("mean_ci_conf_level", "Confiance de l’intervalle de la moyenne", "%", "Intervalle bilatéral de Student sur la moyenne. Valeur historique : 95 %."),
    ("thr_ratio", "Seuil bas de tension pour les recalculs", "% de Y maximal", "Conserve la partie montante au-dessus de ce seuil. Ne modifie pas le DIAG déjà réalisé."),
    ("iso_tol_p_content", "Proportion de population visée", "%", "Part de la population que l'intervalle de tolérance doit couvrir."),
    ("iso_tol_conf_level", "Confiance de l'intervalle de tolérance", "%", "Niveau de confiance demandé pour cette couverture."),
    ("iso_median_conf_level", "Confiance de l'intervalle de la médiane", "%", "Concerne l'incertitude sur la médiane, distincte de la dispersion des essais."),
    ("normality_alpha", "Seuil du test de normalité", "%", "La normalité est rejetée si la p-valeur de Shapiro est inférieure à ce seuil."),
    ("normality_min_n", "Effectif minimal pour tester la normalité", "essais", "Entre 3 et 5 000. En dessous, la méthode non paramétrique est retenue."),
]
LOCK = threading.RLock()
router = APIRouter()


class SettingsConflict(ValueError):
    pass


def validate_settings(values):
    if isinstance(values, dict):
        values = {"mean_ci_conf_level": .95, "subtract_selflock": False, **values}
    if not isinstance(values, dict) or set(values) != set(DEFAULTS):
        raise ValueError("Les paramètres attendus sont requis ; aucun champ supplémentaire n'est accepté.")
    for key, value in values.items():
        if key == "subtract_selflock":
            if type(value) is not bool:
                raise ValueError("Le choix de soustraction d’autofrein doit être booléen.")
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("Valeur numérique finie requise : " + dict((f[0], f[1]) for f in FIELDS)[key] + ".")
        if key != "normality_min_n" and not (0 <= value < 1 if key == "thr_ratio" else 0 < value < 1):
            raise ValueError(dict((f[0], f[1]) for f in FIELDS)[key] + " : pourcentage entre 0 et 100, bornes exclues sauf zéro pour le seuil bas.")
    n = values["normality_min_n"]
    if n != int(n) or not 3 <= n <= 5000:
        raise ValueError("L'effectif minimal de normalité doit être entier, entre 3 et 5 000.")
    result = asdict(ArctaAnalysisConfig(**{k: v if k == "subtract_selflock" else int(v) if k == "normality_min_n" else float(v) for k, v in values.items()}))
    minimum_sample_size(result["iso_tol_p_content"], result["iso_tol_conf_level"])
    return result


def revision(values):
    return hashlib.sha256(json.dumps(values, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _path(session):
    return Path(session.storage_dir) / "arcta_analysis_settings.json"


def _write(session, values, origin):
    payload = {"schema_version": 1, "values": values, "origin": origin,
               "updated_at": datetime.now(timezone.utc).isoformat()}
    path = _path(session)
    fd, name = tempfile.mkstemp(prefix="arcta_settings_", suffix=".part", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        for attempt, delay in enumerate((.02, .05, .1, .2, .4, 0)):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(delay)
    finally:
        temporary.unlink(missing_ok=True)
    return payload


def _load(session):
    path = _path(session)
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("schema_version") != 1:
            raise ValueError("Version de paramètres statistiques non supportée.")
        data["values"] = validate_settings(data.get("values"))
        return data
    values = dict(DEFAULTS)
    legacy = load_session_config(session)
    found = False
    if legacy is not None:
        for key in values:
            if key == "subtract_selflock": continue
            field = legacy.config.fields.get(key)
            if field is not None and field.value is not None:
                if isinstance(field.value, bool):
                    raise ValueError(f"Paramètre historique invalide : {key}.")
                values[key] = float(field.value)
                found = True
    return _write(session, validate_settings(values), "legacy" if found else "defaults")


def read_settings(session):
    with LOCK:
        data = _load(session)
        return {**data, "revision": revision(data["values"]), "defaults": dict(DEFAULTS),
                "customized": data["values"] != DEFAULTS, "fields": FIELDS,
                "required_n": minimum_sample_size(data["values"]["iso_tol_p_content"], data["values"]["iso_tol_conf_level"])}


def save_settings(session, values, expected_revision, *, reset=False):
    with LOCK:
        current = _load(session)
        if expected_revision != revision(current["values"]):
            raise SettingsConflict("Les paramètres ont changé dans une autre fenêtre. Rechargez avant d'enregistrer.")
        checked = validate_settings(dict(DEFAULTS) if reset else values)
        _write(session, checked, "defaults" if reset else "custom")
        return read_settings(session)


def _session(request, session_id):
    try:
        return request.app.state.session_registry.get_session(session_id)
    except (SessionNotFoundError, KeyError):
        raise HTTPException(404, "Campagne inconnue.")


def _error(exc):
    if isinstance(exc, SettingsConflict):
        return HTTPException(409, str(exc))
    if isinstance(exc, (ValueError, TypeError, OverflowError)):
        return HTTPException(422, str(exc))
    return HTTPException(503, "Lecture ou sauvegarde des paramètres impossible. Réessayez.")


@router.get("/api/sessions/{session_id}/analysis-settings")
def get_analysis_settings(request: Request, session_id: str):
    session = _session(request, session_id)
    try:
        return read_settings(session)
    except (ValueError, TypeError, OSError, OverflowError) as exc:
        raise _error(exc) from exc


@router.put("/api/sessions/{session_id}/analysis-settings")
def put_analysis_settings(request: Request, session_id: str, payload: dict):
    session = _session(request, session_id)
    try:
        if set(payload) != {"values", "revision"}:
            raise ValueError("La requête doit contenir values et revision.")
        return save_settings(session, payload["values"], payload["revision"])
    except (ValueError, TypeError, OSError, OverflowError) as exc:
        raise _error(exc) from exc


@router.post("/api/sessions/{session_id}/analysis-settings/reset")
def reset_analysis_settings(request: Request, session_id: str, payload: dict):
    session = _session(request, session_id)
    try:
        if set(payload) != {"revision"}:
            raise ValueError("La requête de restauration doit contenir revision.")
        return save_settings(session, None, payload["revision"], reset=True)
    except (ValueError, TypeError, OSError, OverflowError) as exc:
        raise _error(exc) from exc
