/*
 * knok · núcleo del copiloto (se inyecta en la página SOLO cuando el usuario pulsa un botón).
 *
 * - extract(): lee los campos del formulario (etiqueta, tipo, opciones, obligatorio…).
 * - fill(plan): escribe los valores que devuelve la API y marca lo que requiere revisión.
 * - NUNCA pulsa "Enviar" ni envía el formulario. El usuario revisa y envía.
 * - Si hay un CAPTCHA, lo avisa: lo resuelve el usuario.
 *
 * Los adaptadores (adapters/*.js) se registran con window.__knok.register(adapter) y solo dicen
 * dónde está el formulario de cada plataforma y cómo reconocer que se ha enviado.
 */
(function () {
  "use strict";
  if (window.__knok && window.__knok.version) return;

  const adapters = [];
  const MARK = "data-knok-id";

  function text(el) {
    return (el && (el.innerText || el.textContent) || "").replace(/\s+/g, " ").trim();
  }

  function cleanLabel(t) {
    return (t || "").replace(/\s*[*✱]\s*$/g, "").replace(/\s*\((required|obligatorio|requerido)\)\s*$/i, "")
      .replace(/\s+/g, " ").trim();
  }

  function labelFor(el, adapter) {
    if (adapter && adapter.labelFor) {
      const l = adapter.labelFor(el);
      if (l) return cleanLabel(l);
    }
    if (el.labels && el.labels.length) return cleanLabel(text(el.labels[0]));
    const by = el.getAttribute("aria-labelledby");
    if (by) {
      const t = by.split(/\s+/).map((id) => text(document.getElementById(id))).join(" ");
      if (t.trim()) return cleanLabel(t);
    }
    if (el.getAttribute("aria-label")) return cleanLabel(el.getAttribute("aria-label"));
    const lab = el.closest("label");
    if (lab) return cleanLabel(text(lab));
    // Sube por los contenedores (hasta 5 niveles) buscando una etiqueta que no sea de otro campo
    let box = el.parentElement;
    for (let i = 0; box && i < 5; i++, box = box.parentElement) {
      const cand = box.querySelector("legend, label, .label, [class*='label'], [class*='Label']");
      if (cand && text(cand) && cand.querySelectorAll("input, select, textarea").length === 0) return cleanLabel(text(cand));
      if (box.querySelectorAll("input, select, textarea").length > 3) break;   // ya es el formulario entero
    }
    return cleanLabel(el.getAttribute("placeholder") || el.getAttribute("name") || "");
  }

  function fieldType(el) {
    const tag = el.tagName.toLowerCase();
    if (tag === "select") return el.multiple ? "multiselect" : "select";
    if (tag === "textarea") return "textarea";
    if (el.getAttribute("role") === "combobox") return "combobox";
    const t = (el.getAttribute("type") || "text").toLowerCase();
    return ["email", "tel", "url", "number", "date", "file", "checkbox", "radio", "hidden"].includes(t) ? t : "text";
  }

  function isVisible(el) {
    if (el.type === "file") return true; // los inputs de archivo suelen estar ocultos tras un botón
    const r = el.getBoundingClientRect();
    const s = window.getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== "hidden" && s.display !== "none";
  }

  function adapterFor(loc) {
    return adapters.find((a) => a.matches(loc || window.location)) || null;
  }

  function root(adapter) {
    return (adapter && adapter.root && adapter.root(document)) || document;
  }

  /** Lee el formulario. Agrupa los radios por nombre. */
  function extract() {
    const adapter = adapterFor();
    if (adapter && adapter.blocked) return { platform: adapter.name, blocked: adapter.blocked, fields: [] };
    const r = root(adapter);
    const fields = [];
    const radios = {};
    let n = 0;
    r.querySelectorAll("input, select, textarea, [role='combobox']").forEach((el) => {
      const type = fieldType(el);
      if (type === "hidden" || el.disabled || (type !== "radio" && !isVisible(el))) return;
      if (el.closest("[data-knok-ignore]")) return;
      if (["submit", "button", "reset", "image", "search", "password"].includes((el.type || "").toLowerCase())) return;
      if (type === "radio") {
        const name = el.name || "radio" + n;
        if (!radios[name]) {
          const box = el.closest("fieldset, [role='radiogroup'], .field, [class*='question']") || el.parentElement;
          const leg = box && box.querySelector("legend, label, [class*='label']");
          radios[name] = { id: "", label: cleanLabel(leg ? text(leg) : name), type: "radio", required: !!el.required,
                           options: [], name };
          radios[name].id = "knok-" + n++;
          el.setAttribute(MARK, radios[name].id);
          fields.push(radios[name]);
        } else {
          el.setAttribute(MARK, radios[name].id);
        }
        const lab = (el.labels && el.labels[0]) ? text(el.labels[0]) : el.value;
        radios[name].options.push({ label: cleanLabel(lab), value: el.value });
        return;
      }
      const id = el.getAttribute(MARK) || "knok-" + n++;
      el.setAttribute(MARK, id);
      const f = {
        id, label: labelFor(el, adapter), type, name: el.name || el.id || "",
        required: !!(el.required || el.getAttribute("aria-required") === "true"),
        autocomplete: el.getAttribute("autocomplete") || "", placeholder: el.getAttribute("placeholder") || "",
        options: [],
      };
      if (type === "select" || type === "multiselect") {
        f.options = Array.from(el.options).filter((o) => o.value !== "" && !o.disabled)
          .map((o) => ({ label: text(o) || o.value, value: o.value }));
      }
      fields.push(f);
    });
    const job = extractJob();
    return { platform: adapter ? adapter.name : "generic", url: location.href, fields, captcha: detectCaptcha(),
             company: job.company, title: job.title };
  }

  function detectCaptcha() {
    return !!document.querySelector(
      "iframe[src*='recaptcha'], iframe[src*='hcaptcha'], iframe[src*='turnstile'], .g-recaptcha, .h-captcha, .cf-turnstile");
  }

  function setNative(el, value) {
    const proto = el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype
      : el.tagName === "SELECT" ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
    const desc = Object.getOwnPropertyDescriptor(proto, "value");
    if (desc && desc.set) desc.set.call(el, value); else el.value = value;
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
    el.dispatchEvent(new Event("blur", { bubbles: true }));
  }

  function setFile(el, file) {
    if (!file || !file.bytes) return false;
    const blob = new Blob([new Uint8Array(file.bytes)], { type: file.mime || "application/pdf" });
    const f = new File([blob], file.filename || "cv.pdf", { type: blob.type });
    const dt = new DataTransfer();
    dt.items.add(f);
    el.files = dt.files;
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
    return true;
  }

  function flag(el, reason, suggestion) {
    const target = el.closest(".field, [class*='question'], [class*='fieldEntry'], [class*='form-element'], fieldset, label") ||
      el.parentElement || el;   // nunca dentro del propio <input>, donde no se vería
    target.setAttribute("data-knok-review", "1");
    target.style.outline = "2px dashed #d97706";
    target.style.outlineOffset = "2px";
    if (target.querySelector(":scope > .knok-badge")) return;
    const b = document.createElement("div");
    b.className = "knok-badge";
    b.setAttribute("data-knok-ignore", "1");
    b.style.cssText = "font:12px system-ui;color:#92400e;background:#fef3c7;padding:2px 6px;margin:4px 0;border-radius:4px";
    b.textContent = "knok · revisa este campo" + (reason ? ": " + reason : "") + (suggestion ? " (sugerencia: " + suggestion + ")" : "");
    target.appendChild(b);
  }

  /**
   * plan: { fields: [{id, type, value, display, needs_review, reason}], files: {id: {bytes, filename, mime}} }
   * Devuelve un resumen. NO envía el formulario.
   */
  function fill(plan) {
    const out = { filled: 0, review: 0, skipped: 0, errors: [] };
    const files = plan.files || {};
    (plan.fields || []).forEach((f) => {
      const els = document.querySelectorAll("[" + MARK + "='" + f.id + "']");
      if (!els.length) { out.skipped++; return; }
      const el = els[0];
      try {
        const vacio = f.value === null || f.value === undefined || f.value === "";
        if (f.type === "file") {
          if (files[f.id] && setFile(el, files[f.id])) out.filled++;
          else { flag(el, f.reason); out.review++; }
          return;
        }
        if (vacio) { flag(el, f.reason); out.review++; return; }
        if (f.type === "radio") {
          const r = Array.from(els).find((x) => x.value === String(f.value));
          if (r) { r.checked = true; r.dispatchEvent(new Event("change", { bubbles: true })); r.dispatchEvent(new Event("click", { bubbles: true })); out.filled++; }
          else { flag(el, f.reason); out.review++; }
        } else if (f.type === "checkbox") {
          el.checked = f.value === true || f.value === "true";
          el.dispatchEvent(new Event("change", { bubbles: true }));
          out.filled++;
        } else if (f.type === "combobox") {
          flag(el, "desplegable especial: elígelo tú", f.display || String(f.value)); out.review++;
          return;
        } else {
          setNative(el, String(f.value));
          out.filled++;
        }
        if (f.needs_review) { flag(el, f.reason); out.review++; }
      } catch (e) {
        out.errors.push(String(e));
      }
    });
    out.captcha = detectCaptcha();
    if (out.captcha) {
      const aviso = document.createElement("div");
      aviso.setAttribute("data-knok-ignore", "1");
      aviso.style.cssText = "position:fixed;bottom:12px;right:12px;z-index:2147483647;font:13px system-ui;background:#fee2e2;color:#7f1d1d;padding:8px 12px;border-radius:6px";
      aviso.textContent = "knok: esta página tiene un CAPTCHA. Resuélvelo tú antes de enviar.";
      document.body.appendChild(aviso);
    }
    return out;
  }

  function isSubmitted() {
    const a = adapterFor();
    if (a && a.detectSubmitted) return !!a.detectSubmitted(document, location);
    return /thank you for (applying|your application)|application (received|submitted)|gracias por (tu|su) candidatura|candidatura (enviada|recibida)|bewerbung (erhalten|eingegangen)|candidature (envoy|reçue)/i
      .test(text(document.body).slice(0, 5000));
  }

  function extractJob() {
    const a = adapterFor();
    const base = { url: location.href, title: "", company: "", location: "", apply_url: "", easy_apply: false, description: "" };
    if (a && a.extractJob) Object.assign(base, a.extractJob(document, location));
    else base.title = text(document.querySelector("h1")) || document.title;
    if (!base.company) {   // nombre de la empresa que la propia web declara (para «Estimado equipo de …»)
      const meta = document.querySelector("meta[property='og:site_name'], meta[name='application-name']");
      base.company = (meta && meta.content || "").trim();
    }
    return base;
  }

  /** Lista de ofertas que el usuario tiene en pantalla (página de resultados), si el adaptador sabe leerla. */
  function extractList() {
    const a = adapterFor();
    return a && a.extractList ? a.extractList(document, location).filter((x) => x.title && x.url) : [];
  }

  const register = (a) => { if (!adapters.some((x) => x.name === a.name)) adapters.push(a); };
  window.__knok = { version: "0.1.0", register, adapters, extract, fill, isSubmitted,
                    extractJob, extractList, detectCaptcha, adapterFor, _text: text };
})();
