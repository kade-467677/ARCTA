from __future__ import annotations

import json
import hashlib
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


SUPPORTED_SOURCE_EXTENSIONS = frozenset({
    ".xlsx",
    ".csv",
    ".txt",
})

SOURCE_KIND_TRIAL = "TRIAL"
SOURCE_KIND_CONFIG = "CONFIG"
SOURCE_KINDS = frozenset({
    SOURCE_KIND_TRIAL,
    SOURCE_KIND_CONFIG,
})

SESSION_MANIFEST_FILENAME = "arcta_session.json"
SESSION_MANIFEST_SCHEMA_VERSION = "1.0"
_WINDOWS_REPLACE_RETRY_DELAYS = (0.02, 0.05, 0.1, 0.2, 0.4)


def normalize_source_kind(value: str) -> str:
    normalized = str(value or "").strip().upper()
    if normalized not in SOURCE_KINDS:
        raise ValueError(
            "Type de source inconnu : "
            f"{normalized or '(vide)'}."
        )
    return normalized


def source_kind(source) -> str:
    return normalize_source_kind(
        getattr(source, "source_kind", SOURCE_KIND_TRIAL)
    )


def is_trial_source(source) -> bool:
    return source_kind(source) == SOURCE_KIND_TRIAL


def is_config_source(source) -> bool:
    return source_kind(source) == SOURCE_KIND_CONFIG


class SessionNotFoundError(KeyError):
    """Session Web inconnue."""


class SourceNotFoundError(KeyError):
    """Source Web inconnue."""


def _utc_now_iso() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


def _replace_file_with_retry(
    source: Path,
    destination: Path,
) -> None:
    """Replace atomically, tolerating short-lived Windows file locks."""
    for attempt in range(len(_WINDOWS_REPLACE_RETRY_DELAYS) + 1):
        try:
            os.replace(source, destination)
            return
        except PermissionError:
            if attempt >= len(_WINDOWS_REPLACE_RETRY_DELAYS):
                raise
            time.sleep(_WINDOWS_REPLACE_RETRY_DELAYS[attempt])


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sanitize_source_filename(
    filename: str,
) -> str:
    """Nettoie un nom de fichier fourni par le navigateur."""
    raw_name = Path(
        str(filename or "")
    ).name.strip()

    if not raw_name:
        raise ValueError(
            "Nom de fichier vide."
        )

    path = Path(raw_name)
    extension = path.suffix.lower()

    if extension not in SUPPORTED_SOURCE_EXTENSIONS:
        raise ValueError(
            "Extension non supportée : "
            f"{extension or '(aucune)'}"
        )

    stem = re.sub(
        r"[^A-Za-z0-9._-]+",
        "_",
        path.stem,
    ).strip("._")

    if not stem:
        stem = "source"

    return f"{stem}{extension}"


@dataclass(frozen=True)
class WebSource:
    source_id: str
    original_name: str
    stored_name: str
    storage_path: Path
    size_bytes: int
    uploaded_at: str
    source_kind: str = SOURCE_KIND_TRIAL
    sha256: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "source_id": self.source_id,
            "original_name": self.original_name,
            "stored_name": self.stored_name,
            "size_bytes": self.size_bytes,
            "uploaded_at": self.uploaded_at,
            "source_kind": self.source_kind,
            "display_name": self.original_name,
            "storage_path": str(self.storage_path),
            "sha256": self.sha256,
        }


@dataclass
class WebSession:
    session_id: str
    created_at: str
    storage_dir: Path
    sources: dict[str, WebSource] = field(
        default_factory=dict
    )

    def to_dict(self) -> dict[str, object]:
        trial_count = sum(
            is_trial_source(source)
            for source in self.sources.values()
        )
        config_count = sum(
            is_config_source(source)
            for source in self.sources.values()
        )
        return {
            "session_id": self.session_id,
            "created_at": self.created_at,
            "source_count": len(self.sources),
            "trial_source_count": trial_count,
            "config_source_count": config_count,
            "workspace_path": str(self.storage_dir),
            "sources": [
                source.to_dict()
                for source in self.sources.values()
            ],
        }


class SessionRegistry:
    """
    Registre persistant des sessions Web.

    Chaque campagne possède un manifeste dans son dossier de travail. Le
    registre est reconstruit automatiquement au démarrage de l'application.
    """

    def __init__(
        self,
        root_dir: str | Path,
    ) -> None:
        self.root_dir = Path(
            root_dir
        ).resolve()

        self.root_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        self._sessions: dict[
            str,
            WebSession,
        ] = {}

        self._lock = threading.RLock()

        self._load_sessions()

    @staticmethod
    def _manifest_path(storage_dir: Path) -> Path:
        return storage_dir / SESSION_MANIFEST_FILENAME

    def _session_payload(self, session: WebSession) -> dict[str, object]:
        return {
            "schema_version": SESSION_MANIFEST_SCHEMA_VERSION,
            "session_id": session.session_id,
            "created_at": session.created_at,
            "sources": [
                source.to_dict()
                for source in session.sources.values()
            ],
        }

    def _save_session(self, session: WebSession) -> None:
        path = self._manifest_path(session.storage_dir)
        temporary = path.with_name(path.name + ".part")
        payload = self._session_payload(session)
        try:
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            _replace_file_with_retry(temporary, path)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

    def _load_session(self, storage_dir: Path) -> WebSession | None:
        path = self._manifest_path(storage_dir)
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("schema_version") != SESSION_MANIFEST_SCHEMA_VERSION:
                return None
            session_id = str(payload.get("session_id", "")).strip()
            created_at = str(payload.get("created_at", "")).strip()
            if not session_id or session_id != storage_dir.name or not created_at:
                return None
            sources: dict[str, WebSource] = {}
            for raw in payload.get("sources", []):
                source_id = str(raw.get("source_id", "")).strip()
                stored_name = Path(str(raw.get("stored_name", ""))).name
                original_name = Path(str(raw.get("original_name", ""))).name
                storage_path = storage_dir / stored_name
                if (
                    not source_id
                    or not stored_name
                    or not original_name
                    or not storage_path.is_file()
                ):
                    return None
                sources[source_id] = WebSource(
                    source_id=source_id,
                    original_name=original_name,
                    stored_name=stored_name,
                    storage_path=storage_path,
                    size_bytes=int(raw.get("size_bytes", storage_path.stat().st_size)),
                    uploaded_at=str(raw.get("uploaded_at", "")),
                    source_kind=normalize_source_kind(
                        raw.get("source_kind", SOURCE_KIND_TRIAL)
                    ),
                    sha256=(
                        str(raw.get("sha256", "")).strip()
                        or _sha256_file(storage_path)
                    ),
                )
            return WebSession(
                session_id=session_id,
                created_at=created_at,
                storage_dir=storage_dir,
                sources=sources,
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return None

    def _load_sessions(self) -> None:
        sessions: dict[str, WebSession] = {}
        for storage_dir in self.root_dir.iterdir():
            if not storage_dir.is_dir():
                continue
            session = self._load_session(storage_dir)
            if session is not None:
                sessions[session.session_id] = session
        with self._lock:
            self._sessions.update(sessions)

    def create_session(
        self,
    ) -> WebSession:
        session_id = uuid.uuid4().hex

        storage_dir = (
            self.root_dir
            / session_id
        )

        storage_dir.mkdir(
            parents=True,
            exist_ok=False,
        )

        session = WebSession(
            session_id=session_id,
            created_at=_utc_now_iso(),
            storage_dir=storage_dir,
        )

        with self._lock:
            self._sessions[
                session_id
            ] = session

            try:
                self._save_session(session)
            except Exception:
                self._sessions.pop(session_id, None)
                storage_dir.rmdir()
                raise

        return session

    def get_session(
        self,
        session_id: str,
    ) -> WebSession:
        with self._lock:
            session = self._sessions.get(
                str(session_id)
            )

        if session is None:
            # 64H3 : session créée par le service DABCTA après notre démarrage.
            candidate = (self.root_dir / str(session_id)).resolve()
            if candidate.parent == self.root_dir and candidate.name == str(session_id):
                with self._lock:
                    session = self._sessions.get(str(session_id))
                    if session is None:
                        session = self._load_session(candidate)
                        if session is not None:
                            self._sessions[str(session_id)] = session

        if session is None:
            raise SessionNotFoundError(
                str(session_id)
            )

        return session

    def add_source_bytes(
        self,
        session_id: str,
        filename: str,
        content: bytes,
        source_kind: str = SOURCE_KIND_TRIAL,
    ) -> WebSource:
        session = self.get_session(
            session_id
        )

        normalized_kind = normalize_source_kind(source_kind)

        safe_name = sanitize_source_filename(
            filename
        )

        source_id = uuid.uuid4().hex

        stored_name = (
            f"{source_id}_{safe_name}"
        )

        target = (
            session.storage_dir
            / stored_name
        )

        temporary = target.with_name(
            target.name + ".part"
        )

        try:
            temporary.write_bytes(
                content
            )

            _replace_file_with_retry(
                temporary,
                target,
            )

        except Exception:
            try:
                temporary.unlink(
                    missing_ok=True
                )
            except Exception:
                pass

            raise

        source = WebSource(
            source_id=source_id,
            original_name=Path(
                str(filename)
            ).name,
            stored_name=stored_name,
            storage_path=target,
            size_bytes=len(content),
            uploaded_at=_utc_now_iso(),
            source_kind=normalized_kind,
            sha256=_sha256_bytes(content),
        )

        with self._lock:
            session.sources[
                source_id
            ] = source

            try:
                self._save_session(session)
            except Exception:
                session.sources.pop(source_id, None)
                target.unlink(missing_ok=True)
                raise

        return source

    def get_source(
        self,
        session_id: str,
        source_id: str,
    ) -> WebSource:
        session = self.get_session(
            session_id
        )

        with self._lock:
            source = session.sources.get(
                str(source_id)
            )

        if source is None:
            raise SourceNotFoundError(
                str(source_id)
            )

        return source

    def remove_source(
        self,
        session_id: str,
        source_id: str,
    ) -> None:
        session = self.get_session(
            session_id
        )

        with self._lock:
            source = session.sources.pop(
                str(source_id),
                None,
            )

            if source is not None:
                try:
                    self._save_session(session)
                except Exception:
                    session.sources[source.source_id] = source
                    raise

        if source is None:
            raise SourceNotFoundError(
                str(source_id)
            )

        try:
            source.storage_path.unlink(
                missing_ok=True
            )
        except Exception:
            pass
