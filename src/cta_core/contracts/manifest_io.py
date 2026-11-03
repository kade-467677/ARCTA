from __future__ import annotations

import json
from pathlib import Path

from .manifest import ArctaRunManifest


def manifest_path_from_output(
    output_path: str,
) -> str:
    """
    Construit le chemin du sidecar JSON
    associé au résultat ARCTA.
    """
    path = Path(
        str(output_path).replace(
            "\\",
            "/",
        )
    )
    return str(
        path.with_suffix(
            ".manifest.json"
        )
    )


def write_arcta_run_manifest_json(
    manifest: ArctaRunManifest,
    output_path: str,
) -> str:
    """
    Écrit le manifeste ARCTA en JSON UTF-8.

    Les erreurs d'écriture sont propagées à l'appelant.
    """
    path = Path(output_path)

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    payload = manifest.to_dict()

    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )

    return str(path)


def read_arcta_run_manifest_json(
    path: str,
) -> dict[str, object]:
    """
    Lit un manifeste ARCTA JSON sous
    forme de dictionnaire brut.

    La validation métier/versionnée
    sera ajoutée séparément.
    """
    return json.loads(
        Path(path).read_text(
            encoding="utf-8"
        )
    )