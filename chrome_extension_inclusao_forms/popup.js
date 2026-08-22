chrome.runtime.sendMessage({ type: "PING" }, (resp) => {
  const el = document.getElementById("status");
  if (!el) return;
  if (chrome.runtime.lastError || !resp?.ok) {
    el.textContent = "Erro ao falar com o service worker";
    el.className = "";
    return;
  }
  el.textContent = `Extensão ativa (v${resp.version || "?"})`;
});
