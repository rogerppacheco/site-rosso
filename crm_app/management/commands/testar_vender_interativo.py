# crm_app/management/commands/testar_vender_interativo.py
"""
Teste interativo do fluxo VENDER - simula WhatsApp.

Você digita UMA mensagem por vez, como no WhatsApp. O sistema processa
e mostra a resposta. Ideal para mapear falhas e melhorar o processo.

Comandos especiais:
  /etapa   - Mostra etapa e dados atuais
  /reset   - Reinicia o fluxo (volta ao início)
  /sair    - Encerra o teste
  /log     - Mostra falhas mapeadas na sessão

Uso:
  python manage.py testar_vender_interativo --telefone 5531988804000
"""
from unittest.mock import patch

from django.core.management.base import BaseCommand


# Lista para capturar mensagens enviadas por threads (ex: viabilidade)
_mensagens_async = []


def _mock_enviar(telefone, mensagem, **kwargs):
    """Substitui envio real. Guarda para exibir quando enviado por thread."""
    if mensagem:
        _mensagens_async.append(mensagem)
    return True, "mock"


class Command(BaseCommand):
    help = "Teste interativo: digite como no WhatsApp, uma mensagem por vez, para mapear falhas"

    def add_arguments(self, parser):
        parser.add_argument(
            "--telefone",
            type=str,
            default=None,
            help="Telefone do vendedor (ex: 5531988804000). Obrigatório se não houver vendedor no banco.",
        )

    def handle(self, *args, **options):
        import django
        django.setup()

        from usuarios.models import Usuario
        from crm_app.models import SessaoWhatsapp
        from crm_app.whatsapp_webhook_handler import formatar_telefone, processar_webhook_whatsapp

        telefone = options.get("telefone")
        if not telefone:
            try:
                u = Usuario.objects.filter(
                    autorizar_venda_sem_auditoria=True,
                    matricula_pap__isnull=False,
                ).exclude(tel_whatsapp__isnull=True).exclude(tel_whatsapp="").first()
                if u:
                    telefone = u.tel_whatsapp
                    self.stdout.write(f"Usando telefone: {u.username} -> {telefone}")
            except Exception:
                pass
        if not telefone:
            self.stdout.write(self.style.ERROR("Informe --telefone ou cadastre um vendedor com tel_whatsapp."))
            return

        telefone_raw = "".join(filter(str.isdigit, str(telefone)))
        if not telefone_raw.startswith("55") and len(telefone_raw) >= 10:
            telefone_raw = "55" + telefone_raw
        telefone_formatado = formatar_telefone(telefone_raw)

        falhas = []

        def exibir_mensagens_async():
            """Exibe mensagens que vieram de threads (ex: viabilidade)."""
            while _mensagens_async:
                msg = _mensagens_async.pop(0)
                self.stdout.write("\n" + "-" * 50)
                self.stdout.write("Bot (async):")
                for linha in (msg or "").split("\n"):
                    self.stdout.write(f"  {linha}")
                self.stdout.write("-" * 50 + "\n")

        def payload(msg):
            return {"phone": telefone_raw, "message": {"text": msg}}

        def obter_estado():
            try:
                s = SessaoWhatsapp.objects.get(telefone=telefone_formatado)
                return s.etapa, s.dados_temp or {}
            except SessaoWhatsapp.DoesNotExist:
                return "inicial", {}

        def resetar():
            try:
                from crm_app.pool_bo_pap import liberar_bo
                s = SessaoWhatsapp.objects.get(telefone=telefone_formatado)
                bo_id = (s.dados_temp or {}).get("bo_usuario_id")
                if bo_id:
                    liberar_bo(bo_id, telefone_formatado)
                s.etapa = "inicial"
                s.dados_temp = {}
                s.save()
            except SessaoWhatsapp.DoesNotExist:
                pass

        self.stdout.write(self.style.SUCCESS("\n" + "=" * 60))
        self.stdout.write("  TESTE INTERATIVO VENDER - Simula WhatsApp")
        self.stdout.write("  Digite uma mensagem por vez, como no WhatsApp.")
        self.stdout.write("  Comandos: /etapa | /reset | /sair | /log")
        self.stdout.write("")
        self.stdout.write("  Fluxo esperado: VENDER → SIM → CEP → Número → Ref → CPF → ...")
        self.stdout.write("=" * 60 + "\n")

        with patch("crm_app.whatsapp_service.WhatsAppService") as MockWa:
            MockWa.return_value.enviar_mensagem_texto.side_effect = _mock_enviar

            while True:
                exibir_mensagens_async()
                etapa, dados = obter_estado()
                self.stdout.write(self.style.HTTP_INFO(f"  [etapa: {etapa}]"))
                try:
                    entrada = input("Você: ").strip()
                except (EOFError, KeyboardInterrupt):
                    self.stdout.write("\n")
                    break

                if not entrada:
                    continue

                if entrada.upper().startswith("/ETAPA"):
                    self.stdout.write(f"  Etapa: {etapa}")
                    if dados:
                        for k, v in list(dados.items())[:15]:
                            val = str(v)[:50] + "..." if len(str(v)) > 50 else v
                            self.stdout.write(f"    {k}: {val}")
                    continue

                if entrada.upper().startswith("/RESET"):
                    resetar()
                    self.stdout.write(self.style.WARNING("  Sessão reiniciada.\n"))
                    continue

                if entrada.upper().startswith("/SAIR"):
                    break

                if entrada.upper().startswith("/LOG"):
                    if falhas:
                        for i, f in enumerate(falhas, 1):
                            self.stdout.write(f"  {i}. {f}")
                    else:
                        self.stdout.write("  Nenhuma falha registrada.")
                    continue

                resultado = processar_webhook_whatsapp(payload(entrada))

                if resultado.get("status") == "erro":
                    err = resultado.get("mensagem", "Erro desconhecido")
                    falhas.append(f"etapa={etapa} | entrada='{entrada[:30]}' | erro={err[:80]}")
                    self.stdout.write(self.style.ERROR(f"\n  ⚠ FALHA: {err}\n"))
                    continue

                resposta = resultado.get("mensagem", "")
                if resposta:
                    self.stdout.write("\n" + "-" * 50)
                    self.stdout.write("Bot:")
                    for linha in resposta.split("\n"):
                        self.stdout.write(f"  {linha}")
                    self.stdout.write("-" * 50 + "\n")

        self.stdout.write(self.style.SUCCESS("\nTeste encerrado."))
        if falhas:
            self.stdout.write(self.style.WARNING(f"Falhas mapeadas: {len(falhas)}"))
            for f in falhas:
                self.stdout.write(f"  - {f[:100]}")
