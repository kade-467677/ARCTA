from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pandas as pd

from web_common.sessions import is_trial_source


TRIAL_LABEL_PREFIX = "E"
TRIAL_LABEL_WIDTH = 3


def _trial_sources(session) -> tuple:
    raw_sources = getattr(session, "sources", {})
    values = (
        raw_sources.values()
        if isinstance(raw_sources, Mapping)
        else raw_sources
    )
    return tuple(source for source in values if is_trial_source(source))


def build_trial_identity_map(session) -> dict[str, str]:
    """Associe chaque UUID d'essai à un identifiant métier E001, E002…"""
    return {
        str(source.source_id): f"{TRIAL_LABEL_PREFIX}{index:0{TRIAL_LABEL_WIDTH}d}"
        for index, source in enumerate(_trial_sources(session), start=1)
    }


def _contains_source_id(
    sheets: Mapping[str, pd.DataFrame],
    source_ids: tuple[str, ...],
) -> bool:
    for dataframe in sheets.values():
        if not isinstance(dataframe, pd.DataFrame):
            continue
        if any(
            source_id in str(column)
            for column in dataframe.columns
            for source_id in source_ids
        ):
            return True
        for column in dataframe.select_dtypes(include=["object", "string"]).columns:
            if dataframe[column].map(
                lambda value: isinstance(value, str)
                and any(source_id in value for source_id in source_ids)
            ).any():
                return True
    return False


def _replace_identifiers(value, identities: Mapping[str, str]):
    if not isinstance(value, str):
        return value
    output = value
    for source_id, label in identities.items():
        output = output.replace(source_id, label)
    return output


def _review_decisions(
    sheets: Mapping[str, pd.DataFrame],
) -> dict[str, str]:
    review = sheets.get("DIAG_REVIEW")
    if not isinstance(review, pd.DataFrame) or review.empty:
        return {}
    if "Trial_ID" not in review.columns or "Decision" not in review.columns:
        return {}
    return {
        str(trial_id): str(decision or "")
        for trial_id, decision in zip(review["Trial_ID"], review["Decision"])
    }


def _source_names(session) -> dict[str, str]:
    return {
        str(source.source_id): str(source.original_name)
        for source in _trial_sources(session)
    }


def _transform_dataframe(
    dataframe: pd.DataFrame,
    identities: Mapping[str, str],
    names_by_label: Mapping[str, str],
) -> pd.DataFrame:
    output = dataframe.copy(deep=True)
    output.columns = [
        _replace_identifiers(str(column), identities)
        for column in output.columns
    ]
    for column in output.select_dtypes(include=["object", "string"]).columns:
        output[column] = output[column].map(
            lambda value: _replace_identifiers(value, identities)
        )
    if "Trial_ID" in output.columns and "Source_Name" not in output.columns:
        position = int(output.columns.get_loc("Trial_ID")) + 1
        output.insert(
            position,
            "Source_Name",
            output["Trial_ID"].map(
                lambda value: names_by_label.get(str(value), "")
            ),
        )
    return output


def build_sources_sheet(
    session,
    identities: Mapping[str, str],
    decisions: Mapping[str, str],
) -> pd.DataFrame:
    rows = []
    for source in _trial_sources(session):
        source_id = str(source.source_id)
        decision = str(decisions.get(source_id, ""))
        rows.append({
            "Trial_ID": identities[source_id],
            "Source_Name": str(source.original_name),
            "Source_ID_Technical": source_id,
            "Stored_Name": str(source.stored_name),
            "Server_Copy_Path": str(Path(source.storage_path)),
            "Original_Source_Path": _original_path(session, source_id),
            "SHA256": str(getattr(source, "sha256", "")),
            "Size_Bytes": int(source.size_bytes),
            "Uploaded_At": str(source.uploaded_at),
            "DIAG_Decision": decision,
            "Accepted_For_ARCTA": decision == "ACCEPTED",
        })
    return pd.DataFrame(rows)


def build_export_sheets_with_trial_identity(
    session,
    sheets: Mapping[str, pd.DataFrame],
) -> dict[str, pd.DataFrame]:
    """
    Produit une copie de présentation des feuilles ARCTA.

    Les calculs restent indexés par UUID. Seul le livrable remplace les UUID
    par E001… et ajoute la table de correspondance ARCTA_SOURCES.
    """
    copied = {
        str(name): dataframe.copy(deep=True)
        for name, dataframe in sheets.items()
    }
    identities = build_trial_identity_map(session)
    source_ids = tuple(identities)
    if not source_ids or not _contains_source_id(copied, source_ids):
        return copied

    decisions = _review_decisions(copied)
    names = _source_names(session)
    names_by_label = {
        identities[source_id]: source_name
        for source_id, source_name in names.items()
    }
    output = {
        name: _transform_dataframe(dataframe, identities, names_by_label)
        for name, dataframe in copied.items()
    }
    output["ARCTA_SOURCES"] = build_sources_sheet(
        session,
        identities,
        decisions,
    )
    return output


def _original_path(session, source_id):
    from .local_files import read_state
    return read_state(session).get("source_paths", {}).get(source_id, "")
