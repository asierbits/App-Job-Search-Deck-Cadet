"use strict";
// Panel de knok (diseño de la primera versión). Habla con la API de knok: nada se envía sin tu clic.

const $ = (s, raiz = document) => raiz.querySelector(s);
const $$ = (s, raiz = document) => [...raiz.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const MODOS = { simulation: "Simulación", test: "Prueba real", live: "REAL" };
const MODO_CLASE = { simulation: "simulacion", test: "prueba", live: "real" };
const CATEGORIAS = {
  interview: { txt: "Entrevista", icono: "✓", clase: "entrevista" },
  info: { txt: "Piden info", icono: "i", clase: "info" },
  rejection: { txt: "Rechazo", icono: "✕", clase: "rechazo" },
  auto: { txt: "Automática", icono: "↻", clase: "automatica" },
  other: { txt: "Otra", icono: "•", clase: "otra" },
};
const ESTADOS = {
  new: ["Sin preparar", "nueva"], prepared: ["Preparada", "preparada"], confirmed: ["Confirmada · pendiente", "confirmada"],
  sent: ["Enviada", "enviado"], replied: ["Respondida", "respondida"], interview: ["Entrevista", "entrevista"],
  discarded: ["Descartada", "descartada"], error: ["Error", "error"],
};
const VIAS = {
  email: ["Correo", "Se le escribe a su buzón genérico (info@, empleo@…) con tu mensaje y tus adjuntos."],
  ats_extension: ["Formulario", "Formulario de la empresa (Greenhouse, Lever…): la extensión de knok lo rellena y tú pulsas Enviar."],
  portal_api: ["InfoJobs", "Candidatura por la API oficial de InfoJobs."],
  portal_copilot: ["Portal", "Portal de empleo: la extensión te ayuda a rellenarlo dentro del portal."],
  manual: ["A mano", "No hay buzón ni formulario conocido: abre el enlace y hazla tú."],
};
const ABIERTOS = ["new", "prepared", "error"];
const ICONOS = {
  buscar: '<svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>',
  enviar: '<svg viewBox="0 0 24 24"><path d="M22 2 11 13"/><path d="M22 2 15 22l-4-9-9-4z"/></svg>',
  respuesta: '<svg viewBox="0 0 24 24"><path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/></svg>',
  objetivo: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1"/></svg>',
  flecha: '<svg viewBox="0 0 24 24"><path d="M5 12h14"/><path d="m13 6 6 6-6 6"/></svg>',
};
const PAISES = {
  es: "España", pt: "Portugal", fr: "Francia", de: "Alemania", it: "Italia", nl: "Países Bajos", be: "Bélgica",
  lu: "Luxemburgo", ie: "Irlanda", gb: "Reino Unido", at: "Austria", ch: "Suiza", dk: "Dinamarca", se: "Suecia",
  no: "Noruega", fi: "Finlandia", is: "Islandia", pl: "Polonia", cz: "Chequia", sk: "Eslovaquia", hu: "Hungría",
  si: "Eslovenia", hr: "Croacia", ro: "Rumanía", bg: "Bulgaria", gr: "Grecia", cy: "Chipre", mt: "Malta",
  ee: "Estonia", lv: "Letonia", lt: "Lituania", rs: "Serbia", ad: "Andorra", mc: "Mónaco", ua: "Ucrania", tr: "Turquía",
  us: "Estados Unidos", ca: "Canadá", mx: "México", ar: "Argentina", cl: "Chile", co: "Colombia", pe: "Perú",
  uy: "Uruguay", br: "Brasil", au: "Australia", nz: "Nueva Zelanda", sg: "Singapur", jp: "Japón", kr: "Corea del Sur",
  cn: "China", hk: "Hong Kong", in: "India", ae: "Emiratos Árabes", qa: "Catar", sa: "Arabia Saudí", il: "Israel",
  za: "Sudáfrica", ma: "Marruecos", eg: "Egipto", ph: "Filipinas", my: "Malasia", th: "Tailandia", id: "Indonesia",
};
const IDIOMAS = { es: "Español", en: "English", fr: "Français", de: "Deutsch", it: "Italiano", pt: "Português", nl: "Nederlands" };
const IDIOMAS_ES = { es: "español", en: "inglés", fr: "francés", de: "alemán", it: "italiano", pt: "portugués", nl: "neerlandés" };
const BANDERAS = { es: "🇪🇸", en: "🇬🇧", fr: "🇫🇷", de: "🇩🇪", it: "🇮🇹", pt: "🇵🇹", nl: "🇳🇱" };
const ICONO_NICHO = { marina_mercante: "⚓", doctorados_investigacion: "🎓" };
const NOMBRES_VAR = {
  nombre: "Tu nombre", nombre_pila: "Nombre de pila", apellidos: "Apellidos", email: "Tu email", telefono: "Teléfono",
  linkedin: "LinkedIn", web: "Tu web", empresa: "Empresa", puesto: "Puesto", ciudad: "Ciudad", pais: "País", sector: "Sector",
};
const OPCIONALES = new Set(["telefono", "linkedin", "web", "ciudad", "pais", "sector"]);
const AVISOS = {
  cobro: { txt: "Posible cobro", clase: "critico", ayuda: "Su web habla de pagar una tasa o cuota. Desconfía: no pagues nada por una candidatura (en marina, el Convenio MLC 2006 lo prohíbe)." },
  ucrania: { txt: "Ucrania", clase: "", ayuda: "La empresa es de Ucrania o su web menciona Ucrania o sus puertos. Comprueba en qué zona operan antes de ir." },
  mar_negro: { txt: "Mar Negro", clase: "", ayuda: "Su web menciona el Mar Negro, el Mar de Azov o zonas de riesgo." },
};
const EJEMPLOS = {
  marina_mercante: {
    es: { company: ["Naviera Cantábrica de Ferris", "Ferris", "Santander", "flota@cantabricaferris.example.com"], agency: ["Tripulaciones Marítimas del Norte", "Agencia de tripulación", "Bilbao", "alumnos@tripnorte.example.com"], job: ["Naviera Cantábrica de Ferris", "Ferris", "Santander", "empleo@cantabricaferris.example.com", "Alumno de puente"] },
    en: { company: ["Nordsee Reederei GmbH", "Naviera (carga)", "Hamburg", "crewing@nordsee-reederei.example.com"], agency: ["EuroCrew Manning Agency", "Crewing agency", "Limassol", "cadets@eurocrew.example.org"], job: ["Nordsee Reederei GmbH", "Shipping", "Hamburg", "jobs@nordsee-reederei.example.com", "Deck Cadet"] },
  },
  _: {
    es: { company: ["Empresa de Ejemplo S.L.", "Servicios", "Madrid", "empleo@empresa.example.com"], agency: ["Agencia de Empleo Ejemplo", "Agencia de selección", "Valencia", "seleccion@agencia.example.com"], job: ["Empresa de Ejemplo S.L.", "Servicios", "Madrid", "empleo@empresa.example.com", "Puesto de ejemplo"] },
    en: { company: ["Example Company Ltd", "Services", "London", "jobs@example.com"], agency: ["Example Recruitment Agency", "Recruitment", "Dublin", "careers@agency.example.com"], job: ["Example Company Ltd", "Services", "London", "jobs@example.com", "Example position"] },
  },
};

const st = {
  vista: "panel", estado: null, filas: [], firmaTabla: "", firmaGrafico: "", firmaRegistro: "",
  sel: new Set(), respuestas: [], filtroCat: "todas", respuestaSel: null,
  config: null, sucio: false, idioma: "es", audiencia: "company", plantillas: {}, docs: [], banco: [],
  busqueda: null, ultimoCampo: null, tablaCargando: false, ultimaTabla: 0, dialogoCuentaMostrado: false,
};

// ------------------------------------------------------------ API y sesión

let TOKEN = null;
try { TOKEN = localStorage.getItem("knok-token"); } catch {}

function guardarToken(t) {
  TOKEN = t;
  try { t ? localStorage.setItem("knok-token", t) : localStorage.removeItem("knok-token"); } catch {}
}

async function sesionLocal() {
  const r = await fetch("/auth/local");
  if (!r.ok) return false;
  guardarToken((await r.json()).token);
  return true;
}

function mensajeError(j, status) {
  const d = j && j.detail;
  if (d && typeof d === "object" && !Array.isArray(d) && d.message) return d.message;
  if (Array.isArray(d)) return d.map((x) => `${(x.loc || []).slice(-1)[0] || ""}: ${x.msg}`).join(" · ");
  if (typeof d === "string") return d;
  return `Error ${status}`;
}

async function api(ruta, opciones = {}, reintento = true) {
  const { method = "GET", body, form } = opciones;
  const headers = TOKEN ? { Authorization: "Bearer " + TOKEN } : {};
  let cuerpo;
  if (form) cuerpo = form;
  else if (body !== undefined) { headers["Content-Type"] = "application/json"; cuerpo = JSON.stringify(body); }
  const r = await fetch(ruta, { method: body !== undefined || form ? (method === "GET" ? "POST" : method) : method, headers, body: cuerpo });
  if (r.status === 401 && reintento) {
    guardarToken(null);
    if (await sesionLocal()) return api(ruta, opciones, false);
    pedirLogin();
    throw new Error("Inicia sesión");
  }
  if (r.status === 204) return null;
  const tipo = r.headers.get("content-type") || "";
  const json = tipo.includes("json") ? await r.json().catch(() => ({})) : null;
  if (!r.ok) throw new Error(mensajeError(json, r.status));
  return json ?? r;
}

function pedirLogin() {
  if ($("#dialogo").open) return;
  $("#dialogo-titulo").textContent = "Entrar en knok";
  $("#dialogo-cuerpo").innerHTML = `
    <p class="secundario">Este panel funciona solo en tu ordenador (arráncalo con <code>iniciar.bat</code> o <code>iniciar.sh</code>). Si knok está en un servidor, entra con tu cuenta:</p>
    <form id="form-login"><label>Email<input name="email" type="email" required></label>
    <label>Contraseña<input name="password" type="password" required></label>
    <div class="fila"><button class="btn primario">Entrar</button></div></form>`;
  $("#dialogo").showModal();
  $("#form-login").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const f = Object.fromEntries(new FormData(ev.target));
    try {
      const r = await fetch("/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(f) });
      const j = await r.json();
      if (!r.ok) throw new Error(mensajeError(j, r.status));
      guardarToken(j.token);
      $("#dialogo").close();
      refrescar();
    } catch (err) { aviso(err.message, "critico"); }
  });
}

function aviso(mensaje, tipo = "") {
  const div = document.createElement("div");
  div.className = "aviso " + tipo;
  div.textContent = mensaje;
  $("#avisos").prepend(div);
  setTimeout(() => div.remove(), 7000);
}

// ------------------------------------------------------------ utilidades de presentación

const hora = (iso) => (iso ? new Date(iso).toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" }) : "");
function fecha(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toDateString() === new Date().toDateString() ? "hoy " + hora(iso) : d.toLocaleDateString("es-ES", { day: "numeric", month: "short" }) + " " + hora(iso);
}
const pct = (a, b) => (b ? Math.round((a / b) * 100) + "%" : "—");
const nombrePais = (c) => PAISES[c] || (c ? c.toUpperCase() : "—");
const catInfo = (c) => CATEGORIAS[c] || CATEGORIAS.other;
const cat = (c, pastilla = false) => { const k = catInfo(c); return `<span class="cat cat-${k.clase} ${pastilla ? "pastilla" : ""}"><span class="icono">${k.icono}</span>${k.txt}</span>`; };
const estadoHtml = (e) => { const [t, c] = ESTADOS[e] || [e, e]; return `<span class="estado estado-${esc(c)}">${esc(t)}</span>`; };
const viaHtml = (r) => `<span class="via via-${esc(r)}" title="${esc((VIAS[r] || ["", ""])[1])}">${esc((VIAS[r] || [r])[0])}</span>`;
function iniciales(nombre) {
  const palabras = String(nombre || "?").replace(/<.*>/, "").trim().split(/\s+/).filter((p) => /^[\p{L}\d]/u.test(p));
  return ((palabras[0] || "?")[0] + (palabras[1] ? palabras[1][0] : "")).toUpperCase();
}
const avatar = (nombre, categoria, extra = "") => `<div class="avatar ${categoria ? "cat-" + catInfo(categoria).clase : ""} ${extra}" aria-hidden="true">${esc(iniciales(nombre))}</div>`;
function urlSegura(u) {
  u = String(u || "").trim();
  if (!u) return "";
  if (!/^https?:\/\//i.test(u)) u = "https://" + u.replace(/^[a-z]+:\/*/i, "");
  return esc(u);
}
const enlace = (u, t) => (u ? `<a href="${urlSegura(u)}" target="_blank" rel="noopener">${esc(t || u)}</a>` : "—");
const listaCorta = (xs) => (xs.length <= 3 ? xs.join(", ") : `${xs.slice(0, 3).join(", ")} y ${xs.length - 3} más`);
const icono = () => ICONO_NICHO[(st.estado && st.estado.pack.slug) || ""] || "★";
const tamano = (b) => (b >= 1048576 ? (b / 1048576).toFixed(1) + " MB" : Math.max(1, Math.round(b / 1024)) + " KB");
const guardarLocal = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} };
const leerLocal = (k) => { try { return JSON.parse(localStorage.getItem(k) || "null"); } catch { return null; } };

// ------------------------------------------------------------ navegación

function mostrar(vista) {
  st.vista = vista;
  history.replaceState(null, "", "#" + vista);
  $$(".pestana").forEach((b) => b.classList.toggle("activa", b.dataset.vista === vista));
  $$(".vista").forEach((s) => (s.hidden = s.id !== "vista-" + vista));
  if (vista === "empresas") cargarTabla();
  if (vista === "respuestas") cargarRespuestas();
  if (vista === "config" && !st.sucio) cargarConfig();
  if (vista === "panel" && st.estado) { st.firmaGrafico = ""; pintarGrafico(st.estado.summary.daily); }
}
$$(".pestana").forEach((b) => b.addEventListener("click", () => mostrar(b.dataset.vista)));
window.addEventListener("hashchange", () => {
  const v = location.hash.slice(1);
  if (v !== st.vista && ["panel", "empresas", "respuestas", "config"].includes(v)) mostrar(v);
});
document.addEventListener("click", (ev) => {
  const ir = ev.target.closest("[data-ir]");
  if (ir) mostrar(ir.dataset.ir);
});

// ------------------------------------------------------------ estado general (cada 2 s; más rápido mientras busca)

const buscando = (e) => !!(e && e.search && ["queued", "running", "cancelling"].includes(e.search.status));

async function refrescar() {
  let e;
  try {
    e = await api("/panel/state");
  } catch (err) {
    $("#resumen").textContent = "Sin conexión con knok. ¿Está abierta la ventana de knok (iniciar.bat)?";
    return;
  }
  const antes = st.estado;
  st.estado = e;
  if (!antes || antes.pack.slug !== e.pack.slug) prepararBusqueda();
  pintarCabecera(e);
  pintarPanel(e);
  pintarRegistro(e.events);
  if (st.vista !== "respuestas") { st.respuestas = e.replies; pintarUltimas(); }
  else if (!antes || antes.replies.length !== e.replies.length || antes.summary.unread_replies !== e.summary.unread_replies) cargarRespuestas();

  if (st.vista === "empresas") {
    pintarTarjetaRastreo(e);
    const firma = [e.search && e.search.id, e.search && e.search.status, e.search && e.search.stats.results,
      JSON.stringify(e.summary.by_status), e.replies.length, e.profile.mode].join("|");
    const vivo = buscando(e) && Date.now() - st.ultimaTabla > 3000;
    if (firma !== st.firmaTabla || vivo) { st.firmaTabla = firma; cargarTabla(); }
  }
  if (!st.dialogoCuentaMostrado) {
    st.dialogoCuentaMostrado = true;
    let omitido = false;
    try { omitido = sessionStorage.getItem("cuenta-omitida") === "1"; } catch {}
    if (!e.connections.google.connected && e.profile.mode !== "simulation" && !omitido) abrirCuenta();
  }
  clearTimeout(st.temporizador);
  st.temporizador = setTimeout(refrescar, buscando(e) ? 1200 : 2500);
}

function pintarCabecera(e) {
  const ins = $("#insignia-modo");
  ins.className = "insignia " + MODO_CLASE[e.profile.mode];
  ins.textContent = MODOS[e.profile.mode];
  ins.title = { simulation: "No se envía ningún correo real", test: "Los correos se envían, pero solo a tu propio email", live: "Los correos se envían a las empresas" }[e.profile.mode];
  $("#nicho-chip").textContent = `${icono()} ${e.pack.name}`;

  const g = e.connections.google;
  const chip = $("#chip-cuenta");
  chip.className = "chip-cuenta" + (g.connected ? "" : " desconectada");
  chip.innerHTML = `<span class="punto"></span>${esc(g.connected ? g.email : "Conectar Gmail")}`;
  chip.title = g.connected ? "Cuenta conectada. Pulsa para cambiarla." : "Conecta la cuenta desde la que se enviarán los correos";
  if (st.vista === "config") pintarCuentaConfig();
  pintarRevision(e);

  const n = e.summary.unread_replies;
  $("#contador-no-leidas").hidden = !n;
  $("#contador-no-leidas").textContent = n;
  const enMarcha = buscando(e);
  $("#btn-iniciar").hidden = enMarcha;
  $("#btn-detener").hidden = !enMarcha;
  const hay = e.search && e.search.stats && e.search.stats.results;
  $("#btn-iniciar").lastChild.textContent = hay ? " 1 · Buscar de nuevo" : " 1 · Iniciar búsqueda";
  $("#btn-ir-revisar").hidden = !hay && !Object.keys(e.summary.by_status).length;
  $("#btn-ir-revisar").textContent = st.sel.size ? `2 · Revisar y enviar (${st.sel.size}) →` : "2 · Revisar y enviar →";
  $("#contador-seleccionadas").hidden = !st.sel.size;
  $("#contador-seleccionadas").textContent = st.sel.size;
  document.title = (n ? `(${n}) ` : "") + "knok";

  const avisos = $("#avisos");
  $$(".aviso.fijo", avisos).forEach((x) => x.remove());
  const problemas = e.sending_problems.slice();
  if (e.offline) problemas.push({ message: "knok está en modo sin red (KNOK_OFFLINE_SOURCES): solo usa datos de ejemplo. Quita esa línea del archivo .env para buscar de verdad." });
  if (problemas.length) {
    const div = document.createElement("div");
    div.className = "aviso critico fijo";
    div.innerHTML = `<div><b>Falta configurar algo para el modo ${esc(MODOS[e.profile.mode])}:</b><ul>${problemas.map((p) => `<li>${esc(p.message)}</li>`).join("")}</ul>
      <button class="btn mini" data-ir="config" style="margin-top:6px">Ir a Configuración</button></div>`;
    avisos.append(div);
  }
}

// ------------------------------------------------------------ revisión del correo (respuestas)

function pintarRevision(e) {
  if (st.revisando) return;
  const g = e.connections.google;
  let texto, inactiva = false, boton = false;
  if (e.profile.mode === "simulation") { texto = "Simulación: las respuestas llegan solas"; inactiva = true; }
  else if (!g.connected) { texto = "Conecta Gmail para enviar y leer las respuestas"; inactiva = true; }
  else if (g.method === "app_password") {
    boton = true;
    texto = g.inbox_checked_at ? `Correo revisado a las ${hora(g.inbox_checked_at)} · se revisa cada 3 min` : "Revisaré tu correo en unos minutos";
  } else { texto = "Con «Conectar con Google» knok solo envía: anota las respuestas a mano"; inactiva = true; }
  $$(".revision-texto").forEach((el) => { el.textContent = texto; el.className = "revision-texto" + (inactiva ? " inactiva" : ""); });
  $$("[data-revisar]").forEach((b) => (b.hidden = !boton));
}

document.addEventListener("click", async (ev) => {
  if (!ev.target.closest("[data-revisar]") || st.revisando) return;
  st.revisando = true;
  $$("[data-revisar]").forEach((b) => (b.disabled = true));
  $$(".revision-texto").forEach((el) => { el.textContent = "Revisando tu bandeja de entrada…"; el.className = "revision-texto revisando"; });
  try {
    const r = await api("/panel/check-inbox", { method: "POST", body: {} });
    aviso(r.new ? `${r.new} respuesta(s) nueva(s).` : "No hay respuestas nuevas.", r.new ? "bien" : "");
  } catch (err) {
    aviso(err.message, "critico");
  } finally {
    st.revisando = false;
    $$("[data-revisar]").forEach((b) => (b.disabled = false));
    refrescar();
  }
});

// ------------------------------------------------------------ panel

function pintarPanel(e) {
  const s = e.summary, b = s.by_status;
  const enviadas = (b.sent || 0) + (b.replied || 0) + (b.interview || 0);
  const respondidas = (b.replied || 0) + (b.interview || 0);
  const entrevistas = b.interview || 0;
  const busq = e.search, stats = (busq && busq.stats) || {}, prog = stats.progress || {};
  const encontradas = stats.results || 0;

  $("#hoy").textContent = new Date().toLocaleDateString("es-ES", { weekday: "long", day: "numeric", month: "long" });
  const pila = (e.profile.first_name || "").trim().split(/\s+/)[0];
  $("#saludo").textContent = pila ? `Hola, ${pila}` : "¡Hola!";
  let resumen;
  if (buscando(e)) {
    resumen = `Estoy buscando: <b>${esc((prog.phase || "preparando").toLowerCase())}</b>` +
      (prog.total ? ` (${prog.done} de ${prog.total})` : "") + `. Ya tengo <b>${encontradas}</b> resultados; puedes ir viéndolos en <b>Empresas y ofertas</b>.`;
  } else if (!busq && !enviadas) {
    resumen = `Todavía no has empezado. Rellena <b>¿Qué buscas?</b> y pulsa <b>Iniciar búsqueda</b>: buscaré empresas y ofertas de <b>${esc(e.pack.name.toLowerCase())}</b>, rastrearé sus webs para encontrar el mejor contacto y te las enseñaré para que elijas a cuáles escribir.`;
  } else if (!enviadas) {
    resumen = `He encontrado <b>${encontradas}</b> empresas y ofertas` +
      (stats.crawl && stats.crawl.crawled ? ` y he rastreado <b>${stats.crawl.crawled}</b> webs` : "") +
      `. Revísalas y <b>elige a cuáles escribir</b>` + (st.sel.size ? ` (ya tienes <b>${st.sel.size}</b> seleccionadas).` : ".");
  } else {
    resumen = `Has contactado <b>${enviadas}</b> ${enviadas === 1 ? "empresa" : "empresas"} y <b>${respondidas}</b> ${respondidas === 1 ? "te ha" : "te han"} respondido.`;
    if (entrevistas) resumen += ` Tienes <b>${entrevistas} ${entrevistas === 1 ? "propuesta" : "propuestas"} de entrevista</b>. ¡Enhorabuena!`;
    if (s.unread_replies) resumen += ` Hay <b>${s.unread_replies}</b> ${s.unread_replies === 1 ? "respuesta" : "respuestas"} sin leer.`;
    else if (s.followups_due) resumen += ` <b>${s.followups_due}</b> ${s.followups_due === 1 ? "necesita" : "necesitan"} un seguimiento.`;
  }
  $("#resumen").innerHTML = resumen;
  $("#hero-detalle").textContent = e.profile.mode === "simulation"
    ? "Simulación: busca de verdad, pero no envía nada."
    : e.profile.mode === "test"
      ? `Prueba: los correos te llegan a ti (${s.sent_today ?? 0}/${s.daily_limit} hoy).`
      : `Real: ${s.sent_today ?? 0} de ${s.daily_limit} correos hoy.`;

  // Progreso
  $("#hero-progreso").hidden = !buscando(e);
  $("#fase").textContent = busq && busq.status === "cancelling" ? "Deteniendo…" : (prog.phase || "Preparando") + "…";
  $("#fase-num").textContent = prog.total ? `${prog.done} de ${prog.total}` : "";
  const barra = $("#barra-progreso");
  barra.classList.toggle("indeterminado", buscando(e) && !prog.total);
  barra.style.width = prog.total ? (prog.done / prog.total) * 100 + "%" : "0";

  // Embudo
  const rutas = stats.routes || {};
  const f = prog.found || {};
  const etapas = [
    { txt: "Encontradas", valor: encontradas, icono: ICONOS.buscar, color: "var(--tinta-2)",
      sub: [rutas.email && `${rutas.email} por correo`, (rutas.ats_extension || 0) + (rutas.portal_copilot || 0) ? `${(rutas.ats_extension || 0) + (rutas.portal_copilot || 0)} con formulario` : "",
        f.mentions && `${icono()} ${f.mentions} encajan`].filter(Boolean).join(" · ") },
    { txt: "Contactadas", valor: enviadas, icono: ICONOS.enviar, color: "var(--serie-1)", conv: pct(enviadas, encontradas),
      sub: e.profile.mode === "simulation" ? `${b.prepared || 0} preparadas sin enviar` : `${s.sent_today ?? 0}/${s.daily_limit} hoy · ${b.prepared || 0} preparadas` },
    { txt: "Respondieron", valor: respondidas, icono: ICONOS.respuesta, color: "var(--serie-2)", conv: pct(respondidas, enviadas),
      sub: `tasa de respuesta ${s.response_rate == null ? "—" : Math.round(s.response_rate * 100) + "%"}` },
    { txt: "Entrevistas", valor: entrevistas, icono: ICONOS.objetivo, color: "var(--bien)", conv: pct(entrevistas, respondidas), sub: entrevistas ? "¡a prepararlas!" : "" },
  ];
  $("#embudo").innerHTML = etapas.map((t, i) => `
    ${i ? `<div class="conector" title="Conversión desde la etapa anterior">${ICONOS.flecha}<span>${t.conv}</span></div>` : ""}
    <div class="etapa" style="--color-etapa:${t.color}">
      <div class="etapa-icono">${t.icono}</div>
      <div class="etapa-etiqueta">${t.txt}</div>
      <div class="kpi-valor">${t.valor}</div>
      <div class="etapa-sub">${esc(t.sub)}</div>
    </div>`).join("");

  const cats = Object.keys(CATEGORIAS).map((c) => ({ c, v: s.replies_by_category[c] || 0 }));
  const total = cats.reduce((a, x) => a + x.v, 0);
  const maxCat = Math.max(1, ...cats.map((x) => x.v));
  $("#categorias").innerHTML = !total
    ? `<p class="vacio" style="grid-column:1/-1">Todavía no ha respondido nadie.</p>`
    : cats.map(({ c, v }) => `
      <div class="barra-etiqueta">${cat(c)}</div>
      <div class="barra-pista" title="${esc(catInfo(c).txt)}: ${v}"><div class="barra-relleno cat-${catInfo(c).clase}" style="width:${(v / maxCat) * 100}%"></div></div>
      <div class="barra-valor">${v}</div>`).join("");

  if (st.vista === "panel") pintarGrafico(s.daily);
}

// ------------------------------------------------------------ gráfico diario

function pintarGrafico(diario) {
  const cont = $("#grafico-diario");
  const W = cont.clientWidth, H = cont.clientHeight;
  const firma = W + "|" + JSON.stringify(diario);
  if (!W || firma === st.firmaGrafico) return;
  st.firmaGrafico = firma;

  const m = { l: 28, r: 4, t: 10, b: 24 };
  const pw = W - m.l - m.r, ph = H - m.t - m.b;
  const maxV = Math.max(0, ...diario.flatMap((d) => [d.sent, d.replies]));
  const paso = maxV <= 10 ? 2 : maxV <= 50 ? 10 : 50;
  const tope = Math.max(4, Math.ceil(maxV / paso) * paso + (Math.ceil(maxV / paso) % 2 ? paso : 0));
  const y = (v) => m.t + ph - (v / tope) * ph;
  const n = diario.length, gw = pw / n;
  const bw = Math.max(3, Math.min(14, (gw - 8) / 2 - 1));
  const barra = (x, v, clase) => {
    if (!v) return "";
    const top = y(v), h = m.t + ph - top, r = Math.min(4, bw / 2, h);
    return `<path class="${clase}" d="M${x},${m.t + ph}V${top + r}Q${x},${top} ${x + r},${top}H${x + bw - r}Q${x + bw},${top} ${x + bw},${top + r}V${m.t + ph}Z"/>`;
  };
  let svg = "";
  for (const v of [0, tope / 2, tope]) {
    svg += `<line class="${v ? "rejilla-l" : "base-l"}" x1="${m.l}" x2="${W - m.r}" y1="${y(v)}" y2="${y(v)}"/>`;
    svg += `<text x="${m.l - 8}" y="${y(v) + 4}" text-anchor="end">${v}</text>`;
  }
  diario.forEach((d, i) => {
    const gx = m.l + i * gw, x0 = gx + (gw - (2 * bw + 2)) / 2;
    svg += `<rect class="zona" data-i="${i}" x="${gx}" y="${m.t}" width="${gw}" height="${ph}"/>`;
    svg += barra(x0, d.sent, "b1") + barra(x0 + bw + 2, d.replies, "b2");
    if ((n - 1 - i) % 2 === 0) {
      const f = new Date(d.day + "T12:00");
      svg += `<text x="${gx + gw / 2}" y="${H - 6}" text-anchor="middle">${i === n - 1 ? "hoy" : f.getDate() + "/" + (f.getMonth() + 1)}</text>`;
    }
  });
  const vacio = maxV === 0 ? `<div class="grafico-vacio">Aquí verás cada día cuántas candidaturas envías y cuántas respuestas recibes.</div>` : "";
  cont.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Candidaturas enviadas y respuestas por día en los últimos 14 días">${svg}</svg>${vacio}`;
  $$(".zona", cont).forEach((z) => (z.style.pointerEvents = "all"));
  $("#tabla-diario").innerHTML = `<table><tr><th>Día</th><th>Enviadas</th><th>Respuestas</th></tr>${diario.map((d) => `<tr><td>${esc(d.day)}</td><td>${d.sent}</td><td>${d.replies}</td></tr>`).join("")}</table>`;
}

$("#grafico-diario").addEventListener("mousemove", (ev) => {
  const z = ev.target.closest(".zona");
  const tip = $("#tooltip");
  $$(".zona.activa").forEach((x) => x !== z && x.classList.remove("activa"));
  if (!z || !st.estado) { tip.hidden = true; return; }
  z.classList.add("activa");
  const d = st.estado.summary.daily[Number(z.dataset.i)];
  const f = new Date(d.day + "T12:00").toLocaleDateString("es-ES", { weekday: "long", day: "numeric", month: "long" });
  tip.innerHTML = `<b>${esc(f)}</b>
    <div class="t-fila"><i class="muestra s1"></i><span>Enviadas</span><span>${d.sent}</span></div>
    <div class="t-fila"><i class="muestra s2"></i><span>Respuestas</span><span>${d.replies}</span></div>`;
  tip.hidden = false;
  tip.style.left = Math.min(ev.clientX + 14, window.innerWidth - tip.offsetWidth - 8) + "px";
  tip.style.top = ev.clientY + 14 + "px";
});
$("#grafico-diario").addEventListener("mouseleave", () => {
  $("#tooltip").hidden = true;
  $$(".zona.activa").forEach((x) => x.classList.remove("activa"));
});
window.addEventListener("resize", () => st.estado && st.vista === "panel" && pintarGrafico(st.estado.summary.daily));

function pintarRegistro(eventos) {
  const firma = eventos.length ? eventos[0].id + "|" + eventos.length : "";
  if (firma === st.firmaRegistro) return;
  st.firmaRegistro = firma;
  const clase = { warning: "aviso-t", error: "error", ok: "ok", info: "info" };
  $("#registro").innerHTML = eventos.length
    ? eventos.map((ev) => `<li><span class="hora">${esc(hora(ev.ts))}</span><span class="${clase[ev.level] || "info"}">${esc(ev.message)}</span></li>`).join("")
    : `<li><span></span><span class="info secundario">Aquí verás lo que va haciendo knok.</span></li>`;
}

// ------------------------------------------------------------ ¿Qué buscas? (parámetros de la búsqueda)

const claveBusqueda = () => "knok-busqueda-" + st.estado.pack.slug;

function busquedaPorDefecto() {
  const e = st.estado;
  const fuentes = ["companies", "ats"];
  if (e.sources_ready.adzuna) fuentes.push("adzuna");
  if (e.sources_ready.infojobs) fuentes.push("infojobs");
  if (e.offline) fuentes.splice(0, fuentes.length, "sample");
  return { keywords: "", paises: e.pack.default_countries.slice(), cities: "", radius_km: 10, max_webs: 200, sources: fuentes, include_companies: true };
}

function prepararBusqueda() {
  const e = st.estado;
  $("#sel-pack").innerHTML = e.packs.map((p) => `<option value="${esc(p.slug)}" ${p.slug === e.pack.slug ? "selected" : ""}>${esc((ICONO_NICHO[p.slug] || "★") + " " + p.name)}</option>`).join("");
  st.busqueda = { ...busquedaPorDefecto(), ...(leerLocal(claveBusqueda()) || {}) };
  const f = $("#form-busqueda");
  f.keywords.value = st.busqueda.keywords;
  f.cities.value = st.busqueda.cities;
  f.radius_km.value = st.busqueda.radius_km;
  f.max_webs.value = st.busqueda.max_webs;
  f.include_companies.checked = !!st.busqueda.include_companies;
  $$('[name="sources"]', f).forEach((c) => (c.checked = st.busqueda.sources.includes(c.value)));
  $('[data-falta="adzuna"]').textContent = e.sources_ready.adzuna ? "" : "(necesita claves gratis de Adzuna en .env)";
  $('[data-falta="infojobs"]').textContent = e.sources_ready.infojobs ? "" : "(necesita claves de InfoJobs en .env)";
  $("#pack-descripcion").textContent = "";
  pintarPaises();
}

function leerBusqueda() {
  const f = $("#form-busqueda");
  st.busqueda = {
    ...st.busqueda,
    keywords: f.keywords.value, cities: f.cities.value, radius_km: Number(f.radius_km.value) || 10,
    max_webs: Math.max(0, Number(f.max_webs.value) || 0), include_companies: f.include_companies.checked,
    sources: $$('[name="sources"]:checked', f).map((c) => c.value),
  };
  guardarLocal(claveBusqueda(), st.busqueda);
  return st.busqueda;
}

function pintarPaises() {
  const p = st.busqueda.paises;
  $("#chips-paises").innerHTML = p.length
    ? p.map((c) => `<button type="button" class="chip-pais" data-quitar-pais="${esc(c)}" title="Quitar">${esc(nombrePais(c))}<span>✕</span></button>`).join("")
    : `<span class="vacio-paises">Todos los países (sin filtro)</span>`;
  $("#sel-anadir-pais").innerHTML = `<option value="">+ Añadir país…</option>` + Object.entries(PAISES)
    .filter(([c]) => !p.includes(c)).sort((a, b) => a[1].localeCompare(b[1])).map(([c, n]) => `<option value="${c}">${esc(n)}</option>`).join("");
}
$("#chips-paises").addEventListener("click", (ev) => {
  const b = ev.target.closest("[data-quitar-pais]");
  if (!b) return;
  st.busqueda.paises = st.busqueda.paises.filter((c) => c !== b.dataset.quitarPais);
  leerBusqueda(); pintarPaises();
});
$("#sel-anadir-pais").addEventListener("change", (ev) => {
  if (!ev.target.value) return;
  st.busqueda.paises.push(ev.target.value);
  leerBusqueda(); pintarPaises();
});
$("#btn-paises-pack").addEventListener("click", () => { st.busqueda.paises = st.estado.pack.default_countries.slice(); leerBusqueda(); pintarPaises(); });
$("#btn-paises-ninguno").addEventListener("click", () => { st.busqueda.paises = []; leerBusqueda(); pintarPaises(); });
$("#form-busqueda").addEventListener("change", (ev) => { if (ev.target.id !== "sel-pack" && ev.target.id !== "sel-anadir-pais") leerBusqueda(); });
$("#btn-busqueda-defecto").addEventListener("click", () => {
  try { localStorage.removeItem(claveBusqueda()); } catch {}
  prepararBusqueda();
});
$("#sel-pack").addEventListener("change", async (ev) => {
  try {
    await api("/me/profile", { method: "PATCH", body: { pack: ev.target.value } });
    st.config = null;
    aviso("Nicho cambiado. Revisa tu mensaje en Configuración: cada nicho trae el suyo.", "bien");
    await refrescar();
  } catch (err) { aviso(err.message, "critico"); }
});

$("#form-busqueda").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const b = leerBusqueda();
  if (!b.sources.length) return aviso("Marca al menos un sitio donde buscar.", "critico");
  const params = {
    pack: st.estado.pack.slug, countries: b.paises,
    cities: b.cities.split("\n").map((c) => c.trim()).filter(Boolean), radius_km: b.radius_km,
    keywords: b.keywords.split(",").map((k) => k.trim()).filter(Boolean),
    sources: b.sources, include_companies: b.include_companies, max_webs: b.max_webs,
  };
  await lanzarBusqueda(params);
});

async function lanzarBusqueda(params) {
  try {
    $("#btn-iniciar").disabled = true;
    await api("/searches", { method: "POST", body: params });
    mostrar("empresas");
    await refrescar();
  } catch (err) {
    aviso(err.message, "critico");
  } finally {
    $("#btn-iniciar").disabled = false;
  }
}

const detener = async () => {
  const s = st.estado && st.estado.search;
  if (!s) return;
  try { await api(`/searches/${s.id}/cancel`, { method: "POST", body: {} }); aviso("Deteniendo… (termina las webs que está leyendo; lo encontrado se conserva)"); refrescar(); }
  catch (err) { aviso(err.message, "critico"); }
};
$("#btn-detener").addEventListener("click", detener);
$("#btn-detener-2").addEventListener("click", detener);
$("#btn-seguir-rastreo").addEventListener("click", () => {
  const p = { ...st.estado.search.params, sources: ["companies"] };
  lanzarBusqueda(p);
});

// ------------------------------------------------------------ progreso en directo (pestaña Empresas)

function pintarTarjetaRastreo(e) {
  const s = e.search, tarjeta = $("#tarjeta-rastreo");
  tarjeta.hidden = !s;
  if (!s) return;
  const stats = s.stats || {}, prog = stats.progress || {}, f = prog.found || {}, crawl = stats.crawl || {};
  const vivo = buscando(e);
  const pendientes = crawl.pending_after || 0;
  $("#rastreo-titulo").textContent = s.status === "cancelling" ? "Deteniendo…" : vivo ? (prog.phase || "Preparando") + "…"
    : s.status === "cancelled" ? "Búsqueda detenida" : s.status === "error" ? "La búsqueda falló" : "Búsqueda terminada";
  $("#rastreo-sub").textContent = vivo
    ? (prog.total ? `${prog.done} de ${prog.total} · no se envía nada hasta que tú lo decidas` : "Leyendo las fuentes…")
    : s.status === "error" ? s.error
    : `${stats.results || 0} resultados` + (crawl.crawled ? ` · ${crawl.crawled} webs rastreadas` : "") +
      (pendientes ? ` · quedan ${pendientes} webs por rastrear` : "") + ". Marca a quién quieres escribir y pulsa «Enviar».";
  $("#rastreo-pista").hidden = !vivo;
  const barra = $("#rastreo-barra");
  barra.classList.toggle("indeterminado", vivo && !prog.total);
  barra.style.width = prog.total ? (prog.done / prog.total) * 100 + "%" : "0";
  $("#btn-detener-2").hidden = !vivo;
  const seguir = $("#btn-seguir-rastreo");
  seguir.hidden = vivo || !pendientes;
  seguir.textContent = `Seguir rastreando (${pendientes})`;

  $("#rastreo-contadores").innerHTML = [
    [stats.results || 0, "resultados"], [crawl.crawled ?? (prog.phase === "Rastreando webs" ? prog.done : 0), "webs rastreadas"],
    [f.emails || 0, "con email"], [f.careers || 0, "con página de empleo"], [f.mentions || 0, `${icono()} mencionan lo que buscas`],
    [f.warnings || 0, "⚠ con avisos"], [f.blocked || 0, "bloquean programas"],
  ].map(([n, t]) => `<span><b>${n}</b> ${t}</span>`).join("");
  $("#rastreo-ahora").innerHTML = vivo && (prog.now || []).length
    ? `<span class="pequeno secundario">Ahora:</span>` + prog.now.map((x) => `<span class="chip-vivo">${esc(x)}</span>`).join("")
    : "";
  $("#rastreo-ultimos").innerHTML = (vivo ? prog.recent || [] : []).slice(0, 8)
    .map((x) => `<div class="fila-res"><span>${esc(x.name)}</span><span>${esc(x.summary)}</span></div>`).join("");
}

// ------------------------------------------------------------ tabla de empresas y ofertas

const claveSel = () => "knok-sel-" + (st.estado ? st.estado.profile.mode : "");
function cargarSeleccion() { st.sel = new Set(leerLocal(claveSel()) || []); }
function guardarSeleccion() { guardarLocal(claveSel(), [...st.sel]); }

async function cargarTabla() {
  if (st.tablaCargando) return;
  st.tablaCargando = true;
  try {
    const r = await api("/panel/board");
    if (!st.selModo || st.selModo !== r.mode) { st.selModo = r.mode; cargarSeleccion(); }
    st.filas = r.items;
    st.ultimaTabla = Date.now();
    // Lo ya enviado o descartado sale de la selección
    const porClave = new Map(st.filas.map((x) => [x.key, x]));
    for (const k of [...st.sel]) { const x = porClave.get(k); if (!x || !seleccionable(x)) st.sel.delete(k); }
    guardarSeleccion();
    pintarTabla();
  } catch (err) {
    if (st.vista === "empresas") aviso(err.message, "critico");
  } finally {
    st.tablaCargando = false;
  }
}

const seleccionable = (x) => ABIERTOS.includes(x.status) && x.route !== "manual" && (x.route !== "email" || !!x.email);
const conAvisos = (x) => (x.warnings || []).length > 0;
const recomendada = (x) => seleccionable(x) && !conAvisos(x) && !x.blocked &&
  ((x.mentions || []).length > 0 || (x.signals || []).length > 0 || (x.reasons || []).some((r) => /preferido/.test(r)) ||
   (x.kind === "job" && x.route !== "email") || (x.kind === "job" && /^(jobs?|careers?|empleo|rrhh|hr|recruit|talent|seleccion)/i.test(x.email || "")));

function filasVisibles() {
  const texto = $("#filtro-texto").value.trim().toLowerCase();
  const estado = $("#filtro-estado").value, tipo = $("#filtro-tipo").value, via = $("#filtro-via").value;
  const pais = $("#filtro-pais").value, mencion = $("#filtro-mencion").value;
  const cumpleEstado = (x) =>
    !estado ? true
      : estado === "elegibles" ? seleccionable(x)
      : estado === "seleccionadas" ? st.sel.has(x.key)
      : estado === "enviadas" ? ["sent", "replied", "interview"].includes(x.status)
      : estado === "respondidas" ? ["replied", "interview"].includes(x.status)
      : estado === "menciones" ? (x.mentions || []).length > 0
      : estado === "senales" ? (x.signals || []).length > 0
      : estado === "con_empleo" ? !!x.careers_url
      : estado === "avisos" ? conAvisos(x)
      : estado === "sin_avisos" ? !conAvisos(x)
      : estado === "sin_rastrear" ? x.kind === "company" && !x.crawled && !!x.website
      : estado === "bloqueada" ? !!x.blocked
      : x.status === estado;
  const cumpleTipo = (x) => !tipo ? true : tipo === "job" ? x.kind === "job" : tipo === "agency" ? x.kind === "company" && x.company_kind === "agency" : x.kind === "company" && x.company_kind !== "agency";
  return st.filas.filter((x) => cumpleEstado(x) && cumpleTipo(x) && (!via || x.route === via) && (!pais || (x.country || "") === pais) &&
    (!mencion || (x.mentions || []).includes(mencion)) &&
    (!texto || `${x.name} ${x.title} ${x.sector} ${x.email} ${x.city}`.toLowerCase().includes(texto)));
}

function chipsAvisos(x) {
  return (x.warnings || []).map((a) => {
    const i = AVISOS[a.type] || { txt: a.type, clase: "", ayuda: "" };
    return ` <span class="chip-aviso ${i.clase}" title="${esc(i.ayuda + (a.text ? "\n\n«" + a.text + "»" : ""))}">⚠ ${esc(i.txt)}</span>`;
  }).join("");
}

const MAX_FILAS = 400;

function pintarTabla() {
  const selPais = $("#filtro-pais"), pais = selPais.value;
  const paises = [...new Set(st.filas.map((x) => x.country || ""))].sort((a, b) => nombrePais(a).localeCompare(nombrePais(b)));
  selPais.innerHTML = `<option value="">Todos los países</option>` + paises.map((p) => `<option value="${esc(p)}" ${p === pais ? "selected" : ""}>${esc(nombrePais(p))} (${st.filas.filter((x) => (x.country || "") === p).length})</option>`).join("");
  const selMen = $("#filtro-mencion"), men = selMen.value, cuenta = {};
  st.filas.forEach((x) => (x.mentions || []).forEach((t) => (cuenta[t] = (cuenta[t] || 0) + 1)));
  selMen.innerHTML = `<option value="">Menciona: cualquier cosa</option>` +
    Object.entries(cuenta).sort((a, b) => b[1] - a[1]).map(([t, n]) => `<option value="${esc(t)}" ${t === men ? "selected" : ""}>${icono()} “${esc(t)}” (${n})</option>`).join("");

  const filas = filasVisibles();
  $("#empresas-vacio").hidden = st.filas.length > 0;
  $("#empresas-mas").hidden = filas.length <= MAX_FILAS;
  $("#empresas-mas").textContent = `Mostrando ${MAX_FILAS} de ${filas.length}. Usa los filtros para ver las demás.`;
  pintarBarraEnvio();
  const elegibles = filas.filter(seleccionable);
  const todas = $("#check-todas");
  todas.checked = elegibles.length > 0 && elegibles.every((x) => st.sel.has(x.key));
  todas.indeterminate = !todas.checked && elegibles.some((x) => st.sel.has(x.key));
  const enCurso = new Set(((st.estado && st.estado.search && st.estado.search.stats.progress) || {}).now || []);

  $("#tabla-empresas").innerHTML = filas.slice(0, MAX_FILAS).map((x) => {
    const sel = st.sel.has(x.key);
    const nombre = x.name || x.title || "(sin nombre)";
    const menciones = x.mentions || [];
    const estado = buscando(st.estado) && enCurso.has(x.name) && x.kind === "company"
      ? `<span class="estado estado-rastreando">Rastreando su web…</span>`
      : estadoHtml(x.status) + (x.reply ? " · " + cat(x.reply) : "") + (x.follow_up_due ? ` <span class="chip-aviso" title="Ha pasado el plazo sin respuesta">seguimiento</span>` : "");
    return `
    <tr data-key="${esc(x.key)}" class="${sel ? "seleccionada" : ""} ${conAvisos(x) ? "con-aviso" : ""}">
      <td class="col-check">${seleccionable(x) ? `<input type="checkbox" data-sel="${esc(x.key)}" ${sel ? "checked" : ""} title="Enviarle la candidatura">` : ""}</td>
      <td><div class="celda-nombre">${avatar(nombre, x.reply)}<span>
        <span class="nombre" data-ver="${esc(x.key)}">${esc(nombre)}</span>
        ${x.score != null ? `<span class="puntos" title="Puntuación: ${esc((x.reasons || []).join(" · "))}">${x.score}</span>` : ""}
        ${x.title ? `<span class="subtitulo-fila">${esc(x.title)}${x.city ? " · " + esc(x.city) : ""}</span>` : ""}
        ${x.website ? ` <a href="${urlSegura(x.website)}" target="_blank" rel="noopener" class="pequeno">web</a>` : ""}
        ${x.careers_url ? ` · <a href="${urlSegura(x.careers_url)}" target="_blank" rel="noopener" class="pequeno" title="Su página de empleo">empleo</a>` : ""}
        ${x.job_url ? ` · <a href="${urlSegura(x.job_url)}" target="_blank" rel="noopener" class="pequeno">oferta</a>` : ""}
        ${menciones.length ? ` <span class="chip-cadetes" title="Su web menciona: ${esc(menciones.join(", "))}">${icono()} ${esc(menciones[0])}${menciones.length > 1 ? ` +${menciones.length - 1}` : ""}</span>` : ""}
        ${(x.signals || []).length ? ` <span class="chip-senal" title="${esc(x.signals.join(", "))}">${esc(x.signals[0])}</span>` : ""}
        ${chipsAvisos(x)}
        ${x.blocked ? ` <span class="chip-bloqueada" title="Su web no deja leerla a programas: ábrela tú">web bloquea</span>` : ""}</span></div></td>
      <td title="${esc(x.city)}"><span class="tipo-chip">${esc((x.country || "—").toUpperCase())}</span></td>
      <td><span class="tipo-chip">${x.kind === "job" ? "Oferta" : x.company_kind === "agency" ? "Agencia" : "Empresa"}</span></td>
      <td>${viaHtml(x.route)}</td>
      <td class="contacto" title="${esc(x.email)}">${x.email ? esc(x.email) : x.route !== "email" && x.apply_url ? `<a href="${urlSegura(x.apply_url)}" target="_blank" rel="noopener" class="pequeno">${x.route === "manual" ? "abrir enlace" : "abrir formulario"}</a>` : '<span class="secundario pequeno">—</span>'}</td>
      <td>${estado}</td>
      <td class="acciones-fila">
        <button class="btn mini" data-ver="${esc(x.key)}">Ver</button>
        ${ABIERTOS.includes(x.status) ? `<button class="btn mini" data-descartar="${esc(x.key)}">Descartar</button>` : ""}
      </td>
    </tr>`;
  }).join("");
}

["#filtro-texto", "#filtro-estado", "#filtro-tipo", "#filtro-via", "#filtro-pais", "#filtro-mencion"].forEach((s) => $(s).addEventListener("input", pintarTabla));

function seleccionar(claves, valor) {
  const porClave = new Map(st.filas.map((x) => [x.key, x]));
  for (const k of claves) {
    const x = porClave.get(k);
    if (valor && x && seleccionable(x)) st.sel.add(k); else st.sel.delete(k);
  }
  guardarSeleccion();
  pintarTabla();
  if (st.estado) pintarCabecera(st.estado);
}

function seleccionadas() { return st.filas.filter((x) => st.sel.has(x.key) && seleccionable(x)); }

function pintarBarraEnvio() {
  const e = st.estado;
  const sel = seleccionadas(), n = sel.length;
  $("#sel-num").textContent = n === 1 ? "1 seleccionada" : `${n} seleccionadas`;
  const btn = $("#btn-enviar");
  btn.disabled = !n || !e;
  $("#btn-descartar-sel").disabled = !n;
  if (!e) return;
  const modo = e.profile.mode;
  btn.textContent = !n ? "Enviar" : modo === "test" ? `Enviar ${n} (te llegan a ti)` : modo === "simulation" ? `Enviar ${n} (simulado)` : `Enviar ${n} de verdad`;
  const formularios = sel.filter((x) => x.route !== "email").length;
  $("#sel-ayuda").textContent = !n
    ? "Marca las casillas de las empresas y ofertas a las que quieres escribir, o pulsa «Seleccionar recomendadas»."
    : (modo === "live" ? "Se enviarán de verdad, con una pausa entre correos." : modo === "test" ? "Modo prueba: las empresas son reales, pero el correo te llega a ti, nunca a ellas." : "Simulación: no sale nada. Revisa cada una con «Ver» antes de enviar.") +
      (formularios ? ` ${formularios} con formulario: quedarán listas para que la extensión las rellene.` : "");
}

$("#tabla-empresas").addEventListener("change", (ev) => {
  const c = ev.target.closest("[data-sel]");
  if (c) seleccionar([c.dataset.sel], c.checked);
});
$("#check-todas").addEventListener("change", (ev) => seleccionar(filasVisibles().filter(seleccionable).map((x) => x.key), ev.target.checked));
$("#btn-sel-recomendadas").addEventListener("click", () => {
  const claves = st.filas.filter(recomendada).map((x) => x.key);
  if (!claves.length) return aviso("No hay recomendadas todavía: ninguna menciona lo que buscas ni tiene un buzón de empleo. Elige tú a mano.");
  seleccionar(claves, true);
  aviso(`${claves.length} seleccionadas: las que encajan mejor y no tienen avisos.`, "bien");
});
$("#btn-sel-ninguna").addEventListener("click", () => seleccionar([...st.sel], false));

function idsDe(filas) {
  return { result_ids: filas.filter((x) => !x.application_id).map((x) => x.result_id), application_ids: filas.filter((x) => x.application_id).map((x) => x.application_id) };
}

$("#btn-descartar-sel").addEventListener("click", async () => {
  const sel = seleccionadas();
  if (!confirm(`¿Descartar ${sel.length}? No volverán a salir en las búsquedas.`)) return;
  try {
    await api("/panel/discard", { method: "POST", body: idsDe(sel) });
    seleccionar(sel.map((x) => x.key), false);
    cargarTabla(); refrescar();
  } catch (err) { aviso(err.message, "critico"); }
});

$("#btn-enviar").addEventListener("click", () => enviar(seleccionadas()));

async function enviar(filas) {
  const e = st.estado, n = filas.length;
  if (!n) return;
  const conAviso = filas.filter(conAvisos);
  if (conAviso.length && !confirm(`⚠ ${conAviso.length} de las seleccionadas tienen avisos:\n\n` +
      conAviso.slice(0, 12).map((x) => `• ${x.name}: ${(x.warnings || []).map((a) => (AVISOS[a.type] || {}).txt || a.type).join(", ")}`).join("\n") +
      `\n\n¿Seguro que quieres escribirles?`)) return;
  const texto = e.profile.mode === "live"
    ? `MODO REAL: se enviará tu candidatura de verdad a ${n === 1 ? "esta empresa" : `estas ${n}`}.\n\n¿Has revisado tu mensaje y tus adjuntos?`
    : e.profile.mode === "test"
      ? `Modo prueba: se enviarán ${n} correos, pero todos llegarán a TU email.\n\n¿Continuar?`
      : `Simulación: no sale nada de verdad. ¿Simular el envío a ${n === 1 ? "esta" : `estas ${n}`}?`;
  if (!confirm(texto)) return;
  $("#btn-enviar").disabled = true;
  try {
    const r = await api("/panel/send", { method: "POST", body: idsDe(filas) });
    seleccionar(filas.map((x) => x.key), false);
    mostrarResultadoEnvio(r.results);
  } catch (err) {
    aviso(err.message, "critico");
  } finally {
    cargarTabla(); refrescar();
  }
}

function mostrarResultadoEnvio(res) {
  const grupos = { cola: [], form: [], hecho: [], enlace: [], bloq: [] };
  for (const r of res) {
    if (r.outcome === "email_queued") grupos.cola.push(r);
    else if (r.outcome === "ready_for_extension") grupos.form.push(r);
    else if (["submitted", "submitted_simulated"].includes(r.outcome)) grupos.hecho.push(r);
    else if (r.outcome === "open_link") grupos.enlace.push(r);
    else grupos.bloq.push(r);
  }
  const nombre = (r) => esc(r.company || r.title || "#" + r.id) + (r.title && r.company ? ` <span class="secundario">· ${esc(r.title)}</span>` : "");
  const modo = st.estado.profile.mode;
  $("#dialogo-titulo").textContent = "Candidaturas confirmadas";
  $("#dialogo-cuerpo").innerHTML = `
    ${grupos.cola.length ? `<div class="grupo-envio"><h3>✓ ${grupos.cola.length} ${grupos.cola.length === 1 ? "correo" : "correos"} ${modo === "simulation" ? "simulados" : "en cola"}</h3>
      <p class="secundario pequeno">${modo === "simulation" ? "No sale nada: en unos segundos llegarán respuestas inventadas para que pruebes." : `Salen solos con una pausa de ${st.estado.profile.pause_seconds} s entre ellos${modo === "test" ? ", todos a tu propio email" : ""}. Puedes cerrar esta ventana.`}</p>
      <ul class="resultado-envio">${grupos.cola.map((r) => `<li>${nombre(r)}</li>`).join("")}</ul></div>` : ""}
    ${grupos.form.length ? `<div class="grupo-envio"><h3>📝 ${grupos.form.length} con formulario</h3>
      <p class="secundario pequeno">Abre cada formulario con la extensión de knok instalada en Chrome: rellenará los campos con tu perfil y tu banco de respuestas. Revisa y pulsa <b>Enviar</b> en la web. Después márcala como enviada.</p>
      <ul class="resultado-envio">${grupos.form.map((r) => `<li class="fila-entre">${nombre(r)} <span>${r.apply_url ? `<a class="btn mini" href="${urlSegura(r.apply_url)}" target="_blank" rel="noopener">Abrir formulario</a>` : ""} <button class="btn mini" data-marcar-enviada="${r.id}">Marcar enviada</button></span></li>`).join("")}</ul></div>` : ""}
    ${grupos.hecho.length ? `<div class="grupo-envio"><h3>✓ ${grupos.hecho.length} por InfoJobs</h3><ul class="resultado-envio">${grupos.hecho.map((r) => `<li>${nombre(r)}</li>`).join("")}</ul></div>` : ""}
    ${grupos.enlace.length ? `<div class="grupo-envio"><h3>${grupos.enlace.length} a mano</h3><ul class="resultado-envio">${grupos.enlace.map((r) => `<li class="fila-entre">${nombre(r)} <a class="btn mini" href="${urlSegura(r.apply_url)}" target="_blank" rel="noopener">Abrir</a></li>`).join("")}</ul></div>` : ""}
    ${grupos.bloq.length ? `<div class="grupo-envio"><h3>⚠ ${grupos.bloq.length} no se han podido enviar</h3>
      <ul class="resultado-envio">${grupos.bloq.map((r) => `<li>${nombre(r)}<ul class="problemas">${(r.problems || []).map((p) => `<li>${esc(p.message)}</li>`).join("")}</ul></li>`).join("")}</ul>
      <p class="secundario pequeno">Corrígelo (en Configuración o con «Ver» en cada una) y vuelve a enviarlas.</p></div>` : ""}`;
  $("#dialogo").showModal();
}

document.addEventListener("click", async (ev) => {
  const b = ev.target.closest("[data-marcar-enviada]");
  if (!b) return;
  try {
    await api(`/applications/${b.dataset.marcarEnviada}/mark-sent`, { method: "POST", body: {} });
    b.replaceWith(Object.assign(document.createElement("span"), { className: "estado estado-enviado", textContent: "Enviada" }));
    cargarTabla(); refrescar();
  } catch (err) { aviso(err.message, "critico"); }
});

$("#tabla-empresas").addEventListener("click", async (ev) => {
  const ver = ev.target.closest("[data-ver]");
  if (ver) return abrirFicha(ver.dataset.ver);
  const d = ev.target.closest("[data-descartar]");
  if (d) {
    const x = st.filas.find((f) => f.key === d.dataset.descartar);
    try { await api("/panel/discard", { method: "POST", body: idsDe([x]) }); seleccionar([x.key], false); cargarTabla(); refrescar(); }
    catch (err) { aviso(err.message, "critico"); }
  }
});

// ------------------------------------------------------------ ficha: datos, correo editable, formulario y respuestas

async function abrirFicha(clave) {
  let x = st.filas.find((f) => f.key === clave);
  if (!x) { await cargarTabla(); x = st.filas.find((f) => f.key === clave); }
  if (!x) return;
  $("#dialogo-titulo").textContent = x.name || x.title;
  $("#dialogo-cuerpo").innerHTML = `<p class="secundario">Cargando…</p>`;
  if (!$("#dialogo").open) $("#dialogo").showModal();

  let item = null;
  try {
    if (x.application_id) item = await api(`/applications/${x.application_id}`);
    else if (x.route !== "manual") {
      item = (await api("/panel/prepare", { method: "POST", body: { result_ids: [x.result_id] } })).items[0];
      x.application_id = item.id; x.status = item.status;
      cargarTabla();
    }
  } catch (err) { aviso(err.message, "critico"); }

  const avisos = (x.warnings || []).map((a) => {
    const i = AVISOS[a.type] || { txt: a.type, clase: "", ayuda: "" };
    return `<div class="caja-aviso ${i.clase}"><b>⚠ ${esc(i.txt)}.</b> ${esc(i.ayuda)}${a.text ? `<q>${esc(a.text)}</q>` : ""}${a.url ? `<div class="pequeno" style="margin-top:4px">Visto en ${enlace(a.url, "esta página")}</div>` : ""}</div>`;
  }).join("");
  const respuestas = item ? st.respuestas.filter((r) => r.application_id === item.id) : [];
  const abierta = item && ABIERTOS.includes(item.status);
  const rastreo = x.kind !== "company" ? "" : x.blocked ? "Su web no deja leerla a programas: ábrela tú." : x.crawled ? "Rastreada" : x.website ? "Aún no se ha rastreado su web." : "No tiene web.";

  $("#dialogo-cuerpo").innerHTML = `
    ${avisos}
    <dl class="ficha">
      <dt>Estado</dt><dd>${estadoHtml(item ? item.status : x.status)}${x.reply ? " · " + cat(x.reply) : ""}</dd>
      ${x.title ? `<dt>Puesto</dt><dd>${esc(x.title)}${x.job_url ? " · " + enlace(x.job_url, "ver oferta") : ""}</dd>` : ""}
      <dt>Vía</dt><dd>${viaHtml(x.route)} <span class="secundario pequeno">${esc((item && item.route_reason) || (VIAS[x.route] || ["", ""])[1])}</span></dd>
      <dt>País</dt><dd>${esc(nombrePais(x.country))}${x.city ? " · " + esc(x.city) : ""}</dd>
      ${x.sector ? `<dt>Sector</dt><dd>${esc(x.sector)}</dd>` : ""}
      <dt>Web</dt><dd>${enlace(x.website)}</dd>
      <dt>Página de empleo</dt><dd>${enlace(x.careers_url)}</dd>
      <dt>Su web menciona</dt><dd>${(x.mentions || []).length ? x.mentions.map((t) => `<span class="chip-cadetes">${icono()} ${esc(t)}</span>`).join(" ") : x.crawled ? "nada de lo que buscas" : "—"}${(x.signals || []).length ? " " + x.signals.map((t) => `<span class="chip-senal">${esc(t)}</span>`).join(" ") : ""}</dd>
      ${rastreo ? `<dt>Rastreo</dt><dd>${esc(rastreo)}</dd>` : ""}
      ${(x.reasons || []).length ? `<dt>Por qué sale</dt><dd class="secundario">${esc(x.reasons.join(" · "))}</dd>` : ""}
      ${x.source ? `<dt>De dónde sale</dt><dd class="secundario">${esc(x.source)}</dd>` : ""}
    </dl>
    <div class="fila">
      ${seleccionable({ ...x, status: item ? item.status : x.status }) ? `<button class="btn ${st.sel.has(x.key) ? "" : "primario"}" id="ficha-sel">${st.sel.has(x.key) ? "Quitar de la selección" : "☑ Seleccionar para enviar"}</button>` : ""}
      ${abierta && x.route !== "manual" ? `<button class="btn" id="ficha-enviar">Enviar solo esta</button>` : ""}
      ${(x.route !== "email" && item && ["prepared", "confirmed", "error"].includes(item.status)) || (!item && x.route === "manual") ? `${x.apply_url ? `<a class="btn" href="${urlSegura(x.apply_url)}" target="_blank" rel="noopener">Abrir ${x.route === "manual" ? "enlace" : "formulario"}</a>` : ""}` : ""}
      ${item && ["prepared", "confirmed", "error"].includes(item.status) && x.route !== "email" ? `<button class="btn" id="ficha-marcar">Marcar como enviada</button>` : ""}
      ${item && ["sent", "replied", "interview"].includes(item.status) ? `<button class="btn" id="ficha-anotar">Anotar respuesta</button>` : ""}
      ${(item ? abierta : x.status === "new") ? `<button class="btn" id="ficha-descartar">Descartar</button>` : ""}
    </div>
    ${item ? bloqueCandidatura(item) : ""}
    ${respuestas.length ? `<h3 style="margin:18px 0 0">Respuestas</h3>` + respuestas.map((r) => `<div class="hilo-item"><div class="meta"><b>${esc(r.from)}</b> · ${esc(fecha(r.received_at))} · ${cat(r.category, true)}</div><div class="cuerpo-msg">${esc(r.body)}</div></div>`).join("") : ""}
    <div id="ficha-anotar-form"></div>`;

  const on = (sel, fn) => { const el = $(sel, $("#dialogo-cuerpo")); if (el) el.addEventListener("click", fn); };
  on("#ficha-sel", () => { seleccionar([x.key], !st.sel.has(x.key)); abrirFicha(x.key); });
  on("#ficha-descartar", async () => {
    try { await api("/panel/discard", { method: "POST", body: idsDe([x]) }); $("#dialogo").close(); seleccionar([x.key], false); cargarTabla(); refrescar(); }
    catch (err) { aviso(err.message, "critico"); }
  });
  on("#ficha-marcar", async () => {
    try { await api(`/applications/${item.id}/mark-sent`, { method: "POST", body: {} }); await cargarTabla(); abrirFicha(x.key); refrescar(); }
    catch (err) { aviso(err.message, "critico"); }
  });
  on("#ficha-enviar", async () => {
    if (item && item.email && !(await guardarCorreo(item))) return;
    await enviar([{ ...x, application_id: item ? item.id : x.application_id }]);
  });
  on("#ficha-guardar", async () => { if (await guardarCorreo(item)) { aviso("Cambios guardados.", "bien"); abrirFicha(x.key); } });
  on("#ficha-anotar", () => formularioRespuesta(item.id, x.key));
}

function bloqueCandidatura(item) {
  const bloqueos = (item.blocking || []).filter((p) => p.code !== "manual");
  const problemas = bloqueos.length ? `<ul class="problemas">${bloqueos.map((p) => `<li>${esc(p.message)}</li>`).join("")}</ul>` : "";
  if (item.email) {
    const nombres = (item.email.attachments || []).map((id) => (st.docs.find((d) => d.id === id) || {}).filename).filter(Boolean);
    const editable = ABIERTOS.includes(item.status);
    const modo = st.estado.profile.mode;
    return `<h3 style="margin:18px 0 6px">${editable ? "Correo que recibirá" : "Tu correo"}</h3>${problemas}
      <div class="correo-mock pequeno-mock edicion-correo">
        <div class="meta">${modo === "test" ? "Modo prueba: te llega a ti, no a la empresa · " : modo === "simulation" ? "Simulación: no sale nada · " : ""}en ${esc(IDIOMAS[item.language] || item.language)}</div>
        ${editable ? `
        <label>Para<input id="ed-para" type="email" value="${esc(item.email.to)}"></label>
        <label>Asunto<input id="ed-asunto" value="${esc(item.email.subject)}"></label>
        <label>Mensaje<textarea id="ed-cuerpo" rows="14">${esc(item.email.body)}</textarea></label>
        <div class="fila-entre"><span class="pequeno secundario">Los cambios valen solo para esta empresa. Para todas, edita «Tu mensaje» en Configuración.</span><button class="btn" id="ficha-guardar">Guardar cambios</button></div>`
        : `<div class="meta">Para <b>${esc(item.email.to)}</b>${item.sent_at ? " · " + esc(fecha(item.sent_at)) : ""}</div>
        <div class="correo-asunto">${esc(item.email.subject)}</div><div class="correo-cuerpo">${esc(item.email.body)}</div>`}
        <div class="lista-adjuntos">${nombres.length ? nombres.map((n) => `<div class="adjunto">📎 ${esc(n)}</div>`).join("") : `<div class="adjunto falta">⚠ Sin archivos adjuntos: súbelos en Configuración → Archivos adjuntos</div>`}</div>
      </div>`;
  }
  const campos = item.fields || [];
  return `<h3 style="margin:18px 0 6px">Lo que se rellenará en el formulario</h3>${problemas}
    ${campos.length ? `<table class="lista-campos">${campos.map((f) => {
      const v = f.display || (typeof f.value === "object" && f.value ? f.value.filename || JSON.stringify(f.value) : f.value);
      const falta = f.required && (f.value === null || f.value === "" || f.value === undefined);
      return `<tr class="${f.needs_review ? "revisar" : ""} ${falta ? "falta" : ""}"><td>${esc(f.label)}${f.required ? " *" : ""}</td><td>${falta ? (f.type === "file" ? "falta: sube el archivo en Configuración → Archivos adjuntos" : "falta: contéstala en el formulario") : esc(v ?? "")}</td></tr>`;
    }).join("")}</table>` : `<p class="secundario pequeno">Las preguntas de este formulario se leerán al abrirlo con la extensión: rellenará lo que sepa de tu perfil y tu banco de respuestas.</p>`}
    ${item.cover_letter ? `<details class="original"><summary>Carta de presentación que se usará</summary><pre>${esc(item.cover_letter)}</pre></details>` : ""}`;
}

async function guardarCorreo(item) {
  const para = $("#ed-para"), asunto = $("#ed-asunto"), cuerpo = $("#ed-cuerpo");
  if (!para) return true;
  try {
    await api(`/applications/${item.id}`, { method: "PATCH", body: { contact_email: para.value.trim(), subject: asunto.value, body: cuerpo.value } });
    return true;
  } catch (err) { aviso(err.message, "critico"); return false; }
}

function formularioRespuesta(appId, clave) {
  $("#ficha-anotar-form").innerHTML = `
    <form id="form-anotar" class="tarjeta" style="margin-top:14px">
      <h3>Anotar una respuesta</h3>
      <label>¿Qué te han dicho?<select name="category">${Object.entries(CATEGORIAS).map(([c, k]) => `<option value="${c}">${k.icono} ${k.txt}</option>`).join("")}</select></label>
      <label>Texto (opcional)<textarea name="body" rows="4" placeholder="Pega aquí su respuesta"></textarea></label>
      <div class="fila"><button class="btn primario">Guardar</button></div>
    </form>`;
  $("#form-anotar").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const f = Object.fromEntries(new FormData(ev.target));
    try {
      await api(`/applications/${appId}/replies`, { method: "POST", body: { category: f.category, body: f.body } });
      await refrescar(); await cargarTabla(); abrirFicha(clave);
    } catch (err) { aviso(err.message, "critico"); }
  });
}
$("#dialogo-cerrar").addEventListener("click", () => $("#dialogo").close());

// ------------------------------------------------------------ respuestas

async function cargarRespuestas() {
  st.respuestas = await api("/panel/replies").catch(() => st.respuestas);
  pintarUltimas();
  pintarRespuestas();
}

function pintarUltimas() {
  const ultimas = st.respuestas.slice(0, 6);
  $("#ultimas-respuestas").innerHTML = ultimas.length
    ? ultimas.map((r) => `<li data-abrir="${r.id}">
        ${avatar(r.company || r.from, r.category)}
        <div class="texto"><div class="fila-entre"><span class="nombre">${esc(r.company || r.from)}</span><span class="pequeno secundario">${esc(fecha(r.received_at))}</span></div>
        <div class="extracto">${esc((r.body || r.subject).replace(/\s+/g, " "))}</div></div>
        ${cat(r.category, true)}</li>`).join("")
    : '<li class="vacio" style="cursor:default;display:block">Aún no hay respuestas.</li>';
}
$("#ultimas-respuestas").addEventListener("click", (ev) => {
  const li = ev.target.closest("[data-abrir]");
  if (!li) return;
  mostrar("respuestas");
  seleccionarRespuesta(Number(li.dataset.abrir));
});

function pintarRespuestas() {
  const cuenta = (f) => st.respuestas.filter(f).length;
  const chips = [["todas", "Todas", st.respuestas.length], ["no_leidas", "Sin leer", cuenta((r) => !r.read)],
    ...Object.entries(CATEGORIAS).map(([c, k]) => [c, k.txt, cuenta((r) => r.category === c)])];
  $("#filtro-categorias").innerHTML = chips.map(([v, t, n]) => `<button class="chip ${st.filtroCat === v ? "activo" : ""}" data-cat="${v}">${esc(t)} ${n}</button>`).join("");
  const lista = st.respuestas.filter((r) => st.filtroCat === "todas" || (st.filtroCat === "no_leidas" ? !r.read : r.category === st.filtroCat));
  $("#respuestas-vacio").hidden = lista.length > 0;
  $("#lista-respuestas").innerHTML = lista.map((r) => `
    <li data-id="${r.id}" class="${r.read ? "" : "no-leida"} ${r.id === st.respuestaSel ? "seleccionada" : ""}">
      ${avatar(r.company || r.from, r.category)}
      <div class="texto">
        <div class="cabecera-msg"><span class="nombre">${esc(r.company || r.from)}</span><span class="secundario pequeno">${esc(fecha(r.received_at))}</span></div>
        <div class="extracto">${esc((r.body || r.subject).replace(/\s+/g, " "))}</div>
        ${cat(r.category, true)}
      </div>
    </li>`).join("");
}
$("#filtro-categorias").addEventListener("click", (ev) => {
  const c = ev.target.closest("[data-cat]");
  if (c) { st.filtroCat = c.dataset.cat; pintarRespuestas(); }
});
$("#lista-respuestas").addEventListener("click", (ev) => {
  const li = ev.target.closest("[data-id]");
  if (li) seleccionarRespuesta(Number(li.dataset.id));
});

async function seleccionarRespuesta(id) {
  st.respuestaSel = id;
  if (!st.respuestas.some((x) => x.id === id)) await cargarRespuestas();
  const r = st.respuestas.find((x) => x.id === id);
  if (!r) return;
  if (!r.read) { r.read = true; api(`/replies/${id}`, { method: "PATCH", body: { read: true } }).then(refrescar).catch(() => {}); }
  pintarRespuestas();
  const simulada = r.source === "simulated";
  const direccion = (r.from.match(/<([^>]+)>/) || [, r.from])[1];
  const responder = `mailto:${encodeURIComponent(direccion)}?subject=${encodeURIComponent(/^re:/i.test(r.subject) ? r.subject : "Re: " + r.subject)}`;
  $("#detalle-respuesta").innerHTML = `
    <div class="cabecera-msg">
      <div class="remitente">${avatar(r.company || r.from, r.category, "grande")}
        <div><div><b>${esc(r.company || r.from)}</b> ${simulada ? '<span class="etiqueta-sim">respuesta simulada</span>' : ""}</div>
        <div class="meta">${esc(r.from)} · ${esc(fecha(r.received_at))}${r.title ? " · " + esc(r.title) : ""}</div></div></div>
      <div class="fila" style="margin:0">
        <select id="cambiar-cat" title="Corregir la clasificación" style="width:auto">${Object.entries(CATEGORIAS).map(([c, k]) => `<option value="${c}" ${c === r.category ? "selected" : ""}>${k.icono} ${k.txt}</option>`).join("")}</select>
        ${simulada || !direccion.includes("@") ? "" : `<a class="btn primario" href="${responder}">Responder</a>`}
      </div>
    </div>
    <h2 style="margin:18px 0 0">${esc(r.subject || "(sin asunto)")}</h2>
    <div class="cuerpo-msg">${esc(r.body || "")}</div>
    <div class="fila">
      ${r.application_id ? `<button class="btn" id="ver-candidatura">Ver la candidatura</button>` : ""}
      <button class="btn" id="marcar-no-leida">Marcar como no leída</button>
    </div>`;
  $("#cambiar-cat").addEventListener("change", async (ev) => {
    try { await api(`/replies/${id}`, { method: "PATCH", body: { category: ev.target.value } }); r.category = ev.target.value; pintarRespuestas(); refrescar(); }
    catch (err) { aviso(err.message, "critico"); }
  });
  $("#marcar-no-leida").addEventListener("click", async () => {
    await api(`/replies/${id}`, { method: "PATCH", body: { read: false } }).catch(() => {});
    r.read = false; pintarRespuestas(); refrescar();
  });
  const ver = $("#ver-candidatura");
  if (ver) ver.addEventListener("click", async () => {
    if (!st.filas.length) await cargarTabla();
    const x = st.filas.find((f) => f.application_id === r.application_id);
    if (x) abrirFicha(x.key); else aviso("Esa candidatura es de otro modo (simulación / prueba / real).");
  });
}

// ------------------------------------------------------------ cuenta de Gmail

function abrirCuenta() {
  const g = st.estado.connections.google;
  const f = $("#form-cuenta");
  f.usuario.value = g.email || (st.estado.profile.email || "");
  f.contrasena.value = "";
  f.contrasena.type = "password";
  $("#ver-clave").textContent = "Mostrar";
  $("#cuenta-resultado").hidden = true;
  $("#cuenta-con-clave").hidden = !g.app_password_allowed;
  $("#cuenta-enviar").hidden = !g.app_password_allowed;
  $("#cuenta-enviar").disabled = false;
  $("#cuenta-oauth").hidden = !g.oauth_configured;
  $("#cuenta-oauth-texto").textContent = g.app_password_allowed
    ? "O, si lo prefieres, conecta con el botón de Google (solo permite enviar; las respuestas las anotarás tú):"
    : "Google te pedirá permiso solo para enviar correos en tu nombre. knok no puede leer tu correo.";
  const sin = $("#cuenta-sin-opciones");
  sin.hidden = g.app_password_allowed || g.oauth_configured;
  sin.textContent = "Para enviar desde esta instalación hace falta configurar el acceso a Gmail: arranca knok con iniciar.bat (modo local, contraseña de aplicación) o pon KNOK_GOOGLE_CLIENT_ID y KNOK_GOOGLE_CLIENT_SECRET en el archivo .env.";
  $("#cuenta-nota-sim").hidden = st.estado.profile.mode !== "simulation";
  $("#dialogo-cuenta").showModal();
}
$("#chip-cuenta").addEventListener("click", abrirCuenta);
$("#btn-conectar").addEventListener("click", abrirCuenta);
$("#ver-clave").addEventListener("click", () => {
  const c = $("#form-cuenta").contrasena;
  c.type = c.type === "password" ? "text" : "password";
  $("#ver-clave").textContent = c.type === "password" ? "Mostrar" : "Ocultar";
});
$("#cuenta-luego").addEventListener("click", () => {
  try { sessionStorage.setItem("cuenta-omitida", "1"); } catch {}
  $("#dialogo-cuenta").close();
});
$("#btn-oauth").addEventListener("click", async () => {
  try {
    const r = await api(`/connections/google/start?return_to=${encodeURIComponent(location.origin + "/")}`);
    location.href = r.url;
  } catch (err) { aviso(err.message, "critico"); }
});
$("#form-cuenta").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const f = ev.target, res = $("#cuenta-resultado");
  if (!f.usuario.value || !f.contrasena.value) { res.hidden = false; res.className = "resultado error"; res.textContent = "Escribe tu Gmail y la contraseña de aplicación."; return; }
  res.hidden = false;
  res.className = "resultado cargando";
  res.textContent = "Probando la conexión con Gmail (envío y lectura)…";
  $("#cuenta-enviar").disabled = true;
  try {
    const c = await api("/connections/google/app-password", { method: "POST", body: { email: f.usuario.value.trim(), password: f.contrasena.value } });
    res.className = "resultado ok";
    res.textContent = `✓ Conectado como ${c.email}. Ya se puede enviar y leer las respuestas.`;
    f.contrasena.value = "";
    await refrescar();
    pintarCuentaConfig();
    setTimeout(() => $("#dialogo-cuenta").close(), 1400);
  } catch (err) {
    res.className = "resultado error";
    res.textContent = err.message;
    $("#cuenta-enviar").disabled = false;
  }
});
$("#btn-desconectar").addEventListener("click", async () => {
  if (!confirm("¿Desconectar la cuenta de Gmail? Se borrará el acceso guardado.")) return;
  await api("/connections/google", { method: "DELETE" }).catch((err) => aviso(err.message, "critico"));
  await refrescar();
  pintarCuentaConfig();
});

function pintarCuentaConfig() {
  const g = st.estado && st.estado.connections.google;
  if (!g) return;
  $("#cuenta-estado").innerHTML = g.connected
    ? `Conectada: <b>${esc(g.email)}</b>${g.method === "app_password" ? " (contraseña de aplicación)" : " (Google, solo envío)"}. Los correos saldrán desde esta cuenta${g.method === "app_password" ? " y aquí se leerán las respuestas" : ""}.`
    : "No hay ninguna cuenta conectada. Hace falta para los modos «Prueba real» y «Real».";
  $("#btn-conectar").textContent = g.connected ? "Cambiar cuenta" : "Conectar Gmail";
  $("#btn-conectar").className = g.connected ? "btn" : "btn primario";
  $("#btn-desconectar").hidden = !g.connected;
}

// ------------------------------------------------------------ configuración

async function cargarConfig() {
  try {
    const [me, pack, tpls, docs, banco] = await Promise.all([
      api("/me"), api(`/packs/${encodeURIComponent(st.estado ? st.estado.pack.slug : "general")}`), api("/me/templates"),
      api("/me/documents"), api("/me/answers"),
    ]);
    st.config = { profile: me.profile, pack, variables: tpls.variables };
    st.docs = docs;
    st.banco = banco;
    st.plantillas = {};
    for (const t of tpls.templates.filter((t) => t.kind === "email")) {
      st.plantillas[t.audience + "|" + t.language] = { subject: t.subject, body: t.body, source: t.source, orig: { subject: t.subject, body: t.body } };
    }
    if (!pack.languages.includes(st.idioma)) st.idioma = pack.languages[0];
  } catch (err) { aviso(err.message, "critico"); return; }

  const p = st.config.profile, f = $("#form-config");
  $$('[name="mode"]', f).forEach((r) => (r.checked = r.value === p.mode));
  for (const k of ["first_name", "last_name", "email", "phone", "city", "daily_limit", "pause_seconds", "followup_days"]) f[k].value = p[k] ?? "";
  f.country.innerHTML = `<option value="">—</option>` + Object.entries(PAISES).sort((a, b) => a[1].localeCompare(b[1])).map(([c, n]) => `<option value="${c}" ${c === p.country ? "selected" : ""}>${esc(n)}</option>`).join("");
  f["links.linkedin"].value = (p.links || {}).linkedin || "";
  f["links.website"].value = (p.links || {}).website || "";

  // Campos propios del nicho (titulación, universidad…), con versión por idioma si el campo lo admite
  const langs = st.config.pack.languages;
  $("#campos-pack").innerHTML = st.config.pack.profile_fields.map((c) => {
    const etiqueta = c.label.es || c.label.en || c.key;
    const campo = (nombre, texto, ph = "") => c.type === "textarea"
      ? `<label>${esc(texto)}<textarea name="${nombre}" rows="3">${esc((p.pack_data || {})[nombre.slice(10)] || "")}</textarea></label>`
      : c.type === "select" ? `<label>${esc(texto)}<select name="${nombre}"><option value=""></option>${c.options.map((o) => `<option ${o === (p.pack_data || {})[nombre.slice(10)] ? "selected" : ""}>${esc(o)}</option>`).join("")}</select></label>`
      : `<label>${esc(texto)}<input name="${nombre}" ${c.type === "number" ? 'type="number"' : ""} value="${esc((p.pack_data || {})[nombre.slice(10)] ?? "")}" placeholder="${esc(ph)}"></label>`;
    return campo(`pack_data.${c.key}`, etiqueta) + (c.localized ? langs.filter((l) => l !== langs[0]).map((l) =>
      campo(`pack_data.${c.key}_${l}`, `${etiqueta} en ${IDIOMAS_ES[l] || l} (para los correos en ${IDIOMAS_ES[l] || l})`)).join("") : "");
  }).join("");

  // Banco de respuestas
  $("#campos-banco").innerHTML = st.banco.map((k) => {
    const v = (k.values || {})["*"];
    const nombre = `banco.${k.key}`;
    const etiqueta = `${esc(k.label.es || k.key)}${k.sensitive ? ' <span class="sensible" title="Dato sensible: solo se usa si lo guardas tú">· sensible</span>' : ""}`;
    if (k.type === "boolean") return `<label class="campo-banco">${etiqueta}<select name="${nombre}"><option value="">—</option><option value="true" ${v === true ? "selected" : ""}>Sí</option><option value="false" ${v === false ? "selected" : ""}>No</option></select></label>`;
    if (k.type === "choice" || (k.options || []).length) return `<label class="campo-banco">${etiqueta}<select name="${nombre}"><option value="">—</option>${k.options.map((o) => `<option ${o === v ? "selected" : ""}>${esc(o)}</option>`).join("")}</select></label>`;
    if (k.type === "textarea") return `<label class="campo-banco">${etiqueta}<textarea name="${nombre}" rows="3">${esc(v ?? "")}</textarea></label>`;
    return `<label class="campo-banco">${etiqueta}<input name="${nombre}" ${k.type === "number" ? 'type="number"' : ""} value="${esc(v ?? "")}"></label>`;
  }).join("");

  $("#selector-idioma").innerHTML = langs.map((l) => `<button type="button" data-idioma="${l}" class="${l === st.idioma ? "activo" : ""}">${esc(IDIOMAS[l] || l)}</button>`).join("");
  $("#insertar-vars").innerHTML = `<span class="pequeno secundario">Insertar:</span>` + st.config.variables
    .filter((v) => v !== "asunto" && v !== "nombre_pila" && v !== "apellidos")
    .map((v) => `<button type="button" class="var" data-var="${esc(v)}">${esc(etiquetaVar(v))}</button>`).join("");
  $("#ayuda-adjuntos").innerHTML = `Tu CV y lo que quieras enviar (certificados, cartas…). A cada empresa se le envían los archivos del idioma de su correo y los de «Todos los idiomas»${langs.includes("es") ? ": español a las de España (y países hispanohablantes), inglés al resto" : ""}. Se guardan solo en tu ordenador.`;
  marcarSucio(false);
  pintarCuentaConfig();
  mostrarPlantilla();
  pintarAdjuntos();
}

function etiquetaVar(v) {
  if (NOMBRES_VAR[v]) return NOMBRES_VAR[v];
  const c = st.config && st.config.pack.profile_fields.find((f) => f.key === v);
  return c ? c.label.es || v : v;
}

function marcarSucio(sucio) {
  st.sucio = sucio;
  const e = $("#estado-guardado");
  e.className = "pequeno" + (sucio ? " pendiente" : "");
  e.textContent = sucio ? "Cambios sin guardar" : "";
}
$("#form-config").addEventListener("input", (ev) => {
  if (ev.target.id === "input-adjuntos") return;
  if (ev.target.id === "tpl-asunto" || ev.target.id === "tpl-cuerpo") {
    const t = plantillaActual();
    t.subject = $("#tpl-asunto").value;
    t.body = $("#tpl-cuerpo").value;
  }
  marcarSucio(true);
  pintarPrevia();
});
window.addEventListener("beforeunload", (ev) => { if (st.sucio) ev.preventDefault(); });

// --- editor del mensaje (por idioma y por tipo de destinatario)

function plantillaActual() {
  const k = st.audiencia + "|" + st.idioma;
  if (!st.plantillas[k]) {
    const base = st.plantillas["company|" + st.idioma] || { subject: "", body: "" };
    st.plantillas[k] = { subject: base.subject, body: base.body, source: "none", orig: { subject: base.subject, body: base.body } };
  }
  return st.plantillas[k];
}

function mostrarPlantilla() {
  $$("#selector-idioma button").forEach((x) => x.classList.toggle("activo", x.dataset.idioma === st.idioma));
  $$("#selector-plantilla button").forEach((x) => x.classList.toggle("activo", x.dataset.plantilla === st.audiencia));
  const t = plantillaActual();
  $("#tpl-asunto").value = t.subject;
  $("#tpl-cuerpo").value = t.body;
  const para = { company: "empresas (sin oferta publicada)", agency: "agencias de empleo o tripulación", job: "ofertas publicadas" }[st.audiencia];
  $("#etq-mensaje").textContent = `Mensaje para ${para}${st.idioma !== "es" ? ` (en ${IDIOMAS_ES[st.idioma] || st.idioma})` : ""}`;
  $("#ayuda-plantilla").textContent = st.audiencia === "job"
    ? "Se usa cuando respondes a una oferta concreta: {puesto} es el título de la oferta."
    : st.audiencia === "agency" ? "Se usa con las agencias (de selección, de tripulación…)." : "Se usa para escribir a una empresa aunque no tenga ofertas publicadas.";
  $("#tpl-origen").textContent = t.source === "user" ? "Mensaje tuyo" : t.source === "pack" ? "Mensaje original del nicho" : "Aún no hay un mensaje específico: se usa el de empresas";
  st.ultimoCampo = $("#tpl-cuerpo");
  pintarPrevia();
}
$("#selector-idioma").addEventListener("click", (ev) => {
  const b = ev.target.closest("[data-idioma]");
  if (b) { st.idioma = b.dataset.idioma; mostrarPlantilla(); }
});
$("#selector-plantilla").addEventListener("click", (ev) => {
  const b = ev.target.closest("[data-plantilla]");
  if (b) { st.audiencia = b.dataset.plantilla; mostrarPlantilla(); }
});
$$("[data-editable]").forEach((el) => el.addEventListener("focus", () => (st.ultimoCampo = el)));
$("#insertar-vars").addEventListener("mousedown", (ev) => ev.preventDefault());
$("#insertar-vars").addEventListener("click", (ev) => {
  const b = ev.target.closest("[data-var]");
  if (!b) return;
  const campo = st.ultimoCampo || $("#tpl-cuerpo");
  const texto = `{${b.dataset.var}}`;
  const ini = campo.selectionStart ?? campo.value.length, fin = campo.selectionEnd ?? ini;
  campo.focus();
  campo.setRangeText(texto, ini, fin, "end");
  campo.dispatchEvent(new Event("input", { bubbles: true }));
});
$("#btn-restaurar").addEventListener("click", async () => {
  const t = plantillaActual();
  if (!confirm("¿Restaurar el asunto y el mensaje originales del nicho? Perderás tus cambios en este texto.")) return;
  try {
    await api(`/me/templates/email/${st.audiencia}/${st.idioma}`, { method: "DELETE" });
    const tpls = await api("/me/templates");
    const orig = tpls.templates.find((x) => x.kind === "email" && x.audience === st.audiencia && x.language === st.idioma)
      || tpls.templates.find((x) => x.kind === "email" && x.audience === "company" && x.language === st.idioma);
    Object.assign(t, { subject: orig ? orig.subject : "", body: orig ? orig.body : "", source: orig ? orig.source : "none" });
    t.orig = { subject: t.subject, body: t.body };
    mostrarPlantilla();
    aviso("Mensaje original restaurado.", "bien");
  } catch (err) { aviso(err.message, "critico"); }
});

function valoresPrevia() {
  const f = $("#form-config");
  const ej = (EJEMPLOS[st.estado.pack.slug] || EJEMPLOS._)[st.idioma] || EJEMPLOS._.en;
  const [empresa, sector, ciudad, , puesto] = ej[st.audiencia];
  const v = {
    nombre: [f.first_name.value, f.last_name.value].filter(Boolean).join(" ").trim(), nombre_pila: f.first_name.value,
    apellidos: f.last_name.value, email: f.email.value, telefono: f.phone.value, linkedin: f["links.linkedin"].value,
    web: f["links.website"].value, empresa, puesto: st.audiencia === "job" ? puesto : "", ciudad: ciudad || f.city.value,
    pais: "", sector, asunto: "(asunto original)",
  };
  for (const c of st.config.pack.profile_fields) {
    const loc = f[`pack_data.${c.key}_${st.idioma}`];
    v[c.key] = (loc && loc.value.trim()) || (f[`pack_data.${c.key}`] || { value: "" }).value;
  }
  return v;
}

function rellenarConMarcas(texto, valores) {
  return texto.split(/(\{\w+\})/).map((trozo) => {
    const m = trozo.match(/^\{(\w+)\}$/);
    if (!m) return esc(trozo);
    const clave = m[1];
    if (!(clave in valores)) return `<mark class="desconocida" title="Variable desconocida: no se sustituirá">${esc(trozo)}</mark>`;
    if (!String(valores[clave]).trim()) {
      return OPCIONALES.has(clave)
        ? `<mark class="vacia" title="Vacío: esa línea se quitará del correo">(sin ${esc(etiquetaVar(clave).toLowerCase())})</mark>`
        : `<mark class="desconocida" title="Rellénalo en «Tu perfil»: sin esto no se podrá enviar">falta: ${esc(etiquetaVar(clave).toLowerCase())}</mark>`;
    }
    return `<mark>${esc(valores[clave])}</mark>`;
  }).join("");
}

function pintarPrevia() {
  if (!st.config || !st.estado) return;
  const v = valoresPrevia(), t = plantillaActual();
  const ej = ((EJEMPLOS[st.estado.pack.slug] || EJEMPLOS._)[st.idioma] || EJEMPLOS._.en)[st.audiencia];
  const g = st.estado.connections.google;
  $("#previa-quien").textContent = { company: "una empresa", agency: "una agencia", job: "una empresa con una oferta" }[st.audiencia] + ` (correo en ${IDIOMAS_ES[st.idioma] || st.idioma})`;
  $("#previa-avatar").textContent = iniciales(v.nombre);
  $("#previa-de").textContent = `${v.nombre || "Tu nombre"} <${g.email || v.email || "tu@gmail.com"}>`;
  $("#previa-para").textContent = `${ej[0]} <${ej[3]}>`;
  $("#previa-asunto").innerHTML = rellenarConMarcas(t.subject, v);
  $("#previa-cuerpo").innerHTML = rellenarConMarcas(t.body.replace(/\n{3,}/g, "\n\n").trimEnd(), v);
  const archivos = st.docs.filter((d) => d.language === st.idioma || d.language === "");
  $("#previa-adjuntos").innerHTML = archivos.length
    ? archivos.map((d) => `<div class="adjunto">📎 ${esc(d.filename)}</div>`).join("")
    : `<div class="adjunto falta">⚠ Sin archivos en ${esc(IDIOMAS[st.idioma] || st.idioma)}: súbelos en «Archivos adjuntos»</div>`;
}

// --- guardar

$("#form-config").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const f = ev.target, p = st.config.profile;
  const modo = ($('[name="mode"]:checked', f) || {}).value || p.mode;
  if (modo === "live" && p.mode !== "live" &&
      !confirm("Vas a activar el MODO REAL: al pulsar Enviar, los correos saldrán de verdad hacia las empresas.\n\nTe recomiendo probar antes con «Prueba real». ¿Continuar?")) return;
  const pack_data = {};
  $$('[name^="pack_data."]', f).forEach((el) => (pack_data[el.name.slice(10)] = el.value));
  const cuerpo = {
    mode: modo, first_name: f.first_name.value.trim(), last_name: f.last_name.value.trim(), email: f.email.value.trim(),
    phone: f.phone.value.trim(), city: f.city.value.trim(), country: f.country.value,
    links: { ...(p.links || {}), linkedin: f["links.linkedin"].value.trim(), website: f["links.website"].value.trim() },
    pack_data, daily_limit: Number(f.daily_limit.value) || p.daily_limit, pause_seconds: Number(f.pause_seconds.value) || p.pause_seconds,
    followup_days: Number(f.followup_days.value) || p.followup_days,
  };
  try {
    st.config.profile = await api("/me/profile", { method: "PATCH", body: cuerpo });
    for (const [k, t] of Object.entries(st.plantillas)) {
      if (t.subject === t.orig.subject && t.body === t.orig.body) continue;
      const [aud, lang] = k.split("|");
      if (!t.body.trim()) throw new Error("El mensaje no puede quedar vacío.");
      await api(`/me/templates/email/${aud}/${lang}`, { method: "PUT", body: { subject: t.subject, body: t.body } });
      t.orig = { subject: t.subject, body: t.body };
      t.source = "user";
    }
    for (const k of st.banco) {
      const el = f[`banco.${k.key}`];
      if (!el) continue;
      const antes = (k.values || {})["*"];
      let v = el.value;
      if (k.type === "boolean") v = v === "" ? null : v === "true";
      else if (k.type === "number") v = v === "" ? null : Number(v);
      else if (v === "") v = null;
      if (v === (antes ?? null)) continue;
      if (v === null) await api(`/me/answers/${k.key}`, { method: "DELETE" });
      else await api(`/me/answers/${k.key}`, { method: "PUT", body: { value: v } });
      k.values = { ...(k.values || {}), "*": v };
    }
    marcarSucio(false);
    const e = $("#estado-guardado");
    e.className = "pequeno ok";
    e.textContent = "✓ Guardado";
    mostrarPlantilla();
    refrescar();
  } catch (err) {
    aviso(err.message, "critico");
  }
});

// --- archivos adjuntos (por idioma)

function pintarAdjuntos() {
  if (!st.config) return;
  const columnas = [...st.config.pack.languages, ""];
  $("#cajas-adjuntos").innerHTML = columnas.map((l) => {
    const lista = st.docs.filter((d) => d.language === l);
    const titulo = l ? `${BANDERAS[l] || ""} ${IDIOMAS[l] || l}` : "🌐 Todos los idiomas";
    return `<div class="caja-adjuntos" data-idioma-adj="${l}">
      <div class="fila-entre"><b>${esc(titulo)}</b><button type="button" class="btn mini" data-subir="${l}">+ Subir archivos</button></div>
      <ul class="adjuntos">${lista.length ? lista.map((d) => `<li><span class="n" title="${esc(d.filename)}">📎 ${esc(d.filename)}</span>
        ${d.kind === "cv" ? '<span class="chip-cv">CV</span>' : ""}<span class="pequeno secundario">${tamano(d.size)}</span>
        <button type="button" class="btn mini" data-abrir-doc="${d.id}">Ver</button>
        <button type="button" class="btn mini" data-quitar-doc="${d.id}">Quitar</button></li>`).join("")
        : `<li class="vacio-adj">Aún no hay archivos.</li>`}</ul></div>`;
  }).join("");
  pintarPrevia();
}

async function subirArchivos(idioma, archivos) {
  for (const f of archivos) {
    const datos = new FormData();
    const yaHayCv = st.docs.some((d) => d.kind === "cv" && d.language === idioma);
    datos.append("file", f);
    datos.append("kind", yaHayCv || !/\.(pdf|docx?|odt|rtf)$/i.test(f.name) ? "other" : "cv");
    datos.append("language", idioma);
    try {
      const d = await api("/me/documents", { method: "POST", form: datos });
      st.docs.push(d);
      aviso(`Subido «${d.filename}».`, "bien");
    } catch (err) {
      aviso(`«${f.name}»: ${err.message}`, "critico");
    }
  }
  pintarAdjuntos();
  refrescar();
}

let subirIdioma = "";
document.addEventListener("click", async (ev) => {
  const sub = ev.target.closest("[data-subir]");
  if (sub) { subirIdioma = sub.dataset.subir; $("#input-adjuntos").click(); return; }
  const ab = ev.target.closest("[data-abrir-doc]");
  if (ab) {
    try {
      const r = await fetch(`/me/documents/${ab.dataset.abrirDoc}/file`, { headers: { Authorization: "Bearer " + TOKEN } });
      if (!r.ok) throw new Error("No se pudo abrir");
      window.open(URL.createObjectURL(await r.blob()), "_blank");
    } catch (err) { aviso(err.message, "critico"); }
    return;
  }
  const q = ev.target.closest("[data-quitar-doc]");
  if (q) {
    const d = st.docs.find((x) => x.id === Number(q.dataset.quitarDoc));
    if (!confirm(`¿Quitar «${d.filename}»?`)) return;
    try {
      await api(`/me/documents/${d.id}`, { method: "DELETE" });
      st.docs = st.docs.filter((x) => x.id !== d.id);
      pintarAdjuntos();
      refrescar();
    } catch (err) { aviso(err.message, "critico"); }
  }
});
$("#input-adjuntos").addEventListener("change", (ev) => {
  const archivos = [...ev.target.files];
  ev.target.value = "";
  if (archivos.length) subirArchivos(subirIdioma, archivos);
});
$("#cajas-adjuntos").addEventListener("dragover", (ev) => { const c = ev.target.closest("[data-idioma-adj]"); if (c) { ev.preventDefault(); c.classList.add("soltar"); } });
$("#cajas-adjuntos").addEventListener("dragleave", (ev) => { const c = ev.target.closest("[data-idioma-adj]"); if (c) c.classList.remove("soltar"); });
$("#cajas-adjuntos").addEventListener("drop", (ev) => {
  const c = ev.target.closest("[data-idioma-adj]");
  if (!c) return;
  ev.preventDefault();
  c.classList.remove("soltar");
  const archivos = [...ev.dataTransfer.files];
  if (archivos.length) subirArchivos(c.dataset.idiomaAdj, archivos);
});

// ------------------------------------------------------------ arranque

(async function arrancar() {
  const q = new URLSearchParams(location.search);
  if (q.get("connected") === "google") aviso("Gmail conectado.", "bien");
  if (q.get("error")) aviso("No se pudo conectar: " + q.get("error"), "critico");
  if (q.toString()) history.replaceState(null, "", location.pathname + location.hash);
  if (!TOKEN && !(await sesionLocal())) { pedirLogin(); return; }
  await refrescar();
  if (st.estado) {
    st.selModo = st.estado.profile.mode;
    cargarSeleccion();
    pintarCabecera(st.estado);
  }
  const inicial = location.hash.slice(1);
  mostrar(["panel", "empresas", "respuestas", "config"].includes(inicial) ? inicial : "panel");
})();

$("#btn-exportar").addEventListener("click", async () => {
  try {
    const r = await fetch("/tracking/export.csv", { headers: { Authorization: "Bearer " + TOKEN } });
    if (!r.ok) throw new Error("No se pudo exportar");
    const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(await r.blob()), download: "knok-seguimiento.csv" });
    document.body.append(a); a.click(); a.remove();
  } catch (err) { aviso(err.message, "critico"); }
});
