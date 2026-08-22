# Cutover Z-API -> Evolution (site-record Railway)
# Uso: powershell -ExecutionPolicy Bypass -File scripts\railway_evolution_cutover.ps1
# Requer: railway CLI autenticado no projeto site-record

$ErrorActionPreference = "Stop"

Write-Host "=== Cutover WhatsApp: Z-API -> Evolution ===" -ForegroundColor Cyan

$vars = @{
    WHATSAPP_PROVIDER = "evolution"
    EVOLUTION_INSTANCE_NAME = "site_record_zap"
}

foreach ($kv in $vars.GetEnumerator()) {
    Write-Host "Definindo $($kv.Key)=$($kv.Value)" -ForegroundColor Yellow
    railway variables --set "$($kv.Key)=$($kv.Value)" --skip-deploys
}

Write-Host @"

Variaveis obrigatorias (defina manualmente se ainda nao existirem):
  EVOLUTION_API_URL=https://evolution-api-production-8bbb.up.railway.app
  EVOLUTION_API_KEY=<apikey do servidor Evolution>
  N8N_OUTBOUND_WEBHOOK_URL=<webhook n8n site-record-enviar-mensagem>

Infra (antes do deploy):
  python ferramentas/setup_evolution_site_record.py --qrcode
  python ferramentas/n8n/deploy_site_record_outbound_flow.py --dry-run

Outbound: Django -> n8n -> Evolution (instancia site_record_zap)
Inbound:  Evolution -> Django (/api/crm/webhook-whatsapp/)

Rollback:
  railway variables --set WHATSAPP_PROVIDER=zapi --skip-deploys
  Reativar webhook no painel Z-API

Deploy quando pronto:
  railway up --detach
"@ -ForegroundColor Gray

Write-Host "Cutover vars aplicadas (sem redeploy automatico)." -ForegroundColor Green
