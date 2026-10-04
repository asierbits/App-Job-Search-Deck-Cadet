/* Cliente mínimo de la API de knok (URL y token guardados en chrome.storage.local). */
export async function settings() {
  const s = await chrome.storage.local.get(["apiBase", "token"]);
  return { apiBase: (s.apiBase || "http://localhost:8000").replace(/\/$/, ""), token: s.token || "" };
}

export async function api(path, { method = "GET", body, raw = false } = {}) {
  const { apiBase, token } = await settings();
  if (!token) throw new Error("Conecta la extensión con tu cuenta de knok (token).");
  const r = await fetch(apiBase + path, {
    method,
    headers: { Authorization: "Bearer " + token, ...(body ? { "Content-Type": "application/json" } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) {
    let msg = r.status + "";
    try { const j = await r.json(); msg = (j.detail && (j.detail.message || j.detail)) || msg; } catch (_) {}
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  if (raw) return r;
  return r.status === 204 ? null : r.json();
}
