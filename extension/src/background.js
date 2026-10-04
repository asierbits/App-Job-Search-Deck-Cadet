/*
 * Service worker de knok. Todo empieza por un clic del usuario en el popup: nada corre en segundo plano.
 */
import { api, settings } from "./lib/api.js";
import { buildPlan, runBatch } from "./lib/runner.js";

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
