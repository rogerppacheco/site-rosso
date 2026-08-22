# crm_app/management/commands/testar_credito_lista_vendedores_pap.py
"""
Debug local: login PAP + etapa 1 + listagem de vendedores do dropdown (fluxo CRÉDITO).

Uso:
  python manage.py testar_credito_lista_vendedores_pap
  python manage.py testar_credito_lista_vendedores_pap --slow-mo 500 --selecionar
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Testa listagem de vendedores no dropdown PAP (navegador visível, fluxo crédito)"

    def add_arguments(self, parser):
        parser.add_argument("--matricula-bo", type=str, help="Matrícula BO (login PAP)")
        parser.add_argument("--senha-bo", type=str, help="Senha BO")
        parser.add_argument(
            "--slow-mo",
            type=int,
            default=400,
            help="Pausa em ms entre ações Playwright (padrão 400)",
        )
        parser.add_argument(
            "--selecionar",
            action="store_true",
            help="Após listar, escolhe TT via controle_tts e conclui etapa 1",
        )

    def handle(self, *args, **options):
        import django

        django.setup()

        from django.conf import settings
        from usuarios.models import Usuario
        from crm_app.controle_tts_service import obter_matricula_tt_para_credito_pap
        from crm_app.services_pap_nio import PAPNioAutomation

        matricula_bo = options.get("matricula_bo")
        senha_bo = options.get("senha_bo")
        if not matricula_bo or not senha_bo:
            bo = (
                Usuario.objects.filter(
                    perfil__cod_perfil__iexact="backoffice",
                    is_active=True,
                    matricula_pap__isnull=False,
                )
                .exclude(matricula_pap="")
                .exclude(senha_pap__isnull=True)
                .exclude(senha_pap="")
                .first()
            )
            if bo:
                matricula_bo = matricula_bo or bo.matricula_pap
                senha_bo = senha_bo or bo.senha_pap
                self.stdout.write(f"BO: {bo.username} ({matricula_bo})")

        if not matricula_bo or not senha_bo:
            self.stdout.write(self.style.ERROR("Informe --matricula-bo e --senha-bo"))
            return

        pap = PAPNioAutomation(
            matricula_pap=matricula_bo,
            senha_pap=senha_bo,
            vendedor_nome="Debug-Credito",
            headless=False,
            slow_mo=options.get("slow_mo"),
            run_id=f"debug_lista_{int(__import__('time').time())}",
        )
        pap.optimize_for_credit = getattr(settings, "PAP_CREDITO_FAST_MODE", True)

        self.stdout.write(self.style.SUCCESS("\n=== DEBUG: lista vendedores PAP (crédito) ===\n"))

        try:
            ok, msg = pap.iniciar_sessao()
            if not ok:
                self.stdout.write(self.style.ERROR(f"Login falhou: {msg}"))
                return
            self.stdout.write(self.style.SUCCESS("Login OK"))

            ok_prep, msg_prep = pap._preparar_novo_pedido_etapa1()
            if not ok_prep:
                self.stdout.write(self.style.ERROR(f"Preparar etapa 1 falhou: {msg_prep}"))
                return
            self.stdout.write(self.style.SUCCESS("Etapa 1 preparada — campo vendedor visível"))

            input("\n>>> ENTER para listar vendedores no dropdown (observe o navegador)... ")

            lista = pap.listar_matriculas_vendedor_no_pap()
            if not lista:
                pap._cache_matriculas_pap_dropdown = []
                lista = pap.listar_matriculas_vendedor_no_pap(forcar_recarga=True)

            if lista:
                self.stdout.write(self.style.SUCCESS(f"\n{len(lista)} matrícula(s) encontrada(s):"))
                for i, mat in enumerate(lista[:20], 1):
                    self.stdout.write(f"  {i:2}. {mat}")
                if len(lista) > 20:
                    self.stdout.write(f"  ... e mais {len(lista) - 20}")
            else:
                self.stdout.write(self.style.ERROR("\nNenhuma matrícula no dropdown."))

            if options.get("selecionar") and lista:
                from crm_app.whatsapp_webhook_handler import _run_orm_returning

                mat = _run_orm_returning(
                    lambda fb=matricula_bo, cand=list(lista): obter_matricula_tt_para_credito_pap(
                        fb,
                        candidatos=cand,
                    )
                )
                self.stdout.write(self.style.HTTP_INFO(f"\nTT escolhido (distribuição): {mat}"))
                input(">>> ENTER para selecionar vendedor e avançar etapa 1... ")
                ok_conc, msg_conc = pap._concluir_novo_pedido_etapa1(mat)
                if ok_conc:
                    self.stdout.write(self.style.SUCCESS(f"Etapa 1 concluída com {mat}"))
                else:
                    self.stdout.write(self.style.ERROR(f"Falha ao concluir: {msg_conc}"))

            input("\n>>> ENTER para fechar o navegador... ")
        finally:
            try:
                pap._fechar_sessao()
            except Exception:
                pass
