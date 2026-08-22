# 📸 Como Acessar Screenshots no Railway

## 🎯 Objetivo
Acessar os screenshots de debug salvos no servidor de produção (Railway) para análise de problemas.

---

## 📋 Pré-requisitos

1. **Railway CLI instalado**
   ```powershell
   # Instalar Railway CLI
   npm install -g @railway/cli
   
   # OU via winget (Windows)
   winget install Railway
   ```

2. **Autenticação no Railway**
   ```powershell
   railway login
   ```

---

## 🚀 Método 1: Via Railway CLI (Recomendado)

### Passo 1: Conectar ao Projeto
```powershell
# Listar projetos
railway list

# Conectar ao projeto (substitua 'seu-projeto' pelo nome do seu projeto)
railway link

# OU conectar diretamente pelo ID do projeto
railway link --project seu-project-id
```

### Passo 2: Acessar o Container/Shell
```powershell
# Abrir shell interativo no container
railway shell

# OU executar comando direto
railway run bash
```

### Passo 3: Navegar até a pasta downloads
```bash
# Dentro do shell do Railway
cd /app
ls -la downloads/

# Ver screenshots específicos
ls -la downloads/debug_nio_negocia_*.png
ls -la downloads/debug_nio_negocia_*.html
```

### Passo 4: Copiar arquivos para sua máquina
```powershell
# IMPORTANTE: No Windows PowerShell, use bash -c para executar comandos Linux
# Opção 1: Baixar um screenshot específico
railway run bash -c "cat /app/downloads/debug_nio_negocia_botao_desabilitado_70401681629.png" > screenshot.png

# Opção 2: Baixar todos os screenshots de um CPF (compactado)
railway run bash -c "cd /app/downloads && tar -czf - debug_nio_negocia_*70401681629*" > screenshots_70401681629.tar.gz

# Opção 3: Usar base64 para arquivos grandes (mais confiável)
railway run bash -c "base64 /app/downloads/debug_nio_negocia_botao_desabilitado_70401681629.png" | Out-File -Encoding ASCII screenshot_base64.txt
# Depois decodificar: [System.Convert]::FromBase64String((Get-Content screenshot_base64.txt -Raw)) | Set-Content screenshot.png -Encoding Byte
```

---

## 🌐 Método 2: Via Dashboard do Railway

### Passo 1: Acessar o Dashboard
1. Acesse: https://railway.app
2. Faça login na sua conta
3. Selecione o projeto da aplicação

### Passo 2: Acessar o Service/Container
1. Clique no **service** que está rodando a aplicação
2. Vá na aba **"Deployments"** ou **"Metrics"**
3. Clique em **"View Logs"** ou **"Shell"**

### Passo 3: Executar Comandos
No terminal/shell do dashboard:
```bash
# Listar arquivos
ls -la /app/downloads/

# Ver screenshots
ls -la /app/downloads/debug_nio_negocia_*.png
```

**⚠️ Nota:** O dashboard do Railway pode não permitir download direto de arquivos. Use o CLI para isso.

---

## 🔧 Método 3: Via Endpoint Django (✅ RECOMENDADO - Mais Fácil!)

**✅ Endpoints já criados e prontos para uso!**

### Passo 1: Fazer Login na Aplicação
1. Acesse sua aplicação: `https://seu-dominio.com` ou `https://site-record-production.up.railway.app`
2. Faça login com suas credenciais

### Passo 2: Listar Screenshots Disponíveis
Abra no navegador:
```
https://seu-dominio.com/api/crm/debug/screenshots/
```

Ou via curl/Postman:
```powershell
# Com autenticação (token JWT)
curl -H "Authorization: Bearer SEU_TOKEN" https://seu-dominio.com/api/crm/debug/screenshots/
```

A resposta será um JSON com todos os screenshots:
```json
{
  "total": 3,
  "screenshots": [
    {
      "nome": "debug_nio_negocia_botao_desabilitado_70401681629.png",
      "tamanho": 245678,
      "data_modificacao": "2026-01-24T20:09:02",
      "url": "/api/crm/debug/screenshots/debug_nio_negocia_botao_desabilitado_70401681629.png/"
    },
    ...
  ]
}
```

### Passo 3: Baixar um Screenshot
Clique no link `url` do screenshot ou acesse diretamente:
```
https://seu-dominio.com/api/crm/debug/screenshots/debug_nio_negocia_botao_desabilitado_70401681629.png/
```

O arquivo será baixado automaticamente!

### Via PowerShell (com autenticação):
```powershell
# 1. Obter token de autenticação (faça login primeiro)
$token = "SEU_TOKEN_JWT"

# 2. Listar screenshots
Invoke-RestMethod -Uri "https://seu-dominio.com/api/crm/debug/screenshots/" -Headers @{"Authorization"="Bearer $token"}

# 3. Baixar screenshot específico
Invoke-WebRequest -Uri "https://seu-dominio.com/api/crm/debug/screenshots/debug_nio_negocia_botao_desabilitado_70401681629.png/" -Headers @{"Authorization"="Bearer $token"} -OutFile "screenshot.png"
```

**✅ Vantagens:**
- Não precisa instalar Railway CLI
- Funciona em qualquer navegador
- Mais rápido e confiável
- Interface visual (pode ver a lista de screenshots)

---

## 🔧 Método 4: Criar Endpoint de Download (Já Implementado!)

Se você precisar acessar screenshots frequentemente, podemos criar um endpoint na aplicação Django para listar e baixar os screenshots.

### Exemplo de View Django:
```python
# crm_app/views.py
from django.http import FileResponse, JsonResponse
import os
from pathlib import Path

def listar_screenshots(request):
    """Lista todos os screenshots de debug"""
    downloads_dir = Path(__file__).parent.parent.parent / 'downloads'
    screenshots = []
    
    if downloads_dir.exists():
        for file in downloads_dir.glob('debug_nio_negocia_*.png'):
            screenshots.append({
                'nome': file.name,
                'tamanho': file.stat().st_size,
                'data': file.stat().st_mtime
            })
    
    return JsonResponse({'screenshots': screenshots})

def baixar_screenshot(request, nome_arquivo):
    """Baixa um screenshot específico"""
    downloads_dir = Path(__file__).parent.parent.parent / 'downloads'
    arquivo = downloads_dir / nome_arquivo
    
    if arquivo.exists() and nome_arquivo.startswith('debug_nio_negocia_'):
        return FileResponse(open(arquivo, 'rb'), content_type='image/png')
    
    return JsonResponse({'erro': 'Arquivo não encontrado'}, status=404)
```

### Adicionar URLs:
```python
# gestao_equipes/urls.py
from crm_app.views import listar_screenshots, baixar_screenshot

urlpatterns = [
    # ... outras URLs
    path('api/debug/screenshots/', listar_screenshots, name='listar_screenshots'),
    path('api/debug/screenshots/<str:nome_arquivo>/', baixar_screenshot, name='baixar_screenshot'),
]
```

---

## 📝 Método 5: Via Logs do Railway

Os screenshots são salvos, mas você pode ver os caminhos nos logs:

```powershell
# Ver logs do Railway
railway logs

# Filtrar por screenshots
railway logs | grep "Screenshot"
railway logs | grep "debug_nio_negocia"
```

Os logs mostrarão mensagens como:
```
INFO Screenshot do botão desabilitado: /downloads/debug_nio_negocia_botao_desabilitado_70401681629.png
INFO Screenshot para extração de dados: /downloads/debug_nio_negocia_extraindo_dados_70401681629.png
```

---

## 🎯 Comandos Rápidos (Copy & Paste)

### Listar todos os screenshots:
```powershell
railway run ls -lah /app/downloads/debug_nio_negocia_*
```

### Baixar um screenshot específico (Windows PowerShell):
```powershell
# IMPORTANTE: Use bash -c no Windows
railway run bash -c "cat /app/downloads/debug_nio_negocia_botao_desabilitado_70401681629.png" > screenshot_botao.png
```

### Baixar todos os screenshots de um CPF:
```powershell
railway run bash -c "cd /app/downloads && tar -czf - debug_nio_negocia_*70401681629*" > screenshots_70401681629.tar.gz
```

### Ver HTML de debug:
```powershell
railway run bash -c "cat /app/downloads/debug_nio_negocia_sem_pagar_contas_70401681629.html" > debug.html
```

### Método alternativo usando base64 (mais confiável no Windows):
```powershell
# Codificar em base64
railway run bash -c "base64 /app/downloads/debug_nio_negocia_botao_desabilitado_70401681629.png" | Out-File -Encoding ASCII screenshot_b64.txt

# Decodificar no PowerShell
$base64 = Get-Content screenshot_b64.txt -Raw
[System.Convert]::FromBase64String($base64) | Set-Content screenshot.png -Encoding Byte
```

---

## ⚠️ Troubleshooting

### Erro: "railway: command not found"
```powershell
# Instalar Railway CLI
npm install -g @railway/cli
```

### Erro: "Not authenticated"
```powershell
railway login
```

### Erro: "No project linked"
```powershell
railway link
# Ou
railway link --project seu-project-id
```

### Erro: "'cat' não é reconhecido" (Windows)
**Problema:** No Windows PowerShell, `cat` não existe.  
**Solução:** Use `bash -c` para executar comandos Linux dentro do container:
```powershell
# ❌ ERRADO (não funciona no Windows):
railway run cat /app/downloads/arquivo.png > arquivo.png

# ✅ CORRETO (funciona no Windows):
railway run bash -c "cat /app/downloads/arquivo.png" > arquivo.png
```

### Arquivos não encontrados
- Verifique se o código está salvando na pasta correta
- Os screenshots são criados apenas quando há erros ou em pontos específicos do código
- Verifique os logs para confirmar que os screenshots foram criados
- Use `railway run ls -la /app/downloads/` para listar arquivos

---

## 📌 Notas Importantes

1. **Armazenamento**: Os screenshots ficam no sistema de arquivos do container Railway, que é **efêmero**. Eles podem ser perdidos se o container for reiniciado ou recriado.

2. **Limpeza**: Considere implementar uma limpeza automática de screenshots antigos para não encher o disco.

3. **Segurança**: Se criar endpoints de download, adicione autenticação para proteger os screenshots (podem conter informações sensíveis).

4. **Tamanho**: Screenshots podem ser grandes. Considere comprimir ou limitar o número mantido.

---

## 🔄 Próximos Passos

Se você quiser, posso:
1. Criar um endpoint Django para listar/baixar screenshots via web
2. Implementar limpeza automática de screenshots antigos
3. Adicionar upload automático dos screenshots para um storage externo (S3, etc.)
4. Criar um script para facilitar o download via Railway CLI
