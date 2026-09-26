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
const ESTADOS = { nueva: "Pendiente de enviar", sin_email: "Sin email", enviado: "Enviado", respondida: "Respondida", descartada: "Descartada", error: "Error" };

const st = {
  vista: "panel",
  modo: null,
  estado: null,
  empresas: [],
  respuestas: [],
  ultimoEvento: 0,
  firma: "",
  filtroCat: "todas",
  respuestaSel: null,
  config: null,
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
  const hoy = new Date();
  return d.toDateString() === hoy.toDateString() ? "hoy " + hora(iso) : d.toLocaleDateString("es-ES", { day: "numeric", month: "short" }) + " " + hora(iso);
}
const pct = (a, b) => (b ? Math.round((a / b) * 100) + "%" : "—");
const cat = (c) => { const k = CATEGORIAS[c] || CATEGORIAS.otra; return `<span class="cat cat-${esc(c)}"><span class="icono">${k.icono}</span>${k.txt}</span>`; };
const estadoHtml = (e) => `<span class="estado estado-${esc(e)}">${esc(ESTADOS[e] || e)}</span>`;

// ------------------------------------------------------------ navegación

function mostrar(vista) {
  st.vista = vista;
  history.replaceState(null, "", "#" + vista);
  $$(".pestana").forEach((b) => b.classList.toggle("activa", b.dataset.vista === vista));
  $$(".vista").forEach((s) => (s.hidden = s.id !== "vista-" + vista));
  if (vista === "empresas") cargarEmpresas();
  if (vista === "respuestas") cargarRespuestas();
  if (vista === "config") cargarConfig();
}
$$(".pestana").forEach((b) => b.addEventListener("click", () => mostrar(b.dataset.vista)));
document.addEventListener("click", (ev) => {
  const ir = ev.target.closest("[data-ir]");
  if (ir) mostrar(ir.dataset.ir);
});

// ------------------------------------------------------------ estado y panel

async function refrescar() {
  let e;
  try {
    e = await api("estado");
  } catch {
    $("#fase").textContent = "Sin conexión con el programa (¿está abierto app.py?)";
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

  // Si algo cambió (nuevas empresas, envíos o respuestas), recargar las listas visibles
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

  const n = e.kpis.no_leidas;
  $("#contador-no-leidas").hidden = !n;
  $("#contador-no-leidas").textContent = n;

  $("#btn-iniciar").disabled = e.motor.ejecutando;
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

function pintarPanel(e) {
  const k = e.kpis;
  const entrevistas = k.categorias.entrevista || 0;
  $("#k-empresas").textContent = k.empresas;
  $("#k-empresas-sub").textContent = `${k.con_email} con email · ${k.agencias} agencias`;
  $("#k-enviados").textContent = k.enviados;
  $("#k-enviados-sub").textContent = e.modo === "simulacion" ? `${k.pendientes_envio} pendientes` : `${e.enviados_hoy}/${e.limite_diario} hoy · ${k.pendientes_envio} pendientes`;
  $("#k-respondidas").textContent = k.respondidas;
  $("#k-respondidas-sub").textContent = `tasa de respuesta ${pct(k.respondidas, k.enviados)}`;
  $("#k-entrevistas").textContent = entrevistas;
  $("#k-entrevistas-sub").textContent = k.no_leidas ? `${k.no_leidas} respuesta(s) sin leer` : "";

  // progreso
  const m = e.motor;
  $("#fase").textContent = m.ejecutando ? m.fase + "…" : "Parado";
  $("#fase-num").textContent = !m.total ? "" : m.ejecutando ? `${m.hecho} / ${m.total}` : `Última ejecución: ${m.hecho} de ${m.total} correos`;
  const barra = $("#barra-progreso");
  barra.classList.toggle("indeterminado", m.ejecutando && !m.total);
  barra.style.width = m.ejecutando && m.total ? (m.hecho / m.total) * 100 + "%" : "0";
  $("#fase-ayuda").hidden = m.ejecutando;

  // embudo (una sola serie: longitud = cantidad)
  const etapas = [
    ["Con email", k.con_email, ""],
    ["Contactadas", k.enviados, pct(k.enviados, k.con_email)],
    ["Respondieron", k.respondidas, pct(k.respondidas, k.enviados)],
    ["Entrevistas", entrevistas, pct(entrevistas, k.enviados)],
  ];
  pintarBarras($("#embudo"), etapas.map(([t, v, p]) => ({ etiqueta: esc(t), valor: v, extra: p, titulo: `${t}: ${v}${p ? " (" + p + ")" : ""}` })), Math.max(k.con_email, 1));

  const cats = Object.keys(CATEGORIAS).map((c) => ({ etiqueta: cat(c), valor: k.categorias[c] || 0, clase: "cat-" + c, titulo: `${CATEGORIAS[c].txt}: ${k.categorias[c] || 0}` }));
  const maxCat = Math.max(1, ...cats.map((c) => c.valor));
  if (!k.respondidas) $("#categorias").innerHTML = `<p class="vacio" style="grid-column:1/-1">Todavía no ha respondido nadie.</p>`;
  else pintarBarras($("#categorias"), cats, maxCat);
}

function pintarBarras(cont, filas, max) {
  cont.innerHTML = filas.map((f) => `
    <div class="barra-etiqueta">${f.etiqueta}</div>
    <div class="barra-pista" title="${esc(f.titulo)}"><div class="barra-relleno ${f.clase || ""}" style="width:${(f.valor / max) * 100}%"></div></div>
    <div class="barra-valor">${f.valor}${f.extra ? `<span class="secundario">${esc(f.extra)}</span>` : ""}</div>`).join("");
}

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
    const ok = confirm(`MODO REAL: se enviarán correos de verdad a empresas y agencias (hasta ${e.limite_diario - e.enviados_hoy} hoy).\n\n¿Has revisado tu plantilla y tu CV?`);
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
  // No repintar mientras se escribe un email en la tabla
  if (tbody.contains(document.activeElement) && document.activeElement.tagName === "INPUT") return;
  tbody.innerHTML = filas.map((e) => `
    <tr data-id="${e.id}">
      <td><span class="nombre" data-ver="${e.id}">${esc(e.nombre)}</span>${e.web ? ` <a href="${esc(e.web)}" target="_blank" rel="noopener" class="pequeno">web</a>` : ""}</td>
      <td>${e.tipo === "agencia" ? "Agencia" : "Empresa"}</td>
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
    <form id="form-empresa" style="margin-top:12px">
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
    ...d.respuestas.map((r) => ({ ts: r.recibido_en, html: `<div class="meta"><b>${esc(r.remitente)}</b> · ${esc(fecha(r.recibido_en))} · ${cat(r.categoria)} ${r.simulada ? '<span class="etiqueta-sim">simulada</span>' : ""}</div><div class="cuerpo-msg">${esc(r.cuerpo)}</div>` })),
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
  const ul = $("#ultimas-respuestas");
  const ultimas = st.respuestas.slice(0, 6);
  ul.innerHTML = ultimas.length
    ? ultimas.map((r) => `<li data-abrir="${r.id}"><span><span class="nombre">${esc(r.empresa || r.remitente)}</span><br><span class="secundario pequeno">${esc(fecha(r.recibido_en))}</span></span>${cat(r.categoria)}</li>`).join("")
    : '<li class="vacio" style="cursor:default">Aún no hay respuestas.</li>';
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
      <div class="cabecera-msg"><span class="nombre">${esc(r.empresa || r.remitente)}</span><span class="secundario pequeno">${esc(fecha(r.recibido_en))}</span></div>
      <div class="extracto">${esc(r.cuerpo.replace(/\s+/g, " "))}</div>
      <div>${cat(r.categoria)}</div>
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
    original = d && d.correos.find((c) => c.id === r.correo_id) || (d && d.correos[0]);
  }
  const responder = `mailto:${encodeURIComponent((r.remitente.match(/<([^>]+)>/) || [, r.remitente])[1])}?subject=${encodeURIComponent(r.asunto.startsWith("Re:") ? r.asunto : "Re: " + r.asunto)}`;
  $("#detalle-respuesta").innerHTML = `
    <div class="cabecera-msg">
      <div><h2 style="margin:0">${esc(r.asunto)}</h2>
        <div class="meta">De <b>${esc(r.remitente)}</b> · ${esc(fecha(r.recibido_en))} ${r.simulada ? '<span class="etiqueta-sim">respuesta simulada</span>' : ""}</div></div>
      <div class="fila" style="margin:0">
        <select id="cambiar-cat" title="Corregir la clasificación">${Object.entries(CATEGORIAS).map(([c, k]) => `<option value="${c}" ${c === r.categoria ? "selected" : ""}>${k.icono} ${k.txt}</option>`).join("")}</select>
        ${r.simulada ? "" : `<a class="btn primario" href="${responder}">Responder</a>`}
        ${r.empresa_id ? `<button class="btn" data-ver-empresa="${r.empresa_id}">Ver empresa</button>` : ""}
        <button class="btn" id="marcar-no-leida">Marcar no leída</button>
      </div>
    </div>
    <div class="cuerpo-msg">${esc(r.cuerpo)}</div>
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
  $("#estado-guardado").textContent = "";
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

$("#form-config").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const cfg = leerFormulario();
  if (!cfg.busqueda.tipos.length) return aviso("Marca al menos «Empresas» o «Agencias».", "critico");
  if (cfg.modo === "real" && st.config.modo !== "real" &&
      !confirm("Vas a activar el MODO REAL: al pulsar Iniciar se enviarán correos de verdad a las empresas.\n\nTe recomiendo probar antes con «Prueba real». ¿Continuar?")) return;
  try {
    st.config = await api("config", cfg);
    $("#estado-guardado").textContent = "Guardado ✓";
    $("#modo-borrar").textContent = MODOS[st.config.modo];
    refrescar();
  } catch (err) {
    aviso(err.message, "critico");
  }
});

$$("[data-previa]").forEach((b) => b.addEventListener("click", async () => {
  const p = await api("vista-previa", { tipo: b.dataset.previa, config: leerFormulario() });
  const pre = $("#vista-previa");
  pre.hidden = false;
  pre.textContent = `Asunto: ${p.asunto}\n\n${p.cuerpo}`;
}));

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
    aviso("Datos borrados.");
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
