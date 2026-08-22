from django.core.management.base import BaseCommand
from django.db.models import Count

from crm_app.models import ContratoM10, FaturaM10, ImportacaoFPD
from crm_app.services.qualidade_service import (
    STATUS_FATURA_FECHADA,
    _contrato_tem_campo,
    contagens_filas_tratamento,
    mes_range,
)


class Command(BaseCommand):
    help = 'Diagnostica divergência Dashboard FPD x Tratamento por mês'

    def add_arguments(self, parser):
        parser.add_argument('--mes', default='2026-06')

    def handle(self, *args, **options):
        mes = options['mes']
        inicio, fim = mes_range(mes)
        self.stdout.write(f'=== {mes} range {inicio}..{fim} ===')

        qs_fpd = ImportacaoFPD.objects.filter(
            indicador='FPD',
            dt_venc_orig__gte=inicio,
            dt_venc_orig__lt=fim,
        )
        self.stdout.write(f'ImportacaoFPD total {qs_fpd.count()}')
        for row in qs_fpd.values('match_status').annotate(n=Count('id')):
            self.stdout.write(f'  match {row}')
        for row in qs_fpd.values('ds_sit_fatura').annotate(n=Count('id')):
            self.stdout.write(f'  sit {row}')

        contrato_ids_f1 = set(
            FaturaM10.objects.filter(
                numero_fatura=1,
                data_vencimento__gte=inicio,
                data_vencimento__lt=fim,
                data_importacao_fpd__isnull=False,
            ).values_list('contrato_id', flat=True)
        )
        self.stdout.write(f'F1 venc+import {len(contrato_ids_f1)}')
        if _contrato_tem_campo('orfao'):
            trat_ids = set(
                ContratoM10.objects.filter(id__in=contrato_ids_f1, orfao=False)
                .values_list('id', flat=True)
            )
            self.stdout.write(f'  orfaos excluidos {len(contrato_ids_f1) - len(trat_ids)}')
        else:
            trat_ids = set(contrato_ids_f1)
        self.stdout.write(f'Tratamento universo {len(trat_ids)}')

        matched_rows = qs_fpd.filter(match_status='MATCHED', contrato_m10_id__isnull=False)
        matched_ids = set(matched_rows.values_list('contrato_m10_id', flat=True))
        self.stdout.write(f'MATCHED rows {matched_rows.count()} contratos {len(matched_ids)}')
        dups = matched_rows.values('contrato_m10_id').annotate(n=Count('id')).filter(n__gt=1).count()
        self.stdout.write(f'contratos com >1 linha Imp {dups}')

        so_imp = matched_ids - trat_ids
        so_trat = trat_ids - matched_ids
        self.stdout.write(f'so Importacao {len(so_imp)} | so Tratamento {len(so_trat)}')

        from collections import Counter
        motivos: Counter[str] = Counter()
        for i, cid in enumerate(so_imp):
            f1 = FaturaM10.objects.filter(contrato_id=cid, numero_fatura=1).first()
            c = ContratoM10.objects.filter(id=cid).only('id', 'ordem_servico', 'orfao').first()
            if not f1:
                motivo = 'sem_fatura1'
            elif not f1.data_importacao_fpd:
                motivo = 'f1_sem_import'
            elif not f1.data_vencimento:
                motivo = 'f1_sem_venc'
            elif f1.data_vencimento < inicio or f1.data_vencimento >= fim:
                motivo = 'f1_venc_fora_mes'
            elif getattr(c, 'orfao', False):
                motivo = 'orfao'
            else:
                motivo = 'outro'
            motivos[motivo] += 1
            if i < 15:
                imp = ImportacaoFPD.objects.filter(
                    indicador='FPD', contrato_m10_id=cid,
                    dt_venc_orig__gte=inicio, dt_venc_orig__lt=fim,
                ).first()
                self.stdout.write(
                    f'  amostra os={getattr(c, "ordem_servico", None)} '
                    f'f1={getattr(f1, "data_vencimento", None)} st={getattr(f1, "status", None)} '
                    f'imp={getattr(imp, "dt_venc_orig", None)} sit={getattr(imp, "ds_sit_fatura", None)} '
                    f'motivo={motivo}'
                )
        self.stdout.write('motivos:')
        for k, v in motivos.most_common():
            self.stdout.write(f'  {k}: {v}')

        fatura_crm = dict(
            FaturaM10.objects.filter(contrato_id__in=matched_ids, numero_fatura=1)
            .values_list('contrato_id', 'status')
        )
        paga = aberta = sem = 0
        for cid in matched_ids:
            st = (fatura_crm.get(cid) or '').upper()
            if st in STATUS_FATURA_FECHADA:
                paga += 1
            elif st:
                aberta += 1
            else:
                sem += 1
        self.stdout.write(f'MATCHED CRM paga={paga} aberta={aberta} sem={sem}')

        filas = contagens_filas_tratamento(ContratoM10.objects.filter(id__in=trat_ids))
        self.stdout.write(f'filas {filas} soma={sum(filas.values())}')
