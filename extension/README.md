# Extensión de Chrome · knok copiloto (Manifest V3)

Rellena solicitudes de empleo con tus datos de knok. **Nunca envía nada**: el botón *Enviar* de cada web lo
pulsas tú. Solo actúa cuando pulsas un botón del popup; no hay nada corriendo en segundo plano.

## Instalar (modo desarrollador)

1. Arranca la API de knok (por defecto en `http://localhost:8000`).
2. En Chrome: `chrome://extensions` → activa **Modo desarrollador** → **Cargar descomprimida** → elige esta carpeta `extension/`.
3. Crea un token para la extensión: `POST /auth/tokens` con `{"name": "extensión"}` (o desde tu web).
4. Abre el popup de knok, pega la URL de la API y el token, y pulsa **Conectar**.

> Si la API no está en `localhost:8000`, la extensión te pedirá permiso para esa dirección al conectar.
> Para que **tu web** pase el token sin copiar y pegar, cambia `externally_connectable.matches` en
> `manifest.json` por el dominio de tu web y llama desde ella a
> `chrome.runtime.sendMessage(EXTENSION_ID, {type: "knok:token", token, apiBase})`.

## Qué hace

- **Iniciar búsqueda**: lanza una búsqueda con tus filtros, prepara una tanda (~40) de ofertas cuyo formulario
  es de Greenhouse, Lever o Ashby, y las abre una a una en pestañas (con pausas de 8–20 s), rellenas y
  **sin enviar**. Revisa cada pestaña y pulsa *Enviar* tú; knok lo anota en el seguimiento.
- **Rellenar esta página**: rellena el formulario de la pestaña actual (incluido el paso visible de
  LinkedIn Easy Apply, **de una en una**).
- **Guardar oferta en knok**: guarda la oferta que estás viendo (LinkedIn, Indeed, Google…). A la base común
  solo van empresa, puesto, ubicación y enlace de solicitud; la descripción queda en tu candidatura.
- Los campos que requieren revisión se marcan en naranja. Los consentimientos y los datos sensibles nunca se
  marcan solos. Si hay un CAPTCHA, lo resuelves tú.

## Plataformas

| Plataforma | Estado |
|---|---|
| Greenhouse, Lever, Ashby | Fase 1: relleno completo |
| LinkedIn Easy Apply | Copiloto de una en una (⚠ sus condiciones prohíben automatizar la cuenta: hay riesgo) |
| Workable, SmartRecruiters, Recruitee, Teamtailor, Personio | Fase 2 (beta): extracción genérica |
| Workday | Pendiente (cuenta por empresa y formulario por pasos) |
| Indeed | Solo guardar la oferta. **Indeed Apply nunca se rellena** (lo prohíben sus condiciones) |

Cada plataforma es un fichero en `src/content/adapters/`: si una web cambia su HTML, se toca solo ese fichero.

## Tests

```
npm install
npm test        # lógica de tandas (node --test) + copiloto en Chromium con páginas de ejemplo (Playwright)
```
