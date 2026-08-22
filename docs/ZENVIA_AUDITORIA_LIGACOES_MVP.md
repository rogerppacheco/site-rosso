# Zenvia Voice API na Auditoria (MVP)

## O que foi implementado

- Modelo `AuditoriaLigacao` para rastrear chamada, gravação e link do OneDrive.
- Endpoint para iniciar chamada:
  - `POST /api/crm/auditoria/ligacoes/<venda_id>/iniciar/`
- Endpoint para listar ligações da venda:
  - `GET /api/crm/auditoria/ligacoes/<venda_id>/`
- Endpoint de webhook para atualização de status/gravação:
  - `POST /api/crm/auditoria/ligacoes/webhook/`
- Serviço `ZenviaVoiceService` com criação de chamada e busca de gravação.
- Sincronização de gravação para OneDrive ao receber `url_gravacao` no webhook.

## Variáveis de ambiente

```env
ZENVIA_VOICE_API_URL=https://voice-api.zenvia.com
ZENVIA_VOICE_ACCESS_TOKEN=SEU_TOKEN_DA_VOZ
ZENVIA_VOICE_CALLS_ENDPOINT=/chamada
ZENVIA_VOICE_RECORDING_ENDPOINT_TEMPLATE=/chamada/{call_id}/gravacao
ZENVIA_VOICE_DEFAULT_SOURCE_NUMBER=5511999999999
ZENVIA_VOICE_TIMEOUT_SECONDS=20
ZENVIA_VOICE_WEBHOOK_SECRET=SEGREDO_WEBHOOK
AUDITORIA_ONEDRIVE_FOLDER=Auditoria_Ligacoes
```

## Migração

```bash
python manage.py migrate
```

## Teste rápido (manual)

1. Autentique no sistema e pegue JWT.
2. Inicie uma chamada:

```bash
curl -X POST "https://SEU_DOMINIO/api/crm/auditoria/ligacoes/123/iniciar/" \
  -H "Authorization: Bearer SEU_JWT" \
  -H "Content-Type: application/json" \
  -d "{\"consentimento_declarado\": true}"
```

3. Configure o webhook na Zenvia apontando para:
   - `https://SEU_DOMINIO/api/crm/auditoria/ligacoes/webhook/?secret=SEGREDO_WEBHOOK`
4. Após encerrar a chamada, confirme em:
   - `GET /api/crm/auditoria/ligacoes/123/`

## Observações importantes

- O payload de chamada e webhook da Zenvia pode variar por conta/plano. Os endpoints no código estão configuráveis por variáveis de ambiente.
- Se o payload do webhook chegar com nomes de campos diferentes, ajuste o parser em `crm_app/auditoria_ligacoes_api.py`.
- O upload para OneDrive usa as mesmas credenciais já existentes no projeto (`MS_CLIENT_ID`, `MS_CLIENT_SECRET`, `MS_REFRESH_TOKEN`).
