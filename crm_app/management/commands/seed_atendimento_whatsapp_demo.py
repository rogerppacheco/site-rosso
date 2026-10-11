"""Cria conversas fictícias no inbox de atendimento WhatsApp (somente banco local).

Uso:
    python manage.py seed_atendimento_whatsapp_demo
    python manage.py seed_atendimento_whatsapp_demo --limpar
"""
from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.utils import timezone

PREFIXO_DEMO = "demo-atendimento-"

CONVERSAS = (
    {
        "telefone": "11900000001",
        "descricao": "janela aberta",
        "mensagens": (
            ("SAIDA", "MODELO", 26 * 60, "Modelo: boas_vindas_exemplo\n{{1}} Maria"),
            ("ENTRADA", "SESSAO", 40, "Oi, recebi a mensagem. Quando o técnico vem?"),
            ("SAIDA", "SESSAO", 35, "Olá, Maria! A visita está agendada para amanhã, das 8h às 12h."),
            ("ENTRADA", "SESSAO", 10, "Perfeito, obrigada!"),
        ),
    },
    {
        "telefone": "21900000002",
        "descricao": "janela fechada",
        "mensagens": (
            ("SAIDA", "MODELO", 4 * 24 * 60, "Modelo: confirmacao_exemplo\n{{1}} João"),
            ("ENTRADA", "SESSAO", 3 * 24 * 60, "Pode confirmar meu endereço?"),
            ("SAIDA", "SESSAO", 3 * 24 * 60 - 20, "Claro, João. Confirmado: Rua Exemplo, 100."),
        ),
    },
    {
        "telefone": "31900000003",
        "descricao": "sem resposta do cliente",
        "mensagens": (
            ("SAIDA", "MODELO", 2 * 60, "Modelo: aviso_exemplo\n{{1}} Ana"),
        ),
    },
)


class Command(BaseCommand):
    help = "Cria conversas fictícias de atendimento WhatsApp no banco SQLite local."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limpar",
            action="store_true",
            help="Apaga apenas as conversas fictícias criadas por este comando.",
        )

    def handle(self, *args, **options):
        if connection.vendor != "sqlite":
            raise CommandError(
                "Este comando só roda no banco SQLite local. "
                f"Banco atual: {connection.vendor}."
            )

        from crm_app.models import MensagemWhatsAppAtendimento, WhatsAppTelefoneSemIa

        telefones = [c["telefone"] for c in CONVERSAS]
        MensagemWhatsAppAtendimento.objects.filter(
            message_id__startswith=PREFIXO_DEMO
        ).delete()
        WhatsAppTelefoneSemIa.objects.filter(telefone__in=telefones).delete()
        if options["limpar"]:
            self.stdout.write(self.style.SUCCESS("Conversas fictícias removidas."))
            return

        agora = timezone.now()
        total = 0
        for conversa in CONVERSAS:
            for indice, (direcao, tipo, minutos_atras, texto) in enumerate(conversa["mensagens"]):
                MensagemWhatsAppAtendimento.objects.create(
                    telefone=conversa["telefone"],
                    direcao=direcao,
                    tipo=tipo,
                    texto=texto,
                    template_name=texto.split("\n")[0].replace("Modelo: ", "") if tipo == "MODELO" else "",
                    message_id=f"{PREFIXO_DEMO}{conversa['telefone']}-{indice}",
                    origem="WEBHOOK" if direcao == "ENTRADA" else "CRM",
                    data_hora=agora - timedelta(minutes=minutos_atras),
                )
                total += 1
            self.stdout.write(f"  {conversa['telefone']}: {conversa['descricao']}")
        self.stdout.write(self.style.SUCCESS(f"{total} mensagens fictícias criadas."))
