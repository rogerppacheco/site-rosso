"""
Script para importar CHURN via API e gerar logs
"""
import os
import sys
import django
import tkinter as tk
from tkinter import filedialog

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
django.setup()

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIRequestFactory
from crm_app.views import ImportarChurnView

User = get_user_model()

def importar_churn_com_log():
    print("=" * 80)
    print("🔄 IMPORTADOR CHURN COM LOG - Via API")
    print("=" * 80)
    
    # Selecionar arquivo
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    
    arquivo_path = filedialog.askopenfilename(
        title="Selecione o arquivo CHURN",
        filetypes=[
            ("Excel files", "*.xlsx *.xls *.xlsb"),
            ("CSV files", "*.csv"),
            ("All files", "*.*")
        ]
    )
    
    if not arquivo_path:
        print("❌ Nenhum arquivo selecionado")
        return
    
    print(f"\n📁 Arquivo selecionado: {arquivo_path}")
    
    # Pegar um usuário admin
    try:
        user = User.objects.filter(is_superuser=True).first()
        if not user:
            user = User.objects.filter(groups__name='Admin').first()
        if not user:
            user = User.objects.first()
        
        print(f"👤 Usuário: {user.username}")
    except Exception as e:
        print(f"❌ Erro ao buscar usuário: {e}")
        return
    
    # Ler arquivo e criar upload file
    try:
        with open(arquivo_path, 'rb') as f:
            arquivo_conteudo = f.read()
        
        arquivo_nome = os.path.basename(arquivo_path)
        uploaded_file = SimpleUploadedFile(
            name=arquivo_nome,
            content=arquivo_conteudo,
            content_type='application/vnd.ms-excel'
        )
        
        print(f"📦 Tamanho do arquivo: {len(arquivo_conteudo)} bytes")
        
    except Exception as e:
        print(f"❌ Erro ao ler arquivo: {e}")
        return
    
    # Criar requisição fake
    factory = APIRequestFactory()
    request = factory.post('/api/bonus-m10/importar-churn/', {'file': uploaded_file}, format='multipart')
    request.user = user
    request.FILES['file'] = uploaded_file
    
    # Executar view
    print("\n🚀 Iniciando importação via API...\n")
    
    try:
        view = ImportarChurnView.as_view()
        response = view(request)
        
        print("\n" + "=" * 80)
        print(f"✅ Status HTTP: {response.status_code}")
        print("=" * 80)
        
        if response.status_code == 200:
            data = response.data
            print(f"\n📊 RESULTADO DA IMPORTAÇÃO:")
            print(f"   Mensagem: {data.get('message', 'N/A')}")
            print(f"   Contratos cancelados: {data.get('cancelados', 0)}")
            print(f"   Contratos reativados: {data.get('reativados', 0)}")
            print(f"   Registros salvos: {data.get('salvos_churn', 0)}")
            print(f"   Não encontrados: {data.get('nao_encontrados', 0)}")
            print(f"   Log ID: {data.get('log_id', 'N/A')}")
            
            # Buscar o log criado
            if data.get('log_id'):
                from crm_app.models import LogImportacaoChurn
                try:
                    log = LogImportacaoChurn.objects.get(id=data['log_id'])
                    print(f"\n📋 DETALHES DO LOG:")
                    print(f"   ID: {log.id}")
                    print(f"   Arquivo: {log.nome_arquivo}")
                    print(f"   Status: {log.status}")
                    print(f"   Total linhas: {log.total_linhas}")
                    print(f"   Processadas: {log.total_processadas}")
                    print(f"   Cancelados: {log.total_contratos_cancelados}")
                    print(f"   Reativados: {log.total_contratos_reativados}")
                    print(f"   Não encontrados: {log.total_nao_encontrados}")
                    print(f"   Duração: {log.duracao_segundos}s")
                    print(f"   Iniciado em: {log.iniciado_em}")
                    print(f"   Finalizado em: {log.finalizado_em}")
                    
                    # Verificar total de logs
                    total_logs = LogImportacaoChurn.objects.count()
                    print(f"\n📊 Total de logs na base: {total_logs}")
                    
                except Exception as e:
                    print(f"❌ Erro ao buscar log: {e}")
        else:
            print(f"❌ Erro: {response.data}")
            
    except Exception as e:
        import traceback
        print(f"❌ Erro durante importação: {e}")
        traceback.print_exc()

if __name__ == '__main__':
    importar_churn_com_log()
    input("\n\nPressione ENTER para sair...")
