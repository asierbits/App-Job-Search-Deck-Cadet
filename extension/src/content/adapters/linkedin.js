/*
 * Adaptador LinkedIn — COPILOTO, de una en una.
 * Solo rellena el paso visible del diálogo "Easy Apply" cuando el usuario pulsa "Rellenar" en knok.
 * El usuario pulsa "Siguiente" y "Enviar". Sus condiciones prohíben automatizar la cuenta: hay riesgo.
 */
(function () {
  const t = (el) => (el && (el.innerText || el.textContent) || "").replace(/\s+/g, " ").trim();
  window.__knok.register({
    name: "linkedin",
    oneByOne: true,
    matches: (loc) => /(^|\.)linkedin\.com$/.test(loc.hostname) && /^\/jobs\//.test(loc.pathname),
    root: (doc) => doc.querySelector(".jobs-easy-apply-modal, [data-test-modal][role='dialog'], div[role='dialog']") || doc.createElement("div"),
    labelFor: (el) => {
      const box = el.closest(".fb-dash-form-element, .jobs-easy-apply-form-element, fieldset, [data-test-form-element]");
      const lab = box && box.querySelector("label, legend, .fb-dash-form-element__label");
      return lab ? t(lab) : "";
    },
    detectSubmitted: (doc) => /your application was sent|application submitted|solicitud enviada|se ha enviado tu solicitud/i
      .test(t(doc.querySelector("div[role='dialog']") || doc.body).slice(0, 3000)),
    extractJob: (doc) => {
      const botones = Array.from(doc.querySelectorAll(".jobs-apply-button, button"));
      const easy = botones.some((b) => /easy apply|solicitud sencilla/i.test(t(b)));
      return {
        title: t(doc.querySelector(".job-details-jobs-unified-top-card__job-title, .jobs-unified-top-card__job-title, h1")),
        company: t(doc.querySelector(".job-details-jobs-unified-top-card__company-name, .jobs-unified-top-card__company-name")),
        location: t(doc.querySelector(".job-details-jobs-unified-top-card__primary-description-container span, .jobs-unified-top-card__bullet")),
        apply_url: "", easy_apply: easy,
        description: t(doc.querySelector(".jobs-description__content, #job-details")).slice(0, 20000),
      };
    },
  });
})();
