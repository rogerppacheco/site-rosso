# crm_app/management/commands/processar_fila_boas_vindas.py
"""
Processa a fila de envio de boas-vindas.
O scheduler chama a cada 5 min. Envia todas as mensagens cujo agendado_para <= agora.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from crm_app.models import FilaEnvioBoasVindas
from crm_app.services.boas_vindas_envio_service import enviar_boas_vindas_venda

logger = __import__('logging').getLogger(__name__)


class Command(BaseCommand):
    help = 'Processa a fila de boas-vindas: envia mensagens cujo horário já passou'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Apenas lista o que seria enviado')
        parser.add_argument('--limite', type=int, default=10, help='Máximo de envios por execução (default 10)')

    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)
        limite = options.get('limite', 10)
        agora = timezone.now()

        pendentes = list(
            FilaEnvioBoasVindas.objects.filter(
                enviado_em__isnull=True,
                agendado_para__lte=agora,
            ).select_related('venda__cliente', 'criado_por')[:limite]
        )

        if not pendentes:
            if not dry_run:
                logger.debug("[BoasVindas] Nenhum envio pendente na fila.")
            return

        self.stdout.write(f"[BoasVindas] {len(pendentes)} envio(s) na fila para processar")

        if dry_run:
            for f in pendentes:
                self.stdout.write(f"  - Venda #{f.venda_id} agendado para {f.agendado_para}")
            return

        enviados = 0
        erros = 0
        for f in pendentes:
            v = f.venda
            if not v.telefone1:
                f.erro = "Telefone não informado"
                f.save(update_fields=['erro'])
                erros += 1
                continue
            try:
                res = enviar_boas_vindas_venda(v, usuario=f.criado_por)
                if res.get('enviado') or (
                    res.get('ok') and 'já enviad' in (res.get('detail') or '').lower()
                ):
                    f.enviado_em = timezone.now()
                    f.erro = None
                    f.save(update_fields=['enviado_em', 'erro'])
                    enviados += 1
                    self.stdout.write(self.style.SUCCESS(
                        f"  ✓ Venda #{v.id} ({res.get('canal') or res.get('detail')})"
                    ))
                else:
                    f.erro = (res.get('detail') or 'Falha ao enviar')[:500]
                    f.save(update_fields=['erro'])
                    erros += 1
            except Exception as e:
                f.erro = str(e)[:500]
                f.save(update_fields=['erro'])
                erros += 1
                self.stdout.write(self.style.ERROR(f"  ✗ Venda #{v.id}: {e}"))

        self.stdout.write(self.style.SUCCESS(f"\n[BoasVindas] Concluído: {enviados} enviados, {erros} erros"))
