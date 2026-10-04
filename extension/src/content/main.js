/*
 * Punto de entrada en la página. Responde a las órdenes del service worker (que solo llegan tras un
 * clic del usuario) y avisa cuando el USUARIO ha enviado la solicitud.
 */
(function () {
  "use strict";
  if (window.__knokMain || typeof chrome === "undefined" || !chrome.runtime || !chrome.runtime.onMessage) return;
  window.__knokMain = true;
  let applicationId = null;
  let avisado = false;

  function vigilarEnvio() {
    const comprobar = () => {
      if (avisado || !applicationId) return;
      if (window.__knok.isSubmitted()) {
        avisado = true;
        chrome.runtime.sendMessage({ type: "knok:submitted", applicationId, url: location.href });
      }
    };
    // Solo se observa: si el usuario envía (o la web cambia a la página de confirmación), se avisa a knok.
    new MutationObserver(comprobar).observe(document.body, { childList: true, subtree: true });
    setInterval(comprobar, 2000);
  }

  chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
    if (!msg || !msg.cmd) return;
    if (msg.cmd === "extract") reply(window.__knok.extract());
    else if (msg.cmd === "fill") {
      applicationId = msg.applicationId || applicationId;
      const res = window.__knok.fill(msg.plan);
      if (applicationId) vigilarEnvio();
      reply(res);
    } else if (msg.cmd === "capture") reply(window.__knok.extractJob());
    else if (msg.cmd === "submitted?") reply({ submitted: window.__knok.isSubmitted() });
    return true;
  });
})();
