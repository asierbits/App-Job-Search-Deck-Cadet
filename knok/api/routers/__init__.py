"""Todos los routers de la API, en el orden en que aparecen en la documentación."""
from knok.api.routers import admin, auth, connections, extension, me, packs, review, search, tracking

ALL: list = [auth.router, me.router, connections.router, packs.router, search.router, review.router,
             tracking.router, extension.router, search.catalog, admin.router, tracking.inbound]
