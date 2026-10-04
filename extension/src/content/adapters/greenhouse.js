/* Adaptador Greenhouse (boards.greenhouse.io y job-boards.greenhouse.io, también región UE). */
(function () {
  const t = (el) => (el && (el.innerText || el.textContent) || "").replace(/\s+/g, " ").trim();
  window.__knok.register({
    name: "greenhouse",
    matches: (loc) => /(^|\.)(boards|job-boards)(\.eu)?\.greenhouse\.io$/.test(loc.hostname),
    root: (doc) => doc.querySelector("#application_form, form#application-form, #application form, form[action*='greenhouse'], main form") || doc,
    labelFor: (el) => {
      const box = el.closest(".field, .application-question, [class*='question']");
      const lab = box && box.querySelector("label, .label, legend");
      return lab ? t(lab) : "";
    },
    detectSubmitted: (doc, loc) => /confirmation|thank/i.test(loc.pathname) ||
      !!doc.querySelector("#application_confirmation, [class*='confirmation']") ||
      /thank you for applying|application has been submitted/i.test(t(doc.body).slice(0, 4000)),
    extractJob: (doc) => ({
      title: t(doc.querySelector(".app-title, .job__title h1, h1")),
      company: t(doc.querySelector(".company-name, .job__company")).replace(/^at\s+/i, ""),
      location: t(doc.querySelector(".location, .job__location")),
      apply_url: location.href,
      description: t(doc.querySelector("#content, .job__description")).slice(0, 20000),
    }),
  });
})();
