"""Modelo de datos.

Dos mundos separados:
  - Base común (compartida entre usuarios, no depende del modo): empresas, correos genéricos, rastreos,
    catálogo de ATS, ofertas, ejecuciones de fuentes y diccionario de preguntas.
  - Datos de cada usuario: cuenta, perfil, documentos, banco de respuestas, plantillas, búsquedas,
    tandas, candidaturas, correos, respuestas y actividad. Lo que se envía lleva la columna `mode`
    (simulation | test | live) para que las pruebas nunca se mezclen con lo real.
"""
from datetime import datetime, timezone

from sqlalchemy import (JSON, BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, Text,
                        TypeDecorator, UniqueConstraint, text)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# JSONB en Postgres, JSON normal en SQLite (tests rápidos)
Json = JSON().with_variant(JSONB(), "postgresql")
# BIGINT autoincremental en Postgres; INTEGER en SQLite (solo así es autoincremental allí)
BigId = BigInteger().with_variant(Integer(), "sqlite")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """Fecha con zona horaria, siempre en UTC al leer (SQLite la devuelve sin zona; Postgres con ella)."""
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value


class Base(DeclarativeBase):
    pass


def _pk():
    return mapped_column(BigId, primary_key=True, autoincrement=True)


def _created():
    return mapped_column(UTCDateTime, default=utcnow, nullable=False)


# =====================================================================================  usuarios

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = _pk()
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    locale: Mapped[str] = mapped_column(String(8), nullable=False, default="es")
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = _created()

    profile: Mapped["Profile"] = relationship(back_populates="user", uselist=False, cascade="all, delete-orphan")


class ApiToken(Base):
    """Tokens de acceso (Bearer). Se guarda solo el hash; el token se muestra una vez al crearlo."""
    __tablename__ = "api_tokens"
    id: Mapped[int] = _pk()
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False, default="sesión")
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    prefix: Mapped[str] = mapped_column(String(12), nullable=False)
    created_at: Mapped[datetime] = _created()
    last_used_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class OAuthAccount(Base):
    """Cuentas externas conectadas (Gmail, InfoJobs). Tokens cifrados."""
    __tablename__ = "oauth_accounts"
    __table_args__ = (UniqueConstraint("user_id", "provider"),)
    id: Mapped[int] = _pk()
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)        # google | infojobs
    account_email: Mapped[str] = mapped_column(String(320), nullable=False, default="")
    scopes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    access_token_enc: Mapped[str] = mapped_column(Text, nullable=False, default="")
    refresh_token_enc: Mapped[str] = mapped_column(Text, nullable=False, default="")
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = _created()


class OAuthState(Base):
    """Estado anti-CSRF del flujo OAuth (vive unos minutos)."""
    __tablename__ = "oauth_states"
    state: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    return_to: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = _created()


class Profile(Base):
    __tablename__ = "profiles"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    pack: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    mode: Mapped[str] = mapped_column(String(12), nullable=False, default="simulation")
    first_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    last_name: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    email: Mapped[str] = mapped_column(String(320), nullable=False, default="")
    phone: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    city: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    country: Mapped[str] = mapped_column(String(2), nullable=False, default="")
    links: Mapped[dict] = mapped_column(Json, nullable=False, default=dict)          # linkedin, github, web…
    languages: Mapped[list] = mapped_column(Json, nullable=False, default=list)      # [{code, level}]
    pack_data: Mapped[dict] = mapped_column(Json, nullable=False, default=dict)      # campos propios del pack
    daily_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    pause_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=45)
    followup_days: Mapped[int] = mapped_column(Integer, nullable=False, default=7)
    inbound_token: Mapped[str] = mapped_column(String(32), nullable=False, default="")  # reenvío de respuestas
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    user: Mapped[User] = relationship(back_populates="profile")


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[int] = _pk()
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="cv")       # cv | cover_letter | certificate | other
    language: Mapped[str] = mapped_column(String(8), nullable=False, default="")      # '' = vale para todos
    label: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    filename: Mapped[str] = mapped_column(String(200), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(300), nullable=False)
    mime: Mapped[str] = mapped_column(String(120), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = _created()


class Answer(Base):
    """Banco de respuestas: una respuesta por clave canónica (y opcionalmente por idioma)."""
    __tablename__ = "answers"
    __table_args__ = (UniqueConstraint("user_id", "key", "language"),)
    id: Mapped[int] = _pk()
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(80), nullable=False)
    language: Mapped[str] = mapped_column(String(8), nullable=False, default="")
    value: Mapped[object] = mapped_column(Json, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class CustomAnswer(Base):
    """Respuestas a preguntas sin clave canónica que el usuario ya contestó (por texto normalizado)."""
    __tablename__ = "custom_answers"
    __table_args__ = (UniqueConstraint("user_id", "label_norm"),)
    id: Mapped[int] = _pk()
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    label_norm: Mapped[str] = mapped_column(String(400), nullable=False)
    value: Mapped[object] = mapped_column(Json, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class Niche(Base):
    """Nicho creado por el usuario desde el panel (sectores, palabras clave, términos a detectar…).
    Se convierte en un pack igual que los de knok/packs/ (ver knok/packs/custom.py)."""
    __tablename__ = "niches"
    id: Mapped[int] = _pk()
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    slug: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    spec: Mapped[dict] = mapped_column(Json, nullable=False, default=dict)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class Template(Base):
    """Plantillas propias del usuario. Si no tiene, se usan las del pack."""
    __tablename__ = "templates"
    __table_args__ = (UniqueConstraint("user_id", "kind", "audience", "language"),)
    id: Mapped[int] = _pk()
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)          # email | cover_letter | followup
    audience: Mapped[str] = mapped_column(String(40), nullable=False, default="company")
    language: Mapped[str] = mapped_column(String(8), nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False, default="")
    body: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


# =====================================================================================  base común

class Company(Base):
    __tablename__ = "companies"
    __table_args__ = (Index("ix_companies_name_country", "name_norm", "country"),)
    id: Mapped[int] = _pk()
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    name_norm: Mapped[str] = mapped_column(String(300), nullable=False)
    domain: Mapped[str | None] = mapped_column(String(253), unique=True)
    country: Mapped[str] = mapped_column(String(2), nullable=False, default="")
    city: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    sector: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="company")   # company | agency | institution
    website: Mapped[str] = mapped_column(Text, nullable=False, default="")
    careers_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    phone: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    wikidata_id: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    osm_ref: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    packs: Mapped[list] = mapped_column(Json, nullable=False, default=list)       # packs en los que apareció
    sources: Mapped[list] = mapped_column(Json, nullable=False, default=list)     # fuentes que la aportaron
    flags: Mapped[dict] = mapped_column(Json, nullable=False, default=dict)       # bloqueada, menciones, avisos…
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    emails: Mapped[list["CompanyEmail"]] = relationship(back_populates="company", cascade="all, delete-orphan")


class CompanyEmail(Base):
    """Solo buzones GENÉRICOS (info@, rrhh@, jobs@…). Los personales no entran nunca."""
    __tablename__ = "company_emails"
    id: Mapped[int] = _pk()
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    local_part: Mapped[str] = mapped_column(String(120), nullable=False)
    found_on_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    on_careers_page: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    found_at: Mapped[datetime] = _created()
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    company: Mapped[Company] = relationship(back_populates="emails")


class Crawl(Base):
    """Caché de rastreos por dominio y pack (lo que se busca en una web depende del nicho)."""
    __tablename__ = "crawls"
    domain: Mapped[str] = mapped_column(String(253), primary_key=True)
    pack: Mapped[str] = mapped_column(String(60), primary_key=True, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False)      # ok | blocked | down | robots
    result: Mapped[dict] = mapped_column(Json, nullable=False, default=dict)
    fetched_at: Mapped[datetime] = _created()


class AtsBoard(Base):
    """Catálogo de tableros de ATS (empresa → slug). Crece con el uso."""
    __tablename__ = "ats_boards"
    __table_args__ = (UniqueConstraint("ats", "slug"),)
    id: Mapped[int] = _pk()
    ats: Mapped[str] = mapped_column(String(30), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), nullable=False)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id", ondelete="SET NULL"), index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")  # pending | active | empty | invalid
    jobs_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    discovered_from: Mapped[str] = mapped_column(String(40), nullable=False, default="manual")
    last_checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = _created()


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (UniqueConstraint("source", "source_job_id"),
                      Index("ix_jobs_fingerprint", "fingerprint"),
                      Index("ix_jobs_country_seen", "country", "last_seen_at"))
    id: Mapped[int] = _pk()
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id", ondelete="SET NULL"), index=True)
    source: Mapped[str] = mapped_column(String(30), nullable=False)        # greenhouse | lever | ashby | adzuna | infojobs | capture | sample
    source_job_id: Mapped[str] = mapped_column(String(200), nullable=False)
    company_name: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    title: Mapped[str] = mapped_column(String(400), nullable=False)
    title_norm: Mapped[str] = mapped_column(String(400), nullable=False, default="")
    city: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    country: Mapped[str] = mapped_column(String(2), nullable=False, default="")
    remote: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    language: Mapped[str] = mapped_column(String(8), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")   # texto plano
    url: Mapped[str] = mapped_column(Text, nullable=False, default="")           # página de la oferta
    apply_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    apply_platform: Mapped[str] = mapped_column(String(30), nullable=False, default="")
    apply_email: Mapped[str] = mapped_column(String(320), nullable=False, default="")  # solo si es genérico
    easy_apply: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    questions: Mapped[list] = mapped_column(Json, nullable=False, default=list)  # preguntas que da la API de la fuente
    salary: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    canonical_job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    raw: Mapped[dict] = mapped_column(Json, nullable=False, default=dict)
    posted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    first_seen_at: Mapped[datetime] = _created()
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    company: Mapped[Company | None] = relationship()


class SourceRun(Base):
    """Cada lectura de una fuente: para no repetirlas y para llevar la cuenta de cuotas (Adzuna)."""
    __tablename__ = "source_runs"
    __table_args__ = (Index("ix_source_runs_key", "source", "query_key", "ran_at"),)
    id: Mapped[int] = _pk()
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    query_key: Mapped[str] = mapped_column(String(64), nullable=False)
    query: Mapped[dict] = mapped_column(Json, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ok")   # ok | error | skipped
    calls_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stats: Mapped[dict] = mapped_column(Json, nullable=False, default=dict)
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    ran_at: Mapped[datetime] = _created()


class QuestionPattern(Base):
    """Patrones aprendidos/aprobados para reconocer preguntas (además de los semilla en YAML)."""
    __tablename__ = "question_patterns"
    id: Mapped[int] = _pk()
    pack: Mapped[str] = mapped_column(String(60), nullable=False, default="")   # '' = global
    key: Mapped[str] = mapped_column(String(80), nullable=False)
    language: Mapped[str] = mapped_column(String(8), nullable=False, default="")
    pattern: Mapped[str] = mapped_column(String(300), nullable=False)
    weight: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    created_at: Mapped[datetime] = _created()


class UnknownQuestion(Base):
    """Preguntas que el motor no reconoció: material para ampliar el diccionario."""
    __tablename__ = "unknown_questions"
    __table_args__ = (UniqueConstraint("label_norm", "pack"),)
    id: Mapped[int] = _pk()
    label: Mapped[str] = mapped_column(Text, nullable=False)
    label_norm: Mapped[str] = mapped_column(String(400), nullable=False)
    pack: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    language: Mapped[str] = mapped_column(String(8), nullable=False, default="")
    field_type: Mapped[str] = mapped_column(String(20), nullable=False, default="text")
    options: Mapped[list] = mapped_column(Json, nullable=False, default=list)
    platforms: Mapped[list] = mapped_column(Json, nullable=False, default=list)
    times_seen: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    mapped_key: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    first_seen_at: Mapped[datetime] = _created()
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


# =====================================================================================  trabajo del usuario

class Search(Base):
    __tablename__ = "searches"
    id: Mapped[int] = _pk()
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    params: Mapped[dict] = mapped_column(Json, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")  # queued | running | done | error
    stats: Mapped[dict] = mapped_column(Json, nullable=False, default=dict)
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = _created()
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class SearchResult(Base):
    __tablename__ = "search_results"
    __table_args__ = (Index("ix_search_results_search", "search_id", "score"),)
    id: Mapped[int] = _pk()
    search_id: Mapped[int] = mapped_column(ForeignKey("searches.id", ondelete="CASCADE"))
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    route: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    platform: Mapped[str] = mapped_column(String(30), nullable=False, default="")
    reasons: Mapped[list] = mapped_column(Json, nullable=False, default=list)


class Batch(Base):
    __tablename__ = "batches"
    id: Mapped[int] = _pk()
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    search_id: Mapped[int | None] = mapped_column(ForeignKey("searches.id", ondelete="SET NULL"))
    mode: Mapped[str] = mapped_column(String(12), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="review")  # review | closed
    created_at: Mapped[datetime] = _created()


class Application(Base):
    """Una candidatura: a una oferta (job_id) o directa a una empresa (solo company_id, por correo)."""
    __tablename__ = "applications"
    __table_args__ = (
        Index("ux_app_job", "user_id", "mode", "job_id", unique=True,
              postgresql_where=text("job_id IS NOT NULL"), sqlite_where=text("job_id IS NOT NULL")),
        Index("ux_app_company", "user_id", "mode", "company_id", unique=True,
              postgresql_where=text("job_id IS NULL"), sqlite_where=text("job_id IS NULL")),
        Index("ix_app_user_status", "user_id", "mode", "status"),
    )
    id: Mapped[int] = _pk()
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    mode: Mapped[str] = mapped_column(String(12), nullable=False)
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("batches.id", ondelete="SET NULL"), index=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id", ondelete="SET NULL"))
    route: Mapped[str] = mapped_column(String(20), nullable=False)          # ats_extension | portal_api | portal_copilot | email | manual
    platform: Mapped[str] = mapped_column(String(30), nullable=False, default="")
    route_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="prepared")
    language: Mapped[str] = mapped_column(String(8), nullable=False, default="en")
    contact_email: Mapped[str] = mapped_column(String(320), nullable=False, default="")
    apply_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    subject: Mapped[str] = mapped_column(Text, nullable=False, default="")
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    document_ids: Mapped[list] = mapped_column(Json, nullable=False, default=list)
    fields: Mapped[list] = mapped_column(Json, nullable=False, default=list)       # [{key,label,value,origin,confidence,needs_review,…}]
    warnings: Mapped[list] = mapped_column(Json, nullable=False, default=list)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
    confirmed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    follow_up_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_status_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    job: Mapped[Job | None] = relationship()
    company: Mapped[Company | None] = relationship()


class Email(Base):
    __tablename__ = "emails"
    __table_args__ = (Index("ix_emails_user_day", "user_id", "mode", "sent_at"),)
    id: Mapped[int] = _pk()
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), index=True)
    mode: Mapped[str] = mapped_column(String(12), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="application")   # application | followup
    to_addr: Mapped[str] = mapped_column(String(320), nullable=False)        # destinatario real (en test, el propio usuario)
    intended_to: Mapped[str] = mapped_column(String(320), nullable=False)    # la empresa
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    attachments: Mapped[list] = mapped_column(Json, nullable=False, default=list)   # ids de documentos
    message_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    gmail_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    thread_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    sender: Mapped[str] = mapped_column(String(320), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")   # queued | sending | sent | error | cancelled
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    queued_at: Mapped[datetime] = _created()
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class Reply(Base):
    __tablename__ = "replies"
    id: Mapped[int] = _pk()
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    application_id: Mapped[int | None] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), index=True)
    mode: Mapped[str] = mapped_column(String(12), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)       # manual | forward | simulated
    from_addr: Mapped[str] = mapped_column(String(320), nullable=False, default="")
    subject: Mapped[str] = mapped_column(Text, nullable=False, default="")
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    category: Mapped[str] = mapped_column(String(20), nullable=False, default="other")  # interview | info | rejection | auto | other
    read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    received_at: Mapped[datetime] = _created()


class SimulatedReply(Base):
    """Respuestas del modo Simulación pendientes de 'llegar'."""
    __tablename__ = "simulated_replies"
    id: Mapped[int] = _pk()
    email_id: Mapped[int] = mapped_column(ForeignKey("emails.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    due_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)


class Event(Base):
    """Registro de actividad que ve el usuario (y errores del sistema con user_id NULL)."""
    __tablename__ = "events"
    __table_args__ = (Index("ix_events_user_ts", "user_id", "ts"),)
    id: Mapped[int] = _pk()
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    ts: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    level: Mapped[str] = mapped_column(String(10), nullable=False, default="info")   # info | ok | warning | error
    message: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[dict] = mapped_column(Json, nullable=False, default=dict)


# =====================================================================================  cola de tareas

class Task(Base):
    """Cola de tareas sobre Postgres (SELECT … FOR UPDATE SKIP LOCKED). Sin Redis."""
    __tablename__ = "tasks"
    __table_args__ = (Index("ix_tasks_ready", "status", "run_after"),)
    id: Mapped[int] = _pk()
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    payload: Mapped[dict] = mapped_column(Json, nullable=False, default=dict)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="queued")   # queued | running | done | failed | cancelled
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    run_after: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    locked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    locked_by: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    last_error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    result: Mapped[dict] = mapped_column(Json, nullable=False, default=dict)
    created_at: Mapped[datetime] = _created()
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
