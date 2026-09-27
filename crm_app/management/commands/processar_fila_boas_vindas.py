# crm_app/management/commands/processar_fila_boas_vindas.py
"""
Processa a fila de envio de boas-vindas.
O scheduler chama a cada 5 min. Envia todas as mensagens cujo agendado_para <= agora.
"""
import random
from datetime import datetime
from django.core.management.base import BaseCommand
from django.conf import settings
from django.utils import timezone
from crm_app.models import Venda, BoasVindasEnviado, FilaEnvioBoasVindas
from crm_app.whatsapp_service import WhatsAppService

logger = __import__('logging').getLogger(__name__)


def _normalizar_telefone_chave(telefone):
    import re
    if not telefone:
        return ""
    tel = re.sub(r'\D', '', str(telefone))
    if tel.startswith('55') and len(tel) > 12:
        tel = tel[2:]
    return tel


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

        svc = WhatsAppService()
        primeiro_nome = "Especialista"
        saudacao = 'boa tarde' if agora.hour >= 12 else 'bom dia'
        despedida = 'boa tarde!' if agora.hour >= 12 else 'bom dia!'

        msg_base = (
            f"Olá {saudacao}, {{nome_cliente}} tudo bem?\n\n"
            f"Me chamo {primeiro_nome}, sou especialista de qualidade da {settings.SITE_BRAND_NAME}, parceiro Oficial da Nio Fibra.\n\n"
            "Estou entrando em contato para informar que estamos à sua disposição, caso você precise tirar dúvidas sobre seu plano e faturas.\n\n"
            "Sua primeira fatura irá vencer 25 dias após a instalação.\n\n"
            "Você também pode acompanhar sua conta através do app Nio.\n"
            "Instale o aplicativo no seu aparelho celular.\n\n"
            "Disponível para Android e iOS:\n"
            "Google Play Store (Android)\n"
            "https://play.google.com/store/apps/details?id=br.com.niointernet.app\n\n"
            "Apple Store (iOS):\n"
            "https://apps.apple.com/br/app/nio-internet/id6746278488\n\n"
            "Você ainda pode realizar contato pelos canais de comunicação oficiais da Nio:\n"
            "SAC:0800 001 1000\n"
            "WhatsApp: 21-3605-1000\n\n"
            f"Obrigado e tenha um {despedida}"
        )

        enviados = 0
        erros = 0
        for f in pendentes:
            v = f.venda
            if not v.telefone1:
                f.erro = "Telefone não informado"
                f.save(update_fields=['erro'])
                erros += 1
                continue
            nome_cliente = (v.cliente.nome_razao_social if v.cliente else '').strip() or 'Cliente'
            mensagem = msg_base.format(nome_cliente=nome_cliente)
            try:
                ok, _ = svc.enviar_mensagem_texto(v.telefone1, mensagem)
                if ok:
                    v.boas_vindas_enviado_em = timezone.now()
                    v.save(update_fields=['boas_vindas_enviado_em'])
                    tel_chave = _normalizar_telefone_chave(v.telefone1)
                    if tel_chave:
                        BoasVindasEnviado.objects.create(telefone=tel_chave, venda=v)
                    f.enviado_em = timezone.now()
                    f.erro = None
                    f.save(update_fields=['enviado_em', 'erro'])
                    enviados += 1
                    self.stdout.write(self.style.SUCCESS(f"  ✓ Venda #{v.id} enviada"))
                else:
                    f.erro = "Falha ao enviar (API)"
                    f.save(update_fields=['erro'])
                    erros += 1
            except Exception as e:
                f.erro = str(e)[:500]
                f.save(update_fields=['erro'])
                erros += 1
                self.stdout.write(self.style.ERROR(f"  ✗ Venda #{v.id}: {e}"))

        self.stdout.write(self.style.SUCCESS(f"\n[BoasVindas] Concluído: {enviados} enviados, {erros} erros"))
