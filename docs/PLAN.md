# knok — plan del motor (propuesta para aprobar)

> Estado: **aprobado e implementado** (fases 1–8 y parte de la 9). Las decisiones tomadas están en §10 y el estado en §11.

## 0. Resumen en 10 líneas

- **Backend Python 3.12 + FastAPI** (OpenAPI y documentación interactiva gratis = interfaz de prueba), **Postgres 16**, **SQLAlchemy 2 + Alembic**.
- **Cola de tareas sobre el propio Postgres** (sin Redis): menos piezas, coste casi cero. Alternativa: Celery/RQ + Redis.
- **La lógica pura** (fuentes, limpieza, enrutador, relleno, plantillas, clasificación) vive en `knok/core/` sin depender de la web ni de la BD → se prueba con fixtures y sin red.
- **Lo específico de cada nicho** vive en **packs YAML** versionados (`knok/packs/<nicho>/`). El núcleo no sabe nada de barcos.
- **Base común** (empresas, dominios, correos genéricos, ofertas, catálogo de ATS) separada de los **datos de cada usuario** (perfil, candidaturas, envíos, respuestas).
- **Ingesta compartida + consulta por usuario**: las fuentes con cuota (Adzuna ~1.000 llamadas/mes *para todo el servicio*) se leen por lotes cacheados y compartidos; la búsqueda del usuario filtra la base común al instante.
- **Un solo motor de relleno, en el servidor**: la extensión solo lee el formulario (etiquetas, tipos, opciones) y escribe los valores que le devuelve la API. Las reglas viven en un único sitio, en Python, con tests.
- **Gmail solo con `gmail.send`** (scope "sensible", verificación gratuita). Los borradores viven en knok, no en Gmail (`gmail.compose` es restringido).
- **Nada sale sin clic**: toda candidatura pasa por `preparada → confirmada (clic) → enviada`. La extensión nunca pulsa "Enviar".
- Modos **Simulación / Prueba / Real** se mantienen, por usuario.

---

## 1. Qué se reaprovecha de este repositorio

| Ahora | Pasa a | Cambios |
|---|---|---|
| `core/webemail.py` | `knok/core/crawl/website.py` + `knok/core/emails/` | Se conserva casi entero (8 páginas, robots.txt, Cloudflare, ofuscados, detección de página de empleo y de portales ATS). Salen a config del pack: `PAGINAS_CLAVE`, `PREFERIDOS`, `TERMINOS_CADETE`, `EMPLEO_MAR_RE`, `AVISOS`, `COMERCIALES`. Se separa en: *descargar* (httpx, límites, robots) / *extraer* (emails, enlaces, nombre) / *puntuar* (con prioridades del pack). Nuevo: clasificador **genérico vs personal**; los personales se descartan antes de guardar. Los enlaces a ATS detectados alimentan el catálogo de slugs. |
| `core/busqueda.py` (OSM) | `knok/core/sources/osm.py` | Etiquetas `office=*`/`amenity=*` y palabras clave pasan al pack. Caché compartida de geocodificación y de consultas Overpass (sus normas de uso lo exigen en un servicio multiusuario). |
| `core/maritimo.py` | `knok/core/sources/wikidata.py` + `directories.py` + **pack `marina_mercante`** | El lector de directorios HTML/PDF con paginación y el SPARQL quedan genéricos; las consultas (QIDs), la lista de directorios, `RE_NO_NAVIERA`, `IGNORAR_DOMINIOS` y el filtro de países van al YAML del pack. |
| `core/correo.py` | `knok/core/mail/` (`compose.py`, `classify.py`, `gmail.py`) | Plantillas con variables tolerantes, idioma por país (ahora tabla país→idioma configurable), clasificación por palabras clave (las palabras van a `i18n` + pack). SMTP/IMAP con contraseña de aplicación desaparecen → Gmail API OAuth. |
| `core/motor.py` | `knok/worker/` | Hilos → tareas en cola. Se mantienen: límite diario, pausas entre envíos, reserva atómica antes de enviar, caché de rastreos por dominio (30 días). |
| `core/simulador.py` | `knok/core/mail/simulator.py` | Igual, textos por pack e idioma. |
| `core/adjuntos.py` | `knok/core/documents.py` | Documentos por usuario e idioma (CV, carta, certificados), almacenamiento en disco o S3‑compatible. |
| `app.py` + `static/` | Se retiran | Sustituidos por la API. Propuesta: etiquetar el estado actual (`v1-panel-local`) y moverlo a `legacy/` hasta terminar la migración (ver pregunta 5). |

---

## 2. Stack

| Pieza | Elección | Por qué |
|---|---|---|
| Lenguaje | Python 3.12 | Reaprovechar `core/`. |
| API | **FastAPI** + Pydantic v2 | OpenAPI automático, Swagger UI como interfaz mínima de prueba, validación. |
| BD | **Postgres 16** (JSONB para datos de pack) | Pedido. Índices únicos parciales, `SKIP LOCKED` para la cola. |
| ORM / migraciones | SQLAlchemy 2 + Alembic | Estándar, migraciones versionadas. |
| Cola | **Procrastinate** (cola sobre Postgres, reintentos y tareas periódicas) | Sin Redis: una pieza menos que pagar y mantener. Si prefieres Redis, Celery o RQ encajan igual (las tareas se escriben como funciones normales). |
| HTTP saliente | httpx | Timeouts, límites, mocks fáciles en tests (`respx`). |
| Dominios | `tldextract` con lista de sufijos incluida (sin descargar en ejecución) | `careers.empresa.co.uk` → `empresa.co.uk`. |
| OAuth Google | `google-auth` + llamadas REST a Gmail | Solo `gmail.send` (+ `openid email` para saber qué cuenta es). |
| Cifrado de tokens | `cryptography` (Fernet), clave en variable de entorno | Tokens OAuth de Gmail/InfoJobs cifrados en BD. |
| Tests | pytest, respx, fixtures JSON/HTML; Postgres en Docker para los tests de API | Sin red en tests. |
| Extensión | Chrome Manifest V3, JavaScript con módulos ES sin paso de compilación (ver pregunta 11) | Adaptadores fáciles de tocar. Tests de adaptadores con Playwright sobre HTML guardado (Chromium ya disponible). |
| Arranque local | `docker compose up` (api + worker + postgres) o `uv`/`pip` + Postgres local | |

**Sin IA en ningún sitio.** Punto de extensión `knok/core/extension_points/suggest_reply.py` con una interfaz `ReplySuggester` y una implementación nula; activable solo con `KNOK_SUGGEST_REPLY=…` (por defecto desactivado).

---

## 3. Estructura de carpetas

```
knok/                               ← paquete Python
  settings.py                       variables de entorno (pydantic-settings)
  api/
    main.py                         app FastAPI, CORS, routers, manejo de errores
    deps.py                         autenticación, sesión de BD, usuario actual
    routers/
      auth.py  me.py  documents.py  answers.py  templates.py  packs.py
      searches.py  jobs.py  companies.py  batches.py  applications.py
      emails.py  tracking.py  oauth_google.py  oauth_infojobs.py
      extension.py                  capturas y "plan de relleno" para la extensión
      admin.py                      revisar preguntas nuevas → diccionario del pack
    schemas/                        modelos Pydantic de entrada/salida
  db/
    models.py  session.py
    migrations/                     Alembic
  core/                             LÓGICA PURA: sin FastAPI; BD solo vía repositorios
    http.py                         cliente con User-Agent de knok, timeouts, robots
    crawl/website.py                ← core/webemail.py
    emails/generic.py               ¿genérico o personal?
    emails/score.py                 mejor buzón según prioridades del pack
    sources/
      base.py                       interfaz común: RawJob / RawCompany
      ats/detect.py                 URL → (ats, slug, job_id)
      ats/greenhouse.py  ats/lever.py  ats/ashby.py
      adzuna.py  infojobs.py
      osm.py  wikidata.py  directories.py
      capture.py                    lo que envía la extensión
      offline.py                    fuente de ejemplo (fixtures) para Simulación/tests
    cleaning/normalize.py           empresa, dominio, puesto, ciudad
    cleaning/dedupe.py              huella y elección de la oferta original
    routing/router.py               decide la vía de cada oferta
    filling/
      fields.py                     taxonomía de campos (claves canónicas)
      matcher.py                    etiqueta → clave canónica (palabras clave multilingües)
      options.py                    respuesta → opción de un select/radio ("Sí" ↔ "Yes")
      engine.py                     formulario + perfil + banco → valores, origen, faltantes
    mail/compose.py  mail/gmail.py  mail/simulator.py  mail/classify.py  mail/limits.py
    tracking/crm.py  tracking/export_csv.py
    i18n/es.yaml  i18n/en.yaml
    extension_points/suggest_reply.py   (desactivado)
  packs/
    schema.py  loader.py
    marina_mercante/
      pack.yaml                     fuentes, palabras clave, prioridades de buzón, avisos
      questions.yaml                preguntas típicas del nicho → claves canónicas
      templates/es/*.txt  templates/en/*.txt
    doctorados_investigacion/
      …
  worker/
    app.py                          procrastinate
    tasks/ingest.py  crawl.py  send.py  simulate.py  followups.py
extension/
  manifest.json
  background.js                     service worker: cliente de la API, cola de la tanda
  popup/                            mínimo: conectar, filtros, "Iniciar búsqueda", progreso
  content/
    core/extract.js                 lee el formulario: etiqueta, tipo, opciones, obligatorio
    core/fill.js                    escribe valores, sube CV (DataTransfer), marca "revisar"
    core/overlay.js                 aviso visual mínimo de campos sin rellenar
  adapters/
    greenhouse.js  lever.js  ashby.js   (fase 1)
    linkedin.js                         (fase 8)
  tests/fixtures/*.html  tests/*.spec.js
tests/
  fixtures/ats/*.json  fixtures/adzuna/*.json  fixtures/infojobs/*.json
  fixtures/websites/<dominio>/*.html  fixtures/forms/*.json
  test_sources_*.py  test_cleaning.py  test_router.py  test_filling.py
  test_website_crawl.py  test_generic_emails.py  test_compose.py  test_api_*.py
docs/PLAN.md  docs/API.md
docker-compose.yml  pyproject.toml  alembic.ini  .env.example  README.md
legacy/                              panel actual, hasta completar la migración (opcional)
```

Cada **adaptador** de la extensión exporta lo mismo: `matches(url)`, `extract(document)`, `fill(document, plan)`, `detectSubmitted(document, url)`. Si un portal cambia su HTML, se toca un solo fichero.

---

## 4. Modelo de datos

### 4.1 Base común (compartida, independiente del modo)

```
companies          id, name, name_norm, domain (único), country, city, sector,
                   website, careers_url, wikidata_id, osm_ref,
                   flags jsonb (web_bloqueada, menciones, avisos…), sources jsonb,
                   created_at, updated_at
company_emails     id, company_id, email (único), local_part, kind (rrhh|empleo|info|comercial),
                   found_on_url, found_at, last_seen_at
                   ─ CHECK lógico en código: solo buzones genéricos; los personales nunca llegan aquí
crawls             domain (PK), fetched_at, status (ok|bloqueada|caida|robots), result jsonb
                   ─ la caché de 30 días de rastreos.db, ahora compartida entre usuarios
ats_boards         id, ats (greenhouse|lever|ashby|workday|…), slug, company_id,
                   status (activo|vacio|invalido), jobs_count, last_checked_at,
                   discovered_from (rastreo|adzuna|infojobs|extension|manual|adivinado)
                   UNIQUE(ats, slug)
jobs               id, company_id, source, source_job_id, title, title_norm,
                   city, country, remote, language, description_html,
                   apply_url, apply_platform (greenhouse|lever|…|linkedin|infojobs|email|otro),
                   posted_at, last_seen_at, closed_at, raw jsonb,
                   fingerprint (empresa + puesto + ciudad normalizados),
                   canonical_job_id (NULL si es la original; si no, apunta a ella)
                   UNIQUE(source, source_job_id)
job_questions      job_id, field_key_externo, label, type, required, options jsonb
                   ─ preguntas que dan las APIs (Greenhouse ?questions=true, InfoJobs /question)
source_runs        id, source, query jsonb, pack, ran_at, status, stats jsonb, calls_used
                   ─ controla cuotas (Adzuna) y evita repetir lecturas
```

### 4.2 Packs y diccionario

```
packs              (ficheros YAML en el repo; en BD solo un registro con slug y versión)
question_patterns  id, pack (NULL = global), canonical_key, language, pattern, weight,
                   origin (semilla|aprendido), approved
unknown_questions  id, label_norm, language, platform, pack, times_seen, first_seen, last_seen,
                   example_options jsonb, mapped_to (canonical_key, NULL hasta revisarla)
```

### 4.3 Datos de cada usuario

```
users              id, email, external_auth_id (si el login es de tu web), locale, created_at, deleted_at
api_tokens         id, user_id, name ("extensión", "web"), token_hash, scopes, last_used_at, expires_at
oauth_accounts     id, user_id, provider (google|infojobs), account_email, scopes,
                   access_token_enc, refresh_token_enc, expires_at
profiles           user_id (PK), pack, mode (simulacion|prueba|real), full_name, first_name, last_name,
                   email, phone, city, country, links jsonb, languages jsonb,
                   pack_data jsonb (p. ej. titulación, universidad), daily_limit, pause_seconds
documents          id, user_id, kind (cv|carta|certificado), language, label, storage_key,
                   mime, size, is_default
answers            id, user_id, canonical_key (años_experiencia, salario, permiso_trabajo,
                   disponibilidad, idioma.en…), language (NULL = vale para todos), value jsonb
custom_answers     id, user_id, label_norm, value      ← preguntas sin clave canónica que el usuario ya contestó
templates          id, user_id (NULL = la del pack), pack, kind (correo|carta|seguimiento),
                   audience (empresa|agencia|…), language, subject, body
searches           id, user_id, params jsonb (pack, países, ciudades, palabras, fuentes), status,
                   created_at, finished_at, stats jsonb
batches            id, user_id, search_id, size (~40), status (preparando|en_revision|cerrada), created_at
applications       id, user_id, mode, batch_id, job_id (NULL si es solo empresa), company_id,
                   route (ats_extension|portal_api|portal_copiloto|correo|manual), platform,
                   status (preparada|confirmada|enviada|respondida|entrevista|descartada|error),
                   language, document_ids, fields jsonb [ {key, label, value, origin
                   (perfil|banco|plantilla|defecto|usuario), confidence, needs_review} ],
                   missing jsonb, created_at, confirmed_at, sent_at, follow_up_at, notes
                   UNIQUE(user_id, mode, job_id) / UNIQUE(user_id, mode, company_id) WHERE job_id IS NULL
emails             id, application_id, to_addr, subject, body, attachments, message_id,
                   gmail_id, gmail_thread_id, status (en_cola|enviado|error), error, sent_at
replies            id, application_id, source (manual|reenvio|extension|simulada),
                   from_addr, subject, body, category (entrevista|info|rechazo|automatica|otra),
                   received_at, read
events             id, user_id, ts, level, message, data jsonb   ← el registro de actividad actual
```

Los **modos** dejan de ser tres ficheros: `applications`, `emails` y `replies` llevan columna `mode` y todas las consultas filtran por el modo actual del usuario. La base común no depende del modo (igual que hoy `rastreos.db`).

---

## 5. Cómo funciona cada pieza

### 5.1 Packs de nicho

`pack.yaml` (ejemplo resumido de `marina_mercante`):

```yaml
slug: marina_mercante
names: {es: Marina mercante (alumnos de puente), en: Merchant navy (deck cadets)}
profile_fields: [titulacion, titulacion_en, universidad]      # campos extra del perfil
sources:
  wikidata: [{label: Naviera, where: "?item wdt:P31 wd:Q1807108 ."}, …]
  directories: ["https://www.anave.es/…pdf | es", …]
  osm_tags: {office: [shipping_agent, company]}
  ats_queries: {keywords: [deck cadet, cadete, trainee officer]}
  adzuna: {what: "deck cadet", countries: [gb, nl, de, es]}
crawl:
  page_keywords: [cadet, crewing, crew, tripulacion, career, jobs, contact, impressum, …]
  mailbox_priority: [cadet, crewing, crew, manning, fleet, jobs, careers, rrhh, hr]
  commercial: [chartering, freight, booking, …]
  mentions: [{label: deck cadet, variants: [deck cadet]}, …]
  warnings: {cobro: […], ucrania: […], mar_negro: […]}
  exclude_names_regex: "\\b(associa\\w*|shipyard|…)\\b"
reply_keywords: {interview: [sign on, embarkation date, …], info: [libreta marítima, stcw, …]}
```

El núcleo lee el pack y nunca contiene listas de nicho. Segundo pack, `doctorados_investigacion`: Wikidata (universidades y centros de investigación con web), OSM (`amenity=university`, `office=research`), palabras de página de empleo (`phd`, `doctoral`, `vacancies`, `positions`, `promotion`, `doctorado`), buzones (`phd`, `doctoral`, `graduate`, `admissions`, `jobs`, `hr`) y preguntas típicas (propuesta de investigación, director, publicaciones).

### 5.2 Búsqueda: ingesta compartida, consulta por usuario

1. **Ingesta** (tareas en cola, compartidas): cada fuente produce `RawJob` / `RawCompany`.
   - **Greenhouse / Lever / Ashby**: por cada `ats_boards` activo, como mucho una lectura cada N horas. Sin clave.
   - **Catálogo de slugs** que crece solo: (a) enlaces a ATS que encuentra el rastreo de webs (ya detecta `greenhouse.io`, `lever.co`…), (b) `apply_url` de Adzuna/InfoJobs que resuelven a un ATS, (c) capturas de la extensión, (d) alta manual, (e) "adivinar" slug = nombre del dominio y probar las 3 APIs (un 404 es barato).
   - **Adzuna**: la cuota es por aplicación, no por usuario → consultas por (país, palabras del pack), cacheadas y repartidas en el mes; `source_runs` lleva la cuenta. Se muestra la atribución que exigen sus condiciones.
   - **InfoJobs**: búsqueda con credenciales de la app (cacheada); preguntas y candidatura con el OAuth del candidato.
   - **OSM + Wikidata + directorios**: empresas sin oferta; después, rastreo de su web → correo genérico.
2. **Limpieza** (`cleaning/`): normaliza dominio (raíz registrable), nombre de empresa (quita S.L., GmbH, Ltd…), puesto (quita "(m/f/d)", "(h/m)", espacios) y ciudad; calcula la **huella** `empresa|puesto|ciudad`. Si dos ofertas comparten huella, la **original** es la de mayor prioridad: ATS de la empresa > web de la empresa > InfoJobs > Adzuna > captura de portal. Las demás apuntan a ella (`canonical_job_id`).
3. **Consulta** (por usuario, instantánea): filtra la base común por pack, países, ciudades, palabras y fecha; excluye lo que el usuario ya tiene en el CRM; si una parte está "caducada" encola su ingesta y la búsqueda se completa al terminar.

### 5.3 Enrutador

Reglas en orden (cada resultado lleva `route`, `platform`, `reason`, `adapter_available`):

1. `apply_url` es de un ATS conocido (`boards.greenhouse.io`, `job-boards.greenhouse.io`, `jobs.lever.co`, `jobs.ashbyhq.com`, `*.myworkdayjobs.com`, …) → **`ats_extension`** (si el adaptador aún no existe → `manual` con el enlace).
2. Oferta de InfoJobs y el usuario tiene InfoJobs conectado → **`portal_api`**.
3. LinkedIn con Easy Apply → **`portal_copiloto`**; si LinkedIn redirige a un ATS → regla 1.
4. Indeed Apply → **`manual`** (nunca se toca). Indeed que redirige a un ATS → regla 1.
5. La oferta solo da un correo de candidatura y es genérico → **`correo`**.
6. Solo empresa, con correo genérico → **`correo`**; sin correo pero con página de empleo → **`manual`**.

### 5.4 Motor de relleno (sin IA)

- **Taxonomía** de claves canónicas: `first_name`, `last_name`, `full_name`, `email`, `phone`, `city`, `country`, `linkedin`, `website`, `resume`, `cover_letter`, `work_authorization`, `needs_sponsorship`, `years_experience`, `salary_expectation`, `notice_period`, `start_date`, `relocation`, `language.<iso>`, `how_did_you_hear`, `eeo.*` + las del pack.
- **Reconocimiento**: etiqueta normalizada (minúsculas, sin tildes) contra patrones por idioma con peso (`question_patterns`); gana el mayor peso por encima de un umbral; empates → "requiere revisión".
- **Opciones**: para `select`/`radio`, se mapea la respuesta a la opción con sinónimos ("Sí"/"Yes"/"Ja"; rangos numéricos "3-5 años").
- **Salida por campo**: `value`, `origin` (perfil|banco|plantilla|defecto), `confidence`, `needs_review`. Desconocidas → vacías, `needs_review=true`, y se registran en `unknown_questions` (para ampliar el banco del usuario y, tras revisión, el diccionario del pack).
- **EEO / datos sensibles** (género, etnia, discapacidad): nunca se deducen; solo si el usuario ha guardado esa respuesta explícitamente.
- Mismo motor para todo: la API lo usa con las preguntas de Greenhouse/InfoJobs y la extensión le manda el formulario extraído (`POST /extension/fill-plan`).

### 5.5 Revisión y envío

- `POST /batches` crea una tanda (~40) con las mejores candidaturas de una búsqueda.
- `GET /batches/{id}` → para cada candidatura: oferta, campos rellenos con su origen, faltantes, vista previa del correo.
- `PATCH /applications/{id}` corrige campos; `POST /applications/{id}/confirm` es **el clic**.
- Correo: `POST /batches/{id}/send` con la lista explícita de ids confirmados → el worker envía respetando límite diario, pausas y modo. Nunca se envía nada sin confirmar.
- Extensión: deja el formulario relleno; **el usuario pulsa Enviar en la web de la empresa**; el adaptador detecta la página de confirmación y avisa a la API (`enviada`). Si no la detecta, botón "Marcar como enviada".

### 5.6 Gmail OAuth

- Scopes: `openid email` + `https://www.googleapis.com/auth/gmail.send`.
- Envío por `users.messages.send` (endpoint de subida, adjuntos hasta ~35 MB en total). Se guardan `gmail_id` y `threadId`.
- Límites: tope duro de 500/día por cuenta de Google (configurable a 2.000 para Workspace), por defecto mucho menos (p. ej. 30/día) y pausa entre envíos; contador por cuenta de Google, no por usuario de knok.
- Prueba real: todo va al propio Gmail del usuario con `[PRUEBA → destino]`, como ahora.

### 5.7 Seguimiento

Estados `preparada → confirmada → enviada → respondida / entrevista / descartada`; `follow_up_at` automático (p. ej. +7 días tras enviar) con plantilla de seguimiento (también requiere clic); `GET /tracking/export.csv`.

---

## 6. Detectar respuestas (decisión pendiente)

`gmail.readonly`/`gmail.metadata`/`gmail.modify` son **restringidos** (auditoría CASA anual de pago). Alternativas:

| Opción | Cómo | Pros | Contras |
|---|---|---|---|
| **A. Marcado manual** | Botones en el CRM ("respondió", "entrevista", "rechazo") + pegar el texto de la respuesta para clasificarlo con las reglas actuales | Cero coste, cero permisos | Depende del usuario |
| **B. Reenvío a knok** | knok genera un **filtro de Gmail importable (XML)** con `from:(@dominio1 OR @dominio2 …)` que reenvía a `u-<id>@in.knok…`. Recepción con Cloudflare Email Routing + Worker (gratis) o un receptor SMTP propio. Se casa por `In-Reply-To` y dominio, como hoy | Automático, sin scope restringido, el usuario ve qué se reenvía | Gmail exige verificar la dirección de reenvío (knok recibe el código y se lo muestra); hay que regenerar el filtro cuando se contacta a empresas nuevas; los filtros tienen longitud limitada (varios filtros) |
| **C. Lectura en la extensión** | La extensión, cuando el usuario abre Gmail y pulsa "Revisar respuestas", lee la bandeja en su navegador y manda solo las coincidencias | Sin scope, trabajo en el navegador | Frágil (HTML de Gmail), requiere acción del usuario, revisión de la Chrome Web Store por leer correo |
| **D. Scope restringido** | `gmail.readonly` con auditoría | Lo más cómodo | Coste anual y meses de trámite |

**Recomendación**: A desde el principio (fase 7) + B como primera mejora; D solo si hay usuarios suficientes para pagarla.

---

## 7. Choques con principios o condiciones de plataformas (aviso antes de implementar)

1. **Capturas de LinkedIn / Indeed / Google para la base común.** Sus condiciones prohíben copiar y reutilizar su contenido, y en la UE las bases de datos tienen protección propia. Propuesta: la captura solo ocurre cuando el usuario pulsa "Guardar en knok" y a la base común solo van **hechos mínimos** (empresa, dominio, puesto, ciudad, enlace al ATS original); la descripción se queda en el CRM privado del usuario. La oferta "buena" se vuelve a leer del ATS de la empresa.
2. **LinkedIn**: su acuerdo de usuario prohíbe automatizar la cuenta, aunque haya clic del usuario. Propuesta: copiloto **de una en una** (el usuario abre la oferta, pulsa "Rellenar", revisa y envía); sin abrir 40 pestañas de LinkedIn seguidas. Aviso de riesgo antes de activarlo.
3. **"Borradores" en Gmail**: `gmail.compose` es restringido → los borradores viven en knok y se envían con `gmail.send`.
4. **Verificación de Google**: `gmail.send` es sensible: verificación gratuita pero exige política de privacidad, página de inicio en dominio verificado y vídeo de demostración. Mientras la app esté en modo "Testing": máximo 100 usuarios de prueba y los permisos caducan cada 7 días (el usuario tiene que volver a conectar).
5. **Adzuna**: exige atribución y enlazar con su `redirect_url`; la cuota de 1.000 llamadas/mes es para todo knok.
6. **InfoJobs**: la candidatura por API requiere app registrada y que te concedan los permisos de candidato; hay que comprobarlo antes de la fase 3.
7. **Nominatim / Overpass** (OSM): sus normas piden caché y prohíben uso intensivo; en multiusuario se cachea todo y, si crece, se usa una instancia propia o un proveedor gratuito alternativo.
8. **RGPD**: knok guardará CVs y datos personales de usuarios → política de privacidad, borrado de cuenta (`DELETE /me` borra todo), tokens cifrados, alojamiento en la UE recomendado.
9. **Correos personales**: en descripciones de ofertas a veces aparece "envía tu CV a maria.lopez@…". Propuesta: nunca a la base común; se puede usar solo dentro de esa candidatura del usuario (ver pregunta 6).

---

## 8. API (borrador de recursos)

```
POST   /auth/…                    (según tu web, ver pregunta 1)
GET/PUT /me  /me/profile  /me/settings (modo, límites)   DELETE /me
CRUD   /me/documents  /me/answers  /me/templates  /me/api-tokens
GET    /packs  /packs/{slug}
POST   /searches            GET /searches/{id}  /searches/{id}/results
GET    /jobs/{id}  /companies/{id}
POST   /batches             GET /batches/{id}    POST /batches/{id}/send
GET/PATCH /applications/{id}   POST /applications/{id}/confirm  /discard  /mark-sent
GET    /applications/{id}/preview   (correo exacto que se enviaría)
GET    /tracking  /tracking/export.csv     POST /applications/{id}/replies (marcado manual)
GET    /oauth/google/start  /oauth/google/callback   (igual para InfoJobs)
POST   /extension/captures  /extension/fill-plan  /extension/submitted
GET    /admin/unknown-questions   POST /admin/question-patterns
GET    /events                   (actividad, como el registro actual)
```

Autenticación por `Authorization: Bearer <token>`; CORS por lista blanca en `KNOK_CORS_ORIGINS`. La extensión obtiene su token desde tu web vía `externally_connectable` (sin copiar/pegar) o pegándolo en el popup.

---

## 9. Fases, entregables y tests

| # | Entrega | Tests |
|---|---|---|
| 1 | Esqueleto: FastAPI, Postgres, Alembic, cola, Docker Compose, `.env.example`, CI con pytest, `/health` | arranque, migraciones |
| 2 | Cuentas/tokens, perfil, documentos, banco de respuestas, plantillas, packs (`marina_mercante` migrado + `doctorados_investigacion`) | validación de packs, plantillas e idioma, API de perfil |
| 3 | Fuentes Greenhouse/Lever/Ashby/Adzuna/InfoJobs, catálogo de slugs, limpieza, enrutador | parsers con fixtures, huella y elección de original, todas las reglas del enrutador |
| 4 | OSM + Wikidata + directorios (genéricos), rastreo de webs, genérico vs personal, borradores, Gmail OAuth, modos | rastreo sobre HTML guardado, clasificador de buzones, composición, envío simulado, límites |
| 5 | Motor de relleno + API de revisión y tandas | etiquetas multilingües, opciones, faltantes, preguntas nuevas |
| 6 | Extensión: Greenhouse, Lever, Ashby | Playwright sobre HTML guardado: extraer, rellenar, no enviar |
| 7 | CRM, seguimientos, CSV, marcado manual de respuestas (+ reenvío si se aprueba) | transiciones de estado, CSV |
| 8 | Copiloto LinkedIn (una a una, con aviso) | fixtures |
| 9 | Fase 2 y 3 de plataformas | por adaptador |

Commits pequeños por fase; todo en Simulación y sin red en los tests.

---

## 10. Decisiones tomadas

El usuario delegó las decisiones técnicas ("haz lo que creas mejor"). Se decidió:

1. **Login**: la web es Next.js sin sistema de login definido → knok tiene sus propias cuentas (email +
   contraseña, tokens Bearer revocables; token aparte para la extensión). Si la web adopta un proveedor con JWT,
   se verifica en `knok/api/deps.py`.
2. **Alojamiento**: sin decidir → todo en Docker (API + worker + Postgres), desplegable en cualquier VPS/PaaS.
   CVs en disco (`KNOK_STORAGE_DIR`) detrás de una interfaz mínima para pasar a S3/R2.
3. **Cola**: propia sobre Postgres (`SELECT … FOR UPDATE SKIP LOCKED`), sin Redis.
4. **Respuestas**: A (marcado manual) + B (reenvío con filtro de Gmail importable). D (scope restringido) descartado por ahora.
5. **Repositorio**: knok vive aquí; el panel anterior está en `legacy/` y en la etiqueta `v1-panel-local`.
6. **Correos personales en ofertas**: se descartan siempre (ni base común ni candidatura).
7. **Envío**: el usuario selecciona las candidaturas y **aprueba una vez** (`POST /batches/{id}/send`).
8. **LinkedIn**: copiloto de una en una; nunca en tanda.
9. **Capturas**: a la base común solo hechos mínimos; la descripción queda en la candidatura del usuario.
10. **Extensión**: JavaScript sin paso de compilación. **Idiomas**: es y en (diccionario de preguntas también fr/de/it/pt).
11. **Límite por defecto**: 30 correos/día y 45 s de pausa, ajustable hasta el tope de Gmail.

## 11. Estado

| Fase | Estado |
|---|---|
| 1 Estructura, stack, modelo de datos | Hecho |
| 2 Cuentas, perfil, banco, packs (marina mercante + doctorados) | Hecho |
| 3 Greenhouse, Lever, Ashby, Adzuna, InfoJobs; limpieza; enrutador | Hecho (validar en vivo con claves) |
| 4 OSM + Wikidata + directorios, rastreo, Gmail OAuth, modos | Hecho |
| 5 Motor de relleno sin IA + revisión | Hecho |
| 6 Extensión Greenhouse/Lever/Ashby | Hecho |
| 7 Seguimiento y CSV | Hecho |
| 8 Copiloto LinkedIn | Hecho (una en una, con aviso) |
| 9 Fase 2 de plataformas | Beta genérica (Workable, SmartRecruiters, Recruitee, Teamtailor, Personio); Workday pendiente. Fase 3 pendiente |
