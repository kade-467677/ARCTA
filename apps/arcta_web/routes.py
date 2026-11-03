from __future__ import annotations

from pathlib import Path

from fastapi import (
    APIRouter,
    Body,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from cta_core.contracts import (
    ARCTA_RUN_MANIFEST_SCHEMA_VERSION,
)
from web_common import (
    SessionNotFoundError,
    SourceNotFoundError,
    SOURCE_KIND_CONFIG,
    SOURCE_KIND_TRIAL,
    is_config_source,
    normalize_source_kind,
)

from .settings import (
    ARCTA_WEB_APP_NAME,
    ARCTA_WEB_APP_VERSION,
    ARCTA_WEB_MAX_UPLOAD_BYTES,
    ARCTA_WEB_PREVIEW_ROWS,
)
from .source_preview import (
    read_source_preview,
)

from cta_core.config_model import (
    arcta_input_config_from_dict,
    build_default_campaign_config,
    import_templatesynth_to_config,
)

from .config_editor import (
    add_custom_config_field,
    apply_config_form,
    config_ready_for_continue,
    deserialize_config,
    remove_custom_config_field,
    restore_config_field,
    serialize_config,
)

from .session_config import (
    ArctaSessionConfig,
    load_session_config,
    save_session_config,
    session_config_path,
)
from .session_canonical_config import (
    ensure_session_canonical_config,
    extract_and_save_session_canonical_config,
)
from .canonical_config_page import (
    render_canonical_config_page,
    update_canonical_config_page,
)

router = APIRouter()

TEMPLATES_DIR = (
    Path(__file__)
    .resolve()
    .parent
    / "templates"
)

templates = Jinja2Templates(
    directory=str(TEMPLATES_DIR)
)


def _session_registry(
    request: Request,
):
    return request.app.state.session_registry


def _get_session_or_404(
    request: Request,
    session_id: str,
):
    try:
        return _session_registry(
            request
        ).get_session(
            session_id
        )

    except SessionNotFoundError:
        raise HTTPException(
            status_code=404,
            detail="Session ARCTA inconnue.",
        )


def _get_source_or_404(
    request: Request,
    session_id: str,
    source_id: str,
):
    try:
        return _session_registry(
            request
        ).get_source(
            session_id,
            source_id,
        )

    except SessionNotFoundError:
        raise HTTPException(
            status_code=404,
            detail="Session ARCTA inconnue.",
        )

    except SourceNotFoundError:
        raise HTTPException(
            status_code=404,
            detail="Source ARCTA inconnue.",
        )

def _resolve_template_source(
    session,
    template_source_id: str | None,
):
    if template_source_id:
        source = session.sources.get(
            template_source_id
        )

        if source is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    "Source TemplateSynth "
                    "inconnue."
                ),
            )

        if not is_config_source(source):
            raise HTTPException(
                status_code=400,
                detail=(
                    "La source sélectionnée n'est pas "
                    "identifiée comme fichier CONFIG."
                ),
            )

        if (
            source.storage_path
            .suffix.lower()
            != ".xlsx"
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    "La source CONFIG "
                    "sélectionnée doit être XLSX."
                ),
            )

        return (
            source,
            [],
        )

    candidates = []

    for source in session.sources.values():
        if not is_config_source(source):
            continue

        if (
            source.storage_path
            .suffix.lower()
            != ".xlsx"
        ):
            continue

        candidates.append(
            source
        )

    if len(candidates) == 1:
        return (
            candidates[0],
            [],
        )

    if len(candidates) > 1:
        return (
            None,
            [
                (
                    "Plusieurs fichiers CONFIG "
                    "ont été détectés. Sélectionnez "
                    "explicitement la source CONFIG."
                )
            ],
        )

    return (
        None,
        [],
    )

def _initialize_session_config(
    session,
    template_source_id: str | None = None,
) -> tuple[
    ArctaSessionConfig,
    object | None,
    list[str],
]:
    template_source, warnings = (
        _resolve_template_source(
            session,
            template_source_id,
        )
    )

    if template_source is None:
        config = (
            build_default_campaign_config(
                campaign_id=session.session_id
            )
        )

        state = save_session_config(
            session,
            config,
            status="DRAFT",
            template_source_id=None,
        )

        return (
            state,
            None,
            warnings,
        )

    try:
        result = (
            import_templatesynth_to_config(
                campaign_id=
                    session.session_id,
                template_path=
                    template_source.storage_path,
            )
        )

        warnings.extend(
            result.warnings
        )

        state = save_session_config(
            session,
            result.config,
            status="DRAFT",
            template_source_id=
                template_source.source_id,
        )

        return (
            state,
            template_source,
            warnings,
        )

    except Exception as exc:
        config = (
            build_default_campaign_config(
                campaign_id=session.session_id
            )
        )

        warnings.append(
            "Import de la source CONFIG "
            f"impossible : {exc}"
        )

        state = save_session_config(
            session,
            config,
            status="DRAFT",
            template_source_id=None,
        )

        return (
            state,
            None,
            warnings,
        )

def _render_config_page(
    *,
    request: Request,
    session,
    session_config: ArctaSessionConfig,
    template_source=None,
    warnings=None,
    message: str = "",
):
    warnings = list(
        warnings or []
    )

    config = (
        session_config.config
    )

    summary = (
        config.validation_summary()
    )

    categories = []

    for category in config.categories():
        categories.append({
            "name": category,
            "fields":
                config.fields_in_category(
                    category
                ),
        })

    xlsx_sources = [
        source
        for source
        in session.sources.values()
        if (
            is_config_source(source)
            and
            source.storage_path
            .suffix.lower()
            == ".xlsx"
        )
    ]

    return templates.TemplateResponse(
        request=request,
        name="config.html",
        context={
            "session":
                session,
            "session_config":
                session_config,
            "config":
                config,
            "categories":
                categories,
            "summary":
                summary,
            "ready":
                config_ready_for_continue(
                    config
                ),
            "template_source":
                template_source,
            "xlsx_sources":
                xlsx_sources,
            "warnings":
                warnings,
            "message":
                message,
            "statuses": (
                "VALID",
                "TO_CONFIRM",
                "MISSING",
                "INVALID",
            ),
        },
    )

@router.get(
    "/health",
    tags=["system"],
)

def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "arcta-web",
    }


@router.get(
    "/api/version",
    tags=["system"],
)
def api_version() -> dict[str, str]:
    return {
        "application":
            ARCTA_WEB_APP_NAME,
        "application_version":
            ARCTA_WEB_APP_VERSION,
        "manifest_schema_version":
            ARCTA_RUN_MANIFEST_SCHEMA_VERSION,
    }


@router.post(
    "/api/sessions",
    status_code=201,
    tags=["sessions"],
)
def create_session(
    request: Request,
) -> dict[str, object]:
    session = _session_registry(
        request
    ).create_session()

    return session.to_dict()


@router.get(
    "/api/sessions/{session_id}",
    tags=["sessions"],
)
def get_session(
    request: Request,
    session_id: str,
) -> dict[str, object]:
    session = _get_session_or_404(
        request,
        session_id,
    )

    return session.to_dict()


@router.post(
    "/api/sessions/{session_id}/sources",
    status_code=201,
    tags=["sources"],
)
async def upload_source(
    request: Request,
    session_id: str,
    file: UploadFile = File(...),
    source_kind: str = Form(SOURCE_KIND_TRIAL),
) -> dict[str, object]:
    session = _get_session_or_404(
        request,
        session_id,
    )

    try:
        normalized_kind = normalize_source_kind(source_kind)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    filename = str(
        file.filename or ""
    )

    if (
        normalized_kind == SOURCE_KIND_CONFIG
        and Path(filename).suffix.lower() != ".xlsx"
    ):
        raise HTTPException(
            status_code=400,
            detail="Le fichier CONFIG doit être au format XLSX.",
        )

    previous_config_ids = tuple(
        source.source_id
        for source in session.sources.values()
        if is_config_source(source)
    )

    try:
        content = await file.read(
            ARCTA_WEB_MAX_UPLOAD_BYTES
            + 1
        )

    finally:
        await file.close()

    if len(content) > ARCTA_WEB_MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                "Fichier trop volumineux. "
                "Limite : "
                f"{ARCTA_WEB_MAX_UPLOAD_BYTES} octets."
            ),
        )

    registry = _session_registry(
        request
    )

    try:
        source = registry.add_source_bytes(
            session_id,
            filename,
            content,
            source_kind=normalized_kind,
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    try:
        preview = read_source_preview(
            source.storage_path,
            max_rows=
                ARCTA_WEB_PREVIEW_ROWS,
        )

    except Exception as exc:
        try:
            registry.remove_source(
                session_id,
                source.source_id,
            )
        except Exception:
            pass

        raise HTTPException(
            status_code=422,
            detail=(
                "Lecture de la source impossible : "
                f"{exc}"
            ),
        )

    replaced_config_count = 0
    canonical_config = None

    if normalized_kind == SOURCE_KIND_CONFIG:
        try:
            canonical_config = extract_and_save_session_canonical_config(
                session,
                source,
            )
        except Exception as exc:
            try:
                registry.remove_source(session_id, source.source_id)
            except Exception:
                pass

            raise HTTPException(
                status_code=500,
                detail={
                    "code": "CANONICAL_CONFIG_PERSISTENCE_FAILED",
                    "message": (
                        "La source CONFIG est lisible mais son état "
                        f"canonique n'a pas pu être persisté : {exc}"
                    ),
                },
            ) from exc

        for old_source_id in previous_config_ids:
            if old_source_id == source.source_id:
                continue
            registry.remove_source(session_id, old_source_id)
            replaced_config_count += 1

        session_config_path(session).unlink(missing_ok=True)

    return {
        "source":
            source.to_dict(),
        "preview":
            preview,
        "replaced_config_count":
            replaced_config_count,
        "canonical_config": (
            canonical_config.summary_dict()
            if canonical_config is not None
            else None
        ),
    }


@router.get(
    (
        "/api/sessions/{session_id}"
        "/sources/{source_id}/preview"
    ),
    tags=["sources"],
)
def preview_source(
    request: Request,
    session_id: str,
    source_id: str,
    sheet: str | None = None,
) -> dict[str, object]:
    source = _get_source_or_404(
        request,
        session_id,
        source_id,
    )

    try:
        preview = read_source_preview(
            source.storage_path,
            sheet_name=sheet,
            max_rows=
                ARCTA_WEB_PREVIEW_ROWS,
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=(
                "Lecture de la source impossible : "
                f"{exc}"
            ),
        )

    return {
        "source":
            source.to_dict(),
        "preview":
            preview,
    }


@router.get(
    "/",
    response_class=HTMLResponse,
    include_in_schema=False,
)
def home(
    request: Request,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "app_name":
                ARCTA_WEB_APP_NAME,
            "app_version":
                ARCTA_WEB_APP_VERSION,
            "manifest_schema_version":
                ARCTA_RUN_MANIFEST_SCHEMA_VERSION,
        },
    )

@router.get(
    "/sessions/{session_id}/config",
    response_class=HTMLResponse,
    include_in_schema=False,
)
def config_page(
    request: Request,
    session_id: str,
    template_source_id: str | None = None,
    blocked: str | None = None,
):
    session = _get_session_or_404(
        request,
        session_id,
    )

    try:
        canonical_state = ensure_session_canonical_config(session)
    except Exception as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "CANONICAL_CONFIG_UNAVAILABLE",
                "message": str(exc),
            },
        ) from exc

    if canonical_state is not None:
        return render_canonical_config_page(
            templates=templates,
            request=request,
            session=session,
            state=canonical_state,
            mapping_blocked=blocked == "mapping",
        )

    warnings: list[str] = []

    if template_source_id is not None:
        (
            session_config,
            template_source,
            warnings,
        ) = _initialize_session_config(
            session,
            template_source_id,
        )

    else:
        session_config = (
            load_session_config(
                session
            )
        )

        if session_config is None:
            (
                session_config,
                template_source,
                warnings,
            ) = _initialize_session_config(
                session
            )

        else:
            template_source = None

            source_id = (
                session_config
                .template_source_id
            )

            if source_id:
                template_source = (
                    session.sources.get(
                        source_id
                    )
                )

    return _render_config_page(
        request=request,
        session=session,
        session_config=
            session_config,
        template_source=
            template_source,
        warnings=warnings,
    )

@router.post(
    "/sessions/{session_id}/config",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def config_page_update(
    request: Request,
    session_id: str,
):
    session = _get_session_or_404(
        request,
        session_id,
    )

    try:
        canonical_state = ensure_session_canonical_config(session)
    except Exception as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "CANONICAL_CONFIG_UNAVAILABLE",
                "message": str(exc),
            },
        ) from exc

    if canonical_state is not None:
        form = await request.form()
        return update_canonical_config_page(
            templates=templates,
            request=request,
            session=session,
            state=canonical_state,
            form=form,
        )

    session_config = (
        load_session_config(
            session
        )
    )

    if session_config is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "Aucune CONFIG n'existe "
                "pour cette session."
            ),
        )

    config = (
        session_config.config
    )

    template_source_id = (
        session_config
        .template_source_id
    )

    form = await request.form()

    action = str(
        form.get(
            "action",
            "save_draft",
        )
    )

    warnings: list[str] = []
    message = ""

    try:
        apply_config_form(
            config,
            form,
        )

        if action.startswith(
            "restore:"
        ):
            key = action.split(
                ":",
                1,
            )[1]

            restore_config_field(
                config,
                key,
            )

            message = (
                "Valeur d'origine restaurée : "
                f"{key}"
            )

        elif action.startswith(
            "remove:"
        ):
            key = action.split(
                ":",
                1,
            )[1]

            remove_custom_config_field(
                config,
                key,
            )

            message = (
                f"Paramètre supprimé : {key}"
            )

        elif action == "add":
            add_custom_config_field(
                config,
                key=str(
                    form.get(
                        "new_key",
                        "",
                    )
                ),
                label=str(
                    form.get(
                        "new_label",
                        "",
                    )
                ),
                value=form.get(
                    "new_value",
                    "",
                ),
                category=str(
                    form.get(
                        "new_category",
                        "utilisateur",
                    )
                ),
                unit=str(
                    form.get(
                        "new_unit",
                        "",
                    )
                ),
                value_type=str(
                    form.get(
                        "new_value_type",
                        "text",
                    )
                ),
                required=(
                    str(
                        form.get(
                            "new_required",
                            "",
                        )
                    ).lower()
                    in {
                        "1",
                        "true",
                        "on",
                        "yes",
                    }
                ),
            )

            message = (
                "Paramètre ajouté à CONFIG."
            )

        elif action == "validate":
            if not config_ready_for_continue(
                config
            ):
                warnings.append(
                    "CONFIG non validable : "
                    "des champs obligatoires "
                    "sont manquants, invalides "
                    "ou encore à confirmer."
                )

            else:
                session_config = (
                    save_session_config(
                        session,
                        config,
                        status="VALIDATED",
                        template_source_id=
                            template_source_id,
                    )
                )

                return RedirectResponse(
                    url=(
                        f"/sessions/{session.session_id}/mapping"
                    ),
                    status_code=303,
                )

        else:
            message = (
                "Brouillon CONFIG enregistré."
            )

    except Exception as exc:
        warnings.append(
            str(exc)
        )

    session_config = (
        save_session_config(
            session,
            config,
            status="DRAFT",
            template_source_id=
                template_source_id,
        )
    )

    return _render_config_page(
        request=request,
        session=session,
        session_config=
            session_config,
        template_source=(
            session.sources.get(
                template_source_id
            )
            if template_source_id
            else None
        ),
        warnings=warnings,
        message=message,
    )

@router.get(
    "/api/sessions/{session_id}/config/canonical",
    tags=["config"],
)
def get_session_canonical_config_api(
    request: Request,
    session_id: str,
) -> dict[str, object]:
    session = _get_session_or_404(
        request,
        session_id,
    )

    try:
        state = ensure_session_canonical_config(session)
    except Exception as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "CANONICAL_CONFIG_UNAVAILABLE",
                "message": str(exc),
            },
        ) from exc

    if state is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "CONFIG_SOURCE_MISSING",
                "message": "Aucune source CONFIG n'est disponible.",
            },
        )

    return state.to_dict()


@router.get(
    "/api/sessions/{session_id}/config",
    tags=["config"],
)
def get_session_config_api(
    request: Request,
    session_id: str,
) -> dict[str, object]:
    session = _get_session_or_404(
        request,
        session_id,
    )

    state = load_session_config(
        session
    )

    if state is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "Aucune CONFIG enregistrée."
            ),
        )

    return state.to_dict()


@router.put(
    "/api/sessions/{session_id}/config",
    tags=["config"],
)
def put_session_config_api(
    request: Request,
    session_id: str,
    payload: dict = Body(...),
) -> dict[str, object]:
    session = _get_session_or_404(
        request,
        session_id,
    )

    raw_config = payload.get(
        "config"
    )

    if not isinstance(
        raw_config,
        dict,
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "'config' doit être un objet."
            ),
        )

    try:
        config = (
            arcta_input_config_from_dict(
                raw_config
            )
        )

        requested_status = str(
            payload.get(
                "status",
                "DRAFT",
            )
        ).strip().upper()

        if (
            requested_status
            == "VALIDATED"
            and not
            config_ready_for_continue(
                config
            )
        ):
            raise ValueError(
                "CONFIG non validable."
            )

        state = save_session_config(
            session,
            config,
            status=requested_status,
            template_source_id=(
                payload.get(
                    "template_source_id"
                )
            ),
        )

    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    return state.to_dict()
