/*
 * Indeed: SOLO para guardar la oferta en knok (y seguir su enlace si redirige al ATS de la empresa).
 * Nunca se rellena ni se envía Indeed Apply: sus condiciones lo prohíben expresamente.
 */
(function () {
  const t = (el) => (el && (el.innerText || el.textContent) || "").replace(/\s+/g, " ").trim();
  window.__knok.register({
    name: "indeed",
    blocked: "Indeed Apply no se rellena: sus condiciones lo prohíben. Si la oferta enlaza a la web de la empresa, ábrela y usa knok allí.",
    matches: (loc) => /(^|\.)indeed\.[a-z.]+$/.test(loc.hostname),
    extractJob: (doc) => {
      const ext = doc.querySelector("a[href*='applystart'], a[href*='/rc/clk'], #applyButtonLinkContainer a");
      return {
        title: t(doc.querySelector("h1, .jobsearch-JobInfoHeader-title")),
        company: t(doc.querySelector("[data-company-name], [data-testid='inlineHeader-companyName']")),
        location: t(doc.querySelector("[data-testid='inlineHeader-companyLocation'], [data-testid='job-location']")),
        apply_url: ext ? ext.href : "",
        description: t(doc.querySelector("#jobDescriptionText")).slice(0, 20000),
      };
    },
  });
})();
