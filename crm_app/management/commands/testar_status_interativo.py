# crm_app/management/commands/testar_status_interativo.py
"""
Teste interativo do fluxo STATUS (consulta CRM + PAP Consulta OS).

Ao abrir, o fluxo STATUS já é iniciado (equivalente a digitar STATUS no WhatsApp).
A consulta online no PAP roda em thread; use PAP_HEADLESS=false para ver o navegador.

Comandos especiais:
  /etapa   - Mostra etapa e dados atuais
  /reset   - Reinicia e abre STATUS de novo
  /sair    - Encerra o teste
  /log     - Mostra falhas mapeadas na sessão

Uso:
  $env:PAP_HEADLESS="false"
  python manage.py testar_status_interativo --telefone 21979630377
"""
from unittest.mock import patch

from django.core.management.base import BaseCommand

_mensagens_async = []

_DICA_POR_ETAPA = {
    "inicial": "comando perdido — use /reset para reabrir STATUS",
    "status_tipo": "digite 1 (CPF) ou 2 (O.S.)",
    "status_cpf": "digite o CPF (apenas números)",
    "status_os": "digite o número da O.S.",
    "status_aguardando_online": "aguarde o PAP (Enter vazio atualiza)",
}


def _mock_enviar_texto(telefone, mensagem, **kwargs):
    if mensagem:
        _mensagens_async.append(mensagem)
    return True, "mock"


def _mock_enviar_imagem(telefone, img_b64, caption="", **kwargs):
    legenda = (caption or "").strip() or "(sem legenda)"
    _mensagens_async.append(f"📷 [imagem enviada]\n{legenda}")
    return True, "mock"


class Command(BaseCommand):
    help = "Teste interativo do comando STATUS (CRM + consulta OS no PAP)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--telefone",
            type=str,
            default=None,
            help="Telefone do vendedor (ex: 5521979630377). Obrigatório se não houver no banco.",
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
                u = (
                    Usuario.objects.exclude(tel_whatsapp__isnull=True)
                    .exclude(tel_whatsapp="")
                    .first()
                )
                if u:
                    telefone = u.tel_whatsapp
                    self.stdout.write(f"Usando telefone: {u.username} -> {telefone}")
            except Exception:
                pass
        if not telefone:
            self.stdout.write(
                self.style.ERROR("Informe --telefone ou cadastre um usuário com tel_whatsapp.")
            )
            return

        telefone_raw = "".join(filter(str.isdigit, str(telefone)))
        if not telefone_raw.startswith("55") and len(telefone_raw) >= 10:
            telefone_raw = "55" + telefone_raw
        telefone_formatado = formatar_telefone(telefone_raw)

        falhas = []

        def exibir_mensagens_async():
            while _mensagens_async:
                msg = _mensagens_async.pop(0)
                self.stdout.write("\n" + "-" * 50)
                self.stdout.write("Bot:")
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

        def dica_etapa(etapa):
            return _DICA_POR_ETAPA.get(etapa, "siga as instruções do bot")

        pap_headless = __import__("os").environ.get("PAP_HEADLESS", "true").lower()
        visivel = pap_headless in ("0", "false", "no")

        self.stdout.write(self.style.SUCCESS("\n" + "=" * 60))
        self.stdout.write("  TESTE INTERATIVO STATUS")
        self.stdout.write("  O fluxo STATUS abre automaticamente ao iniciar.")
        self.stdout.write("  Comandos: /etapa | /reset | /sair | /log")
        if visivel:
            self.stdout.write(self.style.WARNING("  PAP_HEADLESS=false → navegador visível no login PAP"))
        else:
            self.stdout.write(
                self.style.WARNING('  Dica: $env:PAP_HEADLESS="false" para ver o PAP')
            )
        self.stdout.write("=" * 60 + "\n")

        def _ia_desligada(*args, **kwargs):
            return None

        def processar_entrada(entrada, etapa_antes):
            resultado = processar_webhook_whatsapp(payload(entrada))
            exibir_mensagens_async()

            if resultado.get("status") == "erro":
                err = resultado.get("mensagem", "Erro desconhecido")
                falhas.append(f"etapa={etapa_antes} | entrada='{entrada[:30]}' | erro={err[:80]}")
                self.stdout.write(self.style.ERROR(f"\n  ⚠ FALHA: {err}\n"))
                return

            resposta = (resultado.get("mensagem") or "").strip()
            if resposta and resposta != "Processado com sucesso":
                self.stdout.write("\n" + "-" * 50)
                self.stdout.write("Bot (sync):")
                for linha in resposta.split("\n"):
                    self.stdout.write(f"  {linha}")
                self.stdout.write("-" * 50 + "\n")

        def iniciar_fluxo_status():
            resetar()
            self.stdout.write(self.style.HTTP_INFO("\n  → Abrindo fluxo STATUS (como no WhatsApp)...\n"))
            processar_entrada("STATUS", "inicial")

        def _ia_desligada_fn(*args, **kwargs):
            return None

        with patch("crm_app.whatsapp_service.WhatsAppService") as MockWa, patch(
            "crm_app.ai_chat_service.responder_com_ia", side_effect=_ia_desligada_fn
        ):
            inst = MockWa.return_value
            inst.enviar_mensagem_texto.side_effect = _mock_enviar_texto
            inst.enviar_imagem_b64.side_effect = _mock_enviar_imagem

            iniciar_fluxo_status()

            while True:
                etapa, dados = obter_estado()
                self.stdout.write(self.style.HTTP_INFO(f"\n  [etapa: {etapa}] — próximo: {dica_etapa(etapa)}"))
                if etapa == "status_aguardando_online":
                    self.stdout.write(
                        self.style.WARNING("  (PAP em andamento — Enter vazio para ver novas mensagens)")
                    )
                try:
                    entrada = input("Você: ").strip()
                except (EOFError, KeyboardInterrupt):
                    self.stdout.write("\n")
                    break

                if not entrada:
                    exibir_mensagens_async()
                    continue

                cmd = entrada.upper()
                if cmd.startswith("/ETAPA"):
                    self.stdout.write(f"  Etapa: {etapa}")
                    if dados:
                        for k, v in list(dados.items())[:15]:
                            val = str(v)[:50] + "..." if len(str(v)) > 50 else v
                            self.stdout.write(f"    {k}: {val}")
                    continue

                if cmd.startswith("/RESET"):
                    iniciar_fluxo_status()
                    continue

                if cmd.startswith("/SAIR"):
                    break

                if cmd.startswith("/LOG"):
                    if falhas:
                        for i, f in enumerate(falhas, 1):
                            self.stdout.write(f"  {i}. {f}")
                    else:
                        self.stdout.write("  Nenhuma falha registrada.")
                    continue

                # Atalho: 1/2 na etapa inicial reinicia STATUS e aplica a opção
                if etapa == "inicial" and entrada in ("1", "2"):
                    self.stdout.write(
                        self.style.WARNING(
                            "  (você digitou só a opção — reiniciando STATUS e aplicando…)\n"
                        )
                    )
                    iniciar_fluxo_status()
                    etapa, _ = obter_estado()
                    if etapa != "status_tipo":
                        continue
                    processar_entrada(entrada, etapa)
                    continue

                processar_entrada(entrada, etapa)

        exibir_mensagens_async()
        resetar()
        self.stdout.write(self.style.SUCCESS("\nTeste encerrado."))
        if falhas:
            self.stdout.write(self.style.WARNING(f"Falhas mapeadas: {len(falhas)}"))
            for f in falhas:
                self.stdout.write(f"  - {f[:100]}")
