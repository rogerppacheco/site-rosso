/**
 * Preenche o Google Forms de Inclusão/Viabilidade quando aberto pela extensão.
 */
(function () {
  const params = new URLSearchParams(window.location.search);
  const demandaId = Number(params.get("record_inclusao") || 0);
  if (!demandaId) return;

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  function send(msg) {
    return new Promise((resolve) => {
      chrome.runtime.sendMessage(msg, (resp) => {
        if (chrome.runtime.lastError) {
          resolve({ ok: false, error: chrome.runtime.lastError.message });
          return;
        }
        resolve(resp || { ok: false, error: "Sem resposta" });
      });
    });
  }

  function banner(texto, tipo = "info") {
    let el = document.getElementById("record-inclusao-banner");
    if (!el) {
      el = document.createElement("div");
      el.id = "record-inclusao-banner";
      el.style.cssText =
        "position:fixed;top:12px;right:12px;z-index:999999;max-width:360px;" +
        "padding:12px 14px;border-radius:8px;font:14px/1.4 system-ui,sans-serif;" +
        "box-shadow:0 4px 16px rgba(0,0,0,.25);color:#fff;";
      document.documentElement.appendChild(el);
    }
    el.style.background =
      tipo === "ok" ? "#198754" : tipo === "erro" ? "#dc3545" : "#0d6efd";
    el.textContent = texto;
  }

  function visibleTextInputs() {
    return Array.from(
      document.querySelectorAll(
        'input[type="text"]:not([aria-hidden="true"]), input:not([type]):not([aria-hidden="true"])'
      )
    ).filter((el) => el.offsetParent !== null && el.name !== "ca");
  }

  function textAreas() {
    return Array.from(document.querySelectorAll("textarea")).filter(
      (el) => el.offsetParent !== null
    );
  }

  function contentEditables() {
    return Array.from(
      document.querySelectorAll('div[contenteditable="true"], div[role="textbox"]')
    ).filter((el) => el.offsetParent !== null);
  }

  async function setValue(el, valor) {
    el.focus();
    el.click();
    await sleep(80);
    if ("value" in el) {
      el.value = "";
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.value = String(valor);
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
    } else {
      el.textContent = String(valor);
      el.dispatchEvent(new InputEvent("input", { bubbles: true, data: String(valor) }));
    }
    await sleep(120);
  }

  async function fillTextlike(idx, valor) {
    const tas = textAreas();
    if (tas[idx]) {
      await setValue(tas[idx], valor);
      return true;
    }
    const ces = contentEditables();
    if (ces[idx]) {
      await setValue(ces[idx], valor);
      return true;
    }
    return false;
  }

  async function clickOptionByText(texto) {
    const alvo = String(texto || "").trim().toLowerCase();
    if (!alvo) return false;
    const nodes = Array.from(
      document.querySelectorAll('[role="radio"], [role="option"], label, span, div')
    );
    for (const n of nodes) {
      const t = (n.textContent || "").trim().toLowerCase();
      if (t === alvo || t.includes(alvo)) {
        n.click();
        await sleep(200);
        return true;
      }
    }
    return false;
  }

  async function selectDropdown(nth, valor) {
    const listboxes = Array.from(document.querySelectorAll('[role="listbox"]'));
    const lb = listboxes[nth];
    if (!lb) return false;
    lb.click();
    await sleep(400);
    const options = Array.from(document.querySelectorAll('[role="option"]'));
    const alvo = String(valor || "").trim().toLowerCase();
    for (const opt of options) {
      const t = (opt.textContent || "").trim().toLowerCase();
      if (t === alvo || t.includes(alvo)) {
        opt.click();
        await sleep(300);
        return true;
      }
    }
    document.body.click();
    return false;
  }

  async function limparFormulario() {
    const limpar = Array.from(document.querySelectorAll("span, button, div")).find(
      (el) => /limpar formul[aá]rio/i.test((el.textContent || "").trim())
    );
    if (!limpar) return;
    limpar.click();
    await sleep(500);
    const confirmar = Array.from(document.querySelectorAll("span, button")).find((el) =>
      /^limpar$/i.test((el.textContent || "").trim())
    );
    if (confirmar) {
      confirmar.click();
      await sleep(800);
    }
  }

  function base64ToFile(base64, nome, contentType) {
    const bin = atob(base64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    return new File([bytes], nome, { type: contentType || "application/octet-stream" });
  }

  async function uploadArquivos(arquivos) {
    if (!arquivos?.length) return true;
    const files = [];
    for (const a of arquivos) {
      const dl = await send({ type: "INCLUSAO_DOWNLOAD", url: a.url, nome: a.nome });
      if (!dl?.ok) throw new Error(dl?.error || "Falha ao baixar anexo");
      files.push(base64ToFile(dl.base64, dl.nome, dl.contentType));
    }

    const addBtn = Array.from(document.querySelectorAll("span, div, button")).find((el) =>
      /adicionar arquivo/i.test((el.textContent || "").trim())
    );
    if (addBtn) {
      addBtn.click();
      await sleep(1200);
    }

    let fileInput = document.querySelector('input[type="file"]');
    if (!fileInput) {
      for (const iframe of document.querySelectorAll("iframe")) {
        try {
          const doc = iframe.contentDocument;
          if (!doc) continue;
          fileInput = doc.querySelector('input[type="file"]');
          if (fileInput) break;
        } catch (_) {
          /* cross-origin */
        }
      }
    }

    if (!fileInput) {
      // Fallback: cria input e dispara (alguns layouts do Picker)
      fileInput = document.createElement("input");
      fileInput.type = "file";
      fileInput.multiple = true;
      fileInput.style.display = "none";
      document.body.appendChild(fileInput);
    }

    const dt = new DataTransfer();
    files.forEach((f) => dt.items.add(f));
    fileInput.files = dt.files;
    fileInput.dispatchEvent(new Event("input", { bubbles: true }));
    fileInput.dispatchEvent(new Event("change", { bubbles: true }));
    await sleep(2000);

    const fechar = Array.from(document.querySelectorAll("span, button")).find((el) =>
      /^(inserir|enviar|upload)$/i.test((el.textContent || "").trim())
    );
    if (fechar) {
      fechar.click();
      await sleep(1500);
    }
    return true;
  }

  async function clicarEnviar() {
    const btn =
      Array.from(document.querySelectorAll('div[role="button"], button, span')).find((el) =>
        /^enviar$/i.test((el.textContent || "").trim())
      ) || null;
    if (!btn) throw new Error('Botão "Enviar" não encontrado');
    btn.click();
    await sleep(4000);
    const ok =
      /obrigado|respostas enviadas|sua resposta foi registrada|thank you|response recorded/i.test(
        document.body.innerText || ""
      ) || /formResponse/i.test(location.href);
    return ok;
  }

  async function preencher(job) {
    const p = job.payload;
    banner(`Preenchendo protocolo ${p.protocolo || demandaId}…`);

    await sleep(1500);
    if (/accounts\.google\.com/i.test(location.href)) {
      throw new Error("Faça login no Google neste Chrome e tente novamente.");
    }

    await limparFormulario();
    await sleep(500);

    const inputs = visibleTextInputs();
    if (inputs[0]) await setValue(inputs[0], p.codigo_sap || "");
    await selectDropdown(0, p.executivo);
    await clickOptionByText(p.tipo_canal || "PAP");

    const email = document.querySelector('input[type="email"]');
    if (email) await setValue(email, p.email || "");

    await selectDropdown(1, p.empresa);
    if (p.uf) await selectDropdown(2, p.uf);

    const inputs2 = visibleTextInputs();
    if (inputs2[1]) await setValue(inputs2[1], p.cep || "");
    await fillTextlike(0, p.cidade || "");
    await clickOptionByText(p.tipo_logradouro || "Outros");
    await fillTextlike(1, p.logradouro || "");
    const inputs3 = visibleTextInputs();
    if (inputs3[2]) await setValue(inputs3[2], p.numero || "");
    await fillTextlike(2, p.bairro || "");
    await fillTextlike(3, p.complementos || "");
    await fillTextlike(4, p.fachadas_vizinhos || "");
    const inputs4 = visibleTextInputs();
    if (inputs4[3]) await setValue(inputs4[3], p.coordenadas || "");

    await uploadArquivos(p.arquivos || []);
    await fillTextlike(5, p.observacoes || "");

    const enviado = await clicarEnviar();
    if (!enviado) {
      throw new Error("Envio não confirmado. Verifique o formulário e envie manualmente se preciso.");
    }

    const fim = await send({
      type: "INCLUSAO_CONCLUIR",
      demandaId: job.demandaId,
      apiBase: job.apiBase,
      accessToken: job.accessToken,
    });
    if (!fim?.ok) {
      banner("Forms enviado, mas falhou ao marcar demanda: " + (fim?.error || ""), "erro");
      return;
    }
    banner(`✅ Enviado! Protocolo ${p.protocolo}`, "ok");
  }

  async function run() {
    banner("Record Inclusão: carregando demanda…");
    let jobResp = await send({ type: "INCLUSAO_GET_JOB", demandaId });
    for (let i = 0; i < 10 && !jobResp?.ok; i++) {
      await sleep(500);
      jobResp = await send({ type: "INCLUSAO_GET_JOB", demandaId });
    }
    if (!jobResp?.ok || !jobResp.job) {
      banner("Não achei os dados da demanda. Abra pelo botão na Auditoria.", "erro");
      return;
    }
    try {
      await preencher(jobResp.job);
    } catch (err) {
      const msg = String(err?.message || err);
      banner("❌ " + msg, "erro");
      await send({
        type: "INCLUSAO_ERRO",
        demandaId: jobResp.job.demandaId,
        apiBase: jobResp.job.apiBase,
        accessToken: jobResp.job.accessToken,
        erro: msg,
      });
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => setTimeout(run, 800));
  } else {
    setTimeout(run, 800);
  }
})();
