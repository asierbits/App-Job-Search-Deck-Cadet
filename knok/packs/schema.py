"""Esquema de un pack de nicho. Todo lo específico de un sector vive aquí; el núcleo no sabe de nichos.

Un pack es una carpeta `knok/packs/<slug>/` con:
  pack.yaml           fuentes, palabras clave, prioridades de buzón, avisos, campos extra del perfil…
  questions.yaml      preguntas típicas del nicho → claves del banco de respuestas (opcional)
  templates/<idioma>/<tipo>_<audiencia>.txt   plantillas (primera línea "Subject: …")
"""
from pydantic import BaseModel, Field

Localized = dict[str, str]          # {"es": "...", "en": "..."}


class ProfileField(BaseModel):
    key: str
    label: Localized
    type: str = "text"              # text | textarea | number | select
    options: list[str] = []
    localized: bool = False         # True: el usuario puede dar un valor por idioma (titulacion / titulacion_en)


class AnswerKey(BaseModel):
    """Clave extra del banco de respuestas propia del nicho (además de las globales)."""
    key: str
    label: Localized
    type: str = "text"              # text | number | boolean | choice | textarea
    options: list[str] = []
    patterns: dict[str, list[str]] = {}   # idioma → palabras clave que la reconocen en un formulario


class WikidataQuery(BaseModel):
    label: str
    where: str                      # patrón SPARQL sobre ?item, p. ej. "?item wdt:P31 wd:Q1807108 ."


class WikidataCfg(BaseModel):
    queries: list[WikidataQuery] = []
    countries: list[str] = []       # ISO 3166-1 alfa-2


class DirectoryCfg(BaseModel):
    url: str
    country: str = ""


class OsmCfg(BaseModel):
    tags: dict[str, list[str]] = {}          # clave OSM → valores, p. ej. office: [company, it]
    agency_tags: list[str] = []              # "office=employment_agency" → tipo agencia
    sector_labels: dict[str, str] = {}       # valor OSM → etiqueta legible


class AtsCfg(BaseModel):
    seed_boards: list[dict] = []             # [{ats: greenhouse, slug: acme}]


class AdzunaCfg(BaseModel):
    what: list[str] = []
    countries: list[str] = []
    category: str = ""


class InfojobsCfg(BaseModel):
    q: list[str] = []
    category: str = ""


class SourcesCfg(BaseModel):
    default_countries: list[str] = []
    wikidata: WikidataCfg = WikidataCfg()
    directories: list[DirectoryCfg] = []
    osm: OsmCfg = OsmCfg()
    ats: AtsCfg = AtsCfg()
    adzuna: AdzunaCfg = AdzunaCfg()
    infojobs: InfojobsCfg = InfojobsCfg()


class Mention(BaseModel):
    label: str
    variants: list[str]


class CareerSignal(BaseModel):
    label: str
    terms: list[str]                         # fragmentos de regex; se buscan como palabras completas


class CrawlCfg(BaseModel):
    """Se SUMA a los valores globales de knok/core/crawl/defaults.py."""
    page_keywords: list[str] = []            # páginas de empleo propias del nicho (crewing, phd…), por prioridad
    mailbox_priority: list[str] = []         # buzones preferidos, del mejor al peor
    extra_generic: list[str] = []            # más buzones de rol que cuentan como genéricos
    commercial: list[str] = []               # buzones comerciales (peores que info@)
    mentions: list[Mention] = []             # términos que conviene detectar en la web (⚓ cadetes…)
    career_signals: list[CareerSignal] = []  # señales en la página de empleo (empleo a bordo…)
    warnings: dict[str, list[str]] = {}      # tipo → expresiones regulares
    warnings_on_careers_only: list[str] = [] # tipos de aviso que solo cuentan en páginas de empleo
    exclude_names: list[str] = []            # términos (regex) de entidades que no son empleadores del nicho
    exclude_domains: list[str] = []
    allowed_countries: list[str] = []        # vacío = todos


class MatchCfg(BaseModel):
    """Qué ofertas son del nicho (se busca en título y descripción, sin tildes ni mayúsculas)."""
    keywords: dict[str, list[str]] = {}
    title_keywords: dict[str, list[str]] = {}   # cuentan más si aparecen en el título
    negative: list[str] = []


class TemplateText(BaseModel):
    subject: str = ""
    body: str


class Pack(BaseModel):
    slug: str
    version: int = 1
    names: Localized
    description: Localized = {}
    languages: list[str] = ["es", "en"]
    profile_fields: list[ProfileField] = []
    answer_keys: list[AnswerKey] = []
    sources: SourcesCfg = SourcesCfg()
    crawl: CrawlCfg = CrawlCfg()
    match: MatchCfg = MatchCfg()
    reply_keywords: dict[str, list[str]] = {}    # interview | info | rejection | auto → frases extra
    sample_data: str = ""                        # fichero de ejemplo (Simulación / tests sin red)
    # Cargado de templates/: "email.company.es" → TemplateText
    templates: dict[str, TemplateText] = Field(default_factory=dict)

    def name(self, lang: str) -> str:
        return self.names.get(lang) or self.names.get("en") or self.slug

    def template(self, kind: str, audience: str, lang: str) -> TemplateText | None:
        for clave in (f"{kind}.{audience}.{lang}", f"{kind}.company.{lang}", f"{kind}.{audience}.en",
                      f"{kind}.company.en"):
            if clave in self.templates:
                return self.templates[clave]
        return None
