from __future__ import annotations

from dataclasses import replace
from typing import Any

from fastapi.responses import RedirectResponse
from cta_core.config_model import CANONICAL_FIELD_SPECS

from .canonical_config_editor import (
    REQUIREMENT_LABELS,
    STATUS_LABELS,
    apply_canonical_config_form,
    canonical_config_categories,
    canonical_to_legacy_config,
)
from .session_canonical_config import (
    ArctaSessionCanonicalConfig,
    extract_and_save_session_canonical_config,
    save_session_canonical_config,
)
from .session_config import save_session_config


def render_canonical_config_page(
    *,
    templates,
    request,
    session,
    state: ArctaSessionCanonicalConfig,
    warnings: list[str] | None = None,
    message: str = "",
    mapping_blocked: bool = False,
):
    config = state.config
    validation = config.validation_summary() if config is not None else None

    if mapping_blocked:
        warnings = list(warnings or [])
        warnings.insert(
            0,
            "Le Mapping reste inaccessible tant que la CONFIG n'est pas "
            "validée pour le calcul ARCTA.",
        )

    return templates.TemplateResponse(
        request=request,
        name="config_canonical.html",
        context={
            "session": session,
            "state": state,
            "config": config,
            "validation": validation,
            "categories": (
                canonical_config_categories(config)
                if config is not None
                else []
            ),
            "requirement_labels": REQUIREMENT_LABELS,
            "status_labels": STATUS_LABELS,
            "field_labels": {
                spec.field_id: spec.label
                for spec in CANONICAL_FIELD_SPECS
            },
            "warnings": list(warnings or []),
            "message": message,
        },
    )


def update_canonical_config_page(
    *,
    templates,
    request,
    session,
    state: ArctaSessionCanonicalConfig,
    form: Any,
):
    action = str(form.get("action", "save_draft")).strip()
    warnings: list[str] = []
    message = ""

    if action == "reextract":
        source = session.sources.get(state.source_id)

        if source is None:
            warnings.append("La source CONFIG d'origine n'existe plus.")
        else:
            state = extract_and_save_session_canonical_config(session, source)
            message = "Les 96 champs ont été réextraits depuis la source CONFIG."

        return render_canonical_config_page(
            templates=templates,
            request=request,
            session=session,
            state=state,
            warnings=warnings,
            message=message,
        )

    if not state.extracted or state.config is None:
        warnings.append(
            "La source CONFIG doit être reconnue avant toute édition."
        )
        return render_canonical_config_page(
            templates=templates,
            request=request,
            session=session,
            state=state,
            warnings=warnings,
        )

    try:
        apply_canonical_config_form(state.config, form)
        validation = state.config.validation_summary()

        if action == "validate" and validation["calculation_ready"]:
            state = replace(
                state,
                workflow_status="VALIDATED",
                updated_at="",
            )
            legacy = canonical_to_legacy_config(state.config)
            save_session_config(
                session,
                legacy,
                status="VALIDATED",
                template_source_id=state.source_id,
            )

            try:
                save_session_canonical_config(session, state)
            except Exception:
                save_session_config(
                    session,
                    legacy,
                    status="DRAFT",
                    template_source_id=state.source_id,
                )
                raise

            return RedirectResponse(
                url=f"/sessions/{session.session_id}/mapping",
                status_code=303,
            )

        if action == "validate":
            warnings.append(
                "CONFIG non validable pour le calcul : complétez les champs "
                "marqués Obligatoire pour le calcul."
            )
        else:
            message = "Brouillon CONFIG canonique enregistré."

        state = replace(
            state,
            workflow_status="DRAFT",
            updated_at="",
        )
        save_session_config(
            session,
            canonical_to_legacy_config(state.config),
            status="DRAFT",
            template_source_id=state.source_id,
        )
        save_session_canonical_config(session, state)
    except Exception as exc:
        warnings.append(str(exc))

    return render_canonical_config_page(
        templates=templates,
        request=request,
        session=session,
        state=state,
        warnings=warnings,
        message=message,
    )
