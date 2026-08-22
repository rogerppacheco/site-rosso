# Teste local com o mesmo código de produção (navegador visível)

Este guia permite rodar **o mesmo código que está em produção** na sua máquina, com o **navegador abrindo na tela** para você ver onde os cliques acontecem. As mensagens **SIM**, CEP, etc. vêm do **WhatsApp de verdade** (via Z-API), e o webhook é recebido pela sua API local.

---

## O que você precisa

| Programa / item | Para quê |
|-----------------|-----------|
| **Python 3.10+** | Rodar o Django e a automação PAP |
| **Node.js** (opcional, só se o Playwright pedir) | Playwright às vezes usa Node para baixar browsers |
| **Playwright (Chromium)** | Navegador controlado pela automação – instalado pelo próprio projeto |
| **ngrok** (ou similar) | Expor seu `localhost` na internet para o Z-API enviar o webhook |
| **Conta Z-API** | É o serviço que envia as mensagens do WhatsApp para a sua API (já usado em produção) |

Não é necessário criar scripts separados: você sobe o **mesmo** Django que sobe em produção, com duas diferenças: variável `PAP_HEADLESS=false` e URL do webhook no Z-API apontando para o ngrok.

---

## Passo a passo

### 1. Código e ambiente Python

Se ainda não tiver o projeto:

```bash
cd c:\site-record   # ou clone do repositório
```

Crie e ative o ambiente virtual:

**PowerShell:**
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**CMD:**
```cmd
python -m venv .venv
.venv\Scripts\activate.bat
```

Instale as dependências:

```bash
pip install -r requirements.txt
```

### 2. Instalar o navegador do Playwright

O projeto usa Playwright para controlar o Chromium. Instale os browsers uma vez:

```bash
playwright install chromium
```

Se o comando não existir, use:

```bash
python -m playwright install chromium
```

### 3. Banco de dados (local ou produção)

- **Opção A – Banco local:** use SQLite para testar sem mexer em produção.
  - No seu `.env` (ou variáveis de ambiente), **não** defina `DATABASE_URL` (ou use `sqlite:///db.sqlite3` se o projeto tiver suporte).
  - Rode as migrações: `python manage.py migrate`
  - Crie um superusuário se precisar: `python manage.py createsuperuser`
  - Você precisará ter (ou criar) usuários BackOffice e vendedores no banco local para o fluxo VENDER (pool de BO, matrícula PAP, etc.).

- **Opção B – Mesmo banco de produção:** defina no `.env` a mesma `DATABASE_URL` de produção. **Cuidado:** qualquer dado criado/alterado no fluxo (sessões, etapas) afeta produção.

### 4. Variáveis de ambiente (arquivo `.env`)

Crie ou edite o `.env` na raiz do projeto (`c:\site-record\.env`). Use como base o que está em produção e ajuste só o que for necessário:

| Variável | Uso em teste local |
|----------|---------------------|
| `SECRET_KEY` | Qualquer string (ex.: a mesma de desenvolvimento). |
| `DEBUG` | `True` se quiser mensagens de erro detalhadas. |
| `DATABASE_URL` | Vazio (SQLite) ou igual a produção (ver passo 3). |
| `ZAPI_INSTANCE_ID` | **Mesmo de produção** – para receber e enviar WhatsApp. |
| `ZAPI_TOKEN` | **Mesmo de produção**. |
| `ZAPI_CLIENT_TOKEN` | **Mesmo de produção**. |
| **`PAP_HEADLESS`** | **`false`** – é isso que faz o navegador abrir na tela. |
| `PAP_CAPTURE_SCREENSHOTS` | Opcional: `true` se quiser screenshots em cada etapa (em `downloads/`). |

Em produção você **não** deve usar `PAP_HEADLESS=false` (no servidor não há tela).

Exemplo mínimo no PowerShell (só para esta sessão):

```powershell
$env:PAP_HEADLESS="false"
# As demais (ZAPI_*, DATABASE_URL, etc.) podem estar no .env
```

### 5. Subir a API local

Na raiz do projeto, com o venv ativado e `PAP_HEADLESS=false`:

```bash
python manage.py runserver
```

A API fica em `http://127.0.0.1:8000/`. O endpoint que recebe as mensagens do WhatsApp é:

- `http://127.0.0.1:8000/api/crm/webhook-whatsapp/`

Como o Z-API só consegue chamar URLs **públicas**, você precisa expor essa URL com o ngrok.

### 6. Expor o localhost com ngrok

1. Baixe e instale o [ngrok](https://ngrok.com/download) (ou use outro túnel, ex.: Cloudflare Tunnel).
2. Em outro terminal, execute:

   ```bash
   ngrok http 8000
   ```

3. O ngrok mostra uma URL pública, por exemplo:
   `https://abc123.ngrok-free.app`
4. A URL completa do webhook que o Z-API deve chamar é:
   **`https://SEU_SUBDOMINIO.ngrok-free.app/api/crm/webhook-whatsapp/`**
   (troque `SEU_SUBDOMINIO` pelo que o ngrok exibir; use **https** e a barra no final.)

### 7. Configurar o webhook no Z-API (para receber SIM e demais etapas)

O Z-API é o programa/serviço que envia as mensagens do WhatsApp para a sua API. É nele que você configura **para onde** as notificações (incluindo “SIM”, CEP, etc.) são enviadas.

1. Acesse o **painel do Z-API** (onde você já configurou a instância usada em produção).
2. Localize a configuração de **Webhook** ou **URL de retorno** / **Callback** para mensagens recebidas.
3. Altere a URL do webhook para a URL pública do ngrok:
   - **URL do webhook:** `https://SEU_SUBDOMINIO.ngrok-free.app/api/crm/webhook-whatsapp/`
4. Salve.

A partir daí, quando alguém enviar uma mensagem (VENDER, SIM, CEP, etc.) para o número conectado no Z-API, essa mensagem será enviada **para a sua API local** (via ngrok). O mesmo código que sobe em produção processa o webhook e dispara a automação; na sua máquina o navegador abre porque `PAP_HEADLESS=false`.

### 8. Testar

1. Deixe rodando: `python manage.py runserver` (com `PAP_HEADLESS=false`) e o `ngrok http 8000`.
2. Pelo **WhatsApp**, envie para o número da Record/API:
   - **VENDER**
   - Depois **SIM** quando perguntado.
3. Na sua máquina:
   - O **navegador** (Chromium) deve abrir sozinho.
   - Você verá o PAP (login, novo pedido, etc.) sendo preenchido e **onde os cliques acontecem** (já existe `slow_mo` quando não é headless para facilitar a visualização).

Se algo falhar, confira o terminal do `runserver` para erros e logs (ex.: “[VENDER]”, “[PAP]”, “[Webhook]”).

---

## Resumo rápido

| Passo | O quê |
|-------|--------|
| 1 | Código em `c:\site-record`, venv, `pip install -r requirements.txt` |
| 2 | `playwright install chromium` (ou `python -m playwright install chromium`) |
| 3 | Banco: migrações (local ou mesmo de produção) |
| 4 | `.env` com Z-API de produção e **`PAP_HEADLESS=false`** |
| 5 | `python manage.py runserver` |
| 6 | Em outro terminal: `ngrok http 8000` |
| 7 | No **painel Z-API**: webhook = `https://SEU_NGROK.ngrok-free.app/api/crm/webhook-whatsapp/` |
| 8 | WhatsApp: enviar VENDER → SIM e acompanhar o navegador na sua tela |

---

## Voltando para produção

Quando terminar o teste local:

1. No **painel Z-API**, altere de novo a URL do webhook para a de produção:
   - `https://www.recordpap.com.br/api/crm/webhook-whatsapp/`
2. Pode desligar o ngrok e o `runserver` local.

Assim, a API que roda em produção volta a receber o SIM e todas as etapas normalmente.
