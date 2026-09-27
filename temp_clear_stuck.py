import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
django.setup()

from crm_app.models import SyncStatusEsteiraExecucao
from django.utils import timezone

stuck = SyncStatusEsteiraExecucao.objects.filter(
    status__in=[SyncStatusEsteiraExecucao.STATUS_PENDENTE, SyncStatusEsteiraExecucao.STATUS_EM_ANDAMENTO]
)

count = stuck.count()
print(f"Encontradas {count} execuções travadas.")

for ex in stuck:
    ex.status = SyncStatusEsteiraExecucao.STATUS_ERRO
    ex.mensagem_erro = "Encerrado automaticamente (travado)."
    ex.finalizado_em = timezone.now()
    ex.save(update_fields=['status', 'mensagem_erro', 'finalizado_em'])
    print(f"Execução {ex.id} encerrada.")

print("Concluído.")
