/*
 * Adaptadores de fase 2 (beta): Workable, SmartRecruiters, Recruitee, Teamtailor y Personio.
 * Usan la extracción genérica del núcleo; aquí solo se declara dónde está el formulario.
 * Workday queda para más adelante (el usuario crea cuenta en cada empresa y el formulario es por pasos).
 */
(function () {
  const t = (el) => (el && (el.innerText || el.textContent) || "").replace(/\s+/g, " ").trim();
  const enviado = /thank you for (applying|your application)|application (received|submitted|sent)|gracias por (tu|su) candidatura|bewerbung (erhalten|eingegangen)/i;
  const beta = (name, hostRe) => ({
    name, beta: true,
    matches: (loc) => hostRe.test(loc.hostname),
    root: (doc) => {
      const forms = Array.from(doc.querySelectorAll("form"));
      return forms.sort((a, b) => b.querySelectorAll("input,select,textarea").length - a.querySelectorAll("input,select,textarea").length)[0] || doc;
    },
    detectSubmitted: (doc) => enviado.test(t(doc.body).slice(0, 4000)),
    extractJob: (doc) => ({ title: t(doc.querySelector("h1")), apply_url: location.href }),
  });
  window.__knok.register(beta("workable", /^apply\.workable\.com$/));
  window.__knok.register(beta("smartrecruiters", /^(jobs|careers)\.smartrecruiters\.com$/));
  window.__knok.register(beta("recruitee", /\.recruitee\.com$/));
  window.__knok.register(beta("teamtailor", /\.teamtailor\.com$/));
  window.__knok.register(beta("personio", /\.jobs\.personio\.(de|com)$/));
})();
