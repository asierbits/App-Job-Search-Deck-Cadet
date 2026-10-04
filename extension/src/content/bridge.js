/*
 * Puente entre el panel de knok (la página) y la extensión. Solo se carga en las direcciones del panel
 * (ver content_scripts en manifest.json). El panel pide cosas con window.postMessage; aquí se pasan al
 * service worker, que comprueba que la página es la de tu knok antes de hacer nada.
 */
(function () {
  "use strict";
  if (window.__knokBridge || typeof chrome === "undefined" || !chrome.runtime) return;
  window.__knokBridge = true;
  const responder = (datos) => window.postMessage({ source: "knok-ext", ...datos }, location.origin);
  const anunciar = () => responder({ type: "ready", version: chrome.runtime.getManifest().version });

  window.addEventListener("message", async (ev) => {
    if (ev.source !== window || ev.origin !== location.origin) return;
    const m = ev.data;
    if (!m || m.source !== "knok-panel") return;
    if (m.type === "ping") return anunciar();
    let reply;
    try {
      reply = await chrome.runtime.sendMessage({ type: "knok:panel", action: m.type, payload: m.payload || {} });
    } catch (e) {
      reply = { error: String((e && e.message) || e) };
    }
    responder({ id: m.id, reply });
  });
  anunciar();
})();
