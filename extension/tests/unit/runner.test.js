// Lógica de la tanda sin Chrome: límites, pausas, LinkedIn de una en una y nada de envíos.
import assert from "node:assert/strict";
import { test } from "node:test";
import { buildPlan, randomPause, runBatch } from "../../src/lib/runner.js";

function fakeApi(queue) {
  const calls = [];
  const api = async (path, opts = {}) => {
    calls.push([opts.method || "GET", path, opts.body]);
    if (path === "/searches") return { id: 1, status: "queued" };
    if (path === "/searches/1") return { id: 1, status: "done" };
    if (path === "/batches") return { id: 9 };
    if (path.startsWith("/extension/queue")) return queue;
    throw new Error("ruta inesperada " + path);
  };
  return { api, calls };
}

const item = (i, route = "ats_extension") => ({ id: i, route, apply_url: "https://jobs.lever.co/x/" + i, title: "T" + i });

test("prepara como mucho batchSize, con pausas, y deja LinkedIn para hacerlo de una en una", async () => {
  const cola = [...Array.from({ length: 45 }, (_, i) => item(i)), item(100, "portal_copilot")];
  const { api, calls } = fakeApi(cola);
  const abiertas = [], pausas = [];
  const r = await runBatch({ api, filters: { countries: ["es"] }, limits: { batchSize: 40, pause: [8, 20], pollMs: 0 },
    openAndFill: async (it) => { abiertas.push(it.id); return { filled: 3 }; },
    sleep: async (ms) => { pausas.push(ms); } });
  assert.equal(abiertas.length, 40);
  assert.ok(!abiertas.includes(100), "LinkedIn nunca se abre en tanda");
  assert.equal(r.oneByOne.length, 1);
  const entreOfertas = pausas.slice(1);
  assert.equal(entreOfertas.length, 39);
  assert.ok(entreOfertas.every((ms) => ms >= 8000 && ms <= 20000));
  // Solo se buscan y preparan: ninguna llamada de envío
  assert.ok(!calls.some(([, p]) => /send|submitted|mark-sent/.test(p)));
  const busqueda = calls.find(([, p]) => p === "/searches")[2];
  assert.equal(busqueda.include_companies, false);
});

test("se puede detener a mitad", async () => {
  const { api } = fakeApi(Array.from({ length: 10 }, (_, i) => item(i)));
  let n = 0;
  const r = await runBatch({ api, filters: {}, limits: { pollMs: 0 }, sleep: async () => {},
    openAndFill: async () => { n++; return {}; }, shouldStop: () => n >= 3 });
  assert.equal(r.stopped, true);
  assert.equal(r.prepared.length, 3);
});

test("un fallo en una oferta no para las demás", async () => {
  const { api } = fakeApi([item(1), item(2)]);
  const r = await runBatch({ api, filters: {}, limits: { pollMs: 0 }, sleep: async () => {},
    openAndFill: async (it) => { if (it.id === 1) throw new Error("web caída"); return { filled: 1 }; } });
  assert.equal(r.prepared[0].error, "web caída");
  assert.equal(r.prepared[1].result.filled, 1);
});

test("plan: los archivos van aparte y nunca como valor de texto", () => {
  const p = buildPlan({ fields: [{ id: "a", type: "file", value: { document_id: 1, filename: "cv.pdf" } },
                                 { id: "b", type: "text", value: "Ana", needs_review: false }] }, { a: { bytes: [1] } });
  assert.equal(p.fields[0].value, null);
  assert.equal(p.fields[1].value, "Ana");
  assert.deepEqual(p.files, { a: { bytes: [1] } });
});

test("pausa aleatoria dentro del rango", () => {
  assert.equal(randomPause([8, 20], () => 0), 8000);
  assert.equal(randomPause([8, 20], () => 1), 20000);
});
