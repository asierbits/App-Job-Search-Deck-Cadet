"""Todos los routers de la API, en el orden en que aparecen en la documentación."""
from knok.api.routers import auth, me, packs, search

ALL: list = [auth.router, me.router, packs.router, search.router, search.catalog]
