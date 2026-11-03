from __future__ import annotations

import os
import sys
from pathlib import Path
PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parents[2]
)

SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(SRC_ROOT),
    )

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from web_common import SessionRegistry

from apps.arcta_web.mapping_api import build_mapping_router
from apps.arcta_web.campaign_mapping_api import (
    build_campaign_mapping_router,
)
from apps.arcta_web.diag_review_api import (
    build_diag_review_router,
)
from apps.arcta_web.campaign_run_api import (
    build_campaign_run_router,
)
from .analysis_settings import router as analysis_settings_router
from .output_locations import router as output_locations_router
from .local_files import router as local_files_router
from .local_storage import technical_root, migrate_sessions
from .routes import router
from .settings import (
    ARCTA_WEB_APP_NAME,
    ARCTA_WEB_APP_VERSION,
)
from apps.arcta_web.mapping_page import (
    router as mapping_page_router,
)
from apps.arcta_web.diag_review_page import (
    router as diag_review_page_router,
)
from apps.arcta_web.campaign_run_page import (
    router as campaign_run_page_router,
)


ARCTA_OUTPUTS_ENV = "ARCTA_OUTPUTS_DIR"
STATIC_DIR = Path(__file__).resolve().parent / "static"


def default_session_root() -> Path:
    configured = os.environ.get(ARCTA_OUTPUTS_ENV, "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.home() / "Documents" / "ARCTA_OUTPUTS").resolve()


def create_app(
    session_root: str | Path | None = None,
) -> FastAPI:
    app = FastAPI(
        title=ARCTA_WEB_APP_NAME,
        version=ARCTA_WEB_APP_VERSION,
        description=(
            "Interface Web ARCTA — "
            "Analyse Couple/Tension."
        ),
    )

    if session_root is None:
        outputs_root = default_session_root()
        session_root = technical_root()
        migrate_sessions(outputs_root, session_root)
    else:
        outputs_root = Path(session_root).resolve()
    outputs_root.mkdir(parents=True, exist_ok=True)

    app.state.session_registry = (
        SessionRegistry(
            session_root
        )
    )

    from .session_campaign_run import _atomic_json
    _atomic_json(Path(session_root) / "outputs_root.json", {"path": str(outputs_root)})
    app.include_router(local_files_router)

    app.mount(
        "/static",
        StaticFiles(directory=str(STATIC_DIR)),
        name="static",
    )

    app.include_router(
        router
    )

    app.include_router(
        build_mapping_router(
            app.state.session_registry.get_session
        )
    )

    app.include_router(
        build_campaign_mapping_router(
            app.state.session_registry.get_session
        )
    )

    app.include_router(
        build_diag_review_router(
            app.state.session_registry.get_session
        )
    )

    app.include_router(
        build_campaign_run_router(
            app.state.session_registry.get_session
        )
    )

    app.include_router(
        mapping_page_router
    )

    app.include_router(
        diag_review_page_router
    )

    app.include_router(
        campaign_run_page_router
    )

    app.include_router(output_locations_router)
    app.include_router(analysis_settings_router)

    from .dabcta_page import router as dabcta_router
    app.include_router(dabcta_router)

    return app


app = create_app()
