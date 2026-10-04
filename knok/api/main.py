"""Aplicación FastAPI. Documentación interactiva en /docs (Swagger) y /redoc; esquema en /openapi.json."""
import pathlib

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from knok import __version__
from knok.api import routers
from knok.db import session as dbs
from knok.settings import get_settings

DESCRIPTION = """
Motor de **knok**: busca ofertas y empresas, decide cómo aplicar a cada una, rellena solicitudes y
prepara correos para que el usuario los revise y envíe.

**Autenticación**: `Authorization: Bearer knk_…` (obtén el token con `POST /auth/register` o `POST /auth/login`).

**Principio**: nada se envía sin un clic del usuario. Los envíos solo ocurren con
`POST /batches/{id}/send`, `POST /applications/{id}/send` o `POST /panel/send`, con la lista explícita
de lo que el usuario ha marcado. El panel (diseño de la primera versión) está en `/`.
"""

TAGS = [
    {"name": "auth", "description": "Cuentas y tokens"},
    {"name": "me", "description": "Perfil, documentos, banco de respuestas, plantillas y cuentas conectadas"},
    {"name": "packs", "description": "Packs de nicho (configuración por sector)"},
    {"name": "search", "description": "Búsquedas y resultados"},
    {"name": "review", "description": "Tandas, revisión y envío"},
    {"name": "tracking", "description": "Seguimiento (mini-CRM), respuestas y exportación"},
    {"name": "panel", "description": "Atajos para el panel: estado, tabla y envío de lo marcado"},
    {"name": "extension", "description": "Endpoints para la extensión de Chrome"},
    {"name": "catalog", "description": "Base común: empresas, ofertas y tableros de ATS"},
    {"name": "admin", "description": "Revisión del diccionario de preguntas"},
    {"name": "system", "description": "Salud y utilidades"},
]


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title="knok API", version=__version__, description=DESCRIPTION, openapi_tags=TAGS)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.cors_origins,
        allow_origin_regex=r"^chrome-extension://[a-p]{32}$",  # la extensión de knok
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition"],
    )
    for r in routers.ALL:
        app.include_router(r)

    if s.embedded_worker and not s.tasks_eager:
        @app.on_event("startup")
        def _worker():
            from knok.worker.__main__ import start_embedded
            app.state.worker_stop = start_embedded()

        @app.on_event("shutdown")
        def _parar_worker():
            if getattr(app.state, "worker_stop", None):
                app.state.worker_stop.set()

    @app.get("/health", tags=["system"])
    def health():
        with dbs.engine().connect() as c:
            c.execute(text("SELECT 1"))
        return {"ok": True, "version": __version__}

    panel = pathlib.Path(__file__).with_name("static") / "panel"
    app.mount("/ui", StaticFiles(directory=panel), name="ui")

    @app.get("/", include_in_schema=False)
    def inicio():
        """El panel (diseño de la primera versión). La API está documentada en /docs."""
        return FileResponse(panel / "index.html", headers={"Cache-Control": "no-cache"})

    @app.get("/playground", include_in_schema=False)
    def playground():
        return FileResponse(pathlib.Path(__file__).with_name("static") / "playground.html")

    return app


app = create_app()
