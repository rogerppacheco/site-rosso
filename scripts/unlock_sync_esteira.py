from django.utils import timezone
from crm_app.models import SyncStatusEsteiraExecucao

updated = SyncStatusEsteiraExecucao.objects.filter(status='em_andamento').update(
    status='interrompido',
    finalizado_em=timezone.now(),
    mensagem_erro='Encerrado manualmente — processo travado (deploy/reinício)',
)
print('updated', updated)
for e in SyncStatusEsteiraExecucao.objects.order_by('-iniciado_em')[:3]:
    print(
        f'id={e.id} status={e.status} proc={e.processados}/{e.total_pedidos} '
        f'finalizado={e.finalizado_em}'
    )
