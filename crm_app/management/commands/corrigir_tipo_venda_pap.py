"""
Management command para corrigir tipo_venda incorreto nos registros HistoricoPapPedido.
Uso: python manage.py corrigir_tipo_venda_pap
"""
from django.core.management.base import BaseCommand
from django.db.models import Count


VTAL_TO_INTERNO = {
    "VENDA": "VENDA",
    "CONCLUIDO": "VENDA",
    "concluido": "VENDA",
    "INTERESSE": "INTERESSE",
    "interesse": "INTERESSE",
    "Interesse": "INTERESSE",
    "PRE_VENDA": "PRE_VENDA",
    "PRE-VENDA": "PRE_VENDA",
    "pre_venda": "PRE_VENDA",
}


class Command(BaseCommand):
    help = "Diagnóstico e correção dos registros HistoricoPapPedido"

    def handle(self, *args, **options):
        from crm_app.models import HistoricoPapPedido
        from crm_app.historico_pap_service import map_pedido_api

        total = HistoricoPapPedido.objects.count()
        self.stdout.write(f"Total de registros na tabela: {total}")

        self.stdout.write("\nDistribuição REAL por tipo_venda:")
        for pt in HistoricoPapPedido.objects.values('tipo_venda').annotate(n=Count('id')):
            self.stdout.write(f"  tipo_venda='{pt['tipo_venda']}': {pt['n']} registros")

        vendas = HistoricoPapPedido.objects.filter(tipo_venda="VENDA")[:5]
        self.stdout.write(f"\nAmostra de 5 registros com tipo_venda='VENDA':")
        for p in vendas:
            mapped = map_pedido_api(p.payload or {}, p.tipo_venda)
            self.stdout.write(
                f"  ID={p.id} Pedido={p.numero_pedido} tipo_venda={p.tipo_venda} "
                f"mapped_pedido={mapped.get('pedido')} mapped_cliente={mapped.get('cliente')} "
                f"mapped_cpf={mapped.get('cpf')} status_primario={mapped.get('status_primario')}"
            )

        self.stdout.write(self.style.SUCCESS("Diagnóstico concluído!"))

