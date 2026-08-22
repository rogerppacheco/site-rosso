"""
Diagnóstico: lista registros PapConfirmacaoCliente no banco.
Use para verificar se o resumo foi registrado e se o webhook marcou confirmado.
"""
from django.core.management.base import BaseCommand

from crm_app.models import PapConfirmacaoCliente


class Command(BaseCommand):
    help = "Lista PapConfirmacaoCliente para diagnóstico (resumo enviado, Sim do cliente)"

    def add_arguments(self, parser):
        parser.add_argument("--celular", type=str, help="Filtrar por celular (ex: 31991449649)")

    def handle(self, *args, **options):
        qs = PapConfirmacaoCliente.objects.all().order_by("-criado_em")[:20]
        cel = (options.get("celular") or "").strip()
        if cel:
            cel_limpo = "".join(filter(str.isdigit, cel))
            qs = PapConfirmacaoCliente.objects.filter(
                celular_cliente__icontains=cel_limpo[-11:]
            ).order_by("-criado_em")

        self.stdout.write(f"\nPapConfirmacaoCliente (últimos 20):\n" + "-" * 50)
        if not qs.exists():
            self.stdout.write(self.style.WARNING("  Nenhum registro encontrado."))
            self.stdout.write(
                "\n  Possíveis causas:\n"
                "  - O resumo ainda não foi enviado (terminal não chegou na etapa 11)\n"
                "  - O webhook não está recebendo mensagens (verifique URL no painel Z-API)\n"
            )
            return

        for r in qs:
            status = "✅ confirmado" if r.confirmado else "⏳ pendente"
            self.stdout.write(
                f"  {r.celular_cliente} | {status} | {r.criado_em.strftime('%Y-%m-%d %H:%M:%S')}"
            )

        self.stdout.write("-" * 50)
        self.stdout.write(
            f"\n  Se confirmado=pendente mas o cliente já respondeu Sim:\n"
            "  → O webhook provavelmente não recebeu a mensagem.\n"
            "  → Verifique se a URL do webhook no painel Z-API aponta para o servidor correto.\n"
            "  → Em ambiente local (runserver): Z-API precisa de URL pública (ngrok, etc.).\n"
        )
