# Busca Prácticas

Panel local para buscar empresas y agencias de empleo, enviarles tu candidatura de prácticas por correo y ver sus respuestas en un solo sitio.

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

## Los tres modos

Se eligen en **Configuración**. Cada modo guarda sus datos en su propio fichero (`datos/simulacion.db`, `datos/prueba.db`, `datos/real.db`), así que las pruebas nunca se mezclan con los envíos reales.

| Modo | ¿Sale algún correo? | Para qué sirve |
|---|---|---|
| **Simulación** | No | Probar el panel. Los correos se guardan como `.eml` en `datos/bandeja_salida_simulacion/` y las respuestas se generan solas al cabo de unos segundos. |
| **Prueba real** | Sí, pero **solo a tu propio email** | Comprobar que Gmail funciona. Cada correo te llega a ti con el asunto `[PRUEBA → empresa@...]`. Contéstalo como si fueras la empresa y la respuesta aparecerá en el panel. |
| **Real** | Sí, a las empresas | Buscar prácticas de verdad. Tiene límite diario y una pausa entre correos. |

Orden recomendado: **Simulación → Prueba real → Real**.

## Fuentes de búsqueda

- **Datos de ejemplo**: 22 empresas y agencias ficticias con correos `@example.com`/`.org`/`.net`. Son dominios reservados y ningún correo llega nunca a ellos.
- **OpenStreetMap**: empresas y agencias de empleo reales alrededor de tu ciudad. Es gratis y no necesita clave. Muchas no publican su email; aparecen como «Sin email» y puedes añadírselo a mano en la pestaña **Empresas** (búscalo en su web). También puedes añadir empresas enteras con **+ Añadir a mano**.

## Conectar Gmail (para los modos prueba y real)

Al abrir el panel aparece la ventana **Conecta tu Gmail**. También puedes abrirla desde el botón de arriba a la derecha o desde **Configuración → Cuenta de correo**.

1. Activa la verificación en dos pasos en tu cuenta de Google.
2. Crea una contraseña de aplicación en <https://myaccount.google.com/apppasswords>.
3. Escribe tu Gmail y pega las 16 letras. El panel comprueba que puede enviar (SMTP) y leer (IMAP) antes de guardarla.

La contraseña se guarda solo en `secretos.json`, que está en `.gitignore` y nunca se sube a GitHub. Puedes revocarla cuando quieras desde tu cuenta de Google.

Pon tu CV en `datos/cv.pdf` (o cambia la ruta en **Tu perfil**). El programa solo **lee** la bandeja de entrada y no marca nada como leído.

## Editar el mensaje

En **Configuración → Tu mensaje** hay una versión para empresas y otra para agencias. Los botones «Insertar» añaden variables como `{empresa}` o `{nombre}`, y a la derecha ves en directo cómo quedará el correo. Si un dato de tu perfil está vacío, la vista previa lo marca en amarillo.

## Cómo se detectan las respuestas

Un correo entrante cuenta como respuesta si:

1. contesta directamente a uno de tus envíos (cabeceras `In-Reply-To`/`References`), o
2. viene de la dirección de una empresa contactada, o de su mismo dominio (sin contar Gmail, Hotmail y similares).

Después se clasifica por palabras clave como **Entrevista**, **Piden info**, **Rechazo**, **Automática** u **Otra**. Si la clasificación falla, puedes corregirla desde la respuesta.

## Ficheros

```
app.py                 servidor web y API
core/busqueda.py       búsqueda (ejemplo y OpenStreetMap)
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
