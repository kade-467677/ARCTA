"""Stockage technique séparé et migration sans changement des identités."""
from pathlib import Path
import errno
import hashlib
import json
import os
import shutil
import tempfile


def technical_root():
    configured = os.environ.get("ARCTA_SESSIONS_DIR", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "state")
    return (base / "ARCTA" / "sessions").resolve()


def central_root(session):
    parent = Path(session.storage_dir).resolve().parent
    config = parent / "outputs_root.json"
    return Path(json.loads(config.read_text(encoding="utf-8"))["path"]) if config.exists() else parent


def fingerprints(root):
    result = {}
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"Lien non migré : {path}")
        if path.is_file():
            with path.open("rb") as stream:
                result[path.relative_to(root).as_posix()] = (
                    hashlib.file_digest(stream, "sha256").hexdigest(), path.stat().st_mtime_ns)
    return result

def migration_difference(before, after):
    details = []
    for name in sorted(set(before) | set(after)):
        if name not in after:
            details.append(f"Fichier manquant : {name}")
        elif name not in before:
            details.append(f"Fichier supplémentaire : {name}")
        elif before[name][0] != after[name][0]:
            details.append(f"Contenu SHA-256 différent : {name}")
        elif before[name][1] != after[name][1]:
            details.append(
                f"Date différente : {name}\n"
                f"  avant = {before[name][1]} ns\n"
                f"  après = {after[name][1]} ns"
            )
    return "\n".join(details[:12]) or "Aucune différence relevée."

def migration_matches(before, after):
    # Tous les fichiers initiaux doivent rester strictement identiques.
    if any(
        after.get(name) != fingerprint
        for name, fingerprint in before.items()
    ):
        return False

    # Seul cet ajout à la racine de la session est accepté et conservé.
    added = set(after) - set(before)
    return added <= {"Zone.sav"}

def migrate_sessions(old_root, new_root):
    """Serveur arrêté. Déplacement avec vérification des fichiers."""
    old_root = Path(old_root).resolve()
    new_root = Path(new_root).resolve()

    if (
        old_root == new_root
        or old_root in new_root.parents
        or new_root in old_root.parents
    ):
        raise ValueError(
            "Les racines des résultats et des sessions doivent être distinctes."
        )

    new_root.mkdir(parents=True, exist_ok=True)
    if not old_root.exists():
        return

    for old in sorted(old_root.iterdir()):
        manifest = old / "arcta_session.json"
        if not old.is_dir() or not manifest.is_file():
            continue

        from web_common import SessionRegistry

        registry = object.__new__(SessionRegistry)
        if registry._load_session(old) is None:
            raise ValueError(
                f"Session ancienne illisible : {old}. Aucun effacement."
            )

        target = new_root / old.name
        if target.exists():
            raise ValueError(
                f"Conflit de migration : {target}. Aucun remplacement."
            )

        before = fingerprints(old)

        try:
            old.rename(target)
        except OSError as exc:
            if exc.errno != errno.EXDEV:
                raise

            stage = Path(
                tempfile.mkdtemp(prefix="migration_", dir=new_root)
            )
            try:
                shutil.copytree(
                    old,
                    stage,
                    dirs_exist_ok=True,
                    copy_function=shutil.copy2,
                )
                after = fingerprints(stage)
                if not migration_matches(before, after):
                    raise OSError(
                        f"Copie non identique ; original conservé : {old}\n"
                        + migration_difference(before, after)
                    )
                stage.rename(target)
            finally:
                if stage.exists():
                    shutil.rmtree(stage)

            shutil.rmtree(old)
        else:
            after = fingerprints(target)
            if not migration_matches(before, after):
                detail = migration_difference(before, after)
                target.rename(old)
                raise OSError(
                    f"Migration non identique ; original restauré : {old}\n"
                    + detail
                )