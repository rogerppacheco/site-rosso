# crm_app/cadastro_venda_pap.py
"""
Cadastro de vendas PAP no CRM.
Usado pelo fluxo WhatsApp e pelo teste via terminal.
"""
import logging
import re

logger = logging.getLogger(__name__)


def _preencher_endereco_via_cep(dados: dict) -> None:
    """Se temos CEP mas faltam logradouro/bairro/cidade/estado, consulta ViaCEP e preenche em dados."""
    if dados.get("logradouro") and dados.get("bairro") and dados.get("cidade"):
        return
    cep = dados.get("cep") or ""
    cep_limpo = re.sub(r"\D", "", str(cep))[:8]
    if len(cep_limpo) != 8:
        return
    try:
        import requests
        r = requests.get(f"https://viacep.com.br/ws/{cep_limpo}/json/", timeout=5)
        r.raise_for_status()
        d = r.json()
        if d.get("erro"):
            return
        if not dados.get("logradouro"):
            dados["logradouro"] = d.get("logradouro", "") or None
        if not dados.get("bairro"):
            dados["bairro"] = d.get("bairro", "") or None
        if not dados.get("cidade"):
            dados["cidade"] = d.get("localidade", "") or None
        if not dados.get("estado"):
            dados["estado"] = (d.get("uf", "") or "").strip()[:2] or None
    except Exception as e:
        logger.debug("[CRM] ViaCEP para endereço: %s", e)


def cadastrar_venda_pap_no_crm(dados: dict, numero_os: str, matricula_vendedor: str = None, vendedor=None) -> bool:
    """
    Cadastra a venda no CRM após conclusão no PAP.

    Args:
        dados: dados_pedido com cpf_cliente, nome_cliente, cep, numero, etc.
        numero_os: Número da O.S. extraído do modal Sucesso.
        matricula_vendedor: Matrícula PAP do vendedor (para buscar Usuario).
        vendedor: Usuario vendedor (se já disponível).

    Returns:
        True se cadastrou com sucesso.
    """
    try:
        from crm_app.models import Venda, Cliente, Plano, FormaPagamento, StatusCRM
        from usuarios.models import Usuario
        from django.utils import timezone

        logger.info(f"[CRM] Cadastrando venda PAP - OS: {numero_os}")

        if not vendedor and matricula_vendedor:
            vendedor = Usuario.objects.filter(
                matricula_pap=matricula_vendedor
            ).filter(is_active=True).first()
        if not vendedor:
            # Fallback: usar primeiro vendedor com matrícula PAP
            vendedor = Usuario.objects.filter(
                matricula_pap__isnull=False
            ).exclude(matricula_pap="").filter(is_active=True).first()
        if not vendedor:
            logger.warning("[CRM] Nenhum vendedor encontrado para cadastrar venda PAP")
            return False

        cpf = dados.get("cpf_cliente", "")
        cliente, created = Cliente.objects.get_or_create(
            cpf_cnpj=cpf,
            defaults={
                "nome_razao_social": dados.get("nome_cliente", f"Cliente {cpf}"),
                "email": dados.get("email", ""),
            },
        )
        if not created and not cliente.email:
            cliente.email = dados.get("email", "") or None
            cliente.save(update_fields=["email"])

        plano_map = {
            "1giga": "Nio Fibra Ultra 1 Giga",
            "700mega": "Nio Fibra Super 700 Mega",
            "500mega": "Nio Fibra Essencial 500 Mega",
        }
        plano_nome = plano_map.get(dados.get("plano", ""), "Nio Fibra Essencial 500 Mega")
        plano = Plano.objects.filter(
            nome__icontains=plano_nome.split()[2] if len(plano_nome.split()) > 2 else plano_nome
        ).first()

        forma_map = {
            "boleto": "Boleto",
            "cartao": "Cartão",
            "debito": "Débito",
        }
        forma_nome = forma_map.get(dados.get("forma_pagamento", ""), "Boleto")
        forma_pagamento = FormaPagamento.objects.filter(nome__icontains=forma_nome).first()

        status_agendada = StatusCRM.objects.filter(
            tipo="Esteira", nome__icontains="AGENDAD"
        ).first()

        _preencher_endereco_via_cep(dados)

        from datetime import date, datetime

        # Data completa (dd/mm/yyyy ou date) ou só mês revelado no PAP (**/MM/****) → mes_nascimento_pap
        data_nasc = None
        mes_pap = None
        dt_nasc_str = dados.get("data_nascimento") or dados.get("data_nasc")
        if dt_nasc_str:
            if hasattr(dt_nasc_str, "year"):
                data_nasc = dt_nasc_str
            else:
                try:
                    data_nasc = datetime.strptime(str(dt_nasc_str).strip()[:10], "%d/%m/%Y").date()
                except (ValueError, TypeError):
                    pass
        if data_nasc is None:
            mes_nasc = dados.get("mes_nascimento")
            try:
                mn = int(mes_nasc) if mes_nasc is not None else None
            except (TypeError, ValueError):
                mn = None
            if mn is not None and 1 <= mn <= 12:
                mes_pap = mn

        # Data de agendamento: usar data já vinda da automação ou montar a partir do dia
        data_agend = None
        data_agend_val = dados.get("data_agendamento")
        if data_agend_val and hasattr(data_agend_val, "year"):
            data_agend = data_agend_val
        elif isinstance(data_agend_val, str) and data_agend_val.strip():
            try:
                data_agend = datetime.strptime(data_agend_val.strip()[:10], "%Y-%m-%d").date()
            except (ValueError, TypeError):
                try:
                    data_agend = datetime.strptime(data_agend_val.strip()[:10], "%d/%m/%Y").date()
                except (ValueError, TypeError):
                    pass
        if data_agend is None:
            dia_ag = dados.get("agendamento_dia")
            if dia_ag is not None:
                try:
                    dia_int = int(dia_ag)
                    hoje = timezone.now().date()
                    data_agend = date(hoje.year, hoje.month, min(dia_int, 28))
                except (TypeError, ValueError):
                    pass

        # Período: Manhã -> MANHA, Tarde -> TARDE
        periodo_agend = None
        turno_label = (dados.get("agendamento_turno_label") or dados.get("turno") or "").upper()
        if "MANH" in turno_label or "08H" in turno_label or "12H" in turno_label:
            periodo_agend = "MANHA"
        elif "TARD" in turno_label or "13H" in turno_label or "18H" in turno_label:
            periodo_agend = "TARDE"

        obs_texto = f"Venda realizada via PAP em {timezone.now().strftime('%d/%m/%Y %H:%M')}"
        if numero_os:
            obs_texto = f"O.S. {numero_os}. " + obs_texto

        venda = Venda.objects.create(
            cliente=cliente,
            vendedor=vendedor,
            plano=plano,
            forma_pagamento=forma_pagamento,
            status_esteira=status_agendada,
            ordem_servico=numero_os or None,
            # Telefones
            telefone1=dados.get("celular") or None,
            telefone2=dados.get("celular_sec") or None,
            # Endereço
            cep=dados.get("cep") or None,
            logradouro=dados.get("logradouro") or None,
            numero_residencia=dados.get("numero") or None,
            complemento=dados.get("complemento") or None,
            bairro=dados.get("bairro") or None,
            cidade=dados.get("cidade") or None,
            estado=dados.get("estado") or None,
            ponto_referencia=dados.get("referencia") or None,
            # Identidade (nome_mae pode vir mascarado do PAP, ex.: MARIA *********)
            nome_mae=(dados.get("nome_mae") or "").strip() or None,
            data_nascimento=data_nasc,
            mes_nascimento_pap=mes_pap,
            # Agendamento
            data_agendamento=data_agend,
            periodo_agendamento=periodo_agend,
            # DACC e outros
            tem_fixo=dados.get("tem_fixo", False),
            banco_dacc=dados.get("banco_dacc") or None,
            agencia_dacc=dados.get("agencia_dacc") or None,
            conta_dacc=dados.get("conta_dacc") or None,
            digito_dacc=dados.get("digito_dacc") or None,
            observacoes=obs_texto,
            ativo=True,
        )
        try:
            from crm_app.services.cnpj_mei_service import persistir_classificacao_mei
            persistir_classificacao_mei(cliente, venda)
        except Exception:
            logger.exception('[CRM] Erro ao classificar MEI/NMEI venda PAP #%s', venda.id)

        logger.info(f"[CRM] Venda cadastrada com sucesso! ID: {venda.id}, OS: {numero_os}")
        return True

    except Exception as e:
        logger.exception(f"[CRM] Erro ao cadastrar venda PAP: {e}")
        return False
