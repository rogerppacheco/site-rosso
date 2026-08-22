import logging
from datetime import timedelta
from django.utils import timezone
from django.db.models import Count, Q
from django.contrib.auth import get_user_model
from .models import Venda, AgendamentoDisparo, LogEnvioPerformance, AuditoriaLigacao
from .whatsapp_service import WhatsAppService

logger = logging.getLogger(__name__)

def _filtro_cc():
    return (
        Q(vendas__forma_pagamento__nome__icontains='CREDIT') |
        Q(vendas__forma_pagamento__nome__icontains='CRÉDIT') |
        (Q(vendas__forma_pagamento__nome__icontains='CARTA') & ~Q(vendas__forma_pagamento__nome__icontains='DEBIT'))
    )

def processar_envio_performance():
    """Lógica principal chamada pelo Scheduler"""
    agora = timezone.localtime(timezone.now())
    hora = agora.hour
    minuto = agora.minute
    dia_sem = agora.weekday() # 0=Seg, 1=Ter, 2=Qua, 3=Qui, 4=Sex, 5=Sáb, 6=Dom
    
    logger.info(f"📊 Verificando envios de Performance - {agora.strftime('%d/%m/%Y %H:%M:%S')} (Dia: {dia_sem}, Hora: {hora:02d}:{minuto:02d})")
    
    regras = AgendamentoDisparo.objects.filter(ativo=True, prioridade__isnull=False).order_by('prioridade', 'id')
    logger.info(f"📋 Encontradas {regras.count()} regra(s) de agendamento ativa(s)")
    
    svc = WhatsAppService()
    User = get_user_model()

    for regra in regras:
        enviar = False
        modo_envio = (getattr(regra, 'modo_envio', 'INTERVALO') or 'INTERVALO').upper()
        slot_para_disparo = None

        if modo_envio == 'ESPECIFICO':
            horarios_especificos = getattr(regra, 'horarios_especificos', None) or []
            if not horarios_especificos:
                logger.info(f"⏭ Regra '{regra.nome}': sem horários específicos configurados")
                continue

            dias_config = getattr(regra, 'dias_semana', None) or []
            if regra.tipo == 'SEMANAL':
                if not dias_config:
                    logger.info(f"⏭ Regra '{regra.nome}': semanal sem dias da semana configurados")
                    continue
                if dia_sem not in [int(d) for d in dias_config]:
                    continue
            else:
                # Diário no modo específico mantém comportamento atual de seg a sáb
                if dia_sem not in [0, 1, 2, 3, 4, 5]:
                    continue

            hoje_str = agora.strftime('%Y-%m-%d')
            controle = getattr(regra, 'controle_disparos', None) or {}
            if controle.get('date') != hoje_str:
                slots_enviados = []
            else:
                slots_enviados = list(controle.get('slots', []))
            slots_enviados_set = set(str(s) for s in slots_enviados)

            agora_min = hora * 60 + minuto
            slot_encontrado = None
            for horario_cfg in sorted(str(h).strip() for h in horarios_especificos if str(h).strip()):
                try:
                    hh_str, mm_str = horario_cfg.split(':')
                    hh = int(hh_str)
                    mm = int(mm_str)
                except Exception:
                    continue
                if hh < 8 or hh > 22 or mm < 0 or mm > 59:
                    continue

                alvo_min = (hh * 60) + mm
                atraso = agora_min - alvo_min
                if 0 <= atraso <= 10:
                    slot_ref = f"{hh:02d}:{mm:02d}"
                    if slot_ref not in slots_enviados_set:
                        slot_encontrado = slot_ref
                        break

            if slot_encontrado:
                enviar = True
                slot_para_disparo = slot_encontrado
            else:
                continue
        else:
            intervalo_min = getattr(regra, 'intervalo_minutos', 60) or 60

            # --- Respeitar intervalo mínimo desde o último disparo ---
            if regra.ultimo_disparo:
                try:
                    diff_minutos = (agora - regra.ultimo_disparo).total_seconds() / 60.0
                    if diff_minutos < intervalo_min:
                        logger.info(f"⏳ Regra '{regra.nome}': aguardando intervalo ({diff_minutos:.0f} min < {intervalo_min} min)")
                        continue  # Ainda não passou o intervalo, pula esta regra
                except (TypeError, AttributeError):
                    pass

            # --- VERIFICAÇÃO DE HORÁRIO (janela permitida) ---
            hora_fim = getattr(regra, 'hora_fim', 19) or 19
            if regra.tipo == 'HORARIO':
                if dia_sem in [0, 1, 2, 3, 4]:  # Seg-Sex: 8h30 até hora_fim
                    if (hora == 8 and minuto >= 30) or (9 <= hora <= hora_fim):
                        enviar = True
                elif dia_sem == 5:  # Sábado: 9h até 12h59 (ou hora_fim se menor)
                    fim_sab = min(12, hora_fim)
                    if 9 <= hora <= fim_sab:
                        enviar = True
            elif regra.tipo == 'SEMANAL':
                if dia_sem in [1, 3, 5] and hora == 17 and minuto == 0:
                    enviar = True

        if enviar:
            try:
                hoje = agora.date()
                inicio_semana = hoje - timedelta(days=hoje.weekday())
                fim_semana = inicio_semana + timedelta(days=5)
                dias_semana = [inicio_semana + timedelta(days=i) for i in range(6)]
                inicio_mes = hoje.replace(day=1)
                if inicio_mes.month == 12:
                    prox_mes = inicio_mes.replace(year=inicio_mes.year + 1, month=1, day=1)
                else:
                    prox_mes = inicio_mes.replace(month=inicio_mes.month + 1, day=1)
                fim_mes = prox_mes - timedelta(days=1)

                # Alinhado ao Painel (default gestão): inclui vendedores inativos; bots continuam excluídos
                users = User.objects.exclude(username__in=['OSAB_IMPORT', 'admin', 'root'])
                status_destinatarios = (getattr(regra, 'status_destinatarios', 'somente_ativos') or 'somente_ativos').lower()
                if status_destinatarios == 'somente_ativos':
                    users = users.filter(is_active=True)
                elif status_destinatarios == 'somente_inativos':
                    users = users.filter(is_active=False)
                if regra.canal_alvo != 'TODOS':
                    users = users.filter(canal__iexact=regra.canal_alvo)
                if getattr(regra, 'cluster_alvo', None) and str(regra.cluster_alvo).strip() and str(regra.cluster_alvo).upper() != 'TODOS':
                    users = users.filter(cluster__iexact=regra.cluster_alvo.strip())

                users_perf = users.select_related('perfil')
                users_by_id = {u.id: u for u in users_perf}
                from crm_app.performance_helpers import (
                    carregar_contexto_faixas_comissao,
                    dias_decorridos_semana,
                    perfil_comissao_do_consultor,
                )
                dias_decorridos_zap = dias_decorridos_semana(inicio_semana, fim_semana, hoje)
                ctx_faixas_zap = carregar_contexto_faixas_comissao(inicio_mes.year, inicio_mes.month)

                filtro_os_sem_reemissao = (
                    Q(vendas__ativo=True)
                    & ~Q(vendas__ordem_servico='')
                    & Q(vendas__ordem_servico__isnull=False)
                    & Q(vendas__status_tratamento__nome__iexact='CADASTRADA')
                    & Q(vendas__reemissao=False)
                )
                filtro_os_com_reemissao = (
                    Q(vendas__ativo=True)
                    & ~Q(vendas__ordem_servico='')
                    & Q(vendas__ordem_servico__isnull=False)
                    & Q(vendas__status_tratamento__nome__iexact='CADASTRADA')
                )
                filtro_cc = _filtro_cc()
                filtro_inst = Q(vendas__status_esteira__nome__iexact='INSTALADA')
                tipo_rel = getattr(regra, 'tipo_relatorio', 'HOJE') or 'HOJE'

                lista_dados = []
                t_total = 0
                t_cc = 0
                t_instaladas = 0
                titulo_extra = ""

                if tipo_rel == 'HOJE':
                    filtro = filtro_os_sem_reemissao & Q(vendas__data_abertura__date=hoje)
                    qs = users_perf.annotate(
                        total=Count('vendas', filter=filtro),
                        cc=Count('vendas', filter=filtro & filtro_cc)
                    ).order_by('username')
                    if not qs.exists():
                        logger.info(f"Nenhum usuário ativo para regra {regra.nome} - pulando envio")
                        continue
                    titulo_extra = " Hoje"
                    for u in qs:
                        pct = int((u.cc / u.total * 100)) if u.total > 0 else 0
                        lista_dados.append({
                            'nome': u.username.upper(),
                            'cluster': getattr(u, 'cluster', None) or '-',
                            'canal': getattr(u, 'canal', None) or '-',
                            'total': u.total,
                            'cc': u.cc,
                            'pct': f"{pct}%"
                        })
                        t_total += u.total
                        t_cc += u.cc

                elif tipo_rel == 'SEMANAL':
                    qs_semana = users_perf.annotate(
                        seg=Count('vendas', filter=filtro_os_sem_reemissao & Q(vendas__data_abertura__date=dias_semana[0])),
                        ter=Count('vendas', filter=filtro_os_sem_reemissao & Q(vendas__data_abertura__date=dias_semana[1])),
                        qua=Count('vendas', filter=filtro_os_sem_reemissao & Q(vendas__data_abertura__date=dias_semana[2])),
                        qui=Count('vendas', filter=filtro_os_sem_reemissao & Q(vendas__data_abertura__date=dias_semana[3])),
                        sex=Count('vendas', filter=filtro_os_sem_reemissao & Q(vendas__data_abertura__date=dias_semana[4])),
                        sab=Count('vendas', filter=filtro_os_sem_reemissao & Q(vendas__data_abertura__date=dias_semana[5])),
                        total_semana=Count('vendas', filter=filtro_os_sem_reemissao & Q(vendas__data_abertura__date__gte=inicio_semana) & Q(vendas__data_abertura__date__lte=fim_semana)),
                        total_cc=Count('vendas', filter=filtro_os_sem_reemissao & Q(vendas__data_abertura__date__gte=inicio_semana) & Q(vendas__data_abertura__date__lte=fim_semana) & filtro_cc)
                    ).order_by('username').values('username', 'cluster', 'canal', 'total_semana', 'total_cc')
                    if not qs_semana.exists():
                        logger.info(f"Nenhum usuário ativo para regra {regra.nome} - pulando envio")
                        continue
                    titulo_extra = " Semanal"
                    for u in qs_semana:
                        tot = u['total_semana']
                        cc = u['total_cc']
                        pct = int((cc / tot * 100)) if tot > 0 else 0
                        lista_dados.append({
                            'nome': u['username'].upper(),
                            'cluster': u.get('cluster') or '-',
                            'canal': u.get('canal') or '-',
                            'total': tot,
                            'cc': cc,
                            'pct': f"{pct}%"
                        })
                        t_total += tot
                        t_cc += cc

                else:  # MENSAL
                    filtro_inst_m = (
                        (Q(vendas__data_instalacao_fisica__isnull=False)
                         & Q(vendas__data_instalacao_fisica__gte=inicio_mes)
                         & Q(vendas__data_instalacao_fisica__lte=fim_mes))
                        | (
                            Q(vendas__data_instalacao_fisica__isnull=True)
                            & Q(vendas__data_instalacao__gte=inicio_mes)
                            & Q(vendas__data_instalacao__lte=fim_mes)
                        )
                    )
                    qs_mes = users_perf.annotate(
                        total_vendas=Count('vendas', filter=filtro_os_com_reemissao & Q(vendas__data_abertura__date__gte=inicio_mes) & Q(vendas__data_abertura__date__lte=fim_mes)),
                        instaladas=Count('vendas', filter=filtro_os_com_reemissao & filtro_inst_m & filtro_inst),
                        total_cc=Count('vendas', filter=filtro_os_com_reemissao & Q(vendas__data_abertura__date__gte=inicio_mes) & Q(vendas__data_abertura__date__lte=fim_mes) & filtro_cc)
                    ).order_by('username').values('id', 'username', 'cluster', 'canal', 'total_vendas', 'instaladas', 'total_cc')
                    if not qs_mes.exists():
                        logger.info(f"Nenhum usuário ativo para regra {regra.nome} - pulando envio")
                        continue
                    titulo_extra = " Mensal"
                    for u in qs_mes:
                        tot = u['total_vendas']
                        inst = u['instaladas']
                        cc = u['total_cc']
                        pct = int((cc / tot * 100)) if tot > 0 else 0
                        aprov = int((inst / tot * 100)) if tot > 0 else 0
                        consultor = users_by_id.get(u['id'])
                        config_com = ctx_faixas_zap['configs'].get(u['id']) if consultor else None
                        perfil_com = (
                            perfil_comissao_do_consultor(consultor, config_com)
                            if consultor else 'Vendedor'
                        )
                        lista_dados.append({
                            'nome': u['username'].upper(),
                            'usuario_id': u['id'],
                            'perfil_comissao': perfil_com,
                            'cluster': u.get('cluster') or '-',
                            'canal': u.get('canal') or '-',
                            'total': tot,
                            'instaladas': inst,
                            'aprov': f"{aprov}%",
                            'cc': cc,
                            'pct': f"{pct}%"
                        })
                        t_total += tot
                        t_cc += cc
                        t_instaladas += inst

                pct_geral = int((t_cc / t_total * 100)) if t_total > 0 else 0
                aprov_geral = int((t_instaladas / t_total * 100)) if t_total > 0 and tipo_rel == 'MENSAL' else 0
                payload_imagem = {
                    'titulo': f"Performance -{titulo_extra.strip()}",
                    'data': hoje.strftime('%d/%m/%Y'),
                    'lista': lista_dados,
                    'totais': {
                        'total': t_total,
                        'cc': t_cc,
                        'pct': f"{pct_geral}%",
                        'instaladas': t_instaladas if tipo_rel == 'MENSAL' else None,
                        'aprov': f"{aprov_geral}%" if tipo_rel == 'MENSAL' else None,
                    },
                    'tipo': tipo_rel,
                    'dias_decorridos': dias_decorridos_zap,
                    'ctx_faixas': ctx_faixas_zap if tipo_rel == 'MENSAL' else None,
                }

                # 3. Gerar Imagem no Backend (Pillow)
                img_b64 = svc.gerar_imagem_performance_b64(payload_imagem)

                # 4. Enviar (só registrar sucesso quando a Z-API confirmar com messageId/zaapId)
                if img_b64:
                    # Aceitar vírgula ou ponto-e-vírgula (ex: "id1,id2" ou "id1;id2")
                    raw = (regra.destinatarios or "").replace(";", ",")
                    destinos = [d.strip() for d in raw.split(",") if d.strip()]
                    if not destinos:
                        logger.warning(f"Regra '{regra.nome}': nenhum destinatário válido (destinatarios='{regra.destinatarios}')")
                        try:
                            LogEnvioPerformance.objects.create(
                                regra=regra, regra_nome=regra.nome, sucesso=False,
                                total_destinos=0, sucessos=0, falhas=0,
                                detalhe="Nenhum destinatário válido (use vírgula ou ; para separar)",
                            )
                        except Exception:
                            pass
                        continue
                    logger.info(f"Imagem gerada para regra '{regra.nome}', enviando para {len(destinos)} destino(s)")
                    # Legenda: "Atualização da Parcial de hoje" para HOJE, semanal/mensal para os outros
                    if tipo_rel == 'HOJE':
                        legenda = f"📊 *Atualização da Parcial de hoje* \n⏰ {agora.strftime('%H:%M')}"
                    elif tipo_rel == 'SEMANAL':
                        legenda = f"📊 *Atualização da Parcial semanal* \n⏰ {agora.strftime('%H:%M')}"
                    else:
                        legenda = f"📊 *Atualização da Parcial mensal* \n⏰ {agora.strftime('%H:%M')}"
                    sucessos = 0
                    falhas = 0
                    erros_desc = []

                    for dest in destinos:
                        try:
                            resultado = svc.enviar_imagem_b64(dest, img_b64, caption=legenda)
                            if resultado is not None:
                                sucessos += 1
                                logger.info(f"✅ Imagem enviada com sucesso para {dest}")
                            else:
                                falhas += 1
                                erros_desc.append(f"{dest}: Z-API não confirmou envio")
                                logger.error(f"❌ Falha ao enviar imagem para {dest}: Z-API não retornou messageId/zaapId")
                        except Exception as e:
                            falhas += 1
                            erros_desc.append(f"{dest}: {str(e)[:80]}")
                            logger.error(f"❌ Erro ao enviar imagem para {dest}: {e}")

                    if sucessos > 0:
                        logger.info(f"✅ Enviado regra '{regra.nome}' com imagem para {sucessos}/{len(destinos)} destinatário(s) (falhas: {falhas})")
                        regra.ultimo_disparo = agora
                        if modo_envio == 'ESPECIFICO' and slot_para_disparo:
                            hoje_str = agora.strftime('%Y-%m-%d')
                            controle = getattr(regra, 'controle_disparos', None) or {}
                            if controle.get('date') != hoje_str:
                                slots = []
                            else:
                                slots = list(controle.get('slots', []))
                            if slot_para_disparo not in slots:
                                slots.append(slot_para_disparo)
                            regra.controle_disparos = {'date': hoje_str, 'slots': slots}
                        regra.save()
                        detalhe = f"{sucessos}/{len(destinos)} enviados"
                    else:
                        logger.error(f"❌ Nenhum envio bem-sucedido para regra '{regra.nome}' ({falhas} falha(s))")
                        detalhe = f"0/{len(destinos)} - " + ("; ".join(erros_desc[:3]) if erros_desc else "Z-API não confirmou envio")
                    try:
                        LogEnvioPerformance.objects.create(
                            regra=regra,
                            regra_nome=regra.nome,
                            sucesso=(sucessos > 0),
                            total_destinos=len(destinos),
                            sucessos=sucessos,
                            falhas=falhas,
                            detalhe=detalhe[:500],
                        )
                    except Exception:
                        pass
                else:
                    logger.error(f"❌ Erro ao gerar imagem (Pillow) para regra '{regra.nome}'")
                    try:
                        LogEnvioPerformance.objects.create(
                            regra=regra,
                            regra_nome=regra.nome,
                            sucesso=False,
                            total_destinos=0,
                            sucessos=0,
                            falhas=0,
                            detalhe="Erro ao gerar imagem",
                        )
                    except Exception:
                        pass

            except Exception as e:
                logger.error(f"❌ Erro no disparo da regra '{regra.nome}': {e}")
                import traceback
                logger.error(f"Traceback: {traceback.format_exc()}")
                try:
                    LogEnvioPerformance.objects.create(
                        regra=regra,
                        regra_nome=regra.nome,
                        sucesso=False,
                        total_destinos=0,
                        sucessos=0,
                        falhas=0,
                        detalhe=str(e)[:500],
                    )
                except Exception:
                    pass


def processar_fallback_auditoria_ligacoes_sonax(
    *,
    limite: int = 15,
    grace_seconds: int = 90,
    include_finalizadas_sem_gravacao: bool = False,
) -> None:
    """
    Fallback para quando a Sonax não dispara o webhook de desligamento.
    - Varre ligações Sonax INICIADA/PROCESSANDO com `provider_call_id` numérico.
    - Consulta acao=status_chamada.
    - Se finalizada, persiste status/duração/datas e tenta baixar gravação via pega_gravacao + R2.
    """
    try:
        from crm_app.sonax_voice_service import SonaxVoiceService
        from crm_app.auditoria_ligacoes_api import (
            _finalizada_por_status,
            _parse_provider_datetime,
            _upload_bytes_to_r2,
        )
    except Exception:
        logger.exception("Falha ao importar dependências do fallback Sonax (auditoria).")
        return

    now = timezone.now()
    cutoff = now - timedelta(seconds=max(10, int(grace_seconds)))

    base_qs = AuditoriaLigacao.objects.filter(provedor="SONAX").exclude(provider_call_id__isnull=True)

    pending_q = Q(status__in=["INICIADA", "PROCESSANDO"], criado_em__lte=cutoff)
    if include_finalizadas_sem_gravacao:
        # Também força nova tentativa para chamadas já finalizadas/arquivadas sem link no R2.
        pending_q = pending_q | Q(
            status__in=["FINALIZADA", "ARQUIVADA", "APROVADA"],
            link_gravacao_onedrive__isnull=True,
        )

    rows = base_qs.filter(pending_q).order_by("criado_em")[: max(1, int(limite))]
    if not rows:
        return

    svc = SonaxVoiceService()
    if not svc.is_recording_download_configured:
        logger.warning("Fallback Sonax auditoria: status/gravacao não configurados (SONAX_ID_CLIENTE/token).")
        return

    for ligacao in rows:
        cid = str(ligacao.provider_call_id or "").strip()
        if not cid.isdigit():
            continue

        try:
            st = svc.fetch_call_status(cid)
        except Exception as exc:
            logger.warning(
                "Fallback Sonax auditoria: status_chamada falhou. ligacao_id=%s call_id=%s err=%s",
                ligacao.id,
                cid,
                exc,
            )
            continue

        status_chamada = (st.get("status_chamada") or "").strip()
        status_atendimento = (st.get("status_atendimento") or "").strip()
        dur = st.get("duracao_segundos")
        data_ini = _parse_provider_datetime(st.get("data_inicio"))
        data_fim = _parse_provider_datetime(st.get("data_fim"))

        finalizada = _finalizada_por_status("SONAX", status_chamada)
        if str(status_atendimento).upper() == "S":
            finalizada = True

        update_fields = []
        if status_chamada:
            ligacao.status_chamada_provedor = status_chamada
            update_fields.append("status_chamada_provedor")
        if status_atendimento:
            ligacao.status_atendimento = str(status_atendimento).upper()
            update_fields.append("status_atendimento")
        if dur not in (None, ""):
            try:
                ligacao.duracao_segundos = int(dur)
                update_fields.append("duracao_segundos")
            except (TypeError, ValueError):
                pass
        if data_ini:
            ligacao.data_inicio_chamada = data_ini
            update_fields.append("data_inicio_chamada")
        if data_fim:
            ligacao.data_fim_chamada = data_fim
            update_fields.append("data_fim_chamada")

        if finalizada:
            ligacao.status = "FINALIZADA"
            ligacao.finalizado_em = timezone.now()
            update_fields.extend(["status", "finalizado_em"])
        else:
            ligacao.status = "PROCESSANDO"
            update_fields.append("status")

        if update_fields:
            ligacao.save(update_fields=list(dict.fromkeys(update_fields + ["atualizado_em"])))

        if finalizada and not ligacao.link_gravacao_onedrive:
            try:
                content, ext = svc.download_recording(cid)
                _upload_bytes_to_r2(ligacao, content, ext)
                logger.info(
                    "Fallback Sonax auditoria: gravação arquivada. ligacao_id=%s call_id=%s",
                    ligacao.id,
                    cid,
                )
            except Exception as exc:
                logger.warning(
                    "Fallback Sonax auditoria: falha ao arquivar gravação. ligacao_id=%s call_id=%s err=%s",
                    ligacao.id,
                    cid,
                    exc,
                )