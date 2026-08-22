"""
Re-vincula ContratoM10 à venda com data_criacao mais antiga quando a mesma O.S. tem
várias vendas instaladas no mês (ex.: criada junho, instalada julho vs criada julho, instalada julho).

Assim, passamos a "considerar" as vendas cuja data de criação foi em outro mês.

Uso (produção):
  python manage.py revincular_m10_safra 2025-07
  python manage.py revincular_m10_safra 2025-07 --dry-run
"""
from datetime import date

from django.core.management.base import BaseCommand
from dateutil.relativedelta import relativedelta

from crm_app.models import Venda, ContratoM10, StatusCRM


def parse_month(s):
    y, m = int(s[:4]), int(s[5:7])
    d0 = date(y, m, 1)
    d1 = d0 + relativedelta(months=1)
    return d0, d1


class Command(BaseCommand):
    help = 'Re-vincula ContratoM10 à venda mais antiga (data_criacao) por O.S. na safra'

    def add_arguments(self, parser):
        parser.add_argument('mes', help='Mês YYYY-MM (ex: 2025-07)')
        parser.add_argument('--dry-run', action='store_true', help='Apenas simular, não alterar')

    def handle(self, *args, **options):
        mes = options['mes']
        if len(mes) != 7 or mes[4] != '-':
            self.stdout.write(self.style.ERROR('Use: python manage.py revincular_m10_safra YYYY-MM'))
            return

        inicio, fim = parse_month(mes)
        dry_run = options.get('dry_run', False)

        status_instalada = StatusCRM.objects.filter(tipo='Esteira', nome__iexact='INSTALADA').first()
        if not status_instalada:
            self.stdout.write(self.style.ERROR('Status INSTALADA não encontrado.'))
            return

        contratos = ContratoM10.objects.filter(
            data_instalacao__gte=inicio,
            data_instalacao__lt=fim,
        ).exclude(ordem_servico__isnull=True).exclude(ordem_servico='')

        atualizados = 0
        for c in contratos:
            vendas = list(
                Venda.objects.filter(
                    ativo=True,
                    status_esteira=status_instalada,
                    ordem_servico=c.ordem_servico,
                    data_instalacao__gte=inicio,
                    data_instalacao__lt=fim,
                ).order_by('data_criacao')
            )
            if len(vendas) < 2:
                continue
            # Preferir a com data_criacao mais antiga
            venda_mais_antiga = vendas[0]
            if c.venda_id != venda_mais_antiga.id:
                if not dry_run:
                    c.venda = venda_mais_antiga
                    c.save(update_fields=['venda'])
                self.stdout.write(
                    '  OS {}: venda {} -> {} (data_criacao mais antiga)'.format(
                        c.ordem_servico, c.venda_id, venda_mais_antiga.id
                    )
                )
                atualizados += 1

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            'Re-vincular {}: {} contrato(s) atualizado(s){}'.format(
                mes, atualizados, ' (dry-run)' if dry_run else ''
            )
        ))
