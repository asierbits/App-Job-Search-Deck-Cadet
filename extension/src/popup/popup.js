const $ = (id) => document.getElementById(id);
const send = (msg) => chrome.runtime.sendMessage(msg);
const lista = (v) => v.split(",").map((x) => x.trim()).filter(Boolean);

function pintar(s) {
  if (!s) return;
  if (s.error) { $("estado").textContent = "Error: " + s.error; return; }
  const p = s.progress;
  if (!p) { $("estado").textContent = s.connected ? "Conectado a " + s.apiBase : "Sin conectar"; return; }
  const textos = {
    searching: "Buscando ofertas…",
    filling: `Rellenando ${p.index}/${p.total}: ${p.item && p.item.title}`,
    done: p.result ? `Listo: ${p.result.prepared.length} solicitudes rellenas en pestañas. Revísalas y pulsa Enviar en cada una.` +
      (p.result.oneByOne && p.result.oneByOne.length ? `\n${p.result.oneByOne.length} de LinkedIn: ábrelas y usa «Rellenar esta página», de una en una.` : "") : "Listo",
    stopped: "Detenido.",
    error: "Error: " + p.error,
  };
  $("estado").textContent = textos[p.phase] || p.phase;
}

async function refrescar() {
  const s = await send({ type: "knok:status" });
  if (s && s.apiBase) $("apiBase").value = s.apiBase;
  pintar(s);
}

$("conectar").onclick = async () => {
  const base = ($("apiBase").value.trim() || "http://localhost:8000").replace(/\/$/, "");
  // La extensión solo puede hablar con la API si le das permiso para esa dirección
  if (!/^http:\/\/localhost(:\d+)?$/.test(base)) {
    const ok = await chrome.permissions.request({ origins: [base + "/*"] });
    if (!ok) { $("estado").textContent = "Sin permiso para " + base; return; }
  }
  const r = await send({ type: "knok:connect", apiBase: base, token: $("token").value.trim() });
  $("estado").textContent = r.error ? "Error: " + r.error : "Conectado como " + r.me.user.email + " (modo " + r.me.profile.mode + ")";
};
$("iniciar").onclick = async () => {
  const r = await send({ type: "knok:start", filters: { countries: lista($("paises").value), cities: lista($("ciudades").value),
                                                        keywords: lista($("palabras").value) } });
  if (r.error) $("estado").textContent = "Error: " + r.error;
};
$("detener").onclick = () => send({ type: "knok:stop" });
$("rellenar").onclick = async () => {
  const r = await send({ type: "knok:fillCurrent" });
  $("estado").textContent = r.error ? "Error: " + r.error : r.blocked ? r.blocked :
    `Rellenados ${r.filled}; a revisar ${r.review}.` + (r.captcha ? "\nHay un CAPTCHA: resuélvelo tú." : "") + "\nRevisa y pulsa Enviar tú.";
};
$("capturar").onclick = async () => {
  const r = await send({ type: "knok:captureCurrent" });
  $("estado").textContent = r.error ? "Error: " + r.error : "Guardada en knok (vía: " + r.application.route + ")";
};

chrome.tabs.query({ active: true, currentWindow: true }).then(([tab]) => {
  if (tab && /linkedin\.com\/jobs/.test(tab.url || "")) $("avisoLinkedin").hidden = false;
});
refrescar();
setInterval(refrescar, 1500);
