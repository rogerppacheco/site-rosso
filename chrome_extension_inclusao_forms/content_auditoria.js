/**
 * Ponte Auditoria ↔ extensão.
 *
 * Content scripts rodam em mundo isolado: `window.foo = true` NÃO é visto pelo site.
 * Precisamos injetar a flag no contexto da página (MAIN world) e usar postMessage.
 */
(function () {
  function injetarFlagNaPagina() {
    try {
      document.documentElement.setAttribute("data-record-inclusao-ext", "1");
    } catch (_) {
      /* ignore */
    }
    const code = function () {
      window.__RECORD_INCLUSAO_EXT__ = true;
      try {
        document.documentElement.setAttribute("data-record-inclusao-ext", "1");
        window.dispatchEvent(new CustomEvent("record-inclusao-ext-ready"));
      } catch (_) {
        /* ignore */
      }
    };
    try {
      const script = document.createElement("script");
      script.textContent = "(" + code.toString() + ")();";
      const root = document.documentElement || document.head || document.documentElement;
      if (root) {
        root.appendChild(script);
        script.remove();
      }
    } catch (_) {
      /* ignore */
    }
  }

  injetarFlagNaPagina();
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", injetarFlagNaPagina);
  }
  // Reaplica em SPAs / navegação parcial
  setInterval(injetarFlagNaPagina, 2000);

  window.addEventListener("message", (event) => {
    if (event.origin !== window.location.origin) return;
    const data = event.data;
    if (!data || data.source !== "record-pap-auditoria") return;

    if (data.type === "RECORD_INCLUSAO_PING") {
      window.postMessage(
        { source: "record-inclusao-ext", type: "RECORD_INCLUSAO_PONG", ok: true },
        window.location.origin
      );
      injetarFlagNaPagina();
      return;
    }

    if (data.type !== "RECORD_INCLUSAO_ABRIR_FORMS") return;

    chrome.runtime.sendMessage(
      {
        type: "INCLUSAO_START",
        demandaId: data.demandaId,
        apiBase: data.apiBase,
        accessToken: data.accessToken,
      },
      (resp) => {
        if (chrome.runtime.lastError) {
          alert("Extensão: " + chrome.runtime.lastError.message);
          return;
        }
        if (!resp?.ok) {
          alert("Não foi possível abrir o Forms: " + (resp?.error || "erro desconhecido"));
          return;
        }
        console.info("[Record Inclusão] Forms aberto", resp);
      }
    );
  });
})();
