/*
 * Lógica de la tanda del copiloto, sin dependencias de Chrome (se prueba con node --test).
 *
 * Reglas (no negociables):
 *  - Solo empieza cuando el usuario pulsa "Iniciar búsqueda".
 *  - Prepara como mucho `batchSize` (≈40) solicitudes, con pausas entre ofertas.
 *  - LinkedIn nunca se abre en tanda: queda en la lista para hacerlo de una en una.
 *  - NUNCA envía: deja cada formulario relleno para que el usuario lo revise y pulse Enviar.
 */
export const DEFAULTS = { batchSize: 40, pause: [8, 20], maxPolls: 60, pollMs: 2000 };

export function randomPause([min, max], rnd = Math.random) {
  return Math.round((min + (max - min) * rnd()) * 1000);
}

export async function runBatch({ api, openAndFill, sleep, onProgress = () => {}, shouldStop = () => false,
                                 filters, limits = {} }) {
  const lim = { ...DEFAULTS, ...limits };
  onProgress({ phase: "searching" });
  let s = await api("/searches", { method: "POST", body: { ...filters, include_companies: false } });
  for (let i = 0; s.status !== "done" && s.status !== "error" && i < lim.maxPolls; i++) {
    if (shouldStop()) return { stopped: true, prepared: [] };
    await sleep(lim.pollMs);
    s = await api("/searches/" + s.id);
  }
  if (s.status !== "done") throw new Error("La búsqueda no terminó: " + (s.error || s.status));
  const batch = await api("/batches", { method: "POST",
    body: { search_id: s.id, size: lim.batchSize, routes: ["ats_extension", "portal_copilot"] } });
  const queue = await api("/extension/queue?batch_id=" + batch.id);
  const enTanda = queue.filter((q) => q.route === "ats_extension").slice(0, lim.batchSize);
  const unaAUna = queue.filter((q) => q.route === "portal_copilot");
  const prepared = [];
  for (let i = 0; i < enTanda.length; i++) {
    if (shouldStop()) return { stopped: true, batchId: batch.id, prepared, oneByOne: unaAUna };
    const item = enTanda[i];
    onProgress({ phase: "filling", index: i + 1, total: enTanda.length, item });
    try {
      const res = await openAndFill(item);
      prepared.push({ ...item, result: res });
    } catch (e) {
      prepared.push({ ...item, error: String(e.message || e) });
    }
    if (i < enTanda.length - 1) await sleep(randomPause(lim.pause));
  }
  onProgress({ phase: "done", prepared: prepared.length, oneByOne: unaAUna.length });
  return { batchId: batch.id, prepared, oneByOne: unaAUna };
}

/** Construye el plan de relleno a partir de la respuesta de /extension/fill-plan y los archivos descargados. */
export function buildPlan(fillPlan, files = {}) {
  return {
    fields: fillPlan.fields.map((f) => ({ id: f.id, type: f.type, value: f.value && f.value.document_id ? null : f.value,
                                          display: f.display, needs_review: f.needs_review, reason: f.reason })),
    files,
  };
}
