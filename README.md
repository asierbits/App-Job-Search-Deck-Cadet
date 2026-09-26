# Busca Prácticas

Panel local para encontrar **embarque como alumno de puente**. Busca navieras de toda Europa, rastrea sus webs para encontrar el mejor contacto (tripulación, cadetes, empleo), les envía tu solicitud por correo y reúne sus respuestas en un solo sitio.

## Instalar en tu ordenador

1. **Instala Python** (gratis) desde <https://www.python.org/downloads/>. En Windows, marca la casilla **«Add python.exe to PATH»** al instalarlo. No hace falta instalar nada más.
2. **Descomprime** el ZIP de Busca Prácticas donde quieras, por ejemplo en el Escritorio.
3. **Abre** `iniciar.bat` con doble clic (en Windows). En Mac o Linux, abre una terminal en la carpeta y ejecuta `python3 app.py`.
4. Se abre el panel en el navegador. Deja abierta la ventana negra mientras lo uses; para cerrarlo, ciérrala.
5. Empieza en modo **Simulación** para ver cómo funciona, rellena **Configuración → Tu perfil** y conecta **tu propio Gmail** cuando quieras hacer pruebas reales (más abajo se explica cómo).

Cada persona tiene su propia configuración, su cuenta y sus datos: nada de eso va dentro del ZIP.

## Arrancar

```
python app.py
```

o doble clic en `iniciar.bat`. Se abre el panel en <http://127.0.0.1:8765>, que solo es accesible desde tu PC. Si ya estaba abierto, no se arranca un segundo panel: se abre el que ya existe. Así nunca se envía el mismo correo dos veces.

## Cómo se usa: dos pasos

1. **«1 · Buscar navieras»** (en el Panel): reúne las navieras y rastrea sus webs. **No envía nada.** Se abre la pestaña **Navieras**, donde ves en directo qué webs se están rastreando, las últimas rastreadas con lo que se encontró en cada una (email, ⚓ cadetes, portal de empleo, web que bloquea) y el estado de cada naviera en la tabla. Puedes pararlo con **Detener** y seguir otro día con **«Seguir rastreando»**.
2. **Revisar y enviar** (pestaña **Navieras**): marca con la casilla a quién quieres escribir, o pulsa **«Seleccionar recomendadas»** (las que tienen un buzón de tripulación o de empleo, o cuya web habla de cadetes). Con **«Ver»** abres la ficha de cada naviera: su web, su página de empleo, de dónde salió el email y **el correo exacto que recibiría**. Después pulsa **«Enviar»**: solo se escribe a las seleccionadas, respetando el límite por envío y el diario. Las que no quepan hoy quedan seleccionadas para la próxima vez.

## Los tres modos

Se eligen en **Configuración**. Cada modo guarda sus datos en su propio fichero (`datos/simulacion.db`, `datos/prueba.db`, `datos/real.db`), así que las pruebas nunca se mezclan con los envíos reales.

| Modo | ¿Sale algún correo? | Para qué sirve |
|---|---|---|
| **Simulación** | No | Probar el panel. Los correos se guardan como `.eml` en `datos/bandeja_salida_simulacion/` y las respuestas se generan solas al cabo de unos segundos. |
| **Prueba real** | Sí, pero **solo a tu propio email** | Comprobar que Gmail funciona. Cada correo te llega a ti con el asunto `[PRUEBA → empresa@...]`. Contéstalo como si fueras la empresa y la respuesta aparecerá en el panel. |
| **Real** | Sí, a las empresas | Buscar prácticas de verdad. Tiene límite diario y una pausa entre correos. |

Orden recomendado: **Simulación → Prueba real → Real**.

## Fuentes de búsqueda

- **Navieras europeas** (la opción por defecto). Junta:
  - **Wikidata**: unas 300 navieras, navieras de ferris y de cruceros de países europeos, con su web.
  - **Directorios de asociaciones de navieros**: ANAVE (España, un PDF con webs y emails), VDR (Alemania), Rederi (Noruega), Armateurs de France e Interferry (ferris; se quedan solo las europeas). Se siguen las páginas de las listas paginadas. Puedes añadir más directorios en **Configuración → Búsqueda**, una dirección por línea (web o PDF), y opcionalmente `| es` para indicar el país.

  Se descartan automáticamente las que no son navieras: asociaciones, sindicatos, sociedades de clasificación, astilleros, proveedores y consultoras. En total salen unas 600 navieras.
- **OpenStreetMap**: oficinas alrededor de una lista de ciudades de cualquier país.
- **Datos de ejemplo**: navieras ficticias con correos `@example.com`/`.org`/`.net`, para probar. Son dominios reservados y ningún correo llega nunca a ellos.

## Rastreo a fondo de cada web

Con «Rastrear a fondo la web de cada empresa» activado, el programa visita hasta 8 páginas de cada naviera, priorizando las de tripulación, cadetes, empleo, contacto y aviso legal. De ahí saca:

- **El mejor email** para una candidatura, por este orden de preferencia: `cadets@`, `crewing@`, `crew@`, `flota@`, `jobs@`, `rrhh@`, y si no hay ninguno, `info@`. Los buzones comerciales (ventas, fletes, reservas) quedan en último lugar, y nunca se usan los de otra empresa (por ejemplo, el de la agencia que hizo la web). También entiende emails ofuscados («info [at] empresa [dot] de») y protegidos por Cloudflare.
- **Su página de empleo o de tripulación**, por si solo aceptan candidaturas mediante formulario. Filtra la tabla por «Sin email, con portal de empleo» para ver dónde registrarte a mano.
- **Si su web menciona cadetes o alumnos** (⚓). A esas se les escribe primero.

Se rastrean 6 webs a la vez (cada una es de un servidor distinto), con un máximo de 45 segundos por web. Unas 600 webs tardan entre 15 y 20 minutos.

**Límites que se respetan:** el `robots.txt` de cada web, y las webs que bloquean la lectura automática. A estas no se las engaña haciéndose pasar por un navegador: se marcan como «web bloquea» para que las mires tú. No se entra en LinkedIn ni en webs que exigen cuenta.

A las navieras de España se les escribe en español; a las demás (y a las de país desconocido), en inglés.

## Conectar Gmail (para los modos prueba y real)

Al abrir el panel aparece la ventana **Conecta tu Gmail**. También puedes abrirla desde el botón de arriba a la derecha o desde **Configuración → Cuenta de correo**.

1. Activa la verificación en dos pasos en tu cuenta de Google.
2. Crea una contraseña de aplicación en <https://myaccount.google.com/apppasswords>.
3. Escribe tu Gmail y pega las 16 letras. El panel comprueba que puede enviar (SMTP) y leer (IMAP) antes de guardarla.

La contraseña se guarda solo en `secretos.json`, que está en `.gitignore` y nunca se sube a GitHub. Puedes revocarla cuando quieras desde tu cuenta de Google.

Pon tu CV en `datos/cv.pdf` (o cambia la ruta en **Tu perfil**). El programa solo **lee** la bandeja de entrada y no marca nada como leído.

## Editar el mensaje

En **Configuración → Tu mensaje** hay cuatro versiones: español e inglés, cada una para navieras y para agencias. Los textos por defecto son una solicitud de embarque como alumno de puente (en inglés, *Deck Cadet*); «Restaurar el mensaje original» los recupera si los has cambiado. Los botones «Insertar» añaden variables como `{empresa}` o `{nombre}`, y a la derecha ves en directo cómo quedará el correo. Si un dato de tu perfil está vacío, la vista previa lo marca en amarillo.

## Cómo se detectan las respuestas

Un correo entrante cuenta como respuesta si:

1. contesta directamente a uno de tus envíos (cabeceras `In-Reply-To`/`References`), o
2. viene de la dirección de una empresa contactada, o de su mismo dominio (sin contar Gmail, Hotmail y similares).

Después se clasifica por palabras clave como **Entrevista**, **Piden info**, **Rechazo**, **Automática** u **Otra**. Si la clasificación falla, puedes corregirla desde la respuesta.

## Ficheros

```
app.py                 servidor web y API
core/busqueda.py       búsqueda (reparte entre las fuentes; OpenStreetMap y ejemplo)
core/maritimo.py       navieras europeas: Wikidata y directorios de asociaciones (web y PDF)
core/webemail.py       rastreo a fondo de la web de cada empresa
core/correo.py         composición, envío SMTP, lectura IMAP y clasificación
core/simulador.py      respuestas simuladas
core/motor.py          proceso en segundo plano (buscar → enviar → revisar respuestas)
static/                panel (HTML, CSS y JS)
datos/                 bases de datos, CV y datos de ejemplo
config.json            tu configuración (se crea al arrancar; no se sube a GitHub)
secretos.json          contraseña del correo (no se sube a GitHub)
```

## Buenas prácticas

- Envía pocos correos al día (el límite por defecto es 20) y personaliza las plantillas.
- Escribe solo a direcciones que las empresas publiquen para contacto o empleo (RRHH, empleo, info).
- Si una empresa te pide que no la contactes más, márcala como **Descartada**.
