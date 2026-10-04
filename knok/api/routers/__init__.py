"""Todos los routers de la API, en el orden en que aparecen en la documentación."""
from knok.api.routers import auth, me, packs

ALL: list = [auth.router, me.router, packs.router]
