"""
Testar API de logs CHURN
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
django.setup()

from django.contrib.auth import get_user_model
from rest_framework.test import APIRequestFactory
from crm_app.views import ListarLogsImportacaoChurnView

User = get_user_model()

# Pegar usuário
user = User.objects.first()
print(f"👤 Usuário: {user.username}\n")

# Criar requisição
factory = APIRequestFactory()
request = factory.get('/api/bonus-m10/logs-importacao-churn/')
request.user = user

# Chamar view
view = ListarLogsImportacaoChurnView.as_view()
response = view(request)

print(f"✅ Status: {response.status_code}")
print(f"📊 Response Data:")
print(f"   Total: {response.data.get('total')}")
print(f"   Page: {response.data.get('page')}")
print(f"   Logs: {len(response.data.get('logs', []))}")
print(f"\n📈 Estatísticas Gerais:")
stats = response.data.get('estatisticas_gerais', {})
for key, value in stats.items():
    print(f"   {key}: {value}")

print(f"\n📋 Logs encontrados:")
for log in response.data.get('logs', []):
    print(f"   - ID {log['id']}: {log['nome_arquivo']} ({log['status']}) - {log['total_linhas']} linhas")
