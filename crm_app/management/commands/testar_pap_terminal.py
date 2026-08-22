# crm_app/management/commands/testar_pap_terminal.py
"""
Teste: digite no terminal como no WhatsApp + veja cada etapa no site PAP.

O navegador fica aberto em pap.niointernet.com.br. Você digita uma
mensagem por vez no terminal e acompanha a automação executando no site.

Fluxo VENDER: VENDER → SIM → CEP → Número → Referência → CPF → Celular → Cel. sec. → E-mail
       → Pagamento (1/2/3) → [Débito: Banco, Agência, Conta, Dígito]
       → Plano (1/2/3) → Fixo (1/2) → [se Fixo=1: Portabilidade 1/2 → número → operadora]
       → Streaming (1/2) → [Streaming: opções]
       → Avançar → Biometria → CONFIRMAR (agendamento etapa 7)

Fluxo CRÉDITO (igual produção/WhatsApp): CRÉDITO → CPF ou CNPJ → [se CNPJ: CPF representante]
       → consulta automática no PAP (endereço fixo da loja, complemento 1 se o site exigir).

Comandos: /sair

Debug: use --slow-mo 800 para cliques mais lentos e --trace para gravar pap_trace_*.zip
(abrir em https://trace.playwright.dev e ver cada clique/seletor).
"""
import logging
import re
import threading
from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)


def _entrada_e_credito(entrada: str) -> bool:
    """True se o usuário pediu o fluxo de análise de crédito (CRÉDITO / CREDITO)."""
    u = (entrada or "").strip().upper().replace("É", "E")
    return u == "CREDITO"


def _salvar_pap_confirmacao_thread(celulares_registrar, protocolo_pedido=None):
    """Salva PapConfirmacaoCliente em thread separada (evita SynchronousOnlyOperation em contexto async)."""
    try:
        from crm_app.models import PapConfirmacaoCliente
        for c in celulares_registrar:
            q = PapConfirmacaoCliente.objects.filter(celular_cliente=c, confirmado=False)
            if protocolo_pedido:
                q = q.filter(protocolo_pedido=protocolo_pedido)
            q.delete()
            PapConfirmacaoCliente.objects.create(
                celular_cliente=c,
                confirmado=False,
                protocolo_pedido=protocolo_pedido or None,
            )
        logger.info(f"[PAP] PapConfirmacaoCliente registrado para {celulares_registrar} proto={protocolo_pedido!r}")
    except Exception as e:
        logger.warning(f"[PAP] Falha ao salvar PapConfirmacaoCliente em thread: {e}", exc_info=True)


def _verificar_sim_cliente_no_bd_thread(pap_dados):
    """Verifica se cliente confirmou no BD para *este* protocolo (evita SIM de venda antiga no mesmo celular)."""
    result = [False]
    def _run():
        try:
            from crm_app.whatsapp_webhook_handler import formatar_telefone
            from crm_app.models import PapConfirmacaoCliente
            cel = pap_dados.get('celular', '') or ''
            cel_sec = pap_dados.get('celular_sec', '') or ''
            celulares = [formatar_telefone(c) for c in [cel, cel_sec] if c]
            celulares = [c for c in celulares if c]
            proto = (pap_dados.get('protocolo') or '').strip()
            if not celulares:
                logger.debug("[PAP] [DEBUG] _verificar_sim: sem celulares no pedido")
                result[0] = False
                return
            if not proto:
                logger.info("[PAP] [DEBUG] _verificar_sim: sem protocolo no pedido — não usando confirmação antiga do BD")
                result[0] = False
                return
            pend = (
                PapConfirmacaoCliente.objects.filter(
                    celular_cliente__in=celulares,
                    confirmado=True,
                    protocolo_pedido=proto,
                )
                .order_by("-criado_em")
                .first()
            )
            result[0] = pend is not None
            if result[0]:
                logger.info(
                    f"[PAP] [DEBUG] Sim do cliente encontrado no BD (celular={pend.celular_cliente}, protocolo={proto})"
                )
            else:
                logger.debug(
                    f"[PAP] [DEBUG] _verificar_sim: celulares={celulares}, proto={proto}, nenhum confirmado"
                )
        except Exception as e:
            logger.warning(f"[PAP] [DEBUG] _verificar_sim exceção: {e}", exc_info=True)
            result[0] = False
    th = threading.Thread(target=_run)
    th.start()
    th.join(timeout=3)
    return result[0]


def _limpar(s):
    return re.sub(r"\D", "", s) if s else ""


class Command(BaseCommand):
    help = "Digite no terminal como WhatsApp e veja cada etapa no site PAP (navegador visível)"

    def add_arguments(self, parser):
        parser.add_argument("--matricula-bo", type=str, help="Matrícula BackOffice (login PAP)")
        parser.add_argument("--senha-bo", type=str, help="Senha BackOffice")
        parser.add_argument("--matricula-vendedor", type=str, help="Matrícula do vendedor")
        parser.add_argument(
            "--slow-mo",
            type=int,
            default=None,
            metavar="MS",
            help="Pausa em ms entre ações do Playwright (padrão 300 com navegador visível)",
        )
        parser.add_argument(
            "--trace",
            action="store_true",
            help="Grava trace Playwright em downloads/pap_trace_*.zip (trace.playwright.dev)",
        )

    def handle(self, *args, **options):
        import django
        django.setup()

        from usuarios.models import Usuario
        from crm_app.services_pap_nio import PAPNioAutomation

        def pedir(rotulo, default=""):
            p = f"  {rotulo}: " if not default else f"  {rotulo} [{default}]: "
            v = input(p).strip() or default
            return v

        matricula_bo = options.get("matricula_bo")
        senha_bo = options.get("senha_bo")
        matricula_vendedor = options.get("matricula_vendedor")
        if not all([matricula_bo, senha_bo]):
            try:
                bo = Usuario.objects.filter(
                    perfil__cod_perfil__iexact="backoffice",
                    is_active=True,
                    matricula_pap__isnull=False,
                ).exclude(matricula_pap="").exclude(senha_pap__isnull=True).exclude(senha_pap="").first()
                if bo:
                    matricula_bo = matricula_bo or bo.matricula_pap
                    senha_bo = senha_bo or bo.senha_pap
                    self.stdout.write(f"BO: {bo.username}")
            except Exception:
                pass
        if not matricula_vendedor:
            v = Usuario.objects.filter(matricula_pap__isnull=False).exclude(matricula_pap="").first()
            matricula_vendedor = v.matricula_pap if v else matricula_bo

        if not matricula_bo or not senha_bo:
            self.stdout.write(self.style.ERROR("Informe --matricula-bo e --senha-bo"))
            return

        self.stdout.write(self.style.SUCCESS("\n" + "=" * 60))
        self.stdout.write("  PAP + TERMINAL - Digite como WhatsApp, veja no site")
        self.stdout.write("  Início: *VENDER* (venda) ou *CRÉDITO* (análise de crédito). Comando: /sair")
        if options.get("trace"):
            self.stdout.write(self.style.WARNING("  Trace: ao encerrar, abra pap_trace_*.zip em https://trace.playwright.dev"))
        self.stdout.write("=" * 60 + "\n")

        pap = PAPNioAutomation(
            matricula_pap=matricula_bo,
            senha_pap=senha_bo,
            vendedor_nome="Teste",
            headless=False,
            slow_mo=options.get("slow_mo"),
            record_trace=bool(options.get("trace")),
            run_id=f"term_{int(__import__('time').time())}",
        )

        etapa_pap = -1
        credito_doc_limpo = ""
        credito_cpf_rep_limpo = ""
        cep = numero = referencia = cpf = celular = celular_sec = email = ""
        forma = "boleto"
        banco = agencia = conta = digito = ""
        tem_fixo = tem_stream = False
        fixo_port_num = ""
        streaming_opcoes = ""
        plano = "500mega"
        sim_cliente_recebido = False
        enviou_resumo_whatsapp = ""

        def responder(msg):
            self.stdout.write("\n" + "-" * 50)
            self.stdout.write("Bot:")
            for ln in (msg or "").split("\n"):
                self.stdout.write(f"  {ln}")
            self.stdout.write("-" * 50 + "\n")

        def _enviar_resumo_whatsapp_cliente():
            """Tenta enviar resumo ao cliente via Z-API. Retorna (enviou: bool, msg_extra: str)."""
            try:
                cel = pap.dados_pedido.get('celular', '')
                if not cel or len(re.sub(r'\D', '', cel)) < 10:
                    return False, ""
                from crm_app.whatsapp_service import WhatsAppService
                from crm_app.whatsapp_webhook_handler import formatar_telefone
                from crm_app.models import PapConfirmacaoCliente
                svc = WhatsAppService()
                resumo = pap.obter_resumo_pedido_para_cliente()
                proto = (pap.dados_pedido.get("protocolo") or "").strip()
                texto_extra = "\n\nPara confirmar, toque no botão *SIM* ou responda *SIM*."
                ok, _ = svc.enviar_resumo_pap_com_botao_confirmar(cel, resumo, texto_extra=texto_extra)
                if not ok:
                    ok, _ = svc.enviar_mensagem_texto(cel, f"{resumo}\n\nPara confirmar, responda *SIM*.")
                if ok:
                    m = re.sub(r'\D', '', cel)
                    mask = f"({m[-11:-9]}) {m[-9:-4]}-{m[-4:]}" if len(m) >= 11 else cel[:6] + "****"
                    msg_ok = f"\n📤 Resumo enviado via API WhatsApp para o cliente ({mask}). Aguardando confirmação (sim)."
                    try:
                        cel_norm = formatar_telefone(cel)
                        cel_sec = pap.dados_pedido.get('celular_sec', '') or ''
                        cel_sec_norm = formatar_telefone(cel_sec) if cel_sec else ''
                        celulares_registrar = [cel_norm] if cel_norm else []
                        if cel_sec_norm and cel_sec_norm != cel_norm:
                            celulares_registrar.append(cel_sec_norm)
                        if celulares_registrar:
                            th = threading.Thread(
                                target=_salvar_pap_confirmacao_thread,
                                args=(celulares_registrar, proto or None),
                            )
                            th.start()
                            th.join(timeout=5)
                    except Exception as e:
                        logger.warning(f"[PAP] Falha ao salvar PapConfirmacaoCliente (resumo foi enviado): {e}", exc_info=True)
                    return True, msg_ok
            except Exception as e:
                logger.warning(f"[PAP] Falha ao enviar resumo WhatsApp: {e}", exc_info=True)
            return False, ""

        def _msg_resumo_biometria(resumo, biometria_ok, sim_ok, enviou_whatsapp="", apenas_status=False):
            """Se apenas_status=True, não inclui o resumo (para CONSULTAR - evita repetir resumo ao vendedor)."""
            status_bio = "✅ Aprovada" if biometria_ok else "⏳ Pendente"
            status_sim = "✅ Recebido" if sim_ok else "⏳ Aguardando"
            parte_resumo = "" if apenas_status else (f"{resumo}\n\n{enviou_whatsapp}")
            return (
                f"{parte_resumo}"
                f"*Status:*\n"
                f"  Biometria: {status_bio}\n"
                f"  Sim do cliente: {status_sim}\n\n"
                "Digite *SIM* ou *CONFIRMAR* quando receber o sim do cliente.\n"
                "Digite *CONSULTAR* para verificar biometria e validar."
            )

        def credito_etapa3_e4():
            """Cadastro documento + contato/análise de crédito (após viabilidade ok). Retorna (código, detalhe, meta)."""
            from crm_app.credito_utils import gerar_celular_random, gerar_email_credito

            doc = credito_doc_limpo
            rep = credito_cpf_rep_limpo if len(doc) == 14 else None
            sucesso, msg, _ = pap.etapa3_cadastro_cliente(doc, cpf_representante=rep)
            if not sucesso:
                try:
                    pap._fechar_sessao()
                except Exception:
                    pass
                return "erro", msg, None

            cel = gerar_celular_random()
            cel_sec = gerar_celular_random()
            email = gerar_email_credito()
            ultimo_msg = ""
            for _t in range(5):
                sucesso, msg, resultado_credito, _shot = pap.etapa4_contato(
                    cel,
                    email,
                    celular_secundario=cel_sec,
                    parar_no_modal_credito=True,
                )
                ultimo_msg = msg
                if sucesso:
                    pap._fechar_sessao()
                    return (
                        "aprovado",
                        resultado_credito or "Elegível para formas de pagamento disponíveis.",
                        None,
                    )
                if msg in ("TELEFONE_REJEITADO", "CELULAR_INVALIDO"):
                    cel = gerar_celular_random()
                    cel_sec = gerar_celular_random()
                    continue
                if msg in ("EMAIL_REJEITADO", "EMAIL_INVALIDO"):
                    email = gerar_email_credito()
                    continue
                if msg == "CREDITO_NEGADO":
                    pap._fechar_sessao()
                    return "negado", "", None
                pap._fechar_sessao()
                return "erro", msg, None

            pap._fechar_sessao()
            return "erro", ultimo_msg or "Falha após várias tentativas.", None

        def executar_credito_terminal():
            """Login → pedido (fluxo produção) → viabilidade fixa CRÉDITO."""
            from django.conf import settings
            from crm_app.controle_tts_service import obter_matricula_tt_para_credito_pap
            from crm_app.whatsapp_webhook_handler import (
                CREDITO_CEP_FIXO,
                CREDITO_ENDERECO_ALVO,
                CREDITO_NUMERO_FIXO,
                CREDITO_REFERENCIA_FIXA,
                _run_orm_returning,
            )

            pap.optimize_for_credit = getattr(settings, "PAP_CREDITO_FAST_MODE", True)
            sucesso, msg = pap.iniciar_sessao()
            if not sucesso:
                try:
                    pap._fechar_sessao()
                except Exception:
                    pass
                return "erro", f"Erro ao acessar PAP: {msg}", None

            ok_prep, msg_prep = pap._preparar_novo_pedido_etapa1()
            if not ok_prep:
                pap._fechar_sessao()
                return "erro", f"Erro ao preparar pedido: {msg_prep}", None

            matriculas_pap = pap.listar_matriculas_vendedor_no_pap()
            if not matriculas_pap:
                pap._cache_matriculas_pap_dropdown = []
                matriculas_pap = pap.listar_matriculas_vendedor_no_pap(forcar_recarga=True)
            if not matriculas_pap:
                pap._fechar_sessao()
                return "erro", "Não foi possível carregar os vendedores deste PDV no PAP.", None

            matricula_escolhida = _run_orm_returning(
                lambda fb=matricula_vendedor or matricula_bo, cand=list(matriculas_pap): obter_matricula_tt_para_credito_pap(
                    fb,
                    candidatos=cand,
                )
            )
            self.stdout.write(
                self.style.HTTP_INFO(
                    f"  [CRÉDITO] TT escolhido: {matricula_escolhida} "
                    f"(de {len(matriculas_pap)} no PDV)"
                )
            )
            sucesso, msg = pap._concluir_novo_pedido_etapa1(matricula_escolhida)
            if not sucesso:
                pap._fechar_sessao()
                return "erro", f"Erro ao iniciar pedido: {msg}", None

            ok_tela, msg_tela = pap.validar_tela_pronta_para_cep()
            if not ok_tela:
                pap._fechar_sessao()
                return "erro", f"Página não pronta: {msg_tela}", None

            cep_f = CREDITO_CEP_FIXO
            numero_f = CREDITO_NUMERO_FIXO
            ref_f = CREDITO_REFERENCIA_FIXA
            sucesso, msg, extra = pap.etapa2_viabilidade(cep_f, numero_f, ref_f)

            if isinstance(extra, dict) and extra.get("_codigo") == "COMPLEMENTOS":
                sucesso, msg, extra = pap.etapa2_credito_selecionar_complemento_e_avancar(cep_f, numero_f, 1)

            if not sucesso:
                if isinstance(extra, dict) and extra.get("_codigo") == "MULTIPLOS_ENDERECOS":
                    lista = extra.get("lista", [])
                    idx = 1
                    for item in lista:
                        txt = (item.get("texto") or "").upper()
                        if CREDITO_ENDERECO_ALVO.upper() in txt and numero_f in txt:
                            idx = item.get("indice", 1)
                            break
                    ok_sel, _ = pap.etapa2_selecionar_endereco_instalacao(idx)
                    if ok_sel:
                        sucesso, msg, extra = pap.etapa2_preencher_referencia_e_continuar(cep_f, numero_f, ref_f)
                        if isinstance(extra, dict) and extra.get("_codigo") == "COMPLEMENTOS":
                            sucesso, msg, extra = pap.etapa2_credito_selecionar_complemento_e_avancar(
                                cep_f, numero_f, 1
                            )
                if not sucesso:
                    pap._fechar_sessao()
                    return "erro", msg, None

            return credito_etapa3_e4()

        try:
            while True:
                self.stdout.write(self.style.HTTP_INFO(f"  [PAP etapa: {etapa_pap}]"))
                try:
                    entrada = input("Você: ").strip()
                except (EOFError, KeyboardInterrupt):
                    break

                if not entrada:
                    continue

                ent_norm = entrada.strip().upper()
                if etapa_pap == 0 and ent_norm in ("CANCELAR", "SAIR"):
                    responder("Cancelado.")
                    etapa_pap = -1
                    continue
                if etapa_pap in (100, 101) and ent_norm == "CANCELAR":
                    credito_doc_limpo = ""
                    credito_cpf_rep_limpo = ""
                    responder("Ok. Digite *VENDER* ou *CRÉDITO* para iniciar.")
                    etapa_pap = -1
                    continue

                if ent_norm in ["/SAIR", "SAIR", "CANCELAR"]:
                    if etapa_pap >= 0:
                        try:
                            pap._fechar_sessao()
                        except Exception:
                            pass
                    break

                if etapa_pap == -1:
                    if entrada.upper() in ["VENDER", "VENDA", "NOVA VENDA"]:
                        responder(
                            "🛒 NOVA VENDA - PAP NIO\n\n"
                            "Matrícula vendedor: " + matricula_vendedor + "\n\n"
                            "Confirma? Digite SIM para continuar ou CANCELAR."
                        )
                        etapa_pap = 0
                    elif _entrada_e_credito(entrada):
                        responder(
                            "🔍 *ANÁLISE DE CRÉDITO* (mesmo fluxo do WhatsApp)\n\n"
                            "Digite o *CPF* (11 dígitos) ou *CNPJ* (14 dígitos), só números.\n"
                            "Se for CNPJ, na próxima mensagem pedirei o CPF do representante legal.\n\n"
                            "*CANCELAR* — voltar ao menu."
                        )
                        etapa_pap = 100
                    else:
                        responder("Digite *VENDER* (venda completa) ou *CRÉDITO* (análise de crédito).")
                    continue

                if etapa_pap == 100:
                    from crm_app.cadastro_venda_whatsapp import validar_cpf_ou_cnpj_whatsapp

                    doc_ok, err_val = validar_cpf_ou_cnpj_whatsapp(entrada)
                    if err_val or not doc_ok:
                        responder(f"❌ {err_val or 'Documento inválido.'}\nDigite CPF (11) ou CNPJ (14) ou *CANCELAR*.")
                        continue
                    credito_doc_limpo = doc_ok
                    if len(credito_doc_limpo) == 14:
                        responder(
                            "📋 CNPJ registrado.\n\n"
                            "Digite o *CPF do representante legal* (11 dígitos, só números) ou *CANCELAR*."
                        )
                        etapa_pap = 101
                        continue

                    responder("⏳ Consultando crédito no PAP... (observe o navegador)")
                    codigo, detalhe, _ = executar_credito_terminal()
                    credito_doc_limpo = ""
                    credito_cpf_rep_limpo = ""
                    etapa_pap = -1
                    if codigo == "erro":
                        responder(f"❌ {detalhe}\n\nDigite *CRÉDITO* para tentar novamente.")
                    elif codigo == "negado":
                        responder(
                            "❌ *Crédito NEGADO* para este documento.\n\n"
                            "Digite *CRÉDITO* para tentar com outro CPF/CNPJ."
                        )
                    else:
                        responder(f"✅ *Crédito APROVADO!*\n\n{detalhe}")
                    continue

                if etapa_pap == 101:
                    cpf_r = _limpar(entrada)
                    if len(cpf_r) != 11:
                        responder("❌ CPF do representante deve ter 11 dígitos. Tente de novo ou *CANCELAR*.")
                        continue
                    from crm_app.cadastro_venda_whatsapp import validar_cpf_ou_cnpj_whatsapp

                    ok_cpf, err_cpf = validar_cpf_ou_cnpj_whatsapp(cpf_r)
                    if err_cpf or not ok_cpf or len(ok_cpf) != 11:
                        responder(f"❌ {err_cpf or 'CPF inválido.'}\nDigite novamente ou *CANCELAR*.")
                        continue
                    credito_cpf_rep_limpo = ok_cpf
                    responder("⏳ Consultando crédito no PAP... (observe o navegador)")
                    codigo, detalhe, _ = executar_credito_terminal()
                    credito_doc_limpo = ""
                    credito_cpf_rep_limpo = ""
                    etapa_pap = -1
                    if codigo == "erro":
                        responder(f"❌ {detalhe}\n\nDigite *CRÉDITO* para tentar novamente.")
                    elif codigo == "negado":
                        responder(
                            "❌ *Crédito NEGADO* para este documento.\n\n"
                            "Digite *CRÉDITO* para tentar com outro CPF/CNPJ."
                        )
                    else:
                        responder(f"✅ *Crédito APROVADO!*\n\n{detalhe}")
                    continue

                if etapa_pap == 0:
                    if entrada.upper() == "SIM":
                        sucesso, msg = pap.iniciar_sessao()
                        if not sucesso:
                            responder(f"❌ Login: {msg}")
                            continue
                        sucesso, msg = pap.iniciar_novo_pedido(matricula_vendedor)
                        if not sucesso:
                            responder(f"❌ Novo pedido: {msg}")
                            pap._fechar_sessao()
                            return
                        etapa_pap = 1
                        protocolo = pap.dados_pedido.get('protocolo', '')
                        msg_ok = "✅ Acesso OK!"
                        if protocolo:
                            msg_ok += f"\n📋 Protocolo: {protocolo}"
                        msg_ok += "\n\n📍 Digite o CEP do endereço:"
                        responder(msg_ok)
                    else:
                        responder("Digite SIM ou CANCELAR.")
                    continue

                if etapa_pap == 1:
                    cep = _limpar(entrada)
                    if len(cep) < 8:
                        responder("❌ CEP inválido. Digite 8 dígitos:")
                        continue
                    etapa_pap = 2
                    responder(f"✅ CEP: {cep}\n\nDigite o número (ou SN se sem número):")
                    continue

                if etapa_pap == 2:
                    numero = "S/N" if entrada.upper() == "SN" else entrada.strip()
                    etapa_pap = 3
                    responder(f"✅ Número: {numero}\n\nDigite a referência do endereço:")
                    continue

                if etapa_pap == 3:
                    referencia = entrada.strip()
                    if len(referencia) < 3:
                        responder("❌ Referência muito curta:")
                        continue
                    responder("⏳ Consultando viabilidade no site... (observe o navegador)")
                    sucesso, msg, extra = pap.etapa2_viabilidade(cep, numero, referencia)
                    if not sucesso:
                        if extra == "POSSE_ENCONTRADA":
                            etapa_pap = 30
                            responder(msg)
                        elif extra == "INDISPONIVEL_TECNICO":
                            etapa_pap = 31
                            responder(msg)
                        else:
                            responder(f"❌ Viabilidade: {msg}")
                        continue
                    if isinstance(extra, dict) and extra.get('_codigo') == 'MULTIPLOS_ENDERECOS':
                        etapa_pap = 24
                        lista = extra.get('lista', [])
                        linha = "\n".join(f"  {p['indice']} - {p['texto']}" for p in lista)
                        responder(
                            f"📋 *Múltiplos endereços encontrados:*\n\n{linha}\n\n"
                            "Digite o *número* do endereço desejado (ex: 1, 2):"
                        )
                        continue
                    if isinstance(extra, dict) and extra.get('_codigo') == 'COMPLEMENTOS':
                        etapa_pap = 25
                        lista = extra.get('lista', [])
                        linha = "\n".join(f"  {p['indice']} - {p['texto']}" for p in lista)
                        responder(
                            f"📋 *Complementos encontrados:*\n\n{linha}\n\n"
                            "Digite *0* ou *SEM COMPLEMENTO* se não tiver complemento,\n"
                            "ou o *número* do complemento desejado (ex: 1, 2, 3):"
                        )
                        continue
                    etapa_pap = 4
                    protocolo = pap.dados_pedido.get('protocolo', '')
                    msg_viab = "✅ Endereço disponível!"
                    if protocolo:
                        msg_viab += f"\n📋 Protocolo: {protocolo}"
                    msg_viab += "\n\n📋 Digite o CPF do cliente:"
                    responder(msg_viab)
                    continue

                if etapa_pap == 24:
                    escolha = entrada.strip()
                    if not escolha.isdigit():
                        responder("Digite o número do endereço (ex: 1, 2):")
                        continue
                    idx = int(escolha)
                    sucesso, msg = pap.etapa2_selecionar_endereco_instalacao(idx)
                    if not sucesso:
                        responder(f"❌ {msg}")
                        continue
                    sucesso2, msg2, extra2 = pap.etapa2_preencher_referencia_e_continuar(cep, numero, referencia)
                    if not sucesso2:
                        if extra2 == "POSSE_ENCONTRADA":
                            etapa_pap = 30
                            responder(msg2)
                        elif extra2 == "INDISPONIVEL_TECNICO":
                            etapa_pap = 31
                            responder(msg2)
                        else:
                            responder(f"❌ {msg2}")
                        continue
                    if isinstance(extra2, dict) and extra2.get('_codigo') == 'COMPLEMENTOS':
                        etapa_pap = 25
                        lista = extra2.get('lista', [])
                        linha = "\n".join(f"  {p['indice']} - {p['texto']}" for p in lista)
                        responder(
                            f"📋 *Complementos encontrados:*\n\n{linha}\n\n"
                            "Digite *0* ou *SEM COMPLEMENTO* se não tiver complemento,\n"
                            "ou o *número* do complemento desejado (ex: 1, 2, 3):"
                        )
                    else:
                        etapa_pap = 4
                        protocolo = pap.dados_pedido.get('protocolo', '')
                        msg_viab = "✅ Endereço disponível!"
                        if protocolo:
                            msg_viab += f"\n📋 Protocolo: {protocolo}"
                        msg_viab += "\n\n📋 Digite o CPF do cliente:"
                        responder(msg_viab)
                    continue

                if etapa_pap == 25:
                    escolha = entrada.strip().upper()
                    # Opção 1: Sem complemento (0, sem, não, nao)
                    if escolha in ("0", "SEM", "SEM COMPLEMENTO", "NAO", "NÃO", "N"):
                        sucesso, msg = pap.etapa2_selecionar_sem_complemento()
                    # Opção 2: Número do complemento (1, 2, 3...)
                    elif escolha.isdigit():
                        idx = int(escolha)
                        sucesso, msg = pap.etapa2_selecionar_complemento(idx)
                    else:
                        responder(
                            "Digite *0* ou *SEM COMPLEMENTO* se não tiver complemento,\n"
                            "ou o *número* do complemento desejado (ex: 1, 2, 3):"
                        )
                        continue
                    if sucesso:
                        sucesso2, msg2, extra2 = pap.etapa2_clicar_avancar_apos_complemento(cep, numero)
                        if sucesso2:
                            etapa_pap = 4
                            protocolo = pap.dados_pedido.get('protocolo', '')
                            msg_viab = "✅ Endereço disponível!"
                            if protocolo:
                                msg_viab += f"\n📋 Protocolo: {protocolo}"
                            msg_viab += "\n\n📋 Digite o CPF do cliente:"
                            responder(msg_viab)
                        else:
                            if extra2 == "POSSE_ENCONTRADA":
                                etapa_pap = 30
                                responder(msg2)
                            elif extra2 == "INDISPONIVEL_TECNICO":
                                etapa_pap = 31
                                responder(msg2)
                            else:
                                responder(f"❌ {msg2}")
                    else:
                        responder(
                            f"❌ {msg}\n\nDigite *0* ou *SEM COMPLEMENTO*, ou o número do complemento (ex: 1):"
                        )
                    continue

                if etapa_pap == 30:
                    if entrada.strip().upper() == "CONCLUIR":
                        pap._fechar_sessao()
                        responder("Sessão encerrada. Até logo!")
                        break
                    cep_novo = _limpar(entrada)
                    if len(cep_novo) < 8:
                        responder(
                            "❌ CEP inválido. Digite 8 dígitos para consultar outro endereço\n"
                            "ou *CONCLUIR* para sair."
                        )
                        continue
                    ok, _ = pap.etapa2_modal_posse_clicar_consultar_outro()
                    if not ok:
                        responder(f"⚠️ Erro ao voltar à consulta: {_}\n\nDigite outro CEP ou *CONCLUIR*.")
                        continue
                    cep = cep_novo
                    etapa_pap = 2
                    responder(f"✅ CEP: {cep}\n\nDigite o número (ou SN se sem número):")
                    continue

                if etapa_pap == 31:
                    if entrada.strip().upper() == "CONCLUIR":
                        pap._fechar_sessao()
                        responder("Sessão encerrada. Até logo!")
                        break
                    cep_novo = _limpar(entrada)
                    if len(cep_novo) < 8:
                        responder(
                            "❌ CEP inválido. Digite 8 dígitos para consultar outro endereço\n"
                            "ou *CONCLUIR* para sair."
                        )
                        continue
                    ok, _ = pap.etapa2_modal_indisponivel_clicar_voltar()
                    if not ok:
                        responder(f"⚠️ Erro ao voltar à consulta: {_}\n\nDigite outro CEP ou *CONCLUIR*.")
                        continue
                    cep = cep_novo
                    etapa_pap = 2
                    responder(f"✅ CEP: {cep}\n\nDigite o número (ou SN se sem número):")
                    continue

                if etapa_pap == 4:
                    cpf = _limpar(entrada)
                    if len(cpf) != 11:
                        responder("❌ CPF inválido. Digite 11 dígitos:")
                        continue
                    responder("⏳ Buscando cliente no site... (observe o navegador)")
                    sucesso, msg, _ = pap.etapa3_cadastro_cliente(cpf)
                    if not sucesso:
                        responder(f"❌ Cadastro: {msg}")
                        continue
                    etapa_pap = 5
                    responder(f"✅ {msg}\n\n📱 Digite o celular com DDD:")
                    continue

                if etapa_pap == 5:
                    celular = _limpar(entrada)
                    if len(celular) < 10:
                        responder("❌ Celular inválido:")
                        continue
                    etapa_pap = 55  # 5b = etapa celular secundário
                    responder(f"✅ Celular ok\n\n📱 Celular secundário (opcional, Enter para pular):")
                    continue

                if etapa_pap == 55:
                    celular_sec = _limpar(entrada) if entrada.strip() else ""
                    etapa_pap = 6
                    responder(f"✅ {'Celular sec. ok' if celular_sec else 'Pulado'}\n\n📧 Digite o e-mail:")
                    continue

                if etapa_pap == 6:
                    email = entrada.strip()
                    if "@" not in email or "." not in email:
                        responder("❌ E-mail inválido:")
                        continue
                    responder("⏳ Análise de crédito no site... (observe o navegador)")
                    sucesso, msg, _, _ = pap.etapa4_contato(celular, email, celular_secundario=celular_sec if celular_sec else None)
                    if not sucesso:
                        if msg in ("TELEFONE_REJEITADO", "CELULAR_INVALIDO"):
                            etapa_pap = 5
                            txt = (
                                "⚠️ O número excede repetições. Digite outro celular:"
                                if msg == "TELEFONE_REJEITADO"
                                else "⚠️ Celular inválido. Digite um número válido com DDD:"
                            )
                            responder(txt)
                        elif msg == "EMAIL_REJEITADO":
                            etapa_pap = 6
                            responder("⚠️ E-mail já usado em pedido anterior. Digite outro e-mail:")
                        elif msg == "EMAIL_INVALIDO":
                            etapa_pap = 6
                            responder("⚠️ E-mail inválido. Digite um e-mail válido:")
                        elif msg == "CREDITO_NEGADO":
                            etapa_pap = 4
                            responder(
                                "❌ Crédito negado para este CPF.\n\n"
                                "Digite outro CPF para tentar, ou CANCELAR para sair:"
                            )
                        else:
                            responder(f"❌ Crédito: {msg}")
                        continue
                    etapa_pap = 7
                    responder(
                        "✅ Crédito aprovado!\n\n"
                        "💳 Forma de pagamento: 1=Boleto 2=Cartão 3=Débito"
                    )
                    continue

                if etapa_pap == 7:
                    fp = entrada.strip()
                    forma = {"1": "boleto", "2": "cartao", "3": "debito"}.get(fp, "boleto")
                    sucesso, msg = pap.etapa5_selecionar_forma_pagamento(forma)
                    if not sucesso:
                        responder(f"❌ Forma de pagamento: {msg}")
                        continue
                    if forma == "debito":
                        etapa_pap = 71
                        bancos = "1=Itau 2=Banrisul 3=Santander 4=BB 5=Bradesco 6=Nubank"
                        responder(f"✅ Pagamento: Débito\n🏦 Banco: {bancos}\nDigite o número:")
                    else:
                        etapa_pap = 8
                        responder(f"✅ Pagamento: {forma}\n📦 Plano: 1=1Giga 2=700Mega 3=500Mega")
                    continue

                if etapa_pap == 71:
                    b_map = {"1": "Banco Itau S/A", "2": "Banrisul", "3": "Banco Santander", "4": "Banco do Brasil", "5": "Banco Bradesco", "6": "Nubank"}
                    banco = b_map.get(entrada.strip(), "Banco do Brasil")
                    etapa_pap = 72
                    responder(f"✅ Banco: {banco}\n🏦 Agência:")
                    continue

                if etapa_pap == 72:
                    agencia = entrada.strip()
                    etapa_pap = 73
                    responder("📋 Conta:")
                    continue

                if etapa_pap == 73:
                    conta = entrada.strip()
                    etapa_pap = 74
                    responder("🔢 Dígito:")
                    continue

                if etapa_pap == 74:
                    digito = entrada.strip()
                    sucesso, msg = pap.etapa5_preencher_debito(banco, agencia, conta, digito)
                    if not sucesso:
                        responder(f"❌ Débito: {msg}")
                        continue
                    etapa_pap = 8
                    responder("✅ Débito preenchido\n📦 Plano: 1=1Giga 2=700Mega 3=500Mega")
                    continue

                if etapa_pap == 8:
                    pl = entrada.strip()
                    plano = {"1": "1giga", "2": "700mega", "3": "500mega"}.get(pl, "500mega")
                    sucesso, msg = pap.etapa5_selecionar_plano_com_validacao(plano)
                    if not sucesso:
                        responder(f"❌ Plano: {msg}")
                        continue
                    etapa_pap = 81
                    responder(f"✅ Plano: {plano}\n📞 Tem Fixo (R$ 30)? 1=Sim 2=Não")
                    continue

                if etapa_pap == 81:
                    tem_fixo = entrada.strip() == "1"
                    sucesso, msg = pap.etapa5_selecionar_fixo(tem_fixo)
                    if not sucesso:
                        responder(f"❌ Fixo: {msg}")
                        continue
                    if tem_fixo:
                        etapa_pap = 811
                        responder(
                            "✅ Fixo selecionado no PAP!\n\n"
                            "📞 Portabilidade do fixo — deseja portar o número de outra operadora?\n"
                            "1=Sim 2=Não"
                        )
                    else:
                        etapa_pap = 82
                        responder("✅ Fixo: Não\n📺 Tem Streaming? 1=Sim 2=Não")
                    continue

                if etapa_pap == 811:
                    op = entrada.strip()
                    if op not in ("1", "2"):
                        responder("Digite 1 (Sim) ou 2 (Não):")
                        continue
                    if op == "2":
                        sucesso, msg = pap.etapa5_fixo_finalizar_portabilidade(False, "", "")
                        if not sucesso:
                            responder(f"❌ Portabilidade/Salvar fixo: {msg}")
                            continue
                        etapa_pap = 82
                        responder("✅ Fixo registrado (sem portabilidade)\n📺 Tem Streaming? 1=Sim 2=Não")
                    else:
                        etapa_pap = 812
                        responder("Digite o número do fixo com DDD (somente números):")
                    continue

                if etapa_pap == 812:
                    fixo_port_num = _limpar(entrada)
                    if len(fixo_port_num) < 10:
                        responder("❌ Número inválido (mín. 10 dígitos). Digite de novo:")
                        continue
                    etapa_pap = 813
                    responder("Digite o nome da operadora de origem (ex: Vivo, Claro, Vero, OI):")
                    continue

                if etapa_pap == 813:
                    op_txt = entrada.strip()
                    if len(op_txt) < 2:
                        responder("❌ Nome muito curto. Digite a operadora:")
                        continue
                    sucesso, msg = pap.etapa5_fixo_finalizar_portabilidade(
                        True, fixo_port_num, op_txt
                    )
                    if not sucesso:
                        responder(f"❌ Portabilidade/Salvar fixo: {msg}")
                        continue
                    etapa_pap = 82
                    responder("✅ Fixo e portabilidade registrados\n📺 Tem Streaming? 1=Sim 2=Não")
                    continue

                if etapa_pap == 82:
                    tem_stream = entrada.strip() == "1"
                    if tem_stream:
                        etapa_pap = 83
                        responder(
                            "✅ Streaming: Sim\n"
                            "Streaming:\n"
                            "1=HBO+Globoplay Premium 2=HBO+Globoplay Basico 3=Globoplay Basico "
                            "4=Globoplay Premium 5=HBO"
                        )
                    else:
                        sucesso, msg = pap.etapa5_selecionar_streaming(False)
                        if not sucesso:
                            responder(f"❌ Streaming: {msg}")
                            continue
                        responder("✅ Streaming: Não\n⏳ Clicando Avançar...")
                        sucesso, msg = pap.etapa5_clicar_avancar()
                        if not sucesso:
                            responder(f"❌ Avançar: {msg}")
                            continue
                        etapa_pap = 11
                        sim_cliente_recebido = False
                        responder("⏳ Verificando biometria... (observe)")
                        sucesso, msg, biometria_ok = pap.etapa6_verificar_biometria()
                        resumo = pap.obter_resumo_pedido_para_cliente()
                        if not enviou_resumo_whatsapp:
                            _, enviou_resumo_whatsapp = _enviar_resumo_whatsapp_cliente()
                            if enviou_resumo_whatsapp:
                                enviou_resumo_whatsapp += "\n"
                        responder(_msg_resumo_biometria(resumo, biometria_ok, sim_cliente_recebido, enviou_resumo_whatsapp))
                    continue

                if etapa_pap == 83:
                    st_map = {"1": "hbomax,globoplay_premium", "2": "hbomax,globoplay_basico", "3": "globoplay_basico", "4": "globoplay_premium", "5": "hbomax"}
                    streaming_opcoes = st_map.get(entrada.strip(), "")
                    sucesso, msg = pap.etapa5_selecionar_streaming(True, streaming_opcoes, plano)
                    if not sucesso:
                        responder(f"❌ Streaming: {msg}")
                        continue
                    responder("✅ Streaming ok\n⏳ Clicando Avançar...")
                    sucesso, msg = pap.etapa5_clicar_avancar()
                    if not sucesso:
                        responder(f"❌ Avançar: {msg}")
                        continue
                    etapa_pap = 11
                    sim_cliente_recebido = False
                    responder("⏳ Verificando biometria... (observe)")
                    sucesso, msg, biometria_ok = pap.etapa6_verificar_biometria()
                    resumo = pap.obter_resumo_pedido_para_cliente()
                    if not enviou_resumo_whatsapp:
                        _, enviou_resumo_whatsapp = _enviar_resumo_whatsapp_cliente()
                        if enviou_resumo_whatsapp:
                            enviou_resumo_whatsapp += "\n"
                    responder(_msg_resumo_biometria(resumo, biometria_ok, sim_cliente_recebido, enviou_resumo_whatsapp))
                    continue

                if etapa_pap == 11:
                    if not sim_cliente_recebido and _verificar_sim_cliente_no_bd_thread(pap.dados_pedido):
                        sim_cliente_recebido = True
                    if entrada.strip().upper() in ["FORCAR_SIM", "SIM_MANUAL"]:
                        sim_cliente_recebido = True
                        responder(
                            "⚠️ Confirmação do cliente marcada manualmente (*somente teste*).\n"
                            "Digite *SIM* ou *CONFIRMAR* de novo para consultar biometria e seguir."
                        )
                        continue
                    if entrada.strip().upper() in ["SIM", "CONFIRMAR", "S", "CONFIRMO"]:
                        responder("⏳ Verificando biometria... (observe)")
                        sucesso, msg, biometria_ok = pap.etapa6_verificar_biometria(consultar_primeiro=True)
                        resumo = pap.obter_resumo_pedido_para_cliente()
                        if not sim_cliente_recebido:
                            responder(
                                _msg_resumo_biometria(
                                    resumo,
                                    biometria_ok,
                                    sim_cliente_recebido,
                                    enviou_resumo_whatsapp + "\n" if enviou_resumo_whatsapp else "",
                                )
                                + "\n\n⚠️ Ainda não há *SIM do cliente* registrado (confirmação via WhatsApp). "
                                "Aguarde o cliente responder *SIM* ao resumo ou use *FORCAR_SIM* só em teste."
                            )
                            continue
                        if biometria_ok and sim_cliente_recebido:
                            etapa_pap = 12
                            sucesso, msg = pap.etapa7_ir_para_agendamento()
                            if not sucesso:
                                responder(f"❌ Agendamento: {msg}\n\nDigite *CONCLUIR* para sair.")
                            else:
                                ok, _, datas = pap.etapa7_obter_datas_disponiveis()
                                if ok and datas:
                                    responder(
                                        "✅ Biometria aprovada! Sim recebido.\n\n"
                                        "📅 *Agendamento - Selecione o dia e a hora*\n\n"
                                        f"Datas disponíveis: {', '.join(str(d) for d in datas)}\n\n"
                                        "Digite o *número do dia* para selecionar (ex: 10)\n"
                                        "ou *CONCLUIR* para sair."
                                    )
                                else:
                                    responder(
                                        "✅ Tela de Agendamento aberta.\n\n"
                                        "Digite o número do dia ou *CONCLUIR* para sair."
                                    )
                        else:
                            responder(
                                _msg_resumo_biometria(
                                    resumo,
                                    biometria_ok,
                                    sim_cliente_recebido,
                                    enviou_resumo_whatsapp + "\n" if enviou_resumo_whatsapp else "",
                                )
                                + "\n\nAguardando biometria aprovada. Digite *CONSULTAR* para verificar de novo."
                            )
                    elif entrada.strip().upper() == "CONSULTAR":
                        responder("⏳ Verificando biometria... (observe)")
                        sucesso, msg, biometria_ok = pap.etapa6_verificar_biometria(consultar_primeiro=True)
                        if biometria_ok and sim_cliente_recebido:
                            etapa_pap = 12
                            sucesso, msg = pap.etapa7_ir_para_agendamento()
                            if sucesso:
                                ok, _, datas = pap.etapa7_obter_datas_disponiveis()
                                if ok and datas:
                                    responder(
                                        "✅ Biometria aprovada! Sim recebido.\n\n"
                                        "📅 *Agendamento - Selecione o dia e a hora*\n\n"
                                        f"Datas disponíveis: {', '.join(str(d) for d in datas)}\n\n"
                                        "Digite o *número do dia* para selecionar (ex: 10)\n"
                                        "ou *CONCLUIR* para sair."
                                    )
                                else:
                                    responder("✅ Tela de Agendamento aberta.\n\nDigite o número do dia ou *CONCLUIR* para sair.")
                            else:
                                responder(f"❌ Agendamento: {msg}\n\nDigite *CONCLUIR* para sair.")
                        else:
                            responder(_msg_resumo_biometria("", biometria_ok, sim_cliente_recebido, "", apenas_status=True))
                    else:
                        resumo = pap.obter_resumo_pedido_para_cliente()
                        resp = f"{resumo}\n\n"
                        if enviou_resumo_whatsapp:
                            resp += f"{enviou_resumo_whatsapp}\n"
                        resp += "Digite *SIM* ou *CONFIRMAR* quando receber o sim do cliente.\nDigite *CONSULTAR* para verificar biometria e validar."
                        responder(resp)
                    continue

                if etapa_pap == 12:
                    if entrada.strip().upper() == "CONCLUIR":
                        pap._fechar_sessao()
                        responder("Sessão encerrada. Até logo!")
                        break
                    dia = entrada.strip()
                    if dia.isdigit():
                        dia_int = int(dia)
                        sucesso, msg, periodos = pap.etapa7_selecionar_data_e_obter_periodos(dia_int)
                        if not sucesso:
                            responder(f"❌ {msg}\n\nDigite outro dia ou *CONCLUIR*.")
                        elif periodos:
                            etapa_pap = 121
                            pap.dados_pedido['agendamento_dia'] = dia_int
                            pap.dados_pedido['agendamento_periodos'] = periodos
                            responder(
                                f"✅ Dia *{dia}* selecionado.\n\n"
                                "Deseja *CONFIRMAR* a data ou *ALTERAR*?"
                            )
                        else:
                            responder(f"⚠️ Dia {dia} selecionado, mas nenhum período disponível.\nDigite outro dia ou *CONCLUIR*.")
                    else:
                        responder("Digite o número do dia (ex: 10) ou *CONCLUIR* para sair.")
                    continue

                if etapa_pap == 121:
                    if entrada.strip().upper() == "CONCLUIR":
                        pap._fechar_sessao()
                        responder("Sessão encerrada. Até logo!")
                        break
                    if entrada.strip().upper() == "ALTERAR":
                        ok, _, datas = pap.etapa7_obter_datas_disponiveis()
                        if ok and datas:
                            responder(
                                f"Datas disponíveis: {', '.join(str(d) for d in datas)}\n\n"
                                "Digite o *número do dia* para selecionar (ex: 10)\n"
                                "ou *CONCLUIR* para sair."
                            )
                        etapa_pap = 12
                    elif entrada.strip().upper() in ["CONFIRMAR", "SIM", "S"]:
                        periodos = pap.dados_pedido.get('agendamento_periodos', [])
                        linha = "\n".join(f"  {p['idx']} - {p['label']}" for p in periodos)
                        etapa_pap = 13
                        responder(
                            "✅ Data confirmada!\n\n"
                            "*Períodos disponíveis:*\n" + linha + "\n\n"
                            "Digite o *número do período* (ex: 1) ou *CONCLUIR* para sair."
                        )
                    else:
                        responder("Digite *CONFIRMAR* para a data ou *ALTERAR* para escolher outra.")
                    continue

                if etapa_pap == 13:
                    if entrada.strip().upper() == "CONCLUIR":
                        pap._fechar_sessao()
                        responder("Sessão encerrada. Até logo!")
                        break
                    if entrada.strip().isdigit():
                        idx = int(entrada.strip())
                        sucesso, msg = pap.etapa7_selecionar_periodo(idx)
                        if sucesso:
                            periodos = pap.dados_pedido.get('agendamento_periodos', [])
                            label = periodos[idx - 1]['label'] if idx <= len(periodos) else f"Período {idx}"
                            pap.dados_pedido['agendamento_turno_label'] = label
                            etapa_pap = 131
                            responder(
                                f"✅ Turno *{label}* selecionado.\n\n"
                                "Deseja *CONFIRMAR* o turno ou *ALTERAR*?"
                            )
                        else:
                            responder(f"❌ {msg}\n\nDigite outro período ou *CONCLUIR*.")
                    else:
                        responder("Digite o número do período (ex: 1) ou *CONCLUIR* para sair.")
                    continue

                if etapa_pap == 131:
                    if entrada.strip().upper() == "CONCLUIR":
                        pap._fechar_sessao()
                        responder("Sessão encerrada. Até logo!")
                        break
                    if entrada.strip().upper() == "ALTERAR":
                        periodos = pap.dados_pedido.get('agendamento_periodos', [])
                        linha = "\n".join(f"  {p['idx']} - {p['label']}" for p in periodos)
                        responder(
                            "*Períodos disponíveis:*\n" + linha + "\n\n"
                            "Digite o *número do período* (ex: 1) ou *CONCLUIR* para sair."
                        )
                        etapa_pap = 13
                    elif entrada.strip().upper() in ["CONFIRMAR", "SIM", "S"]:
                        dia = pap.dados_pedido.get('agendamento_dia', '?')
                        turno = pap.dados_pedido.get('agendamento_turno_label', '?')
                        etapa_pap = 14
                        responder(
                            f"✅ Turno confirmado!\n\n"
                            f"Podemos agendar para o dia *{dia}* e turno *{turno}*?\n\n"
                            "Digite *SIM* para confirmar e agendar, ou *CONCLUIR* para sair."
                        )
                    else:
                        responder("Digite *CONFIRMAR* para o turno ou *ALTERAR* para escolher outro.")
                    continue

                if etapa_pap == 14:
                    if entrada.strip().upper() == "CONCLUIR":
                        pap._fechar_sessao()
                        responder("Sessão encerrada. Até logo!")
                        break
                    if entrada.strip().upper() in ["SIM", "S"]:
                        sucesso, msg = pap.etapa7_clicar_agendar()
                        if sucesso:
                            etapa_pap = 15
                            dia = pap.dados_pedido.get('agendamento_dia', '?')
                            turno = pap.dados_pedido.get('agendamento_turno_label', '?')
                            responder(
                                f"📅 *Agendado para* dia *{dia}* e turno *{turno}*\n\n"
                                "Deseja *CONFIRMAR* (clicar Continuar) ou *ALTERAR* (voltar para escolher outra data/turno)?"
                            )
                        else:
                            responder(f"❌ {msg}\n\nDigite *SIM* para tentar novamente ou *CONCLUIR*.")
                    else:
                        dia = pap.dados_pedido.get('agendamento_dia', '?')
                        turno = pap.dados_pedido.get('agendamento_turno_label', '?')
                        responder(f"Digite *SIM* para agendar (dia {dia}, turno {turno}) ou *CONCLUIR* para sair.")
                    continue

                if etapa_pap == 15:
                    if entrada.strip().upper() == "CONCLUIR":
                        pap._fechar_sessao()
                        responder("Sessão encerrada. Até logo!")
                        break
                    if entrada.strip().upper() == "ALTERAR":
                        pap.etapa7_modal_fechar()
                        ok, _, datas = pap.etapa7_obter_datas_disponiveis()
                        etapa_pap = 12
                        if ok and datas:
                            responder(
                                f"Datas disponíveis: {', '.join(str(d) for d in datas)}\n\n"
                                "Digite o *número do dia* para selecionar (ex: 10)\n"
                                "ou *CONCLUIR* para sair."
                            )
                        else:
                            responder("Digite o número do dia ou *CONCLUIR* para sair.")
                    elif entrada.strip().upper() in ["CONFIRMAR", "SIM", "S"]:
                        sucesso, msg, numero = pap.etapa7_modal_clicar_continuar()
                        if sucesso:
                            # Salva no CRM
                            try:
                                from crm_app.cadastro_venda_pap import cadastrar_venda_pap_no_crm
                                cadastrar_venda_pap_no_crm(
                                    pap.dados_pedido, numero or "", matricula_vendedor=matricula_vendedor
                                )
                            except Exception as ex:
                                self.stdout.write(self.style.WARNING(f"  [Aviso] Cadastro CRM: {ex}"))
                            num_txt = f"📋 Número do pedido: *{numero}*" if numero else ""
                            responder(
                                f"🎉 Venda concluída!\n\n{num_txt}\n\n"
                                "Boas vendas!"
                            )
                            pap._fechar_sessao()
                            break
                        else:
                            responder(f"❌ {msg}\n\nDigite *CONFIRMAR* para tentar ou *ALTERAR* para voltar.")
                    else:
                        dia = pap.dados_pedido.get('agendamento_dia', '?')
                        turno = pap.dados_pedido.get('agendamento_turno_label', '?')
                        responder(f"Digite *CONFIRMAR* para continuar ou *ALTERAR* para escolher outra data/turno.")
                    continue

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"\nErro: {e}"))
            import traceback
            traceback.print_exc()
        finally:
            try:
                pap._fechar_sessao()
            except Exception:
                pass
            self.stdout.write("\nEncerrado.\n")
