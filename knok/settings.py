"""Configuración por variables de entorno (prefijo KNOK_). Ver .env.example."""
from functools import lru_cache
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="KNOK_", env_file=".env", extra="ignore")

    # --- básico
    env: str = "development"                       # development | production | test
    database_url: str = "postgresql+psycopg://postgres@localhost:5432/knok"
    secret_key: str = "cambia-esto-en-produccion"  # cifra los tokens OAuth guardados y firma estados
    public_base_url: str = "http://localhost:8000"  # URL pública de esta API (callbacks OAuth)
    web_base_url: str = "http://localhost:3000"    # tu web: adónde volver tras conectar Gmail/InfoJobs
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]
    storage_dir: str = "./storage"                 # CVs, adjuntos y bandeja de salida de Simulación
    admin_emails: Annotated[list[str], NoDecode] = []                   # cuentas con rol admin (revisan el diccionario)
    token_ttl_days: int = 30

    # --- cola de tareas
    tasks_eager: bool = False                      # True: las tareas se ejecutan en el acto (tests/demos)
    embedded_worker: bool = False                  # True: la API lleva el worker dentro (uso local, un solo proceso)
    local_single_user: bool = False                # True: el panel entra sin login (solo desde este ordenador)
    local_default_pack: str = "marina_mercante"    # nicho con el que empieza el usuario local

    # --- red
    crawler_user_agent: str = "knok-bot/0.1 (+https://knok.app/bot; busca contactos de empleo publicados)"
    offline_sources: bool = False                  # True: las fuentes usan datos de ejemplo, sin red

    # --- Google (Gmail OAuth, scope gmail.send)
    google_client_id: str = ""
    google_client_secret: str = ""
    gmail_daily_cap: int = 500                     # tope duro de Google para cuentas personales

    # --- Adzuna (plan gratis)
    adzuna_app_id: str = ""
    adzuna_app_key: str = ""
    adzuna_monthly_quota: int = 1000

    # --- InfoJobs
    infojobs_client_id: str = ""
    infojobs_client_secret: str = ""

    # --- reenvío de respuestas (correo entrante)
    inbound_domain: str = "in.knok.app"            # dominio que recibe los reenvíos u-<token>@...
    inbound_secret: str = ""                       # secreto compartido con el receptor (Cloudflare Worker…)

    # --- punto de extensión opcional (desactivado): sugerir respuesta
    suggest_reply_provider: str = ""

    @field_validator("cors_origins", "admin_emails", mode="before")
    @classmethod
    def _lista(cls, v):
        # Permite "a,b,c" además de JSON en las variables de entorno
        if isinstance(v, str) and not v.strip().startswith("["):
            return [x.strip() for x in v.split(",") if x.strip()]
        return v

    @property
    def is_production(self) -> bool:
        return self.env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
