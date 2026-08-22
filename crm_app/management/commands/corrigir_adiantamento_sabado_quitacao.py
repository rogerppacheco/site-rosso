"""
Corrige vendas instaladas com adiantamento sábado que não foram quitadas na instalação.
"""
from django.core.management.base import BaseCommand
from django.db.models import Q

from crm_app.models import Venda
from crm_app.services.adiantamento_sabado_service import (
    comissao_ja_adiantada_venda,
    garantir_quitacao_adiantamento_sabado_instalada,
    quitar_adiantamento_sabado_na_instalacao,
    sincronizar_antecipacao_quitado_sabado,
    status_esteira_eh_instalada,
)


class Command(BaseCommand):
    help = (
        'Marca antecipacao_comissao e adiantamento_sabado_quitado_em em vendas INSTALADAS '
        'com adiantamento_sábado pendente de quitação.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--ids',
            type=str,
            default='',
            help='IDs separados por vírgula (ex.: 5864,6095). Se vazio, corrige todas elegíveis.',
        )
        parser.add_argument(
            '--aplicar',
            action='store_true',
            help='Persistir alterações (sem flag: apenas dry-run).',
        )

    def handle(self, *args, **options):
        aplicar = options['aplicar']
        ids_raw = (options['ids'] or '').strip()
        qs = Venda.objects.filter(ativo=True).select_related(
            'status_esteira', 'vendedor', 'cliente'
        ).filter(
            Q(adiantamento_sabado_marcado=True, adiantamento_sabado_quitado_em__isnull=True)
            | Q(adiantamento_sabado_quitado_em__isnull=False, antecipacao_comissao=False)
            | Q(adiantamento_sabado_marcado=True, antecipacao_comissao=False)
        )

        if ids_raw:
            ids = [int(x.strip()) for x in ids_raw.split(',') if x.strip()]
            qs = qs.filter(id__in=ids)

        candidatas = []
        for v in qs.order_by('id'):
            if not status_esteira_eh_instalada(v.status_esteira):
                continue
            if v.antecipacao_comissao:
                continue
            if not v.adiantamento_sabado_marcado and not v.adiantamento_sabado_quitado_em:
                continue
            candidatas.append(v)

        if not candidatas:
            self.stdout.write(self.style.WARNING('Nenhuma venda elegível encontrada.'))
            return

        self.stdout.write(f'Vendas elegíveis: {len(candidatas)} (dry-run={not aplicar})')
        for v in candidatas:
            vendedor = v.vendedor.username if v.vendedor else '-'
            cliente = (v.cliente.nome_razao_social[:40] if v.cliente else '-')
            self.stdout.write(
                f'  #{v.id} {vendedor} | {cliente} | inst={v.data_instalacao} | '
                f'val={v.adiantamento_sabado_valor} | antecip={v.antecipacao_comissao}'
            )

        if not aplicar:
            self.stdout.write(self.style.NOTICE('Use --aplicar para gravar.'))
            return

        ok = 0
        for v in candidatas:
            if garantir_quitacao_adiantamento_sabado_instalada(v):
                ok += 1
            elif sincronizar_antecipacao_quitado_sabado(v):
                ok += 1
            elif quitar_adiantamento_sabado_na_instalacao(v, status_esteira_antes=None):
                ok += 1
        self.stdout.write(self.style.SUCCESS(f'Sincronizadas {ok} venda(s).'))
