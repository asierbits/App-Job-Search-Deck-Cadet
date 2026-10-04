/* Adaptador Lever (jobs.lever.co, también región UE). El formulario está en /apply. */
(function () {
  const t = (el) => (el && (el.innerText || el.textContent) || "").replace(/\s+/g, " ").trim();
  window.__knok.register({
    name: "lever",
    matches: (loc) => /^jobs(\.eu)?\.lever\.co$/.test(loc.hostname),
    root: (doc) => doc.querySelector("form#application-form, form.application-form, .application-page form") || doc,
    labelFor: (el) => {
      const box = el.closest(".application-question, li");
      const lab = box && box.querySelector(".application-label, .text, label");
      return lab ? t(lab).replace(/✱/g, "") : "";
    },
    detectSubmitted: (doc, loc) => /\/thanks\/?$/.test(loc.pathname) ||
      /application (submitted|received)|thanks for applying/i.test(t(doc.body).slice(0, 4000)),
    extractJob: (doc) => ({
      title: t(doc.querySelector(".posting-headline h2, h2")),
      company: (document.title.split(" - ")[0] || "").trim(),
      location: t(doc.querySelector(".posting-categories .location, .location")),
      apply_url: location.href.replace(/\/?$/, "").replace(/\/apply$/, "") + "/apply",
      description: t(doc.querySelector(".section-wrapper, .content")).slice(0, 20000),
    }),
  });
})();
