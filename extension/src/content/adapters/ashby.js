/* Adaptador Ashby (jobs.ashbyhq.com). El formulario está en la pestaña /application. */
(function () {
  const t = (el) => (el && (el.innerText || el.textContent) || "").replace(/\s+/g, " ").trim();
  window.__knok.register({
    name: "ashby",
    matches: (loc) => loc.hostname === "jobs.ashbyhq.com",
    root: (doc) => doc.querySelector("form, [class*='application-form'], [class*='ApplicationForm']") || doc,
    labelFor: (el) => {
      const box = el.closest("[class*='fieldEntry'], [class*='FieldEntry'], [class*='question'], fieldset");
      const lab = box && box.querySelector("label, legend, [class*='label']");
      return lab ? t(lab) : "";
    },
    detectSubmitted: (doc) => !!doc.querySelector("[class*='success'], [class*='Success']") ||
      /thanks for applying|application (was )?(submitted|received)/i.test(t(doc.body).slice(0, 4000)),
    extractJob: (doc) => ({
      title: t(doc.querySelector("h1")),
      company: (document.title.split(/[@|–-]/).pop() || "").trim(),
      location: t(doc.querySelector("[class*='location'], [class*='Location']")),
      apply_url: location.href.replace(/\/application\/?$/, "") + "/application",
      description: t(doc.querySelector("[class*='description'], main")).slice(0, 20000),
    }),
  });
})();
