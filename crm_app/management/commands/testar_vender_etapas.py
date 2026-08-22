# crm_app/management/commands/testar_vender_etapas.py
"""
Teste local da automação VENDER, etapa por etapa.

Uso:
  python manage.py testar_vender_etapas

  Ou com telefone específico (deve estar em Usuario.tel_whatsapp de um vendedor autorizado):
  python manage.py testar_vender_etapas --telefone 5511999999999

O comando simula mensagens do WhatsApp sem enviar mensagens reais.
As respostas são exibidas no terminal.
"""
import os
import sys
from unittest.mock import patch

from django.core.management.base import BaseCommand
from django.conf import settings


def _mock_enviar_mensagem_texto(telefone, mensagem, **kwargs):
    """Substitui envio real por print no terminal."""
    print("\n" + "=" * 60)
    print("📤 [BOT RESPONDE]")
    print("=" * 60)
    # Quebrar mensagens longas para leitura
    for linha in (mensagem or "").split("\n"):
        print(linha)
    print("=" * 60 + "\n")


class Command(BaseCommand):
    help = "Testa o fluxo VENDER localmente, etapa por etapa, sem enviar WhatsApp real"

    def add_arguments(self, parser):
        parser.add_argument(
            "--telefone",
            type=str,
            default=None,
            help="Telefone do vendedor (ex: 5511999999999). Deve estar em Usuario.tel_whatsapp",
        )
        parser.add_argument(
            "--auto",
            action="store_true",
            help="Usa dados de teste automáticos em vez de pedir input",
        )

    def handle(self, *args, **options):
        telefone = options.get("telefone")
        auto = options.get("auto")

        # Garantir que Django está carregado
        import django
        django.setup()

        from usuarios.models import Usuario
        from crm_app.whatsapp_webhook_handler import processar_webhook_whatsapp

        # Buscar telefone de teste se não informado
        if not telefone:
            try:
                usuario = Usuario.objects.filter(
                    autorizar_venda_sem_auditoria=True,
                    matricula_pap__isnull=False,
                ).exclude(matricula_pap="").exclude(tel_whatsapp__isnull=True).exclude(tel_whatsapp="").first()
                if usuario:
                    telefone = usuario.tel_whatsapp.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
                    self.stdout.write(f"Usando telefone do vendedor: {usuario.username} -> {telefone}")
                else:
                    self.stdout.write(self.style.WARNING(
                        "Nenhum vendedor com autorizar_venda_sem_auditoria encontrado."
                    ))
            except Exception as e:
                self.stdout.write(self.style.WARNING(f"Erro ao buscar vendedor: {e}"))

            if not telefone:
                self.stdout.write(self.style.ERROR(
                    "Informe --telefone 55XXXXXXXXXXX (número que está em Usuario.tel_whatsapp de um vendedor autorizado)"
                ))
                return

        # Garantir formato do telefone
        telefone = "".join(filter(str.isdigit, str(telefone)))
        if not telefone.startswith("55") and len(telefone) >= 10:
            telefone = "55" + telefone

        def payload(mensagem):
            return {
                "phone": telefone,
                "message": {"text": mensagem},
            }

        self.stdout.write(self.style.SUCCESS("\n🧪 TESTE LOCAL - Fluxo VENDER"))
        self.stdout.write(f"   Telefone: {telefone}\n")

        # Mock do WhatsApp para não enviar mensagens reais
        with patch("crm_app.whatsapp_service.WhatsAppService") as MockWhatsApp:
            mock_instance = MockWhatsApp.return_value
            mock_instance.enviar_mensagem_texto.side_effect = _mock_enviar_mensagem_texto

            etapas = [
                ("1. VENDER", "VENDER"),
                ("2. Confirmar matrícula", "SIM"),
                ("3. CEP", "01310100"),
                ("4. Número", "1000"),
                ("5. Referência", "Próximo ao mercado central"),
                ("6. CPF cliente", "12345678909"),
                ("7. Celular", "11987654321"),
                ("8. E-mail", "cliente@teste.com"),
                ("9. Forma pagamento (1/2/3)", "1"),
                ("10. Plano (1/2/3)", "3"),
                ("11. Turno (1=manhã, 2=tarde)", "1"),
                ("12. Confirmar ou Cancelar", "CANCELAR"),
            ]

            for i, (desc, msg) in enumerate(etapas):
                if not auto:
                    self.stdout.write(f"\n--- Etapa {i+1}: {desc} ---")
                    entrada = input(f"   Digite a mensagem (Enter = '{msg}'): ").strip() or msg
                else:
                    entrada = msg
                    self.stdout.write(f"\n--- Etapa {i+1}: {desc} ---")
                    self.stdout.write(f"   Enviando: {entrada}")

                resultado = processar_webhook_whatsapp(payload(entrada))

                if resultado.get("status") == "erro":
                    self.stdout.write(self.style.ERROR(f"   Erro: {resultado.get('mensagem', '')}"))
                    if not auto:
                        if input("Continuar mesmo assim? (s/N): ").strip().lower() != "s":
                            break
                    else:
                        break

                # Para referência: a resposta foi "enviada" pelo mock
                if not auto and "CANCELAR" not in desc and "Confirmar" not in desc:
                    if input("   Próxima etapa? (Enter=sim, n=sair): ").strip().lower() == "n":
                        break

        self.stdout.write(self.style.SUCCESS("\n✅ Teste finalizado.\n"))
