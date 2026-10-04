# knok · motor

El motor de knok **busca ofertas y empresas, decide cómo aplicar a cada una, rellena las solicitudes y prepara
los correos** para que el usuario los revise y los envíe. Es solo lógica + API REST: tu web (Next.js) se
conecta a esta API. Incluye una extensión de Chrome (modo copiloto) que habla con la misma API.

- Plan y decisiones: [docs/PLAN.md](docs/PLAN.md)
- Conectar tu web: [docs/INTEGRACION_WEB.md](docs/INTEGRACION_WEB.md)
- Extensión de Chrome: [extension/README.md](extension/README.md)
- El programa anterior (panel local de un usuario) sigue en [legacy/](legacy/) y en la etiqueta `v1-panel-local`.

## Principios (y dónde se cumplen)

| Principio | Cómo |
|---|---|
| Sin IA | Reglas fijas: palabras clave por idioma, patrones y puntuaciones explicables. El punto de extensión "sugerir respuesta" existe pero está desactivado (`/replies/{id}/suggestion` → 501). |
| Coste casi cero | Postgres como base de datos **y** como cola (sin Redis); APIs gratuitas; cachés compartidas entre usuarios; el relleno de formularios ocurre en el navegador del usuario. |
| No scrapear Google desde el servidor | El servidor solo lee APIs públicas, Wikidata, OpenStreetMap, directorios y las webs de las empresas (respetando `robots.txt`, sin fingir ser un navegador). |
| Nada sale sin un clic | Las candidaturas se **preparan**; solo `POST /batches/{id}/send` o `POST /applications/{id}/send` con la lista que elige el usuario las envía. La extensión nunca pulsa "Enviar". |
| Base común solo con buzones genéricos | Lista blanca de roles (info@, rrhh@, jobs@… + los del pack). Un buzón personal (nombre.apellido@) se descarta antes de guardarse y no se puede usar ni a mano. |
| Global | Plantillas y textos por idioma (es, en), idioma elegido por país; diccionario de preguntas en es/en/fr/de/it/pt. |
| Multi-nicho | El núcleo no sabe de ningún nicho (un test lo comprueba). Lo específico está en `knok/packs/<nicho>/`. |

## Arrancar en local

### La forma fácil (sin Docker)

1. Ten instalado **Python 3.11 o más reciente** (al instalarlo en Windows, marca «Add python.exe to PATH»).
2. Doble clic en **`iniciar-sin-docker.bat`** (Windows) o ejecuta `./iniciar-sin-docker.sh` (Mac/Linux).
   La primera vez prepara todo (unos minutos).
3. Se abre <http://localhost:8000/playground>. Arranca en **modo de prueba sin red** (datos de ejemplo, no sale
   ningún correo). Para pararlo, cierra la ventana.

Usa una base de datos en un archivo (`knok.db`, SQLite) y el worker va dentro de la API: un solo proceso,
ideal para tu ordenador. Para un servidor con varios usuarios, usa Docker con Postgres.

### Con Docker

Instala y abre **Docker Desktop** (necesita la virtualización activada en la BIOS) y haz doble clic en
**`iniciar.bat`** (o `./iniciar.sh`). Para pararlo: `detener.bat` o `docker compose down`.

### Opción A · Docker (todo incluido)

```bash
cp .env.example .env          # y ajusta lo que quieras
docker compose up --build     # Postgres + API (aplica migraciones) + worker
```

API en <http://localhost:8000> · documentación interactiva en <http://localhost:8000/docs> ·
banco de pruebas mínimo en <http://localhost:8000/playground>.

### Opción B · Python directamente

Requisitos: Python 3.11+ y un Postgres 16.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"                  # incluye el conector de Postgres
cp .env.example .env                     # pon tu KNOK_DATABASE_URL
alembic upgrade head                     # crea las tablas
uvicorn knok.api.main:app --reload       # API
python -m knok.worker                    # en otra terminal: worker (búsquedas, rastreos, envíos)
```

**Para probar sin red ni claves**: `KNOK_OFFLINE_SOURCES=true`. Las búsquedas usan los datos de ejemplo de
cada pack (empresas ficticias con dominios `@example.*`, que nunca reciben correo) y el modo Simulación
no envía nada.

## Variables de entorno

Todas en [.env.example](.env.example) con explicación. Las importantes:

| Variable | Para qué |
|---|---|
| `KNOK_DATABASE_URL` | Postgres (`postgresql+psycopg://usuario:clave@host:5432/knok`) |
| `KNOK_SECRET_KEY` | Cifra los tokens OAuth guardados. **Obligatorio cambiarla en producción** |
| `KNOK_CORS_ORIGINS` | Dominios de tu web que pueden llamar a la API |
| `KNOK_PUBLIC_BASE_URL`, `KNOK_WEB_BASE_URL` | URL pública de la API (callbacks OAuth) y de tu web (vuelta tras conectar) |
| `KNOK_GOOGLE_CLIENT_ID` / `_SECRET` | Gmail OAuth (solo envío). Redirección: `{API}/connections/google/callback` |
| `KNOK_ADZUNA_APP_ID` / `_KEY` | Adzuna (plan gratis, ~1.000 llamadas/mes para todo knok) |
| `KNOK_INFOJOBS_CLIENT_ID` / `_SECRET` | InfoJobs (búsqueda y candidatura por API) |
| `KNOK_INBOUND_SECRET`, `KNOK_INBOUND_DOMAIN` | Reenvío de respuestas a knok (opcional) |
| `KNOK_OFFLINE_SOURCES` | `true` = datos de ejemplo, sin red |

### Gmail (OAuth, solo envío)

1. En Google Cloud Console crea un proyecto, activa la **Gmail API** y una **pantalla de consentimiento OAuth**
   con el scope `https://www.googleapis.com/auth/gmail.send` (más `openid` y `email`).
2. Crea un **ID de cliente OAuth de tipo "Aplicación web"** con la redirección `{KNOK_PUBLIC_BASE_URL}/connections/google/callback`.
3. Mientras la app esté en modo *Testing* solo pueden usarla los usuarios de prueba que añadas (máx. 100) y
   el permiso caduca a los 7 días. Para abrirla a todos, Google pide verificación (gratuita para `gmail.send`):
   política de privacidad, página de inicio en dominio verificado y vídeo de demostración.
4. knok **no** pide permisos de lectura de Gmail (exigirían una auditoría anual de pago).

## Cómo funciona (resumen de la API)

```
POST /auth/register | /auth/login            → token (Bearer)
PATCH /me/profile · POST /me/documents · PUT /me/answers/{clave} · PUT /me/templates/…
GET  /connections/google/start               → URL de Google (conectar Gmail)
POST /searches                               → búsqueda en cola (ingesta compartida + puntuación + vía)
GET  /searches/{id}/results                  → ofertas y empresas con su vía y motivos
POST /batches {search_id}                    → tanda de ~40 candidaturas preparadas y rellenas
GET  /batches/{id}                           → revisión: lo rellenado, lo deducido, lo que falta, bloqueos
PATCH /applications/{id}                     → correcciones (lo nuevo se recuerda en tu banco)
POST /batches/{id}/send {application_ids}    → EL CLIC: se envían solo las seleccionadas
GET  /tracking · /tracking/summary · /tracking/export.csv · POST /applications/{id}/replies
```

La referencia completa, con ejemplos y esquemas, está en `/docs` (OpenAPI en `/openapi.json`).

### Vías (enrutador)

| Vía | Cuándo | Qué pasa al pulsar enviar |
|---|---|---|
| `ats_extension` | La solicitud es el formulario de la empresa (Greenhouse, Lever, Ashby…) | Queda lista; la extensión rellena el formulario y **tú** pulsas Enviar |
| `portal_api` | Oferta de InfoJobs y tienes InfoJobs conectado | Se envía por la API oficial (en Simulación, simulado) |
| `portal_copilot` | Solo se puede aplicar dentro del portal (LinkedIn Easy Apply) | Copiloto de una en una en la extensión (con aviso de riesgo) |
| `email` | Sin formulario: buzón genérico de la empresa | Correo por Gmail, con límites y pausas |
| `manual` | Indeed Apply, plataformas sin adaptador, sin contacto | Se abre el enlace; lo marcas como enviada |

### Modos

| Modo | ¿Sale algo? | Para qué |
|---|---|---|
| `simulation` | No. Los correos se guardan como `.eml` y llegan respuestas simuladas | Probar |
| `test` | Sí, **solo a tu propio email**, con el asunto `[PRUEBA → empresa@…]` | Comprobar Gmail |
| `live` | Sí, a las empresas, con límite diario y pausa entre correos | Uso real |

Límites: el diario del usuario (30 por defecto, como mucho el tope de Gmail: 500/día en cuentas personales) y,
además, por cuenta de Google. Si se alcanza, el correo se aplaza a mañana, no se pierde.

### Detectar respuestas (sin leer Gmail)

- **Marcado manual**: `POST /applications/{id}/replies` (con el texto pegado se clasifica: entrevista, piden
  info, rechazo, automática u otra).
- **Reenvío a knok**: `GET /me/reply-forwarding` da una dirección `u-<token>@{KNOK_INBOUND_DOMAIN}` y
  `GET /me/reply-forwarding/filters.xml` un filtro de Gmail para importar que reenvía los correos de las
  empresas contactadas. Un receptor de correo (por ejemplo Cloudflare Email Routing + un Worker, gratis)
  envía el correo en bruto a `POST /inbound/email` con la cabecera `X-Knok-Inbound-Secret`.

## Packs de nicho

`knok/packs/<slug>/pack.yaml` + `questions.yaml` + `templates/<idioma>/<tipo>_<audiencia>.txt` + `sample.json`.
Incluidos: `general`, `marina_mercante` (migrado del programa anterior) y `doctorados_investigacion`.
Para crear uno, copia uno existente; el esquema está documentado en `knok/packs/schema.py` y los tests
validan que cargue.

## Tests

```bash
pytest                                                                             # SQLite en memoria, sin red
KNOK_TEST_DATABASE_URL=postgresql+psycopg://postgres@localhost:5432/knok_test pytest   # contra Postgres
cd extension && npm install && npm test                                           # extensión (Node + Chromium)
```

Cubren fuentes (con respuestas de ejemplo de cada API), limpieza, enrutador, relleno, rastreo de webs, envío
en los tres modos, revisión, extensión y seguimiento. CI en `.github/workflows/ci.yml`.

## Estructura

```
knok/
  api/            FastAPI: routers, dependencias, banco de pruebas (/playground)
  core/           lógica pura: fuentes, rastreo, limpieza, enrutador, relleno, correo, i18n
  services/       orquestación con la base de datos (búsqueda, candidaturas, envío, seguimiento…)
  packs/          packs de nicho (YAML + plantillas + datos de ejemplo)
  db/             modelos y migraciones (Alembic)
  worker/         cola de tareas sobre Postgres y worker
extension/        extensión de Chrome (Manifest V3)
tests/            tests de Python con datos de ejemplo
legacy/           programa anterior
```

## Pendiente o por validar

- **Validar las APIs en vivo**: Greenhouse, Lever, Ashby, Adzuna e InfoJobs están implementadas según su
  formato documentado y probadas con respuestas de ejemplo; el entorno donde se construyó no tenía acceso a
  esas webs. Conviene una primera prueba real con claves.
- **InfoJobs**: la candidatura por API requiere que InfoJobs conceda a tu app los permisos de candidato; las
  versiones de los endpoints están en `knok/core/sources/infojobs.py`.
- **Workday** y las plataformas de fase 3 (Computrabajo, Seek, Naukri, HelloWork, OCC, StepStone) aún no
  tienen adaptador; las de fase 2 funcionan en beta con la extracción genérica.
- **Login de tu web**: knok tiene sus propias cuentas. Si tu web adopta un proveedor (Supabase, Clerk,
  Auth.js…), se puede verificar su token en `knok/api/deps.py` sin cambiar el resto.
