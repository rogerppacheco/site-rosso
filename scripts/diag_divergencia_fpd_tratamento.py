"""Diagnóstico: Dashboard FPD (ImportacaoFPD) vs Tratamento (FaturaM10) por mês."""
from __future__ import annotations

import os
from collections import Counter

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
django.setup()

from crm_app.models import ContratoM10, FaturaM10, ImportacaoFPD  # noqa: E402
from crm_app.services.qualidade_service import (  # noqa: E402
    STATUS_FATURA_FECHADA,
    _contrato_tem_campo,
    mes_range,
)


def main(mes: str = '2026-06') -> None:
    inicio, fim = mes_range(mes)
    print('=== Diagnóstico', mes, 'range', inicio, fim, '===')

    qs_fpd = ImportacaoFPD.objects.filter(
        indicador='FPD',
        dt_venc_orig__gte=inicio,
        dt_venc_orig__lt=fim,
    )
    print('ImportacaoFPD total', qs_fpd.count())
    for row in qs_fpd.values('match_status').annotate(n=django.db.models.Count('id')):
        print('  match', row)

    from django.db.models import Count

    print('by match_status:')
    for row in qs_fpd.values('match_status').annotate(n=Count('id')):
        print(' ', row)
    print('by ds_sit_fatura:')
    for row in qs_fpd.values('ds_sit_fatura').annotate(n=Count('id')):
        print(' ', row)

    contrato_ids_f1 = set(
        FaturaM10.objects.filter(
            numero_fatura=1,
            data_vencimento__gte=inicio,
            data_vencimento__lt=fim,
            data_importacao_fpd__isnull=False,
        ).values_list('contrato_id', flat=True)
    )
    print('F1 venc+import no mês', len(contrato_ids_f1))
    if _contrato_tem_campo('orfao'):
        trat_ids = set(
            ContratoM10.objects.filter(id__in=contrato_ids_f1, orfao=False)
            .values_list('id', flat=True)
        )
        print('  orfaos excluídos', len(contrato_ids_f1) - len(trat_ids))
    else:
        trat_ids = set(contrato_ids_f1)
    print('Tratamento universo (sem órfão)', len(trat_ids))

    matched_rows = qs_fpd.filter(match_status='MATCHED', contrato_m10_id__isnull=False)
    matched_ids = set(matched_rows.values_list('contrato_m10_id', flat=True))
    print('Importacao MATCHED rows', matched_rows.count())
    print('Importacao MATCHED contratos distinct', len(matched_ids))

    dups = (
        matched_rows.values('contrato_m10_id')
        .annotate(n=Count('id'))
        .filter(n__gt=1)
        .count()
    )
    print('contratos com >1 linha Importacao no mês', dups)

    so_imp = matched_ids - trat_ids
    so_trat = trat_ids - matched_ids
    print('só Importacao (não no Tratamento)', len(so_imp))
    print('só Tratamento (não na Importacao)', len(so_trat))

    motivos: Counter[str] = Counter()
    amostras: list[dict] = []
    for cid in list(so_imp)[:200]:
        f1 = FaturaM10.objects.filter(contrato_id=cid, numero_fatura=1).first()
        c = ContratoM10.objects.filter(id=cid).only(
            'id', 'ordem_servico', 'orfao', 'cliente_nome'
        ).first()
        imp = (
            ImportacaoFPD.objects.filter(
                indicador='FPD',
                contrato_m10_id=cid,
                dt_venc_orig__gte=inicio,
                dt_venc_orig__lt=fim,
            )
            .order_by('id')
            .first()
        )
        if not f1:
            motivo = 'sem_fatura1'
        elif not f1.data_importacao_fpd:
            motivo = 'f1_sem_data_importacao_fpd'
        elif not f1.data_vencimento:
            motivo = 'f1_sem_vencimento'
        elif f1.data_vencimento < inicio or f1.data_vencimento >= fim:
            motivo = f'f1_venc_fora_mes:{f1.data_vencimento}'
        elif getattr(c, 'orfao', False):
            motivo = 'orfao'
        else:
            motivo = 'outro'
        motivos[motivo.split(':')[0]] += 1
        if len(amostras) < 20:
            amostras.append({
                'os': c.ordem_servico if c else None,
                'orfao': getattr(c, 'orfao', None),
                'f1_venc': str(f1.data_vencimento) if f1 and f1.data_vencimento else None,
                'f1_status': f1.status if f1 else None,
                'f1_import': bool(f1.data_importacao_fpd) if f1 else False,
                'imp_venc': str(imp.dt_venc_orig) if imp and imp.dt_venc_orig else None,
                'imp_sit': imp.ds_sit_fatura if imp else None,
                'motivo': motivo,
            })

    print('motivos (até 200):')
    for k, v in motivos.most_common():
        print(f'  {k}: {v}')
    print('amostras:')
    for a in amostras:
        print(' ', a)

    # Contagens estilo Dashboard (status CRM)
    fatura_crm = {
        cid: st
        for cid, st in FaturaM10.objects.filter(
            contrato_id__in=matched_ids,
            numero_fatura=1,
        ).values_list('contrato_id', 'status')
    }
    paga = aberta = sem_crm = 0
    for cid in matched_ids:
        st = (fatura_crm.get(cid) or '').upper()
        if st in STATUS_FATURA_FECHADA:
            paga += 1
        elif st:
            aberta += 1
        else:
            sem_crm += 1
    print('MATCHED by CRM status: paga', paga, 'aberta', aberta, 'sem_crm', sem_crm)

    # Filas tratamento
    from crm_app.services.qualidade_service import contagens_filas_tratamento

    qs_trat = ContratoM10.objects.filter(id__in=trat_ids)
    filas = contagens_filas_tratamento(qs_trat)
    print('filas tratamento', filas, 'soma', sum(filas.values()) if filas else 0)


if __name__ == '__main__':
    import sys
    main(sys.argv[1] if len(sys.argv) > 1 else '2026-06')
