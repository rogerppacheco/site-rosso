"""
Testar API de logs FPD
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
django.setup()

from rest_framework.test import APIRequestFactory
from rest_framework.test import force_authenticate
from crm_app.views import ListarLogsImportacaoFPDView
from usuarios.models import Usuario
import json

print("\n" + "=" * 100)
print("🧪 TESTANDO API DE LOGS FPD")
print("=" * 100)

try:
    # Criar requisição fake
    factory = APIRequestFactory()
    request = factory.get('/api/bonus-m10/logs-importacao-fpd/?page=1&limit=20')
    
    # Pegar primeiro usuário admin
    user = Usuario.objects.filter(is_superuser=True).first()
    if not user:
        user = Usuario.objects.first()
    
    force_authenticate(request, user=user)
    
    # Chamar view
    view = ListarLogsImportacaoFPDView.as_view()
    response = view(request)
    
    print(f"\n✅ Status Code: {response.status_code}")
    
    if response.status_code == 200:
        data = response.data
        print(f"\n📊 Resposta:")
        print(f"   Total: {data.get('total')}")
        print(f"   Páginas: {data.get('total_pages')}")
        print(f"   Logs retornados: {len(data.get('logs', []))}")
        
        print(f"\n📈 Estatísticas Gerais:")
        stats = data.get('estatisticas_gerais', {})
        for key, value in stats.items():
            print(f"   {key}: {value}")
        
        if data.get('logs'):
            print(f"\n📄 Primeiro log:")
            primeiro_log = data['logs'][0]
            for key, value in primeiro_log.items():
                if key not in ['detalhes_json']:
                    print(f"   {key}: {value}")
    else:
        print(f"\n❌ Erro na API!")
        print(f"   Response: {response.data}")
        
except Exception as e:
    print(f"\n❌ ERRO ao executar view: {str(e)}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 100)
