# Conectar tu web (Next.js) con el motor de knok

Tu web (Next.js con `src/`, App Router) solo tiene que hablar con la API REST del motor. Recomendación:
**tu servidor de Next hace de intermediario** y guarda el token de knok en una cookie `httpOnly`. Así el token
nunca está en el JavaScript del navegador y no necesitas CORS (aunque también está configurado por si llamas
a la API directamente desde el cliente).

```
Navegador ──► Next.js (tus páginas y route handlers) ──► API de knok (Bearer token) ──► Postgres + worker
```

## 1. Variables en tu web

`.env.local` de Next:

```
KNOK_API_URL=http://localhost:8000
```

Y en el motor, `KNOK_CORS_ORIGINS` y `KNOK_WEB_BASE_URL` con la URL de tu web (para volver tras conectar Gmail).

## 2. Tipos generados desde OpenAPI (opcional, recomendado)

```bash
npm i openapi-fetch && npm i -D openapi-typescript
npx openapi-typescript http://localhost:8000/openapi.json -o src/lib/knok-api.d.ts
```

Repite el segundo comando cuando cambie la API.

## 3. Cliente de servidor

`src/lib/knok.ts`:

```ts
import "server-only";
import { cookies } from "next/headers";

const API = process.env.KNOK_API_URL!;
export const TOKEN_COOKIE = "knok_token";

export class KnokError extends Error {
  constructor(public status: number, public code: string, message: string) { super(message); }
}

/** Llama a la API de knok con el token del usuario (cookie httpOnly). */
export async function knok<T = unknown>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const token = (await cookies()).get(TOKEN_COOKIE)?.value;
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  let body = init.body;
  if (init.json !== undefined) { headers.set("Content-Type", "application/json"); body = JSON.stringify(init.json); }
  const r = await fetch(API + path, { ...init, headers, body, cache: "no-store" });
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    const d = err.detail ?? {};
    throw new KnokError(r.status, d.code ?? "error", d.message ?? JSON.stringify(d));
  }
  return (r.status === 204 ? null : r.headers.get("content-type")?.includes("json") ? r.json() : r.text()) as T;
}
```

Los errores de la API tienen siempre la forma `{"detail": {"code": "...", "message": "..."}}`: usa `code`
para traducir mensajes en tu web.

## 4. Login y registro (route handlers)

`src/app/api/auth/[action]/route.ts`:

```ts
import { NextResponse } from "next/server";
import { TOKEN_COOKIE } from "@/lib/knok";

export async function POST(req: Request, { params }: { params: Promise<{ action: string }> }) {
  const { action } = await params;
  if (!["login", "register"].includes(action)) return NextResponse.json({}, { status: 404 });
  const r = await fetch(`${process.env.KNOK_API_URL}/auth/${action}`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: await req.text(),
  });
  const data = await r.json();
  if (!r.ok) return NextResponse.json(data, { status: r.status });
  const res = NextResponse.json({ ok: true, userId: data.user_id });
  res.cookies.set(TOKEN_COOKIE, data.token, {
    httpOnly: true, secure: process.env.NODE_ENV === "production", sameSite: "lax", path: "/",
    maxAge: 60 * 60 * 24 * 30,
  });
  return res;
}
```

Cerrar sesión: llama a `POST /auth/logout` con el token y borra la cookie.

## 5. Usar la API desde páginas y acciones

```tsx
// src/app/panel/page.tsx (Server Component)
import { knok } from "@/lib/knok";

export default async function Panel() {
  const me = await knok<any>("/me");
  const resumen = await knok<any>("/tracking/summary");
  return (
    <main>
      <h1>Hola, {me.profile.first_name}</h1>
      {me.sending_problems.map((p: any) => <p key={p.code}>{p.message}</p>)}
      <p>Enviadas: {resumen.by_status.sent ?? 0} · Respuestas: {Object.values(resumen.replies_by_category).reduce((a: any, b: any) => a + b, 0) as number}</p>
    </main>
  );
}
```

```ts
// src/app/busqueda/actions.ts (Server Actions)
"use server";
import { knok } from "@/lib/knok";

export async function lanzarBusqueda(filtros: { countries: string[]; cities: string[]; keywords: string[] }) {
  return knok<{ id: number; status: string }>("/searches", { method: "POST", json: filtros });
}
export async function estadoBusqueda(id: number) { return knok<any>(`/searches/${id}`); }
export async function prepararTanda(searchId: number) {
  return knok<any>("/batches", { method: "POST", json: { search_id: searchId, size: 40 } });
}
/** EL CLIC: solo las candidaturas que el usuario ha marcado. */
export async function enviarSeleccionadas(batchId: number, ids: number[]) {
  return knok<any>(`/batches/${batchId}/send`, { method: "POST", json: { application_ids: ids } });
}
```

La búsqueda corre en el worker: consulta `GET /searches/{id}` cada 1–2 s hasta `status: "done"` (o usa
`router.refresh()` en un intervalo).

## 6. Pantallas que tu web necesita (y su endpoint)

| Pantalla | Endpoints |
|---|---|
| Onboarding: elegir nicho | `GET /packs`, `GET /packs/{slug}` (campos de perfil y banco de respuestas del nicho), `PATCH /me/profile` |
| Perfil y CV | `GET /me`, `PATCH /me/profile`, `POST /me/documents` (multipart: `file`, `kind`, `language`) |
| Banco de respuestas | `GET /me/answers`, `PUT /me/answers/{clave}`, `GET/PUT /me/custom-answers` |
| Plantillas | `GET /me/templates`, `PUT /me/templates/{tipo}/{audiencia}/{idioma}`, `POST /me/templates/preview` |
| Conectar Gmail | `GET /connections/google/start?return_to=<url de tu web>` → redirige a `url` (ver abajo) |
| Buscar | `POST /searches`, `GET /searches/{id}`, `GET /searches/{id}/results` |
| Revisar tanda | `POST /batches`, `GET /batches/{id}`, `PATCH /applications/{id}`, `POST /batches/{id}/send` |
| Seguimiento | `GET /tracking`, `GET /tracking/summary`, `POST /applications/{id}/replies`, `POST /applications/{id}/status`, `GET /tracking/export.csv` |
| Respuestas | `GET /replies`, `PATCH /replies/{id}`, `GET /me/reply-forwarding` |
| Actividad | `GET /events` |
| Cuenta | `GET /me/export` (RGPD), `POST /me/delete` |

Cada candidatura en revisión trae: `fields` (cada campo con `value`, `origin`, `confidence`, `needs_review`,
`reason`), `deduced`, `needs_review`, `missing`, `warnings` y `blocking` (motivos por los que aún no se puede
enviar). Pinta en naranja `needs_review` y desactiva la casilla de las que tienen `blocking`.

## 7. Conectar Gmail desde tu web

```ts
// Server Action
export async function urlConectarGmail() {
  const { url } = await knok<{ url: string }>(
    `/connections/google/start?return_to=${encodeURIComponent(process.env.NEXT_PUBLIC_SITE_URL + "/ajustes")}`);
  return url;   // en el cliente: window.location.href = url
}
```

Al terminar, Google vuelve a la API y la API redirige a `/ajustes?connected=google` (o `?error=…`).
`return_to` solo se acepta si empieza por un origen de `KNOK_CORS_ORIGINS` o `KNOK_WEB_BASE_URL`.

## 8. Pasar el token a la extensión (sin copiar y pegar)

1. En `extension/manifest.json`, pon el dominio de tu web en `externally_connectable.matches`.
2. En tu web, crea un token aparte para la extensión y envíaselo:

```ts
// Server Action: token propio de la extensión (revocable sin cerrar la sesión web)
export async function tokenExtension() {
  return knok<{ token: string }>("/auth/tokens", { method: "POST", json: { name: "extensión", days: 365 } });
}
```
```ts
// Cliente
declare const chrome: any;
const { token } = await tokenExtension();
chrome.runtime.sendMessage(EXTENSION_ID, { type: "knok:token", token, apiBase: "https://api.tu-dominio" });
```

## 9. Despliegue

El motor es una imagen Docker (`Dockerfile`) con dos procesos: la API (`uvicorn`) y el worker
(`python -m knok.worker`), más un Postgres 16. Cualquier VPS o PaaS con Docker sirve. En producción:
`KNOK_ENV=production`, una `KNOK_SECRET_KEY` larga y secreta, HTTPS, `KNOK_PUBLIC_BASE_URL` con la URL
pública de la API y copias de seguridad de Postgres y de `KNOK_STORAGE_DIR` (CVs).
