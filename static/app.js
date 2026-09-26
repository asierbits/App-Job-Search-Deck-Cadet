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
// Empresas de ejemplo para la vista previa del mensaje
const EJEMPLO = {
  empresa: { empresa: "Nortia Software", sector: "Informática / IT", email: "rrhh@nortia.example.com" },
  agencia: { empresa: "Talentia Empleo", sector: "Agencia de empleo / ETT", email: "candidatos@talentia.example.com" },
};
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
  if (firma !== st.firma) {
    st.firma = firma;
    await cargarRespuestas(st.vista !== "respuestas");
    if (st.vista === "empresas") cargarEmpresas();
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

  const n = e.kpis.no_leidas;
  $("#contador-no-leidas").hidden = !n;
  $("#contador-no-leidas").textContent = n;
  $("#btn-iniciar").hidden = e.motor.ejecutando;
  $("#btn-detener").hidden = !e.motor.ejecutando;
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
    resumen = `Todavía no has empezado. Pulsa <b>Iniciar búsqueda</b> y buscaré empresas y agencias en <b>${esc(e.ciudad)}</b> para enviarles tu candidatura.`;
  } else {
    resumen = `Has contactado <b>${k.enviados}</b> ${k.enviados === 1 ? "empresa" : "empresas"} y <b>${k.respondidas}</b> ${k.respondidas === 1 ? "te ha" : "te han"} respondido.`;
    if (entrevistas) resumen += ` Tienes <b>${entrevistas} ${entrevistas === 1 ? "propuesta" : "propuestas"} de entrevista</b>. ¡Enhorabuena!`;
    if (k.no_leidas) resumen += ` Hay <b>${k.no_leidas}</b> ${k.no_leidas === 1 ? "respuesta" : "respuestas"} sin leer.`;
    else if (k.pendientes_envio) resumen += ` Quedan <b>${k.pendientes_envio}</b> por escribir.`;
  }
  $("#resumen").innerHTML = resumen;
  const fuente = e.fuente === "osm" ? "OpenStreetMap" : "datos de ejemplo";
  $("#hero-detalle").textContent = e.modo === "simulacion"
    ? `Simulación: ${fuente} de ${e.ciudad}, sin enviar nada de verdad.`
    : e.modo === "prueba"
      ? `Prueba: hasta ${e.max_por_ejecucion} correos, todos a tu propio email.`
      : `Real: hasta ${Math.min(e.max_por_ejecucion, e.limite_diario - e.enviados_hoy)} correos a empresas de ${e.ciudad}.`;

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
    { txt: "Encontradas", valor: k.empresas, sub: `${k.con_email} con email · ${k.agencias} agencias`, icono: ICONOS.buscar, color: "var(--tinta-2)" },
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

$("#btn-iniciar").addEventListener("click", async () => {
  const e = st.estado;
  if (e && e.modo === "real") {
    const ok = confirm(`MODO REAL: se enviarán correos de verdad a empresas y agencias (hasta ${e.limite_diario - e.enviados_hoy} hoy).\n\n¿Has revisado tu mensaje y tu CV?`);
    if (!ok) return;
  }
  try {
    await api("iniciar", {});
    refrescar();
  } catch (err) {
    aviso(err.message, "critico");
  }
});
$("#btn-detener").addEventListener("click", () => api("detener", {}).catch((err) => aviso(err.message, "critico")));

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

function pintarEmpresas() {
  const texto = $("#filtro-texto").value.trim().toLowerCase();
  const estado = $("#filtro-estado").value;
  const tipo = $("#filtro-tipo").value;
  const filas = st.empresas.filter((e) =>
    (!estado || e.estado === estado) && (!tipo || e.tipo === tipo) &&
    (!texto || `${e.nombre} ${e.sector} ${e.email}`.toLowerCase().includes(texto)));

  $("#empresas-vacio").hidden = st.empresas.length > 0;
  const tbody = $("#tabla-empresas");
  if (tbody.contains(document.activeElement) && document.activeElement.tagName === "INPUT") return;
  tbody.innerHTML = filas.map((e) => `
    <tr data-id="${e.id}">
      <td><div class="celda-nombre">${avatar(e.nombre, e.ultima_categoria)}<span><span class="nombre" data-ver="${e.id}">${esc(e.nombre)}</span>${e.web ? ` <a href="${esc(e.web)}" target="_blank" rel="noopener" class="pequeno">web</a>` : ""}</span></div></td>
      <td><span class="tipo-chip">${e.tipo === "agencia" ? "Agencia" : "Empresa"}</span></td>
      <td class="secundario">${esc(e.sector)}</td>
      <td>${e.email ? esc(e.email) : `<input class="email-input" data-email="${e.id}" type="email" placeholder="añadir email y pulsar Enter">`}</td>
      <td>${estadoHtml(e.estado)}${e.ultima_categoria ? " · " + cat(e.ultima_categoria) : ""}</td>
      <td class="acciones-fila">
        <button class="btn mini" data-ver="${e.id}">Ver</button>
        ${e.estado === "descartada"
          ? `<button class="btn mini" data-estado="${e.id}" data-valor="nueva">Recuperar</button>`
          : ["nueva", "sin_email", "error"].includes(e.estado) ? `<button class="btn mini" data-estado="${e.id}" data-valor="descartada">Descartar</button>` : ""}
      </td>
    </tr>`).join("");
}

["#filtro-texto", "#filtro-estado", "#filtro-tipo"].forEach((s) => $(s).addEventListener("input", pintarEmpresas));

$("#tabla-empresas").addEventListener("click", async (ev) => {
  const ver = ev.target.closest("[data-ver]");
  if (ver) return abrirEmpresa(ver.dataset.ver);
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
  $("#dialogo-titulo").textContent = "Añadir empresa o agencia";
  $("#dialogo-cuerpo").innerHTML = `
    <form id="form-empresa" style="margin-top:14px">
      <label>Nombre<input name="nombre" required></label>
      <label>Email<input name="email" type="email"></label>
      <label>Tipo<select name="tipo"><option value="empresa">Empresa</option><option value="agencia">Agencia de empleo / ETT</option></select></label>
      <label>Sector<input name="sector"></label>
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

async function abrirEmpresa(id) {
  const d = await api("empresas/" + id);
  const e = d.empresa;
  $("#dialogo-titulo").textContent = e.nombre;
  const hilo = [
    ...d.correos.map((c) => ({ ts: c.enviado_en, html: `<div class="meta"><b>Tú</b> → ${esc(c.destinatario)} · ${esc(fecha(c.enviado_en))} · <i>${esc(c.asunto)}</i></div><div class="cuerpo-msg">${esc(c.cuerpo)}</div>` })),
    ...d.respuestas.map((r) => ({ ts: r.recibido_en, html: `<div class="meta"><b>${esc(r.remitente)}</b> · ${esc(fecha(r.recibido_en))} · ${cat(r.categoria, true)} ${r.simulada ? '<span class="etiqueta-sim">simulada</span>' : ""}</div><div class="cuerpo-msg">${esc(r.cuerpo)}</div>` })),
  ].sort((a, b) => a.ts.localeCompare(b.ts));
  $("#dialogo-cuerpo").innerHTML = `
    <p class="meta">${e.tipo === "agencia" ? "Agencia" : "Empresa"} · ${esc(e.sector)} · ${estadoHtml(e.estado)}<br>
      ${e.email ? esc(e.email) : "sin email"}${e.telefono ? " · " + esc(e.telefono) : ""}${e.web ? ` · <a href="${esc(e.web)}" target="_blank" rel="noopener">${esc(e.web)}</a>` : ""}<br>
      Fuente: ${esc(e.fuente)}${e.notas ? "<br>Notas: " + esc(e.notas) : ""}</p>
    ${hilo.length ? hilo.map((h) => `<div class="hilo-item">${h.html}</div>`).join("") : '<p class="vacio">Todavía no se le ha escrito.</p>'}`;
  $("#dialogo").showModal();
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
    else el.value = v ?? "";
  }
  $("#modo-borrar").textContent = MODOS[st.config.modo];
  marcarSucio(false);
  pintarCuentaConfig();
  pintarPrevia();
}

function leerFormulario() {
  const cfg = structuredClone(st.config);
  const f = $("#form-config");
  escribir(cfg, "busqueda.tipos", []);
  for (const el of f.elements) {
    if (!el.name) continue;
    if (el.name === "modo") { if (el.checked) cfg.modo = el.value; continue; }
    if (el.name === "busqueda.tipos") { if (el.checked) cfg.busqueda.tipos.push(el.value); continue; }
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

function textareaActiva() {
  return $(`textarea[data-tipo="${st.plantilla}"]`);
}

$("#selector-plantilla").addEventListener("click", (ev) => {
  const b = ev.target.closest("[data-plantilla]");
  if (!b) return;
  st.plantilla = b.dataset.plantilla;
  $$("#selector-plantilla button").forEach((x) => x.classList.toggle("activo", x === b));
  $$("textarea[data-tipo]").forEach((t) => (t.hidden = t.dataset.tipo !== st.plantilla));
  $("#etq-mensaje").textContent = st.plantilla === "agencia" ? "Mensaje para agencias" : "Mensaje para empresas";
  st.ultimoCampo = textareaActiva();
  pintarPrevia();
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
  if (!confirm(`¿Restaurar el asunto y el mensaje ${st.plantilla === "agencia" ? "para agencias" : "para empresas"} originales? Perderás tus cambios en ese texto.`)) return;
  const def = await api("config/defecto");
  $('[name="envio.asunto"]').value = def.envio.asunto;
  textareaActiva().value = st.plantilla === "agencia" ? def.envio.plantilla_agencia : def.envio.plantilla;
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
  const ej = EJEMPLO[st.plantilla];
  const valores = { ...cfg.perfil, empresa: ej.empresa, sector: ej.sector, ciudad: cfg.busqueda.ciudad };
  delete valores.cv;
  const plantilla = st.plantilla === "agencia" && cfg.envio.plantilla_agencia.trim() ? cfg.envio.plantilla_agencia : cfg.envio.plantilla;
  const cuenta = st.estado && st.estado.cuenta.usuario;
  $("#previa-quien").textContent = st.plantilla === "agencia" ? "una agencia" : "una empresa";
  $("#previa-avatar").textContent = iniciales(cfg.perfil.nombre);
  $("#previa-de").textContent = `${cfg.perfil.nombre} <${cuenta || cfg.perfil.email}>`;
  $("#previa-para").textContent = `${ej.empresa} <${ej.email}>`;
  $("#previa-asunto").innerHTML = rellenarConMarcas(cfg.envio.asunto, valores);
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
