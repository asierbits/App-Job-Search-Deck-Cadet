// Tests del copiloto en un Chromium real con páginas de ejemplo de cada plataforma (sin red).
import { expect, test } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const src = (p) => path.join(here, "../../src/content", p);
const FILES = ["core.js", "adapters/greenhouse.js", "adapters/lever.js", "adapters/ashby.js", "adapters/linkedin.js",
               "adapters/phase2.js", "adapters/indeed.js"].map(src);

async function load(page, url, fixture) {
  const html = fs.readFileSync(path.join(here, "../fixtures", fixture), "utf8");
  await page.route("**/*", (r) => (r.request().url() === url ? r.fulfill({ contentType: "text/html; charset=utf-8", body: html }) : r.abort()));
  await page.goto(url);
  for (const f of FILES) await page.addScriptTag({ path: f });
}

function plan(fields, answers, files = {}) {
  return {
    fields: fields.map((f) => ({ id: f.id, type: f.type, value: answers[f.label] ?? null,
                                 needs_review: !(f.label in answers), reason: "prueba" })),
    files: Object.fromEntries(Object.entries(files).map(([label, file]) => [fields.find((f) => f.label === label).id, file])),
  };
}

const CV = { bytes: [37, 80, 68, 70, 45, 49], filename: "cv-ana.pdf", mime: "application/pdf" };

test("Greenhouse: extrae, rellena y NUNCA envía", async ({ page }) => {
  await load(page, "https://boards.greenhouse.io/naviera/jobs/1001", "greenhouse.html");
  const form = await page.evaluate(() => window.__knok.extract());
  expect(form.platform).toBe("greenhouse");
  const etiquetas = form.fields.map((f) => f.label);
  expect(etiquetas).toEqual(["First Name", "Last Name", "Email", "Phone", "Resume/CV", "LinkedIn Profile",
    "Are you legally authorized to work in Spain?", "What is your favourite ship and why?", "I agree to the privacy policy"]);
  const sel = form.fields.find((f) => f.type === "select");
  expect(sel.options).toEqual([{ label: "Yes", value: "1" }, { label: "No", value: "0" }]);
  expect(form.fields.find((f) => f.label === "First Name").required).toBe(true);

  const p = plan(form.fields, { "First Name": "Ana", "Last Name": "Pérez", Email: "ana@example.com",
    Phone: "+34 600", "LinkedIn Profile": "https://linkedin.com/in/ana", "Are you legally authorized to work in Spain?": "1" },
    { "Resume/CV": CV });
  const res = await page.evaluate((pl) => window.__knok.fill(pl), p);
  expect(res.filled).toBe(7);
  expect(await page.inputValue("#first_name")).toBe("Ana");
  expect(await page.inputValue("#q2")).toBe("1");
  expect(await page.evaluate(() => document.getElementById("resume").files[0].name)).toBe("cv-ana.pdf");
  // Los marcos de "revisar": pregunta desconocida y consentimiento (que nunca se marca solo)
  expect(await page.isChecked("#consent")).toBe(false);
  expect(await page.locator("[data-knok-review]").count()).toBe(2);
  const c = await page.evaluate(() => window.contadores);
  expect(c.submit).toBe(0);
  expect(c.clickEnviar).toBe(0);
  expect(c.input).toBeGreaterThan(0); // eventos para webs con React
  expect(await page.evaluate(() => window.__knok.isSubmitted())).toBe(false);
});

test("Greenhouse: detecta el envío hecho por el usuario", async ({ page }) => {
  await load(page, "https://boards.greenhouse.io/naviera/jobs/1001/confirmation", "greenhouse.html");
  await page.evaluate(() => { document.body.insertAdjacentHTML("beforeend", "<div id='application_confirmation'>Thank you for applying</div>"); });
  expect(await page.evaluate(() => window.__knok.isSubmitted())).toBe(true);
});

test("Lever: etiquetas propias, enlaces y CV", async ({ page }) => {
  await load(page, "https://jobs.lever.co/nordsee/0f9b1c2d-1111-2222-3333-444455556666/apply", "lever.html");
  const form = await page.evaluate(() => window.__knok.extract());
  expect(form.platform).toBe("lever");
  expect(form.fields.map((f) => f.label)).toEqual(["Full name", "Email", "Current company", "LinkedIn URL", "Resume/CV",
                                                   "Additional information"]);
  expect(form.fields.find((f) => f.label === "LinkedIn URL").name).toBe("urls[LinkedIn]");
  const res = await page.evaluate((pl) => window.__knok.fill(pl),
    plan(form.fields, { "Full name": "Ana Pérez", Email: "ana@example.com" }, { "Resume/CV": CV }));
  expect(res.filled).toBe(3);
  expect(await page.evaluate(() => window.contadores.submit)).toBe(0);
});

test("Ashby: radios, desplegable especial y CAPTCHA", async ({ page }) => {
  await load(page, "https://jobs.ashbyhq.com/aegean/9a8b7c6d-1111-2222-3333-444455556666/application", "ashby.html");
  const form = await page.evaluate(() => window.__knok.extract());
  expect(form.platform).toBe("ashby");
  expect(form.captcha).toBe(true);
  const radio = form.fields.find((f) => f.type === "radio");
  expect(radio.label).toBe("Will you now or in the future require visa sponsorship?");
  expect(radio.options.map((o) => o.value)).toEqual(["yes", "no"]);
  const combo = form.fields.find((f) => f.type === "combobox");
  expect(combo.label).toBe("Country of residence");
  const res = await page.evaluate((pl) => window.__knok.fill(pl), plan(form.fields, {
    Name: "Ana Pérez", Email: "ana@example.com", "Will you now or in the future require visa sponsorship?": "no",
    "Country of residence": "Spain" }));
  expect(await page.isChecked("input[value=no]")).toBe(true);
  expect(res.captcha).toBe(true);
  await expect(page.getByText("Resuélvelo tú")).toBeVisible();
  // el desplegable especial no se toca: se sugiere el valor y se marca para revisar
  await expect(page.getByText("sugerencia: Spain")).toBeVisible();
});

test("LinkedIn: solo el paso visible del diálogo Easy Apply, nada de la página", async ({ page }) => {
  await load(page, "https://www.linkedin.com/jobs/view/0000005001/", "linkedin.html");
  const form = await page.evaluate(() => window.__knok.extract());
  expect(form.platform).toBe("linkedin");
  expect(form.fields.map((f) => f.label)).toEqual(["Mobile phone number",
    "How many years of experience do you have with ECDIS?"]); // el buscador de la página queda fuera
  const job = await page.evaluate(() => window.__knok.extractJob());
  expect(job).toMatchObject({ title: "Deck Cadet", company: "Baltic Container Lines", easy_apply: true });
});

test("Indeed: nunca se rellena (solo se puede guardar la oferta)", async ({ page }) => {
  await load(page, "https://fr.indeed.com/viewjob?jk=abc", "indeed.html");
  const form = await page.evaluate(() => window.__knok.extract());
  expect(form.blocked).toContain("prohíben");
  expect(form.fields).toEqual([]);
  const job = await page.evaluate(() => window.__knok.extractJob());
  expect(job.title).toBe("Deck Cadet");
  expect(job.company).toBe("Brittany Sea Ferries");
});

test("Inyectar dos veces no duplica adaptadores", async ({ page }) => {
  await load(page, "https://boards.greenhouse.io/naviera/jobs/1001", "greenhouse.html");
  for (const f of FILES) await page.addScriptTag({ path: f });
  expect(await page.evaluate(() => window.__knok.adapters.filter((a) => a.name === "greenhouse").length)).toBe(1);
});

test("Página de prueba de knok: formulario genérico, empresa y puesto de la propia página", async ({ page }) => {
  const html = fs.readFileSync(path.join(here, "../../../knok/api/static/panel/prueba-extension.html"), "utf8");
  const url = "http://localhost:8000/ui/prueba-extension.html";
  await page.route("**/*", (r) => (r.request().url() === url ? r.fulfill({ contentType: "text/html; charset=utf-8", body: html }) : r.abort()));
  await page.goto(url);
  for (const f of FILES) await page.addScriptTag({ path: f });
  const form = await page.evaluate(() => window.__knok.extract());
  expect(form.platform).toBe("generic");
  expect(form.company).toBe("Empresa de Ejemplo S.L.");
  expect(form.title).toBe("Auxiliar administrativo/a (prácticas)");
  expect(form.fields.map((f) => f.label)).toContain("Correo electrónico");
  const p = plan(form.fields, { Nombre: "Ana", "Correo electrónico": "ana@example.com" }, { "Currículum (CV)": CV });
  await page.evaluate((pl) => window.__knok.fill(pl), p);
  expect(await page.inputValue("#nombre")).toBe("Ana");
  expect(await page.isChecked("#privacidad")).toBe(false);   // el consentimiento nunca se marca solo
  expect(await page.locator("#resultado").isHidden()).toBe(true);   // y nunca se envía
});

test("LinkedIn: guarda la lista que el usuario tiene en pantalla, sin pedir nada más a LinkedIn", async ({ page }) => {
  const peticiones = [];
  page.on("request", (r) => peticiones.push(r.url()));
  await load(page, "https://www.linkedin.com/jobs/search/?keywords=backend", "linkedin_lista.html");
  const lista = await page.evaluate(() => window.__knok.extractList());
  expect(lista).toEqual([
    { url: "https://www.linkedin.com/jobs/view/4011111111/", title: "Backend Engineer (m/f/d)", company: "Acme Corp",
      location: "Madrid, Comunidad de Madrid, España (Híbrido)", easy_apply: false, apply_url: "" },
    { url: "https://www.linkedin.com/jobs/view/4022222222/", title: "Data Analyst", company: "Otra Firma",
      location: "Barcelona, Cataluña, España", easy_apply: true, apply_url: "" },
    { url: "https://www.linkedin.com/jobs/view/4044444444/", title: "Recepcionista", company: "Hotel Mar",
      location: "Valencia, España", easy_apply: false, apply_url: "" },
  ]);
  expect(peticiones).toEqual(["https://www.linkedin.com/jobs/search/?keywords=backend"]);   // solo la página que ya estaba abierta
});
