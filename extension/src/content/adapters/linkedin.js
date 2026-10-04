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
    // Las tarjetas de la página de resultados que el usuario está viendo (solo lo ya cargado en pantalla)
    extractList: (doc) => {
      const tarjetas = doc.querySelectorAll("li[data-occludable-job-id], .job-card-container[data-job-id], div.base-card[data-entity-urn], li .base-search-card");
      const vistos = new Set();
      const out = [];
      tarjetas.forEach((c) => {
        const enlace = c.querySelector("a[href*='/jobs/view/']");
        const id = c.getAttribute("data-occludable-job-id") || c.getAttribute("data-job-id") ||
          ((c.getAttribute("data-entity-urn") || "").match(/(\d+)$/) || [])[1] ||
          ((enlace && enlace.href.match(/\/jobs\/view\/(?:[^/?]*-)?(\d+)/)) || [])[1];
        if (!id || vistos.has(id)) return;
        vistos.add(id);
        // En orden de preferencia (querySelector con varios selectores devolvería el primero del documento)
        const titulo = [".job-card-list__title--link", ".job-card-list__title", ".artdeco-entity-lockup__title",
                        ".base-search-card__title", "a[href*='/jobs/view/']"]
          .map((sel) => c.querySelector(sel)).filter(Boolean)
          .map((el) => (el.getAttribute("aria-label") || t(el)).replace(/\s+with verification$/i, "").trim())
          .find(Boolean) || "";
        const empresa = t(c.querySelector(".artdeco-entity-lockup__subtitle, .job-card-container__primary-description, .job-card-container__company-name, .base-search-card__subtitle"));
        const lugar = t(c.querySelector(".job-card-container__metadata-wrapper li, .artdeco-entity-lockup__caption, .job-card-container__metadata-item, .job-search-card__location"));
        out.push({ url: "https://www.linkedin.com/jobs/view/" + id + "/", title: titulo, company: empresa, location: lugar,
                   easy_apply: /easy apply|solicitud sencilla|candidatura simplificada|einfach bewerben/i.test(t(c)), apply_url: "" });
      });
      return out;
    },
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
