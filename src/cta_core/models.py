from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict

import pandas as pd


@dataclass
class ColumnSelection:
    """
    Mapping des rôles métier ARCTA vers les colonnes source.

    Rôles :
        Y  : tension
        Xg : couple global
        Xh : couple sous-tête
        Xt : couple filet
        A  : angle
    """

    roles: Dict[str, str]

    @property
    def has_angle(self) -> bool:
        return bool(
            self.roles.get("A")
        )

    @property
    def has_fine(self) -> bool:
        return all(
            self.roles.get(r)
            for r in (
                "Xg",
                "Xh",
                "Xt",
            )
        )

    def validate(self) -> None:
        if not self.roles.get("Y"):
            raise ValueError(
                "Il faut sélectionner une colonne Tension Y."
            )

        if not self.roles.get("Xg"):
            raise ValueError(
                "Il faut sélectionner au minimum "
                "une colonne Couple global Xg."
            )

        x_roles = [
            r
            for r in (
                "Xg",
                "Xh",
                "Xt",
            )
            if self.roles.get(r)
        ]

        if len(x_roles) not in (1, 3):
            raise ValueError(
                "Il faut sélectionner 1 colonne couple (Xg) "
                "ou 3 colonnes couple (Xg, Xh, Xt)."
            )

        if (
            len(x_roles) == 3
            and not self.has_fine
        ):
            raise ValueError(
                "En mode fin, Xg, Xh et Xt "
                "doivent tous être renseignés."
            )


@dataclass
class ArctaMemoryStore:
    """
    Conteneur de résultats d'un run ARCTA.

    Cette classe ne dépend volontairement d'aucune interface utilisateur.
    """

    import_path: str
    output_path: str

    result_sheets: Dict[str, pd.DataFrame] = field(
        default_factory=dict
    )

    mode: str = ""

    write_status: Dict[str, Any] = field(
        default_factory=dict
    )