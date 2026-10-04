/*
 * Service worker de knok. Todo empieza por un clic del usuario en el popup: nada corre en segundo plano.
 */
import { api, settings } from "./lib/api.js";
import { buildPlan, runBatch, runPilot } from "./lib/runner.js";

const CONTENT_FILES = [
  "src/content/core.js", "src/content/adapters/greenhouse.js", "src/content/adapters/lever.js",
  "src/content/adapters/ashby.js", "src/content/adapters/linkedin.js", "src/content/adapters/phase2.js",
  "src/content/adapters/indeed.js", "src/content/main.js",
];
let stop = false;
let running = false;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function progress(p) {
  await chrome.storage.session.set({ progress: { ...p, at: Date.now() } });
}

async function inject(tabId) {
  await chrome.scripting.executeScript({ target: { tabId }, files: CONTENT_FILES });
}

function waitLoaded(tabId, timeoutMs = 30000) {
  return new Promise((resolve) => {
    const t = setTimeout(done, timeoutMs);
    function done() { clearTimeout(t); chrome.tabs.onUpdated.removeListener(l); resolve(); }
    function l(id, info) { if (id === tabId && info.status === "complete") done(); }
    chrome.tabs.onUpdated.addListener(l);
  });
}

async function downloadFiles(plan) {
  const files = {};
  for (const f of plan.fields) {
    if (f.type === "file" && f.value && f.value.download_url) {
      const r = await api(f.value.download_url, { raw: true });
      const buf = await r.arrayBuffer();
      files[f.id] = { bytes: Array.from(new Uint8Array(buf)), filename: f.value.filename,
                      mime: r.headers.get("content-type") || "application/pdf" };
    }
  }
  return files;
}

async function fillTab(tabId, applicationId) {
  await inject(tabId);
  const form = await chrome.tabs.sendMessage(tabId, { cmd: "extract" });
  if (form.blocked) return { blocked: form.blocked };
  const plan = await api("/extension/fill-plan", { method: "POST",
    body: { url: form.url, application_id: applicationId || null, platform: form.platform, fields: form.fields,
            company: form.company || "", title: form.title || "" } });
  const files = await downloadFiles(plan);
  const res = await chrome.tabs.sendMessage(tabId, { cmd: "fill", plan: buildPlan(plan, files),
                                                     applicationId: plan.application_id });
  return { ...res, applicationId: plan.application_id, captcha: form.captcha || res.captcha,
           missing: plan.missing, warnings: plan.warnings };
}

async function openAndFill(item) {
  const tab = await chrome.tabs.create({ url: item.apply_url, active: false });
  await waitLoaded(tab.id);
  await sleep(1500); // dejar que la web pinte el formulario
  return fillTab(tab.id, item.id);
}

// --- piloto automático: una ventana aparte (minimizada) con las pestañas agrupadas como «knok · revisar»
let pilotWindowId = null;
let pilotGroupId = null;
const DIAS_SIN_REPETIR = 3;

async function pilotTab(url, minimized) {
  if (pilotWindowId !== null) {
    try {
      await chrome.windows.get(pilotWindowId);
      return chrome.tabs.create({ windowId: pilotWindowId, url, active: false });
    } catch (_) { pilotWindowId = null; pilotGroupId = null; }
  }
  const w = await chrome.windows.create({ url, focused: !minimized, ...(minimized ? { state: "minimized" } : {}) });
  pilotWindowId = w.id;
  return w.tabs[0];
}

async function agrupar(tabId) {
  try {
    if (pilotGroupId === null) {
      pilotGroupId = await chrome.tabs.group({ tabIds: [tabId], createProperties: { windowId: pilotWindowId } });
      await chrome.tabGroups.update(pilotGroupId, { title: "knok · revisar y enviar", color: "blue" });
    } else {
      await chrome.tabs.group({ tabIds: [tabId], groupId: pilotGroupId });
    }
  } catch (_) { /* sin grupos de pestañas: no pasa nada */ }
}

async function rellenadas() {
  const { filled = {} } = await chrome.storage.local.get("filled");
  return filled;
}

async function apuntarRellena(id) {
  const filled = await rellenadas();
  filled[id] = Date.now();
  await chrome.storage.local.set({ filled });
}

async function startPilot({ source = "queue", filters = {}, max = 20, minimized = true } = {}) {
  if (running) return { error: "Ya hay una tanda en marcha" };
  running = true; stop = false;
  const cfg = await api("/extension/config");
  const filled = await rellenadas();
  const limite = Date.now() - DIAS_SIN_REPETIR * 86400000;
  const abrir = async (item) => {
    const tab = await pilotTab(item.apply_url, minimized);
    await agrupar(tab.id);
    await waitLoaded(tab.id);
    await sleep(1500);
    const t = await chrome.tabs.get(tab.id);
    if (/^chrome-error:|^about:blank/.test(t.url || "")) throw new Error("La página no cargó: " + item.apply_url);
    const r = await fillTab(tab.id, item.id);
    if (r.blocked) throw new Error(r.blocked);
    await apuntarRellena(item.id);
    return r;
  };
  runPilot({ api, openAndFill: abrir, sleep, onProgress: progress, shouldStop: () => stop, source, filters,
             max: Math.min(Math.max(1, max), cfg.limits.batch_size), pause: cfg.limits.pause_between_jobs_seconds,
             skip: (id) => (filled[id] || 0) > limite })
    .then((r) => progress({ phase: r.stopped ? "stopped" : "done", result: { prepared: r.prepared.length, oneByOne: r.oneByOne.length,
                                                                              errors: r.prepared.filter((x) => x.error).length }, pilot: true }))
    .catch((e) => progress({ phase: "error", error: String(e.message || e) }))
    .finally(() => { running = false; });
  return { started: true };
}

// El panel solo puede mandar si es TU knok (la dirección a la que está conectada la extensión, o tu ordenador)
async function panelPermitido(sender) {
  const origen = sender && sender.tab && sender.tab.url ? new URL(sender.tab.url).origin : "";
  const { apiBase, token } = await settings();
  const local = /^http:\/\/(localhost|127\.0\.0\.1):8000$/.test(origen);
  return origen && (origen === new URL(apiBase).origin || (local && !token)) ? origen : null;
}

async function conectarLocal(origen) {
  const r = await fetch(origen + "/auth/local?client=extension");
  if (!r.ok) throw new Error("No se pudo conectar con knok (" + r.status + ")");
  await chrome.storage.local.set({ apiBase: origen, token: (await r.json()).token });
}

async function mostrarPiloto() {
  if (pilotWindowId === null) return { error: "Aún no hay ventana del piloto: pulsa «Rellenar las de knok»." };
  try { await chrome.windows.update(pilotWindowId, { focused: true, state: "normal" }); }
  catch (_) { pilotWindowId = null; return { error: "La ventana del piloto se cerró." }; }
  return { ok: true };
}

async function desdePanel(msg, sender) {
  const origen = await panelPermitido(sender);
  if (!origen) return { error: "Esta página no es tu knok" };
  const s = await settings();
  if (!s.token && /^http:\/\/(localhost|127\.0\.0\.1):8000$/.test(origen)) await conectarLocal(origen);
  const { progress: p } = await chrome.storage.session.get("progress");
  switch (msg.action) {
    case "status": {
      const { token } = await settings();
      return { connected: !!token, running, progress: p || null, version: chrome.runtime.getManifest().version };
    }
    case "pilot:start": return startPilot(msg.payload);
    case "pilot:stop": stop = true; return { stopping: true };
    case "pilot:show": return mostrarPiloto();
    default: return { error: "orden desconocida" };
  }
}

chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  (async () => {
    switch (msg.type) {
      case "knok:connect":
        await chrome.storage.local.set({ apiBase: msg.apiBase, token: msg.token });
        return { ok: true, me: await api("/me") };
      case "knok:status": {
        const s = await settings();
        const { progress: p } = await chrome.storage.session.get("progress");
        return { connected: !!s.token, apiBase: s.apiBase, running, progress: p || null };
      }
      case "knok:start": {
        if (running) return { error: "Ya hay una tanda en marcha" };
        running = true; stop = false;
        const cfg = await api("/extension/config");
        runBatch({ api, openAndFill, sleep, onProgress: progress, shouldStop: () => stop, filters: msg.filters,
                   limits: { batchSize: cfg.limits.batch_size, pause: cfg.limits.pause_between_jobs_seconds } })
          .then((r) => progress({ phase: r.stopped ? "stopped" : "done", result: r }))
          .catch((e) => progress({ phase: "error", error: String(e.message || e) }))
          .finally(() => { running = false; });
        return { started: true };
      }
      case "knok:stop":
        stop = true;
        return { stopping: true };
      case "knok:fillCurrent": {
        const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
        return fillTab(tab.id, null);
      }
      case "knok:panel":
        return desdePanel(msg, sender);
      case "knok:pilot":
        return startPilot(msg.payload || {});
      case "knok:pilotShow":
        return mostrarPiloto();
      case "knok:captureList": {
        // Solo lo que ya está en la pantalla del usuario: no se navega ni se pide nada más al portal
        const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
        await inject(tab.id);
        const lista = await chrome.tabs.sendMessage(tab.id, { cmd: "captureList" });
        if (!lista || !lista.length) return { error: "No veo ofertas en esta página. Abre una búsqueda de empleos y baja un poco para que se carguen." };
        return api("/extension/captures/bulk", { method: "POST", body: { items: lista.slice(0, 60) } });
      }
      case "knok:captureCurrent": {
        const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
        await inject(tab.id);
        const job = await chrome.tabs.sendMessage(tab.id, { cmd: "capture" });
        return api("/extension/captures", { method: "POST", body: job });
      }
      case "knok:submitted":
        // El USUARIO ha enviado la solicitud en la web: se anota en el seguimiento
        return api("/extension/submitted", { method: "POST", body: { application_id: msg.applicationId, url: msg.url } });
      default:
        return { error: "orden desconocida" };
    }
  })().then(reply, (e) => reply({ error: String(e.message || e) }));
  return true;
});

// Tu web puede pasar el token a la extensión (ver externally_connectable en manifest.json)
chrome.runtime.onMessageExternal.addListener((msg, sender, reply) => {
  if (msg && msg.type === "knok:token" && msg.token) {
    chrome.storage.local.set({ token: msg.token, ...(msg.apiBase ? { apiBase: msg.apiBase } : {}) })
      .then(() => reply({ ok: true }));
    return true;
  }
  reply({ ok: false });
});
