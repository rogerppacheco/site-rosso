# Como ver a automação PAP no navegador

Você pode acompanhar cada etapa da automação (login, CEP, viabilidade, CPF, etc.) de duas formas.

---

## 1. Pelo terminal (recomendado para debug)

O comando **testar_pap_terminal** abre o navegador na sua tela e você digita no terminal como se fosse o WhatsApp. O fluxo é o mesmo da produção.

```bash
python manage.py testar_pap_terminal
```

- O Chromium abre em **modo visível** (não headless).
- Você digita: **VENDER** → **SIM** → **CEP** → **Número** → **Referência** → **CPF** → etc.
- Cada mensagem que você “envia” no terminal é processada e você vê o site PAP respondendo no navegador.

**Opções:**

```bash
# Usar credenciais específicas (senão usa um BO e vendedor do banco)
python manage.py testar_pap_terminal --matricula-bo=SUA_MAT --senha-bo=SUA_SENHA --matricula-vendedor=MAT_VENDEDOR
```

Para **sair**: digite **CANCELAR** ou **/sair**.

---

## 2. Fluxo real do WhatsApp com navegador visível (teste local)

Quando você sobe o servidor **localmente** e dispara o fluxo pelo WhatsApp de verdade, a automação pode abrir o navegador na sua máquina para você ver cada etapa.

### Passos

1. **Defina a variável de ambiente** para o navegador não ficar em segundo plano:

   **Windows (PowerShell):**
   ```powershell
   $env:PAP_HEADLESS="false"
   python manage.py runserver
   ```

   **Windows (CMD):**
   ```cmd
   set PAP_HEADLESS=false
   python manage.py runserver
   ```

   **Linux/macOS:**
   ```bash
   export PAP_HEADLESS=false
   python manage.py runserver
   ```

2. **Exponha o servidor local** (para o WhatsApp conseguir chamar seu app), por exemplo com [ngrok](https://ngrok.com/):
   ```bash
   ngrok http 8000
   ```
   Configure a URL do webhook do WhatsApp para apontar para o URL do ngrok.

3. **No WhatsApp**, envie **VENDER** e siga o fluxo (SIM, CEP, número, referência, CPF, etc.).

4. Na sua máquina o **navegador abrirá** e você verá o PAP sendo preenchido em tempo real.

### Fluxo *Fatura* (consultar fatura por CPF e baixar PDF)

O mesmo `PAP_HEADLESS=false` vale para o comando **Fatura** no WhatsApp.

**De onde vêm os dados (valor, PIX, código de barras)?**  
Tudo isso vem da **API REST da Nio**, não de cliques no site:

1. **Token** – O sistema obtém um token: primeiro por uma requisição HTTP simples a `/negociar/params`. Se o servidor exigir cookies/captcha, aí sim o **navegador abre uma vez** para carregar a página e pegar o token (é o que você viu ao “abrir o site”).
2. **Session ID** – Uma chamada HTTP à API com o token.
3. **Dados da fatura** – Uma chamada GET à API em `/debts/customers/{CPF}`. O JSON de resposta já traz valor, vencimento, PIX, código de barras, etc. **Nenhum clique nem reCAPTCHA** – só HTTP com token e session ID.

Por isso você viu o site abrir (para pegar o token, se precisou), mas não viu cliques: os dados que apareceram na mensagem vieram dessas chamadas de API.

**E o PDF?**  
O PDF é tentado **primeiro pela API** (endpoint de download da fatura). Se a API devolver a URL do PDF, o sistema usa essa URL e **não abre o navegador** para o PDF – por isso você não viu o clique em “Baixar PDF”. Só quando a API **não** devolve o PDF é que o sistema abre o navegador de novo e faz o fluxo: Consultar CPF → Ver detalhes → Pagar conta → Gerar boleto → **Baixar PDF**.

**reCAPTCHA na página Nio:** A página de consulta da Nio exige reCAPTCHA ("Não sou um robô"). O botão "Consultar dívidas" só é habilitado depois que o reCAPTCHA é resolvido. O sistema não resolve reCAPTCHA automaticamente. Por isso, quando o PDF não vem pela API e o sistema tenta buscar pelo navegador, o clique em "Consultar" costuma falhar (botão permanece desabilitado). Em produção, o ideal é que a API da Nio devolva a URL do PDF; quando isso não acontece, a resposta da fatura segue com os dados (valor, PIX, código de barras), mas sem anexo PDF.

**Como ver o navegador e os cliques do PDF (debug):**

1. **PAP_HEADLESS=false** – O navegador abre na tela quando for usado (token ou PDF).
2. **FORCE_FATURA_PDF_PLAYWRIGHT=true** – **Ignora** o PDF da API e **sempre** busca o PDF abrindo o navegador e fazendo o fluxo completo (Consultar → Pagar conta → Gerar boleto → Baixar PDF). Use só em teste local quando quiser ver exatamente onde clica e por que o download pode falhar.

   **PowerShell (sessão atual):**
   ```powershell
   $env:PAP_HEADLESS="false"
   $env:FORCE_FATURA_PDF_PLAYWRIGHT="true"
   python manage.py runserver
   ```

   Depois envie **Fatura** e o **CPF**; o navegador abrirá e você verá todos os cliques até o “Baixar PDF”.

### Importante

- Use **PAP_HEADLESS=false** só em **ambiente de teste local** (sua máquina com monitor).
- Em **produção** (Railway) **não** defina `PAP_HEADLESS=false`: lá não há tela e o padrão é navegador em segundo plano (`PAP_HEADLESS=true`).

---

## 3. Ver o que aconteceu em produção (screenshots + trace)

Em produção não há tela, então não dá para "abrir o navegador" no servidor. A alternativa é **salvar screenshots** em cada etapa e, quando ativado, um **trace** do Playwright para inspecionar cada clique.

### Ativar em produção

1. **Variável de ambiente** no Railway: `PAP_CAPTURE_SCREENSHOTS=true`
2. A automação salva:
   - **Screenshots** em `downloads/` como `pap_venda_{sessao_id}_{etapa}_{timestamp}.png`
   - **Trace** (quando screenshots estão ativos) como `pap_trace_{sessao_id}_{timestamp}.zip`
3. **Ver os screenshots:** em produção acesse `GET /api/crm/debug/screenshots/` para listar e `GET /api/crm/debug/screenshots/{nome_arquivo}/` para baixar.

### Etapas registradas em screenshot (Etapa 1 – Novo Pedido)

| Arquivo (exemplo) | Momento |
|------------------|--------|
| `01_login_ok` | Após login no PAP |
| `01a_antes_novo_pedido` | Tela atual antes de ir para Novo Pedido (ex.: auditoria) |
| `01b_apos_goto_novo_pedido` | Após navegar pela URL para novo pedido |
| `01c_apos_clique_menu_novo_pedido` | Só se foi usado fallback (clique no menu "Novo Pedido") |
| `01d_etapa1_concluida` | Formulário de novo pedido preenchido, antes da etapa CEP |
| `02_viabilidade_disponivel`, `03_cpf_cliente_ok`, etc. | Demais etapas da venda |

### Ver onde os cliques estão sendo feitos (Trace Playwright)

Quando `PAP_CAPTURE_SCREENSHOTS=true`, a automação também **grava um trace** (todas as ações: cliques, navegação, etc.). Assim você vê exatamente onde cada clique foi dado.

1. Após uma venda (ou erro), acesse `GET /api/crm/debug/screenshots/` e baixe o arquivo `pap_trace_*.zip` mais recente.
2. Abra [https://trace.playwright.dev](https://trace.playwright.dev) no navegador.
3. Arraste o arquivo `.zip` para a página (ou use "Load trace").
4. Use a timeline para ver cada ação; em cada frame dá para ver o snapshot da página e o elemento clicado.

Não é necessário nenhuma tecnologia extra no servidor: o Playwright grava o trace e o Trace Viewer é uma página web que abre o arquivo local.

### Salvar no OneDrive (junto com as outras ferramentas)

Se você já usa OneDrive no projeto (MS_CLIENT_ID, MS_REFRESH_TOKEN, etc.), pode enviar os screenshots para a mesma conta:

1. **Variáveis de ambiente:** `PAP_CAPTURE_SCREENSHOTS=true` e `PAP_SCREENSHOTS_ONEDRIVE=true`
2. Opcional: `PAP_ONEDRIVE_FOLDER=NomeDaPasta` (padrão: `PAP_Screenshots`). Os arquivos ficam em `{MS_DRIVE_FOLDER_ROOT}/{PAP_ONEDRIVE_FOLDER}/`, por exemplo `CDOI_Record_Vertical/PAP_Screenshots/`.
3. Cada screenshot continua sendo salvo em `downloads/` e também é enviado ao OneDrive; assim você vê tudo no mesmo lugar das outras ferramentas e não perde os arquivos se o servidor reiniciar.

**Nota:** Em plataformas como Railway a pasta `downloads/` pode ser efêmera; com OneDrive ativo os screenshots ficam guardados no drive.

---

## Resumo

| Objetivo | Como fazer |
|----------|------------|
| Ver cada etapa sem usar WhatsApp | `python manage.py testar_pap_terminal` |
| Ver cada etapa com fluxo real pelo WhatsApp | Rodar o servidor local com `PAP_HEADLESS=false` e disparar pelo WhatsApp (ex.: com ngrok) |
| Ver como estava a tela em produção | Ativar `PAP_CAPTURE_SCREENSHOTS=true` e acessar `/api/crm/debug/screenshots/` |
| Ver onde cada clique foi dado (trace) | Com screenshots ativos, baixar `pap_trace_*.zip` e abrir em https://trace.playwright.dev |

A lógica da automação é a mesma em ambos os casos; só muda quem “envia” as mensagens (terminal ou WhatsApp).

---

## 4. Correção: "Novo Pedido" (quando a tela não mudava)

Se o sistema ficava em **Auditoria de pedidos** (ou outra tela) e não abria o formulário de **Novo Pedido** só com a URL, a automação agora faz **fallback**: depois de tentar ir para a URL do novo pedido, se o campo "matrícula do vendedor" não aparecer em alguns segundos, ela **clica no item do menu lateral "Novo Pedido"**. Assim a troca de tela passa a funcionar mesmo quando a SPA não responde só ao `goto`.

Para acompanhar isso em produção, ative `PAP_CAPTURE_SCREENSHOTS=true` e confira os screenshots `01a_antes_novo_pedido`, `01b_apos_goto_novo_pedido` e, se houve fallback, `01c_apos_clique_menu_novo_pedido`.
