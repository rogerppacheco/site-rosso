from crm_app.models import SyncStatusEsteiraExecucao

e = SyncStatusEsteiraExecucao.objects.filter(status='em_andamento').first()
if not e:
    print('NENHUMA execucao em_andamento')
else:
    print(
        f'id={e.id} modo={e.modo} proc={e.processados}/{e.total_pedidos} '
        f'erros={e.erros} att={e.atualizados} iniciado={e.iniciado_em} '
        f'msg={(e.mensagem_erro or "")[:120]}'
    )

ultima = SyncStatusEsteiraExecucao.objects.order_by('-iniciado_em').first()
if ultima:
    print(
        f'ultima: id={ultima.id} status={ultima.status} proc={ultima.processados}/{ultima.total_pedidos} '
        f'finalizado={ultima.finalizado_em}'
    )
