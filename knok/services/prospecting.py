"""Empresas sin oferta publicada (OpenStreetMap, Wikidata, directorios del pack) → correo directo.
Se completa en la fase 4."""
from sqlalchemy.orm import Session


def ingest_companies(db: Session, http, pack, params: dict) -> dict:
    return {"skipped": "pendiente"}


def rank_companies(db: Session, search, pack, profile) -> list:
    return []
