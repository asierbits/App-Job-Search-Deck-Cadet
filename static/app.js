"use strict";

const $ = (s, raiz = document) => raiz.querySelector(s);
const $$ = (s, raiz = document) => [...raiz.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const MODOS = { simulacion: "Simulación", prueba: "Prueba real", real: "REAL" };
const CATEGORIAS = {
  entrevista: { txt: "Entrevista", icono: "✓" },
  info: { txt: "Piden info", icono: "i" },
  rechazo: { txt: "Rechazo", icono: "✕" },
  automatica: { txt: "Automática", icono: "↻" },
  otra: { txt: "Otra", icono: "•" },
};
const ESTADOS = { nueva: "Pendiente de enviar", sin_email: "Sin email", enviando: "Enviando…", enviado: "Enviado", respondida: "Respondida", descartada: "Descartada", error: "Error" };
const ICONOS = {
  buscar: '<svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>',
  enviar: '<svg viewBox="0 0 24 24"><path d="M22 2 11 13"/><path d="M22 2 15 22l-4-9-9-4z"/></svg>',
  respuesta: '<svg viewBox="0 0 24 24"><path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/></svg>',
  objetivo: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1"/></svg>',
  flecha: '<svg viewBox="0 0 24 24"><path d="M5 12h14"/><path d="m13 6 6 6-6 6"/></svg>',
};
// Empresas de ejemplo para la vista previa del mensaje, por idioma y tipo
const EJEMPLO = {
  es: {
    empresa: { empresa: "Naviera Cantábrica de Ferris", sector: "Ferris", email: "flota@cantabricaferris.example.com", ciudad: "Santander" },
    agencia: { empresa: "Tripulaciones Marítimas del Norte", sector: "Agencia de tripulación", email: "alumnos@tripnorte.example.com", ciudad: "Bilbao" },
  },
  en: {
    empresa: { empresa: "Nordsee Reederei GmbH", sector: "Naviera (carga)", email: "crewing@nordsee-reederei.example.com", ciudad: "Hamburg" },
    agencia: { empresa: "EuroCrew Manning Agency", sector: "Agencia de tripulación", email: "cadets@eurocrew.example.org", ciudad: "Limassol" },
  },
};
const PAISES = {
  es: "España", pt: "Portugal", fr: "Francia", de: "Alemania", it: "Italia", nl: "Países Bajos", be: "Bélgica",
  lu: "Luxemburgo", ie: "Irlanda", gb: "Reino Unido", at: "Austria", ch: "Suiza", dk: "Dinamarca", se: "Suecia",
  no: "Noruega", fi: "Finlandia", is: "Islandia", pl: "Polonia", cz: "Chequia", sk: "Eslovaquia", hu: "Hungría",
  si: "Eslovenia", hr: "Croacia", ro: "Rumanía", bg: "Bulgaria", gr: "Grecia", cy: "Chipre", mt: "Malta",
  ee: "Estonia", lv: "Letonia", lt: "Lituania", rs: "Serbia", ad: "Andorra", mc: "Mónaco",
};
// Las webs vienen de OpenStreetMap (editable por cualquiera): solo enlaces http(s), nunca "javascript:"
function urlSegura(u) {
  u = String(u || "").trim();
  if (!u) return "";
  if (!/^https?:\/\//i.test(u)) u = "https://" + u.replace(/^[a-z]+:\/*/i, "");
  return esc(u);
}
const nombrePais = (c) => PAISES[c] || (c ? c.toUpperCase() : "—");
function listaCiudades(ciudades) {
  if (ciudades.length <= 2) return ciudades.join(" y ");
  return `${ciudades.slice(0, 2).join(", ")} y ${ciudades.length - 2} más`;
}
const NOMBRES_VAR = { empresa: "empresa", nombre: "tu nombre", titulacion: "titulación", universidad: "universidad", telefono: "teléfono", linkedin: "LinkedIn", ciudad: "ciudad", sector: "sector", email: "email" };

const st = {
  vista: "panel",
  modo: null,
  estado: null,
  empresas: [],
  respuestas: [],
  ultimoEvento: 0,
  firma: "",
  firmaGrafico: "",
  filtroCat: "todas",
  respuestaSel: null,
  config: null,
  sucio: false,
  plantilla: "empresa",
  ultimoCampo: null,
  dialogoCuentaMostrado: false,
};

// ------------------------------------------------------------ utilidades

async function api(ruta, datos) {
  const opciones = datos === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(datos) };
  const r = await fetch("/api/" + ruta, opciones);
  const json = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(json.error || `Error ${r.status}`);
  return json;
}

function aviso(mensaje, tipo = "") {
  const div = document.createElement("div");
  div.className = "aviso " + tipo;
  div.textContent = mensaje;
  $("#avisos").prepend(div);
  setTimeout(() => div.remove(), 6000);
}

const hora = (iso) => (iso ? iso.slice(11, 16) : "");
function fecha(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toDateString() === new Date().toDateString() ? "hoy " + hora(iso) : d.toLocaleDateString("es-ES", { day: "numeric", month: "short" }) + " " + hora(iso);
}
const pct = (a, b) => (b ? Math.round((a / b) * 100) + "%" : "—");
const cat = (c, pastilla = false) => { const k = CATEGORIAS[c] || CATEGORIAS.otra; return `<span class="cat cat-${esc(c)} ${pastilla ? "pastilla" : ""}"><span class="icono">${k.icono}</span>${k.txt}</span>`; };
const estadoHtml = (e) => `<span class="estado estado-${esc(e)}">${esc(ESTADOS[e] || e)}</span>`;
function iniciales(nombre) {
  const palabras = String(nombre || "?").replace(/<.*>/, "").trim().split(/\s+/).filter((p) => /^[\p{L}\d]/u.test(p));
  return ((palabras[0] || "?")[0] + (palabras[1] ? palabras[1][0] : "")).toUpperCase();
}
const avatar = (nombre, categoria, extra = "") => `<div class="avatar ${categoria ? "cat-" + esc(categoria) : ""} ${extra}" aria-hidden="true">${esc(iniciales(nombre))}</div>`;
const nombrePila = (n) => (n && n !== "Tu Nombre" ? n.trim().split(/\s+/)[0] : "");

// ------------------------------------------------------------ navegación

function mostrar(vista) {
  st.vista = vista;
  history.replaceState(null, "", "#" + vista);
  $$(".pestana").forEach((b) => b.classList.toggle("activa", b.dataset.vista === vista));
  $$(".vista").forEach((s) => (s.hidden = s.id !== "vista-" + vista));
  if (vista === "empresas") cargarEmpresas();
  if (vista === "respuestas") cargarRespuestas();
  if (vista === "config" && !st.sucio) cargarConfig();
  if (vista === "panel" && st.estado) { st.firmaGrafico = ""; pintarGrafico(st.estado.diario); }
}
$$(".pestana").forEach((b) => b.addEventListener("click", () => mostrar(b.dataset.vista)));
document.addEventListener("click", (ev) => {
  const ir = ev.target.closest("[data-ir]");
  if (ir) mostrar(ir.dataset.ir);
});

// ------------------------------------------------------------ estado general

async function refrescar() {
  let e;
  try {
    e = await api("estado");
  } catch {
    $("#resumen").textContent = "Sin conexión con el programa. ¿Está abierto app.py?";
    return;
  }
  if (e.modo !== st.modo) {
    st.modo = e.modo;
    st.ultimoEvento = 0;
    st.respuestaSel = null;
    $("#registro").innerHTML = "";
  }
  st.estado = e;
  pintarCabecera(e);
  pintarPanel(e);
  await cargarEventos();

  if (!st.dialogoCuentaMostrado) {
    st.dialogoCuentaMostrado = true;
    let omitido = false;
    try { omitido = sessionStorage.getItem("cuenta-omitida") === "1"; } catch {}
    if (!e.cuenta.conectada && !omitido) abrirCuenta();
  }

  const k = e.kpis;
  const firma = [e.modo, k.empresas, k.enviados, k.respondidas, k.no_leidas, k.errores, e.motor.hecho].join("|");
  const cambio = firma !== st.firma;
  if (cambio) {
    st.firma = firma;
    await cargarRespuestas(st.vista !== "respuestas");
  }
  if (st.vista === "empresas") {
    pintarTarjetaRastreo(e);
    // En directo: mientras trabaja, la lista se recarga en cada vuelta para ver cada naviera cambiar de estado
    if (cambio || e.motor.ejecutando) await cargarEmpresas();
    else pintarBarraEnvio();
  }
}

function pintarCabecera(e) {
  const ins = $("#insignia-modo");
  ins.className = "insignia " + e.modo;
  ins.textContent = MODOS[e.modo];
  ins.title = { simulacion: "No se envía ningún correo real", prueba: "Los correos se envían, pero solo a tu propio email", real: "Los correos se envían a las empresas" }[e.modo];

  const chip = $("#chip-cuenta");
  chip.className = "chip-cuenta" + (e.cuenta.conectada ? "" : " desconectada");
  chip.innerHTML = e.cuenta.conectada ? `<span class="punto"></span>${esc(e.cuenta.usuario)}` : `<span class="punto"></span>Conectar Gmail`;
  chip.title = e.cuenta.conectada ? "Cuenta conectada. Pulsa para cambiarla." : "Conecta la cuenta desde la que se enviarán los correos";
  if (st.vista === "config") { pintarCuentaConfig(); pintarPrevia(); }
  pintarRevision(e);

  const n = e.kpis.no_leidas;
  $("#contador-no-leidas").hidden = !n;
  $("#contador-no-leidas").textContent = n;
  $("#btn-iniciar").hidden = e.motor.ejecutando;
  $("#btn-iniciar").lastChild.textContent = e.kpis.empresas ? " 1 · Buscar navieras nuevas" : " 1 · Buscar navieras";
  $("#btn-detener").hidden = !e.motor.ejecutando;
  $("#btn-ir-revisar").hidden = !e.kpis.empresas;
  $("#btn-ir-revisar").textContent = e.kpis.seleccionadas ? `2 · Revisar y enviar (${e.kpis.seleccionadas}) →` : "2 · Revisar y enviar →";
  $("#contador-seleccionadas").hidden = !e.kpis.seleccionadas;
  $("#contador-seleccionadas").textContent = e.kpis.seleccionadas;
  document.title = (n ? `(${n}) ` : "") + "Busca Prácticas";

  const avisos = $("#avisos");
  $$(".aviso.fijo", avisos).forEach((x) => x.remove());
  if (e.problemas.length) {
    const div = document.createElement("div");
    div.className = "aviso critico fijo";
    div.innerHTML = `<div><b>Falta configurar algo para el modo ${esc(MODOS[e.modo])}:</b><ul>${e.problemas.map((p) => `<li>${esc(p)}</li>`).join("")}</ul></div>`;
    avisos.append(div);
  }
}

// ------------------------------------------------------------ revisión del correo

function pintarRevision(e) {
  if (st.revisando) return;
  const r = e.revision;
  let texto, inactiva = false;
  if (e.modo === "simulacion") { texto = "Simulación: las respuestas llegan solas"; inactiva = true; }
  else if (!e.cuenta.conectada) { texto = "Conecta Gmail para leer las respuestas"; inactiva = true; }
  else if (!r.ultima) { texto = e.kpis.enviados ? "Revisando tu correo en unos segundos…" : "Empezaré a revisar tu correo después del primer envío"; inactiva = !e.kpis.enviados; }
  else {
    const s = r.proxima_seg;
    const siguiente = s == null ? "" : s <= 1 ? " · revisando…" : ` · siguiente en ${s >= 60 ? Math.floor(s / 60) + " min " + (s % 60) + " s" : s + " s"}`;
    texto = `Correo revisado a las ${hora(r.ultima)}${siguiente}`;
  }
  $$(".revision-texto").forEach((el) => { el.textContent = texto; el.className = "revision-texto" + (inactiva ? " inactiva" : ""); });
  $$("[data-revisar]").forEach((b) => (b.hidden = e.modo === "simulacion" || !e.cuenta.conectada));
}

document.addEventListener("click", async (ev) => {
  if (!ev.target.closest("[data-revisar]") || st.revisando) return;
  st.revisando = true;
  $$("[data-revisar]").forEach((b) => (b.disabled = true));
  $$(".revision-texto").forEach((el) => { el.textContent = "Revisando tu bandeja de entrada…"; el.className = "revision-texto revisando"; });
  try {
    const r = await api("comprobar", {});
    aviso(r.nuevas ? `${r.nuevas} respuesta(s) nueva(s).` : "No hay respuestas nuevas.", r.nuevas ? "bien" : "");
  } catch (err) {
    aviso(err.message, "critico");
  } finally {
    st.revisando = false;
    $$("[data-revisar]").forEach((b) => (b.disabled = false));
    st.firma = "";
    refrescar();
  }
});

// ------------------------------------------------------------ panel

function pintarPanel(e) {
  const k = e.kpis;
  const entrevistas = k.categorias.entrevista || 0;

  // Saludo y resumen
  $("#hoy").textContent = new Date().toLocaleDateString("es-ES", { weekday: "long", day: "numeric", month: "long" });
  const pila = nombrePila(e.nombre);
  $("#saludo").textContent = pila ? `Hola, ${pila}` : "¡Hola!";
  let resumen;
  if (!k.empresas) {
    resumen = e.fuente === "maritimo"
      ? `Todavía no has empezado. Pulsa <b>Iniciar búsqueda</b> y buscaré <b>navieras de toda Europa</b>, rastrearé sus webs para encontrar el mejor contacto y les enviaré tu solicitud de embarque.`
      : `Todavía no has empezado. Pulsa <b>Iniciar búsqueda</b> y buscaré empresas y agencias en <b>${esc(listaCiudades(e.ciudades))}</b> para enviarles tu candidatura.`;
  } else if (!k.enviados) {
    resumen = `Has encontrado <b>${k.empresas}</b> navieras, <b>${k.con_email}</b> con email` +
      (k.cadetes ? ` y <b>${k.cadetes}</b> que hablan de cadetes` : "") + `. ` +
      (e.motor.ejecutando ? "Sigo rastreando sus webs…" : `Revísalas y <b>elige a cuáles escribir</b>` +
        (k.seleccionadas ? ` (ya tienes <b>${k.seleccionadas}</b> seleccionadas).` : "."));
  } else {
    resumen = `Has contactado <b>${k.enviados}</b> ${k.enviados === 1 ? "empresa" : "empresas"} y <b>${k.respondidas}</b> ${k.respondidas === 1 ? "te ha" : "te han"} respondido.`;
    if (entrevistas) resumen += ` Tienes <b>${entrevistas} ${entrevistas === 1 ? "propuesta" : "propuestas"} de entrevista</b>. ¡Enhorabuena!`;
    if (k.no_leidas) resumen += ` Hay <b>${k.no_leidas}</b> ${k.no_leidas === 1 ? "respuesta" : "respuestas"} sin leer.`;
    else if (k.pendientes_envio) resumen += ` Quedan <b>${k.pendientes_envio}</b> por escribir.`;
  }
  $("#resumen").innerHTML = resumen;
  const fuente = { osm: "OpenStreetMap en " + listaCiudades(e.ciudades), maritimo: "navieras europeas reales", ejemplo: "navieras ficticias" }[e.fuente];
  $("#hero-detalle").textContent = e.modo === "simulacion"
    ? `Simulación: ${fuente}, sin enviar nada de verdad.`
    : e.modo === "prueba"
      ? `Prueba: hasta ${e.max_por_ejecucion} correos, todos a tu propio email.`
      : `Real: hasta ${Math.min(e.max_por_ejecucion, e.limite_diario - e.enviados_hoy)} correos (${fuente}).`;

  // Progreso
  const m = e.motor;
  $("#hero-progreso").hidden = !m.ejecutando;
  $("#fase").textContent = m.fase + "…";
  $("#fase-num").textContent = m.total ? `${m.hecho} de ${m.total}` : "";
  const barra = $("#barra-progreso");
  barra.classList.toggle("indeterminado", m.ejecutando && !m.total);
  barra.style.width = m.total ? (m.hecho / m.total) * 100 + "%" : "0";

  // Embudo
  const etapas = [
    { txt: "Encontradas", valor: k.empresas, icono: ICONOS.buscar, color: "var(--tinta-2)",
      sub: [`${k.con_email} con email`, k.cadetes && `⚓ ${k.cadetes} cadetes`, k.portales && `${k.portales} solo portal`,
            k.por_rastrear && `${k.por_rastrear} por rastrear`].filter(Boolean).join(" · ") },
    { txt: "Contactadas", valor: k.enviados, sub: e.modo === "simulacion" ? `${k.pendientes_envio} pendientes` : `${e.enviados_hoy}/${e.limite_diario} hoy · ${k.pendientes_envio} pendientes`, icono: ICONOS.enviar, color: "var(--serie-1)", conv: pct(k.enviados, k.con_email) },
    { txt: "Respondieron", valor: k.respondidas, sub: `tasa de respuesta ${pct(k.respondidas, k.enviados)}`, icono: ICONOS.respuesta, color: "var(--serie-2)", conv: pct(k.respondidas, k.enviados) },
    { txt: "Entrevistas", valor: entrevistas, sub: entrevistas ? "¡a prepararlas!" : "", icono: ICONOS.objetivo, color: "var(--bien)", conv: pct(entrevistas, k.respondidas) },
  ];
  $("#embudo").innerHTML = etapas.map((t, i) => `
    ${i ? `<div class="conector" title="Conversión desde la etapa anterior">${ICONOS.flecha}<span>${t.conv}</span></div>` : ""}
    <div class="etapa" style="--color-etapa:${t.color}">
      <div class="etapa-icono">${t.icono}</div>
      <div class="etapa-etiqueta">${t.txt}</div>
      <div class="kpi-valor">${t.valor}</div>
      <div class="etapa-sub">${esc(t.sub)}</div>
    </div>`).join("");

  // Tipo de respuesta
  const cats = Object.keys(CATEGORIAS).map((c) => ({ c, v: k.categorias[c] || 0 }));
  const maxCat = Math.max(1, ...cats.map((x) => x.v));
  $("#categorias").innerHTML = !k.respondidas
    ? `<p class="vacio" style="grid-column:1/-1">Todavía no ha respondido nadie.</p>`
    : cats.map(({ c, v }) => `
      <div class="barra-etiqueta">${cat(c)}</div>
      <div class="barra-pista" title="${esc(CATEGORIAS[c].txt)}: ${v}"><div class="barra-relleno cat-${c}" style="width:${(v / maxCat) * 100}%"></div></div>
      <div class="barra-valor">${v}</div>`).join("");

  if (st.vista === "panel") pintarGrafico(e.diario);
}

// ------------------------------------------------------------ gráfico diario

function pintarGrafico(diario) {
  const cont = $("#grafico-diario");
  const W = cont.clientWidth, H = cont.clientHeight;
  const firma = W + "|" + JSON.stringify(diario);
  if (!W || firma === st.firmaGrafico) return;  // no repintar si nada cambió (mantiene el hover)
  st.firmaGrafico = firma;

  const m = { l: 28, r: 4, t: 10, b: 24 };
  const pw = W - m.l - m.r, ph = H - m.t - m.b;
  const maxV = Math.max(0, ...diario.flatMap((d) => [d.enviados, d.respuestas]));
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
    svg += barra(x0, d.enviados, "b1") + barra(x0 + bw + 2, d.respuestas, "b2");
    if ((n - 1 - i) % 2 === 0) {
      const f = new Date(d.dia + "T12:00");
      svg += `<text x="${gx + gw / 2}" y="${H - 6}" text-anchor="middle">${i === n - 1 ? "hoy" : f.getDate() + "/" + (f.getMonth() + 1)}</text>`;
    }
  });
  const vacio = maxV === 0 ? `<div class="grafico-vacio">Aquí verás cada día cuántos correos envías y cuántas respuestas recibes.</div>` : "";
  cont.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Correos enviados y respuestas por día en los últimos 14 días">${svg}</svg>${vacio}`;
  $$(".zona", cont).forEach((z) => (z.style.pointerEvents = "all"));

  $("#tabla-diario").innerHTML = `<table><tr><th>Día</th><th>Enviados</th><th>Respuestas</th></tr>${diario.map((d) => `<tr><td>${esc(d.dia)}</td><td>${d.enviados}</td><td>${d.respuestas}</td></tr>`).join("")}</table>`;
}

$("#grafico-diario").addEventListener("mousemove", (ev) => {
  const z = ev.target.closest(".zona");
  const tip = $("#tooltip");
  $$(".zona.activa").forEach((x) => x !== z && x.classList.remove("activa"));
  if (!z || !st.estado) { tip.hidden = true; return; }
  z.classList.add("activa");
  const d = st.estado.diario[Number(z.dataset.i)];
  const f = new Date(d.dia + "T12:00").toLocaleDateString("es-ES", { weekday: "long", day: "numeric", month: "long" });
  tip.innerHTML = `<b>${esc(f)}</b>
    <div class="t-fila"><i class="muestra s1"></i><span>Enviados</span><span>${d.enviados}</span></div>
    <div class="t-fila"><i class="muestra s2"></i><span>Respuestas</span><span>${d.respuestas}</span></div>`;
  tip.hidden = false;
  const x = Math.min(ev.clientX + 14, window.innerWidth - tip.offsetWidth - 8);
  tip.style.left = x + "px";
  tip.style.top = ev.clientY + 14 + "px";
});
$("#grafico-diario").addEventListener("mouseleave", () => {
  $("#tooltip").hidden = true;
  $$(".zona.activa").forEach((x) => x.classList.remove("activa"));
});
window.addEventListener("resize", () => st.estado && st.vista === "panel" && pintarGrafico(st.estado.diario));

async function cargarEventos() {
  const eventos = await api("eventos?desde=" + st.ultimoEvento).catch(() => []);
  if (!eventos.length) return;
  st.ultimoEvento = eventos[eventos.length - 1].id;
  const ol = $("#registro");
  for (const ev of eventos) {
    const li = document.createElement("li");
    li.innerHTML = `<span class="hora">${esc(hora(ev.ts))}</span><span class="${ev.nivel === "aviso" ? "aviso-t" : esc(ev.nivel)}">${esc(ev.mensaje)}</span>`;
    ol.prepend(li);
  }
  while (ol.children.length > 200) ol.lastChild.remove();
}

// ------------------------------------------------------------ iniciar / detener

// Paso 1: buscar y rastrear (no envía nada). Se pasa a la pestaña Navieras para verlo en directo.
$("#btn-iniciar").addEventListener("click", async () => {
  try {
    await api("iniciar", {});
    mostrar("empresas");
    refrescar();
  } catch (err) {
    aviso(err.message, "critico");
  }
});
const detener = () => api("detener", {}).then(() => aviso("Deteniendo… (termina lo que está en curso)")).catch((err) => aviso(err.message, "critico"));
$("#btn-detener").addEventListener("click", detener);
$("#btn-detener-2").addEventListener("click", detener);
$("#btn-releer").addEventListener("click", async () => {
  try { await api("iniciar", { forzar: true }); refrescar(); } catch (err) { aviso(err.message, "critico"); }
});
$("#btn-seguir-rastreo").addEventListener("click", async () => {
  try { await api("rastrear-pendientes", {}); refrescar(); } catch (err) { aviso(err.message, "critico"); }
});

// ------------------------------------------------------------ cuenta de Gmail

function abrirCuenta() {
  const f = $("#form-cuenta");
  f.usuario.value = (st.estado && st.estado.cuenta.usuario) || "";
  f.contrasena.value = "";
  f.contrasena.type = "password";
  $("#ver-clave").textContent = "Mostrar";
  $("#cuenta-resultado").hidden = true;
  $("#cuenta-enviar").disabled = false;
  $("#cuenta-nota-sim").hidden = !(st.estado && st.estado.modo === "simulacion");
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
$("#form-cuenta").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const f = ev.target;
  const res = $("#cuenta-resultado");
  res.hidden = false;
  res.className = "resultado cargando";
  res.textContent = "Probando la conexión con Gmail (envío y lectura)…";
  $("#cuenta-enviar").disabled = true;
  try {
    const cuenta = await api("cuenta", { usuario: f.usuario.value, contrasena: f.contrasena.value });
    res.className = "resultado ok";
    res.textContent = `✓ Conectado como ${cuenta.usuario}. Ya se puede enviar y leer correo.`;
    f.contrasena.value = "";
    await refrescar();
    if (st.vista === "config" && !st.sucio) cargarConfig();
    pintarCuentaConfig();
    setTimeout(() => $("#dialogo-cuenta").close(), 1400);
  } catch (err) {
    res.className = "resultado error";
    res.textContent = err.message;
    $("#cuenta-enviar").disabled = false;
  }
});
$("#btn-desconectar").addEventListener("click", async () => {
  if (!confirm("¿Desconectar la cuenta? Se borrará la contraseña de aplicación guardada en tu PC.")) return;
  await api("cuenta/desconectar", {}).catch((err) => aviso(err.message, "critico"));
  await refrescar();
  pintarCuentaConfig();
});

function pintarCuentaConfig() {
  const c = st.estado && st.estado.cuenta;
  if (!c) return;
  $("#cuenta-estado").innerHTML = c.conectada
    ? `Conectada: <b>${esc(c.usuario)}</b>. Los correos saldrán desde esta cuenta y aquí se leerán las respuestas.`
    : "No hay ninguna cuenta conectada. Hace falta para los modos «Prueba real» y «Real».";
  $("#btn-conectar").textContent = c.conectada ? "Cambiar cuenta" : "Conectar Gmail";
  $("#btn-conectar").className = c.conectada ? "btn" : "btn primario";
  $("#btn-desconectar").hidden = !c.conectada;
}

// ------------------------------------------------------------ empresas

async function cargarEmpresas() {
  st.empresas = await api("empresas").catch(() => []);
  pintarEmpresas();
}

const elegible = (e) => e.estado === "nueva" && !!e.email;  // se le puede escribir

// Avisos para revisar antes de escribir, y términos de cadetes que aparecen en su web
const AVISO_INFO = {
  cobro: { txt: "Posible cobro", clase: "critico",
    ayuda: "Su web habla de pagar una tasa o cuota para embarcar. El Convenio MLC 2006 prohíbe que las agencias cobren al marino por buscarle embarque: desconfía y no pagues nada." },
  ucrania: { txt: "Ucrania", clase: "",
    ayuda: "La naviera o la agencia es de Ucrania o su web menciona Ucrania o sus puertos. Comprueba en qué zona operan sus buques antes de embarcar." },
  mar_negro: { txt: "Mar Negro", clase: "",
    ayuda: "Su web menciona el Mar Negro, el Mar de Azov, puertos de la zona o zonas de riesgo. Puede haber buques navegando en zona de conflicto." },
};
function avisosDe(e) {
  try { return JSON.parse(e.avisos || "[]"); } catch { return []; }
}
const mencionesDe = (e) => (e.menciones || "").split("|").filter(Boolean);
// «Empleo embarcado / offshore» se guarda junto a las menciones, pero no es un término de cadetes
const EMPLEO_MAR = "empleo embarcado / offshore";
const terminosCadete = (e) => mencionesDe(e).filter((t) => t !== EMPLEO_MAR);
const aBordo = (e) => mencionesDe(e).includes(EMPLEO_MAR);
const chipsAvisos = (e) => avisosDe(e).map((a) => {
  const i = AVISO_INFO[a.tipo] || { txt: a.tipo, clase: "" };
  return ` <span class="chip-aviso ${i.clase}" title="${esc(i.ayuda + "\n\n«" + a.texto + "»")}">⚠ ${esc(i.txt)}</span>`;
}).join("");
const pendienteRastreo = (e) => !!e.web && !e.email_buscado && ["nueva", "sin_email"].includes(e.estado);
const BUZON_BUENO = /^(cadet|crew|manning|seafarer|marine|tripul|flota|fleet|personal|jobs?|career|karriere|bewerbung|empleo|rrhh|hr|recruit|talent|seleccion|people|practicas|trainee)/i;
// Recomendadas: con buzón de tripulación/empleo o que hablan de cadetes, y SIN avisos
const recomendada = (e) => elegible(e) && !avisosDe(e).length && (!!e.cadetes || BUZON_BUENO.test(e.email.split("@")[0]));
const idsEnCurso = () => new Set(((st.estado && st.estado.motor.en_curso) || []).map((x) => x.id));

function estadoFila(e, enCurso) {
  if (enCurso.has(e.id)) return `<span class="estado estado-rastreando">Rastreando su web…</span>`;
  if (pendienteRastreo(e)) return `<span class="estado estado-pendiente">Pendiente de rastrear</span>`;
  return estadoHtml(e.estado) + (e.ultima_categoria ? " · " + cat(e.ultima_categoria) : "");
}

function filasVisibles() {
  const texto = $("#filtro-texto").value.trim().toLowerCase();
  const estado = $("#filtro-estado").value;
  const tipo = $("#filtro-tipo").value;
  const pais = $("#filtro-pais").value;
  const mencion = $("#filtro-mencion").value;
  const cumpleMencion = (e) => !mencion ? true : mencion === "*" ? terminosCadete(e).length > 0 : mencionesDe(e).includes(mencion);
  const cumpleEstado = (e) =>
    !estado ? true
      : estado === "con_empleo" ? !!e.web_empleo
      : estado === "empleo_mar" ? aBordo(e)
      : estado === "avisos" ? avisosDe(e).length > 0
      : estado === "sin_avisos" ? avisosDe(e).length === 0
      : estado === "elegibles" ? elegible(e)
      : estado === "seleccionadas" ? !!e.seleccionada && elegible(e)
      : estado === "pendiente_rastreo" ? pendienteRastreo(e)
      : estado === "cadetes" ? !!e.cadetes
      : estado === "portal" ? !e.email && !!e.web_empleo
      : estado === "bloqueada" ? !!e.web_bloqueada
      : e.estado === estado;
  return st.empresas.filter((e) =>
    cumpleEstado(e) && cumpleMencion(e) && (!tipo || e.tipo === tipo) && (!pais || (e.pais || "") === pais) &&
    (!texto || `${e.nombre} ${e.sector} ${e.email} ${e.ciudad}`.toLowerCase().includes(texto)));
}

function pintarEmpresas() {
  const selPais = $("#filtro-pais");
  const pais = selPais.value;
  const paises = [...new Set(st.empresas.map((e) => e.pais || ""))].sort((a, b) => nombrePais(a).localeCompare(nombrePais(b)));
  selPais.innerHTML = `<option value="">Todos los países</option>` + paises.map((p) => `<option value="${esc(p)}" ${p === pais ? "selected" : ""}>${esc(nombrePais(p))} (${st.empresas.filter((e) => (e.pais || "") === p).length})</option>`).join("");
  // Filtro «Menciona…»: los términos que se han encontrado en las webs, con cuántas navieras los usan
  const selMen = $("#filtro-mencion");
  const men = selMen.value;
  const cuenta = {};
  st.empresas.forEach((e) => terminosCadete(e).forEach((t) => (cuenta[t] = (cuenta[t] || 0) + 1)));
  const conAlguna = st.empresas.filter((e) => terminosCadete(e).length).length;
  selMen.innerHTML = `<option value="">Menciona: cualquier cosa</option><option value="*" ${men === "*" ? "selected" : ""}>⚓ Algún término de cadetes (${conAlguna})</option>` +
    Object.entries(cuenta).sort((a, b) => b[1] - a[1]).map(([t, n]) => `<option value="${esc(t)}" ${t === men ? "selected" : ""}>“${esc(t)}” (${n})</option>`).join("");
  const filas = filasVisibles();
  const enCurso = idsEnCurso();

  $("#empresas-vacio").hidden = st.empresas.length > 0;
  pintarBarraEnvio();
  const tbody = $("#tabla-empresas");
  if (tbody.contains(document.activeElement) && document.activeElement.tagName === "INPUT" && document.activeElement.type !== "checkbox") return;
  const elegiblesVisibles = filas.filter(elegible);
  const todas = $("#check-todas");
  todas.checked = elegiblesVisibles.length > 0 && elegiblesVisibles.every((e) => e.seleccionada);
  todas.indeterminate = !todas.checked && elegiblesVisibles.some((e) => e.seleccionada);

  tbody.innerHTML = filas.map((e) => `
    <tr data-id="${e.id}" class="${e.seleccionada && elegible(e) ? "seleccionada" : ""} ${avisosDe(e).length ? "con-aviso" : ""}">
      <td class="col-check">${elegible(e) ? `<input type="checkbox" data-sel="${e.id}" ${e.seleccionada ? "checked" : ""} title="Enviarle el correo">` : ""}</td>
      <td><div class="celda-nombre">${avatar(e.nombre, e.ultima_categoria)}<span><span class="nombre" data-ver="${e.id}">${esc(e.nombre)}</span>
        ${e.web ? ` <a href="${urlSegura(e.web)}" target="_blank" rel="noopener" class="pequeno">web</a>` : ""}
        ${e.web_empleo ? ` · <a href="${urlSegura(e.web_empleo)}" target="_blank" rel="noopener" class="pequeno" title="Página de empleo / tripulación: si no tienen email, regístrate ahí">empleo</a>` : ""}
        ${terminosCadete(e).length ? ` <span class="chip-cadetes" title="Su web menciona: ${esc(terminosCadete(e).join(", "))}">⚓ ${esc(terminosCadete(e)[0])}${terminosCadete(e).length > 1 ? ` +${terminosCadete(e).length - 1}` : ""}</span>`
          : e.cadetes && !e.menciones ? ` <span class="chip-cadetes" title="Su web menciona cadetes o alumnos">⚓ cadetes</span>` : ""}
        ${aBordo(e) && e.web_empleo ? ` <a class="chip-cadetes chip-enlace" href="${urlSegura(e.web_empleo)}" target="_blank" rel="noopener" title="Su página de empleo habla de trabajo a bordo / offshore. Pulsa para abrirla">🚢 empleo a bordo</a>` : ""}
        ${chipsAvisos(e)}
        ${e.web_bloqueada ? ` <span class="chip-bloqueada" title="Su web no deja leerla a programas: ábrela tú">web bloquea</span>` : ""}</span></div></td>
      <td title="${esc(e.ciudad)}"><span class="tipo-chip">${esc((e.pais || "—").toUpperCase())}</span></td>
      <td><span class="tipo-chip">${e.tipo === "agencia" ? "Agencia" : "Empresa"}</span></td>
      <td class="secundario">${esc(e.sector)}</td>
      <td>${e.email
        ? `${esc(e.email)}${e.email_fuente ? ` <span class="etiqueta-sim" title="Encontrado en ${esc(e.email_fuente)}">de su web</span>` : ""}`
        : `<div class="celda-email"><input class="email-input" data-email="${e.id}" type="email" placeholder="añadir email y pulsar Enter">
           ${e.web && !enCurso.has(e.id) ? `<button class="btn mini" data-buscar-email="${e.id}" title="${e.email_buscado ? "Ya se buscó y no se encontró. Puedes volver a intentarlo." : "Visitar su web y buscar un email de contacto"}">${e.email_buscado ? "Reintentar" : "Buscar en su web"}</button>` : ""}</div>`}</td>
      <td>${estadoFila(e, enCurso)}</td>
      <td class="acciones-fila">
        <button class="btn mini" data-ver="${e.id}">Ver</button>
        ${e.estado === "descartada"
          ? `<button class="btn mini" data-estado="${e.id}" data-valor="nueva">Recuperar</button>`
          : ["nueva", "sin_email", "error"].includes(e.estado) ? `<button class="btn mini" data-estado="${e.id}" data-valor="descartada">Descartar</button>` : ""}
      </td>
    </tr>`).join("");
}

["#filtro-texto", "#filtro-estado", "#filtro-tipo", "#filtro-pais", "#filtro-mencion"].forEach((s) => $(s).addEventListener("input", pintarEmpresas));

// ------------------------------------------------------------ progreso en directo

function pintarTarjetaRastreo(e) {
  const m = e.motor, k = e.kpis;
  const tarjeta = $("#tarjeta-rastreo");
  const buscando = m.ejecutando && m.tarea === "buscar";
  const enviando = m.ejecutando && m.tarea === "enviar";
  tarjeta.hidden = !(m.ejecutando || k.por_rastrear || k.rastreadas);
  if (tarjeta.hidden) return;

  $("#rastreo-titulo").textContent = buscando ? m.fase + "…" : enviando ? "Enviando correos…"
    : k.por_rastrear ? "Búsqueda en pausa" : "Búsqueda terminada";
  $("#rastreo-sub").textContent = buscando
    ? (m.total ? `${m.hecho} de ${m.total} webs · no se envía nada hasta que tú lo decidas` : "Leyendo las fuentes de navieras…")
    : enviando ? `${m.hecho} de ${m.total} · solo a las que seleccionaste`
    : k.por_rastrear ? `Quedan ${k.por_rastrear} webs por rastrear. Puedes seguir cuando quieras.`
    : "Todas analizadas. La próxima búsqueda solo analizará navieras nuevas." +
      (e.fuentes_leidas ? ` Fuentes leídas ${fecha(e.fuentes_leidas)}.` : "") +
      " Marca las navieras a las que quieres escribir y pulsa «Enviar».";
  const pista = $("#rastreo-pista");
  pista.hidden = !m.ejecutando;
  const barra = $("#rastreo-barra");
  barra.classList.toggle("indeterminado", m.ejecutando && !m.total);
  barra.style.width = m.total ? (m.hecho / m.total) * 100 + "%" : "0";

  $("#btn-detener-2").hidden = !m.ejecutando;
  const seguir = $("#btn-seguir-rastreo");
  seguir.hidden = m.ejecutando || !k.por_rastrear;
  seguir.textContent = `Seguir rastreando (${k.por_rastrear})`;
  $("#btn-releer").hidden = m.ejecutando || !e.fuentes_leidas;

  $("#rastreo-contadores").innerHTML = [
    [k.empresas, "encontradas"], [k.rastreadas, "webs rastreadas"], [k.con_email, "con email"],
    [k.cadetes, "⚓ hablan de cadetes"], [k.empleo_mar, "🚢 empleo a bordo"], [k.portales, "solo portal de empleo"],
    [k.con_avisos, "⚠ con avisos"],
  ].map(([n, t]) => `<span><b>${n}</b> ${t}</span>`).join("");

  $("#rastreo-ahora").innerHTML = buscando && m.en_curso.length
    ? `<span class="pequeno secundario">Ahora:</span>` + m.en_curso.map((x) => `<span class="chip-vivo">${esc(x.nombre)}</span>`).join("")
    : "";

  // Últimas webs rastreadas y qué se encontró en cada una
  const ultimas = st.empresas.filter((x) => x.email_buscado).sort((a, b) => b.email_buscado.localeCompare(a.email_buscado)).slice(0, buscando ? 6 : 0);
  $("#rastreo-ultimos").innerHTML = ultimas.map((x) => {
    const partes = [
      x.web_bloqueada ? "web bloquea programas" : x.email ? "✉ " + x.email : "sin email",
      terminosCadete(x).length ? "⚓ " + terminosCadete(x).join(", ") : "", aBordo(x) ? "🚢 empleo a bordo" : "",
      x.web_empleo && !x.email ? "portal de empleo" : "",
      ...avisosDe(x).map((a) => "⚠ " + ((AVISO_INFO[a.tipo] || {}).txt || a.tipo)),
    ].filter(Boolean).join(" · ");
    return `<div class="fila-res"><span>${esc(x.nombre)}</span><span>${esc(partes)}</span></div>`;
  }).join("");
}

// ------------------------------------------------------------ selección y envío

async function seleccionar(ids, valor) {
  if (!ids.length) return;
  const set = new Set(ids);
  st.empresas.forEach((e) => { if (set.has(e.id) && (elegible(e) || !valor)) e.seleccionada = valor ? 1 : 0; });
  pintarEmpresas();
  try {
    await api("seleccion", { ids, seleccionada: valor });
  } catch (err) {
    aviso(err.message, "critico");
  }
  refrescar();
}

function pintarBarraEnvio() {
  const e = st.estado;
  const sel = st.empresas.filter((x) => x.seleccionada && elegible(x));
  const n = sel.length;
  $("#sel-num").textContent = n === 1 ? "1 seleccionada" : `${n} seleccionadas`;
  const btn = $("#btn-enviar");
  btn.disabled = !n || !e || e.motor.ejecutando;
  if (!e) return;
  const tope = e.modo === "simulacion" ? e.max_por_ejecucion : Math.min(e.max_por_ejecucion, Math.max(0, e.limite_diario - e.enviados_hoy));
  const ahora = Math.min(n, tope);
  btn.textContent = !n ? "Enviar" : e.modo === "prueba" ? `Enviar ${ahora} (te llegan a ti)` : e.modo === "simulacion" ? `Enviar ${ahora} (simulado)` : `Enviar ${ahora} de verdad`;
  $("#sel-ayuda").textContent = !n
    ? "Marca las casillas de las navieras a las que quieres escribir, o pulsa «Seleccionar recomendadas»."
    : n > tope ? `Se enviarán ${ahora} ahora (límite ${e.modo === "simulacion" ? "por envío" : "por envío / diario"}); las demás quedan seleccionadas para después.`
    : e.modo === "real" ? "Se enviarán de verdad a esas navieras, con una pausa entre correos."
    : e.modo === "prueba" ? "Modo prueba: las navieras son reales, pero el correo te llega a ti, nunca a ellas."
    : "Revisa el correo de cada una con «Ver» antes de enviar.";
}

$("#tabla-empresas").addEventListener("change", (ev) => {
  const c = ev.target.closest("[data-sel]");
  if (c) seleccionar([Number(c.dataset.sel)], c.checked);
});
$("#check-todas").addEventListener("change", (ev) => {
  seleccionar(filasVisibles().filter(elegible).map((e) => e.id), ev.target.checked);
});
$("#btn-sel-recomendadas").addEventListener("click", () => {
  const ids = st.empresas.filter(recomendada).map((e) => e.id);
  if (!ids.length) return aviso("No hay recomendadas todavía: ninguna tiene buzón de tripulación/empleo ni habla de cadetes. Elige tú a mano.");
  seleccionar(ids, true);
  aviso(`${ids.length} seleccionadas: las que tienen buzón de tripulación / empleo o hablan de cadetes.`, "bien");
});
$("#btn-sel-ninguna").addEventListener("click", () => {
  seleccionar(st.empresas.filter((e) => e.seleccionada).map((e) => e.id), false);
});
$("#btn-enviar").addEventListener("click", async () => {
  const e = st.estado;
  const n = st.empresas.filter((x) => x.seleccionada && elegible(x)).length;
  const conAviso = st.empresas.filter((x) => x.seleccionada && elegible(x) && avisosDe(x).length);
  if (conAviso.length && !confirm(`⚠ ${conAviso.length} de las seleccionadas tienen avisos:\n\n` +
      conAviso.slice(0, 12).map((x) => `• ${x.nombre}: ${avisosDe(x).map((a) => (AVISO_INFO[a.tipo] || {}).txt || a.tipo).join(", ")}`).join("\n") +
      (conAviso.length > 12 ? `\n… y ${conAviso.length - 12} más` : "") +
      `\n\n¿Seguro que quieres escribirles? (Pulsa Cancelar para revisarlas; filtra por «⚠ Con avisos».)`)) return;
  const texto = e.modo === "real"
    ? `MODO REAL: se enviará tu correo de verdad a las navieras seleccionadas (${n}).\n\n¿Has revisado tu mensaje y tu CV?`
    : e.modo === "prueba"
      ? `Modo prueba: se enviarán los correos de las ${n} seleccionadas, pero todos llegarán a TU email.\n\n¿Continuar?`
      : `Simulación: no sale nada de tu PC. ¿Simular el envío a las ${n} seleccionadas?`;
  if (!confirm(texto)) return;
  try {
    await api("enviar", {});
    refrescar();
  } catch (err) {
    aviso(err.message, "critico");
  }
});

// ------------------------------------------------------------ acciones de la tabla

$("#tabla-empresas").addEventListener("click", async (ev) => {
  const ver = ev.target.closest("[data-ver]");
  if (ver) return abrirEmpresa(ver.dataset.ver);
  const buscar = ev.target.closest("[data-buscar-email]");
  if (buscar) {
    buscar.disabled = true;
    buscar.textContent = "Buscando…";
    try {
      const r = await api(`empresas/${buscar.dataset.buscarEmail}/buscar-email`, {});
      aviso(r.email ? `Encontrado: ${r.email}` : "No se ha encontrado ningún email en su web. Prueba a buscarlo tú y escríbelo a mano.", r.email ? "bien" : "");
    } catch (err) {
      aviso(err.message, "critico");
    }
    cargarEmpresas();
    refrescar();
    return;
  }
  const b = ev.target.closest("[data-estado]");
  if (b) {
    await api(`empresas/${b.dataset.estado}`, { estado: b.dataset.valor }).catch((err) => aviso(err.message, "critico"));
    cargarEmpresas();
  }
});
$("#tabla-empresas").addEventListener("keydown", async (ev) => {
  const inp = ev.target.closest("[data-email]");
  if (!inp || ev.key !== "Enter") return;
  if (!inp.checkValidity() || !inp.value.trim()) return aviso("Ese email no parece válido.", "critico");
  await api(`empresas/${inp.dataset.email}`, { email: inp.value.trim(), estado: "nueva" }).catch((err) => aviso(err.message, "critico"));
  inp.blur();
  cargarEmpresas();
  refrescar();
});

$("#btn-nueva-empresa").addEventListener("click", () => {
  $("#dialogo-titulo").textContent = "Añadir naviera o agencia";
  $("#dialogo-cuerpo").innerHTML = `
    <form id="form-empresa" style="margin-top:14px">
      <label>Nombre<input name="nombre" required></label>
      <label>Email<input name="email" type="email"></label>
      <label>Tipo<select name="tipo"><option value="empresa">Naviera / empresa</option><option value="agencia">Agencia de tripulación</option></select></label>
      <label>País<select name="pais">${Object.entries(PAISES).map(([c, n]) => `<option value="${c}">${esc(n)}</option>`).join("")}</select>
        <span class="ayuda">Decide el idioma del correo: español para España, inglés para el resto.</span></label>
      <label>Ciudad<input name="ciudad"></label>
      <label>Sector<input name="sector" placeholder="Ferris, portacontenedores, cruceros…"></label>
      <label>Web<input name="web" type="url" placeholder="https://"></label>
      <div class="fila"><button class="btn primario">Añadir</button></div>
    </form>`;
  $("#dialogo").showModal();
  $("#form-empresa").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    try {
      await api("empresas", Object.fromEntries(new FormData(ev.target)));
      $("#dialogo").close();
      cargarEmpresas();
      refrescar();
    } catch (err) {
      aviso(err.message, "critico");
    }
  });
});

// ------------------------------------------------------------ ficha de una naviera

async function abrirEmpresa(id) {
  const d = await api("empresas/" + id);
  const e = d.empresa;
  $("#dialogo-titulo").textContent = e.nombre;
  const hilo = [
    ...d.correos.map((c) => ({ ts: c.enviado_en, html: `<div class="meta"><b>Tú</b> → ${esc(c.destinatario)} · ${esc(fecha(c.enviado_en))} · <i>${esc(c.asunto)}</i></div><div class="cuerpo-msg">${esc(c.cuerpo)}</div>` })),
    ...d.respuestas.map((r) => ({ ts: r.recibido_en, html: `<div class="meta"><b>${esc(r.remitente)}</b> · ${esc(fecha(r.recibido_en))} · ${cat(r.categoria, true)} ${r.simulada ? '<span class="etiqueta-sim">simulada</span>' : ""}</div><div class="cuerpo-msg">${esc(r.cuerpo)}</div>` })),
  ].sort((a, b) => a.ts.localeCompare(b.ts));
  const enlace = (u, t) => u ? `<a href="${urlSegura(u)}" target="_blank" rel="noopener">${esc(t || u)}</a>` : "—";
  const rastreo = e.web_bloqueada ? "Su web no deja leerla a programas: ábrela tú."
    : e.email_buscado ? `Rastreada ${esc(fecha(e.email_buscado))}` : e.web ? "Aún no se ha rastreado su web." : "No tiene web.";

  const avisos = avisosDe(e);
  $("#dialogo-cuerpo").innerHTML = `
    ${avisos.map((a) => {
      const i = AVISO_INFO[a.tipo] || { txt: a.tipo, clase: "", ayuda: "" };
      return `<div class="caja-aviso ${i.clase}"><b>⚠ ${esc(i.txt)}.</b> ${esc(i.ayuda)}
        <q>${esc(a.texto)}</q>${a.url ? `<div class="pequeno" style="margin-top:4px">Visto en ${enlace(a.url, "esta página")}</div>` : ""}</div>`;
    }).join("")}
    <dl class="ficha">
      <dt>Estado</dt><dd>${estadoHtml(e.estado)}</dd>
      <dt>Su web menciona</dt><dd>${terminosCadete(e).length ? terminosCadete(e).map((t) => `<span class="chip-cadetes">⚓ ${esc(t)}</span>`).join(" ") : e.email_buscado ? "ningún término de cadetes / alumnos" : "aún no rastreada"}</dd>
      <dt>Empleo a bordo</dt><dd>${aBordo(e) ? `🚢 Sí: su página de empleo habla de trabajo embarcado / offshore · ${enlace(e.web_empleo, "abrir")}` : e.web_empleo ? "Tiene página de empleo, pero no habla de trabajo a bordo" : "—"}</dd>
      <dt>País</dt><dd>${esc(nombrePais(e.pais))}${e.ciudad ? " · " + esc(e.ciudad) : ""}</dd>
      <dt>Sector</dt><dd>${esc(e.sector || "—")} · ${e.tipo === "agencia" ? "Agencia" : "Empresa"}</dd>
      <dt>Web</dt><dd>${enlace(e.web)}</dd>
      <dt>Empleo / tripulación</dt><dd>${enlace(e.web_empleo)}</dd>
      <dt>Email</dt><dd>${e.email ? esc(e.email) : "sin email"}${e.email_fuente ? ` · encontrado en ${enlace(e.email_fuente, "esta página")}` : e.email ? " · del directorio" : ""}</dd>
      ${e.telefono ? `<dt>Teléfono</dt><dd>${esc(e.telefono)}</dd>` : ""}
      <dt>Rastreo</dt><dd>${rastreo}</dd>
      <dt>De dónde sale</dt><dd>${esc(e.fuente)}</dd>
      ${e.notas ? `<dt>Notas</dt><dd>${esc(e.notas)}</dd>` : ""}
    </dl>
    <div class="fila">
      ${elegible(e) ? `<button class="btn ${e.seleccionada ? "" : "primario"}" id="ficha-sel">${e.seleccionada ? "Quitar de la selección" : "☑ Seleccionar para enviar"}</button>` : ""}
      ${e.web ? `<button class="btn" id="ficha-rastrear">${e.email_buscado ? "Rastrear de nuevo" : "Rastrear su web"}</button>` : ""}
      ${["nueva", "sin_email", "error"].includes(e.estado) ? `<button class="btn" id="ficha-descartar">Descartar</button>` : ""}
    </div>
    ${e.email && e.estado === "nueva" ? `<h3 style="margin:18px 0 0">Correo que recibiría</h3><div id="ficha-correo" class="secundario pequeno">Cargando…</div>` : ""}
    ${hilo.length ? `<h3 style="margin:18px 0 0">Conversación</h3>` + hilo.map((h) => `<div class="hilo-item">${h.html}</div>`).join("") : ""}`;
  $("#dialogo").showModal();

  const sel = $("#ficha-sel");
  if (sel) sel.addEventListener("click", async () => { await seleccionar([e.id], !e.seleccionada); abrirEmpresa(e.id); });
  const ras = $("#ficha-rastrear");
  if (ras) ras.addEventListener("click", async () => {
    ras.disabled = true; ras.textContent = "Rastreando…";
    try { await api(`empresas/${e.id}/buscar-email`, {}); } catch (err) { aviso(err.message, "critico"); }
    cargarEmpresas(); abrirEmpresa(e.id);
  });
  const des = $("#ficha-descartar");
  if (des) des.addEventListener("click", async () => {
    await api(`empresas/${e.id}`, { estado: "descartada" }).catch((err) => aviso(err.message, "critico"));
    $("#dialogo").close(); cargarEmpresas(); refrescar();
  });
  if (e.email && e.estado === "nueva") {
    try {
      const c = await api(`empresas/${e.id}/correo`);
      $("#ficha-correo").outerHTML = `
        <div class="correo-mock pequeno-mock">
          <div class="meta">Para <b>${esc(c.destinatario)}</b>${c.modo === "prueba" ? " (modo prueba: te llega a ti)" : c.modo === "simulacion" ? " (simulación: no sale nada)" : ""} · en ${c.idioma === "es" ? "español" : "inglés"}</div>
          <div class="correo-asunto">${esc(c.asunto)}</div>
          <div class="correo-cuerpo">${esc(c.cuerpo)}</div>
          ${c.adjunto ? `<div class="adjunto"><span>📎 ${esc(c.adjunto)}</span></div>` : ""}
        </div>`;
    } catch (err) {
      $("#ficha-correo").textContent = err.message;
    }
  }
}
$("#dialogo-cerrar").addEventListener("click", () => $("#dialogo").close());

// ------------------------------------------------------------ respuestas

async function cargarRespuestas(soloPanel = false) {
  st.respuestas = await api("respuestas").catch(() => []);
  pintarUltimas();
  if (!soloPanel) pintarRespuestas();
}

function pintarUltimas() {
  const ultimas = st.respuestas.slice(0, 6);
  $("#ultimas-respuestas").innerHTML = ultimas.length
    ? ultimas.map((r) => `<li data-abrir="${r.id}">
        ${avatar(r.empresa || r.remitente, r.categoria)}
        <div class="texto"><div class="fila-entre"><span class="nombre">${esc(r.empresa || r.remitente)}</span><span class="pequeno secundario">${esc(fecha(r.recibido_en))}</span></div>
        <div class="extracto">${esc(r.cuerpo.replace(/\s+/g, " "))}</div></div>
        ${cat(r.categoria, true)}</li>`).join("")
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
  const chips = [["todas", "Todas", st.respuestas.length], ["no_leidas", "Sin leer", cuenta((r) => !r.leida)],
    ...Object.entries(CATEGORIAS).map(([c, k]) => [c, k.txt, cuenta((r) => r.categoria === c)])];
  $("#filtro-categorias").innerHTML = chips.map(([v, t, n]) => `<button class="chip ${st.filtroCat === v ? "activo" : ""}" data-cat="${v}">${esc(t)} ${n}</button>`).join("");

  const lista = st.respuestas.filter((r) => st.filtroCat === "todas" || (st.filtroCat === "no_leidas" ? !r.leida : r.categoria === st.filtroCat));
  $("#respuestas-vacio").hidden = lista.length > 0;
  $("#lista-respuestas").innerHTML = lista.map((r) => `
    <li data-id="${r.id}" class="${r.leida ? "" : "no-leida"} ${r.id === st.respuestaSel ? "seleccionada" : ""}">
      ${avatar(r.empresa || r.remitente, r.categoria)}
      <div class="texto">
        <div class="cabecera-msg"><span class="nombre">${esc(r.empresa || r.remitente)}</span><span class="secundario pequeno">${esc(fecha(r.recibido_en))}</span></div>
        <div class="extracto">${esc(r.cuerpo.replace(/\s+/g, " "))}</div>
        ${cat(r.categoria, true)}
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
  if (!st.respuestas.length) await cargarRespuestas();
  const r = st.respuestas.find((x) => x.id === id);
  if (!r) return;
  if (!r.leida) {
    r.leida = 1;
    api(`respuestas/${id}/leida`, { leida: true }).then(refrescar);
  }
  pintarRespuestas();
  let original = null;
  if (r.empresa_id) {
    const d = await api("empresas/" + r.empresa_id).catch(() => null);
    original = d && (d.correos.find((c) => c.id === r.correo_id) || d.correos[0]);
  }
  const direccion = (r.remitente.match(/<([^>]+)>/) || [, r.remitente])[1];
  const responder = `mailto:${encodeURIComponent(direccion)}?subject=${encodeURIComponent(r.asunto.startsWith("Re:") ? r.asunto : "Re: " + r.asunto)}`;
  $("#detalle-respuesta").innerHTML = `
    <div class="cabecera-msg">
      <div class="remitente">${avatar(r.empresa || r.remitente, r.categoria, "grande")}
        <div><div><b>${esc(r.empresa || r.remitente)}</b> ${r.simulada ? '<span class="etiqueta-sim">respuesta simulada</span>' : ""}</div>
        <div class="meta">${esc(r.remitente)} · ${esc(fecha(r.recibido_en))}</div></div></div>
      <div class="fila" style="margin:0">
        <select id="cambiar-cat" title="Corregir la clasificación" style="width:auto">${Object.entries(CATEGORIAS).map(([c, k]) => `<option value="${c}" ${c === r.categoria ? "selected" : ""}>${k.icono} ${k.txt}</option>`).join("")}</select>
        ${r.simulada ? "" : `<a class="btn primario" href="${responder}">Responder</a>`}
      </div>
    </div>
    <h2 style="margin:18px 0 0">${esc(r.asunto)}</h2>
    <div class="cuerpo-msg">${esc(r.cuerpo)}</div>
    <div class="fila">
      ${r.empresa_id ? `<button class="btn" data-ver-empresa="${r.empresa_id}">Ver empresa</button>` : ""}
      <button class="btn" id="marcar-no-leida">Marcar como no leída</button>
    </div>
    ${original ? `<details class="original"><summary>Tu correo original (${esc(fecha(original.enviado_en))})</summary><pre>${esc(original.cuerpo)}</pre></details>` : ""}`;
  $("#cambiar-cat").addEventListener("change", async (ev) => {
    await api(`respuestas/${id}/categoria`, { categoria: ev.target.value });
    r.categoria = ev.target.value;
    pintarRespuestas();
    refrescar();
  });
  $("#marcar-no-leida").addEventListener("click", async () => {
    await api(`respuestas/${id}/leida`, { leida: false });
    r.leida = 0;
    pintarRespuestas();
    refrescar();
  });
  const ver = $("[data-ver-empresa]", $("#detalle-respuesta"));
  if (ver) ver.addEventListener("click", () => abrirEmpresa(ver.dataset.verEmpresa));
}

// ------------------------------------------------------------ configuración

const leer = (obj, ruta) => ruta.split(".").reduce((o, k) => (o ? o[k] : undefined), obj);
function escribir(obj, ruta, valor) {
  const partes = ruta.split(".");
  const ultimo = partes.pop();
  partes.reduce((o, k) => (o[k] ??= {}), obj)[ultimo] = valor;
}

async function cargarConfig() {
  st.config = await api("config");
  const f = $("#form-config");
  for (const el of f.elements) {
    if (!el.name) continue;
    if (el.name === "modo") { el.checked = el.value === st.config.modo; continue; }
    const v = leer(st.config, el.name);
    if (el.type === "checkbox") el.checked = Array.isArray(v) ? v.includes(el.value) : !!v;
    else el.value = Array.isArray(v) ? v.join("\n") : v ?? "";
  }
  $("#modo-borrar").textContent = MODOS[st.config.modo];
  marcarSucio(false);
  pintarCuentaConfig();
  mostrarPlantilla();
  mostrarFuente();
}

// Mostrar solo las opciones de la fuente elegida
function mostrarFuente() {
  const f = $('[name="busqueda.fuente"]').value;
  $$("[data-fuente]").forEach((d) => (d.hidden = d.dataset.fuente !== f));
}
$('[name="busqueda.fuente"]').addEventListener("change", mostrarFuente);

function leerFormulario() {
  const cfg = structuredClone(st.config);
  const f = $("#form-config");
  escribir(cfg, "busqueda.tipos", []);
  for (const el of f.elements) {
    if (!el.name) continue;
    if (el.name === "modo") { if (el.checked) cfg.modo = el.value; continue; }
    if (el.name === "busqueda.tipos") { if (el.checked) cfg.busqueda.tipos.push(el.value); continue; }
    if (["busqueda.ciudades", "busqueda.directorios"].includes(el.name)) { escribir(cfg, el.name, el.value.split("\n").map((c) => c.trim()).filter(Boolean)); continue; }
    if (el.type === "checkbox") escribir(cfg, el.name, el.checked);
    else if (el.type === "number") escribir(cfg, el.name, el.value === "" ? 0 : Number(el.value));
    else escribir(cfg, el.name, el.value);
  }
  return cfg;
}

function marcarSucio(sucio) {
  st.sucio = sucio;
  const e = $("#estado-guardado");
  e.className = "pequeno" + (sucio ? " pendiente" : "");
  e.textContent = sucio ? "Cambios sin guardar" : "";
}
$("#form-config").addEventListener("input", () => { marcarSucio(true); pintarPrevia(); });
$("#form-config").addEventListener("change", () => { marcarSucio(true); pintarPrevia(); });
window.addEventListener("beforeunload", (ev) => { if (st.sucio) ev.preventDefault(); });

$("#form-config").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const cfg = leerFormulario();
  if (!cfg.busqueda.tipos.length) return aviso("Marca al menos «Empresas» o «Agencias».", "critico");
  if (cfg.busqueda.fuente === "osm" && !cfg.busqueda.ciudades.length) return aviso("Escribe al menos una ciudad.", "critico");
  if (cfg.busqueda.fuente === "maritimo" && !cfg.busqueda.usar_wikidata && !cfg.busqueda.directorios.length) return aviso("Activa Wikidata o escribe al menos un directorio.", "critico");
  if (cfg.modo === "real" && st.config.modo !== "real" &&
      !confirm("Vas a activar el MODO REAL: al pulsar Iniciar se enviarán correos de verdad a las empresas.\n\nTe recomiendo probar antes con «Prueba real». ¿Continuar?")) return;
  try {
    st.config = await api("config", cfg);
    marcarSucio(false);
    const e = $("#estado-guardado");
    e.className = "pequeno ok";
    e.textContent = "✓ Guardado";
    $("#modo-borrar").textContent = MODOS[st.config.modo];
    refrescar();
  } catch (err) {
    aviso(err.message, "critico");
  }
});

// --- editor del mensaje

st.idioma = "es";
const sufijo = () => (st.idioma === "en" ? "_en" : "");
const textareaActiva = () => $(`textarea[data-tipo="${st.plantilla}"][data-idioma="${st.idioma}"]`);
const asuntoActivo = () => $(`input[data-idioma="${st.idioma}"]`);

function mostrarPlantilla() {
  $$("#selector-idioma button").forEach((x) => x.classList.toggle("activo", x.dataset.idioma === st.idioma));
  $$("#selector-plantilla button").forEach((x) => x.classList.toggle("activo", x.dataset.plantilla === st.plantilla));
  $$("textarea[data-tipo]").forEach((t) => (t.hidden = t.dataset.tipo !== st.plantilla || t.dataset.idioma !== st.idioma));
  $$("input[data-idioma]").forEach((i) => (i.hidden = i.dataset.idioma !== st.idioma));
  const para = st.plantilla === "agencia" ? "agencias" : "empresas";
  $("#etq-mensaje").textContent = st.idioma === "en" ? `Mensaje para ${para} (en inglés)` : `Mensaje para ${para}`;
  $("#ayuda-idioma").textContent = st.idioma === "en"
    ? "Se usa con las empresas de fuera de España. Si rellenas «Titulación en inglés» en tu perfil, {titulacion} la usará."
    : "Se usa con las empresas de España.";
  st.ultimoCampo = textareaActiva();
  pintarPrevia();
}
$("#selector-idioma").addEventListener("click", (ev) => {
  const b = ev.target.closest("[data-idioma]");
  if (b) { st.idioma = b.dataset.idioma; mostrarPlantilla(); }
});
$("#selector-plantilla").addEventListener("click", (ev) => {
  const b = ev.target.closest("[data-plantilla]");
  if (b) { st.plantilla = b.dataset.plantilla; mostrarPlantilla(); }
});

$$("[data-editable]").forEach((el) => el.addEventListener("focus", () => (st.ultimoCampo = el)));

$(".insertar").addEventListener("mousedown", (ev) => ev.preventDefault());  // no robar el foco al campo
$(".insertar").addEventListener("click", (ev) => {
  const b = ev.target.closest("[data-var]");
  if (!b) return;
  const campo = st.ultimoCampo && !st.ultimoCampo.hidden ? st.ultimoCampo : textareaActiva();
  const texto = `{${b.dataset.var}}`;
  const ini = campo.selectionStart ?? campo.value.length, fin = campo.selectionEnd ?? ini;
  campo.focus();
  campo.setRangeText(texto, ini, fin, "end");
  campo.dispatchEvent(new Event("input", { bubbles: true }));
});

$("#btn-restaurar").addEventListener("click", async () => {
  const cual = `${st.plantilla === "agencia" ? "para agencias" : "para empresas"}${st.idioma === "en" ? " en inglés" : ""}`;
  if (!confirm(`¿Restaurar el asunto y el mensaje ${cual} originales? Perderás tus cambios en ese texto.`)) return;
  const def = await api("config/defecto");
  asuntoActivo().value = def.envio["asunto" + sufijo()];
  textareaActiva().value = def.envio[(st.plantilla === "agencia" ? "plantilla_agencia" : "plantilla") + sufijo()];
  marcarSucio(true);
  pintarPrevia();
});

function rellenarConMarcas(texto, valores) {
  // Igual que el servidor, pero resaltando lo que se sustituye
  return texto.split(/(\{\w+\})/).map((trozo) => {
    const m = trozo.match(/^\{(\w+)\}$/);
    if (!m) return esc(trozo);
    const clave = m[1];
    if (!(clave in valores)) return `<mark class="desconocida" title="Variable desconocida: no se sustituirá">${esc(trozo)}</mark>`;
    if (!String(valores[clave]).trim()) return `<mark class="vacia" title="Rellénalo en «Tu perfil»">falta: ${esc(NOMBRES_VAR[clave] || clave)}</mark>`;
    return `<mark>${esc(valores[clave])}</mark>`;
  }).join("");
}

function pintarPrevia() {
  if (!st.config) return;
  const cfg = leerFormulario();
  const s = sufijo();
  const ej = EJEMPLO[st.idioma][st.plantilla];
  const valores = { ...cfg.perfil, empresa: ej.empresa, sector: ej.sector, ciudad: ej.ciudad || cfg.busqueda.ciudades[0] || "" };
  if (st.idioma === "en" && cfg.perfil.titulacion_en.trim()) valores.titulacion = cfg.perfil.titulacion_en;
  delete valores.cv;
  delete valores.titulacion_en;
  const agencia = cfg.envio["plantilla_agencia" + s];
  const plantilla = st.plantilla === "agencia" && agencia.trim() ? agencia : cfg.envio["plantilla" + s];
  const cuenta = st.estado && st.estado.cuenta.usuario;
  $("#previa-quien").textContent = (st.plantilla === "agencia" ? "una agencia" : "una empresa") + (st.idioma === "en" ? " de fuera de España" : " de España");
  $("#previa-avatar").textContent = iniciales(cfg.perfil.nombre);
  $("#previa-de").textContent = `${cfg.perfil.nombre} <${cuenta || cfg.perfil.email}>`;
  $("#previa-para").textContent = `${ej.empresa} <${ej.email}>`;
  $("#previa-asunto").innerHTML = rellenarConMarcas(cfg.envio["asunto" + s], valores);
  $("#previa-cuerpo").innerHTML = rellenarConMarcas(plantilla.replace(/\n{3,}/g, "\n\n").trimEnd(), valores);
  const adj = $("#previa-adjunto");
  adj.hidden = !cfg.envio.adjuntar_cv;
  $("span", adj).textContent = (cfg.perfil.cv || "cv.pdf").split(/[\\/]/).pop();
}

$("#btn-borrar").addEventListener("click", async () => {
  const modo = st.config.modo;
  let confirmacion = "";
  if (modo === "real") {
    confirmacion = prompt("Vas a borrar el historial REAL (a quién has escrito y sus respuestas). Escribe BORRAR para confirmar:") || "";
    if (confirmacion !== "BORRAR") return;
  } else if (!confirm(`¿Borrar todos los datos del modo ${MODOS[modo]}?`)) return;
  try {
    await api("borrar-datos", { confirmacion });
    st.ultimoEvento = 0;
    $("#registro").innerHTML = "";
    st.firma = "";
    aviso("Datos borrados.", "bien");
    refrescar();
  } catch (err) {
    aviso(err.message, "critico");
  }
});

// ------------------------------------------------------------ arranque

const inicial = location.hash.slice(1);
if (["panel", "empresas", "respuestas", "config"].includes(inicial)) mostrar(inicial);
refrescar();
setInterval(refrescar, 2000);
