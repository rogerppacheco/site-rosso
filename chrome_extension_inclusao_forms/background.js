/**
 * Service worker: inicia demanda na API, abre o Forms e intermedia downloads.
 */

const jobs = new Map();

async function apiJson(apiBase, token, path, options = {}) {
  const url = `${apiBase.replace(/\/$/, "")}${path}`;
  const resp = await fetch(url, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      ...(options.headers || {}),
    },
  });
  const text = await resp.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch (_) {
    data = { detail: text };
  }
  if (!resp.ok) {
    const msg = (data && (data.detail || data.error)) || `HTTP ${resp.status}`;
    throw new Error(String(msg));
  }
  return data;
}

async function handleMessage(message) {
  if (message?.type === "PING") {
    return { ok: true, version: "1.0.1", id: chrome.runtime.id };
  }

    if (message?.type === "INCLUSAO_START") {
      const { demandaId, apiBase, accessToken } = message;
      if (!demandaId || !apiBase || !accessToken) {
        throw new Error("Parâmetros incompletos (demandaId/apiBase/token).");
      }

      const iniciado = await apiJson(
        apiBase,
        accessToken,
        `/auditoria/inclusao-viabilidade/${demandaId}/iniciar/`,
        { method: "POST", body: "{}" }
      );
      const payload = iniciado.form_payload || iniciado.demanda?.form_payload;
      if (!payload?.form_url) {
        throw new Error("API não retornou form_payload.");
      }

      const job = {
        demandaId,
        apiBase,
        accessToken,
        payload,
        status: "abrindo",
        tabId: null,
        erro: "",
      };
      jobs.set(demandaId, job);
      await chrome.storage.session.set({
        [`inclusao_job_${demandaId}`]: {
          demandaId,
          apiBase,
          accessToken,
          payload,
          status: "abrindo",
        },
      });

      const formUrl = payload.form_url.includes("?")
        ? `${payload.form_url}&record_inclusao=${demandaId}`
        : `${payload.form_url}?record_inclusao=${demandaId}`;

      const tab = await chrome.tabs.create({ url: formUrl, active: true });
      job.tabId = tab.id;
      job.status = "aguardando_form";
      return { ok: true, tabId: tab.id, protocolo: payload.protocolo };
    }

    if (message?.type === "INCLUSAO_GET_JOB") {
      const demandaId = Number(message.demandaId);
      let job = jobs.get(demandaId);
      if (!job) {
        const stored = await chrome.storage.session.get(`inclusao_job_${demandaId}`);
        job = stored[`inclusao_job_${demandaId}`] || null;
        if (job) jobs.set(demandaId, job);
      }
      return { ok: !!job, job };
    }

    if (message?.type === "INCLUSAO_DOWNLOAD") {
      const { url, nome } = message;
      const resp = await fetch(url);
      if (!resp.ok) throw new Error(`Falha ao baixar anexo (${resp.status})`);
      const buf = await resp.arrayBuffer();
      const bytes = new Uint8Array(buf);
      let binary = "";
      const chunk = 0x8000;
      for (let i = 0; i < bytes.length; i += chunk) {
        binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
      }
      const base64 = btoa(binary);
      const contentType = resp.headers.get("content-type") || "application/octet-stream";
      return { ok: true, base64, contentType, nome: nome || "arquivo.jpg" };
    }

    if (message?.type === "INCLUSAO_CONCLUIR") {
      const { demandaId, apiBase, accessToken } = message;
      await apiJson(
        apiBase,
        accessToken,
        `/auditoria/inclusao-viabilidade/${demandaId}/concluir/`,
        { method: "POST", body: "{}" }
      );
      jobs.delete(demandaId);
      await chrome.storage.session.remove(`inclusao_job_${demandaId}`);
      return { ok: true };
    }

    if (message?.type === "INCLUSAO_ERRO") {
      const { demandaId, apiBase, accessToken, erro } = message;
      try {
        await apiJson(
          apiBase,
          accessToken,
          `/auditoria/inclusao-viabilidade/${demandaId}/erro/`,
          { method: "POST", body: JSON.stringify({ mensagem: erro || "Erro na extensão" }) }
        );
      } catch (_) {
        /* ignore */
      }
      return { ok: true };
    }

  return { ok: false, error: "Tipo de mensagem desconhecido" };
}

function attachListener(api) {
  api.addListener((message, _sender, sendResponse) => {
    handleMessage(message)
      .then((result) => sendResponse(result))
      .catch((err) => sendResponse({ ok: false, error: String(err?.message || err) }));
    return true;
  });
}

attachListener(chrome.runtime.onMessage);
if (chrome.runtime.onMessageExternal) {
  attachListener(chrome.runtime.onMessageExternal);
}
