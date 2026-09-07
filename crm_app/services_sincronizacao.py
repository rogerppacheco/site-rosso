import logging
from typing import Dict, Any
from django.db import transaction
from django.utils import timezone
from datetime import datetime
import re

from crm_app.models import (
    Venda,
    Cliente,
    Usuario,
    StatusCRM,
    Plano,
    FormaPagamento,
    HistoricoPapPedido
)
from crm_app.historico_pap import map_pedido_api

logger = logging.getLogger(__name__)

def _somente_numeros(valor: str) -> str:
    if not valor:
        return ""
    return re.sub(r"\D", "", str(valor))

def sincronizar_pedido_pap_para_venda(pedido_id: int) -> dict:
    """
    Sincroniza um HistoricoPapPedido específico criando uma Venda no CRM.
    Retorna dict com status de sucesso, warning ou erro.
    """
    try:
        hist = HistoricoPapPedido.objects.get(id=pedido_id)
    except HistoricoPapPedido.DoesNotExist:
        return {"sucesso": False, "mensagem": "Pedido não encontrado no histórico"}

    if hist.tipo_venda != "VENDA":
        return {"sucesso": False, "mensagem": f"Tipo {hist.tipo_venda} ignorado. Somente VENDA é permitido."}

    # Extrai e mapeia os dados do payload da Vtal
    dados_mapeados = map_pedido_api(hist.payload, hist.tipo_venda)
    pedido_pap = dados_mapeados.get("pedido")
    
    if not pedido_pap:
        return {"sucesso": False, "mensagem": "Pedido PAP não tem um ID válido no payload."}

    # Regra 3: Evitar duplicidade
    if Venda.objects.filter(pedido_pap=pedido_pap).exists():
        return {"sucesso": False, "mensagem": f"Venda com pedido {pedido_pap} já existe."}

    cpf_limpo = _somente_numeros(dados_mapeados.get("cpf") or "")
    if not cpf_limpo:
        return {"sucesso": False, "mensagem": "Pedido sem CPF/CNPJ."}

    with transaction.atomic():
        # Cliente
        cliente, created = Cliente.objects.get_or_create(
            cpf_cnpj=cpf_limpo,
            defaults={
                "nome_razao_social": dados_mapeados.get("cliente") or "CLIENTE NÃO INFORMADO",
                "email": dados_mapeados.get("email") or "",
            }
        )
        nome_pap = dados_mapeados.get("cliente")
        if not created and nome_pap and cliente.nome_razao_social != nome_pap:
            cliente.nome_razao_social = nome_pap
            cliente.save(update_fields=['nome_razao_social'])

        # Vendedor (Regra 4)
        vendedor_matricula = dados_mapeados.get("vendedor_matricula")
        vendedor_obj = None
        obs = dados_mapeados.get("observacao_vendedor") or ""
        
        if vendedor_matricula:
            vendedor_obj = Usuario.objects.filter(matricula_pap=vendedor_matricula).first()
            if not vendedor_obj:
                obs_vendedor = f"Atribuir vendedor: {vendedor_matricula}"
                obs = f"{obs_vendedor}\n{obs}".strip()

        # Status inicial da Esteira/Tratamento
        status_tratamento = StatusCRM.objects.filter(nome="SEM TRATAMENTO", tipo="Tratamento").first()

        # Match de Plano e Forma de Pagamento (Best Effort)
        plano_obj = None
        nome_plano_pap = dados_mapeados.get("plano")
        if nome_plano_pap:
            plano_obj = Plano.objects.filter(nome__icontains=nome_plano_pap.strip()).first()

        forma_pgto_obj = None
        forma_pap = dados_mapeados.get("forma_pagamento")
        if forma_pap:
            # Ex: "BOLETO", "CREDITO", "DACC"
            forma_pgto_obj = FormaPagamento.objects.filter(nome__icontains=forma_pap.strip()[:4]).first()

        # Data do pedido
        data_pedido_str = dados_mapeados.get("data_pedido")
        data_pedido = None
        if data_pedido_str:
            try:
                # O map_pedido_api formata em "%d/%m/%Y" ou "%d/%m/%Y %H:%M"
                if len(data_pedido_str) > 11:
                    data_pedido = datetime.strptime(data_pedido_str, "%d/%m/%Y %H:%M")
                else:
                    data_pedido = datetime.strptime(data_pedido_str, "%d/%m/%Y")
                data_pedido = timezone.make_aware(data_pedido)
            except Exception:
                pass

        data_nascimento_str = dados_mapeados.get("data_nascimento")
        data_nascimento = None
        if data_nascimento_str:
            try:
                if "/" in data_nascimento_str:
                    data_nascimento = datetime.strptime(data_nascimento_str[:10], "%d/%m/%Y").date()
                else:
                    data_nascimento = datetime.strptime(data_nascimento_str[:10], "%Y-%m-%d").date()
            except Exception:
                pass

        pref_data_str = dados_mapeados.get("preferencia_data")
        data_agendamento = None
        if pref_data_str:
            try:
                if "/" in pref_data_str:
                    data_agendamento = datetime.strptime(pref_data_str[:10], "%d/%m/%Y").date()
                else:
                    data_agendamento = datetime.strptime(pref_data_str[:10], "%Y-%m-%d").date()
            except Exception:
                pass

        pref_periodo = dados_mapeados.get("preferencia_periodo")
        periodo_agendamento = None
        if pref_periodo:
            pref_periodo_upper = pref_periodo.upper()
            if 'MANH' in pref_periodo_upper:
                periodo_agendamento = 'MANHA'
            elif 'TARD' in pref_periodo_upper:
                periodo_agendamento = 'TARDE'
        
        venda = Venda.objects.create(
            pedido_pap=pedido_pap,
            cliente=cliente,
            vendedor=vendedor_obj,
            vendedor_matricula_pap=vendedor_matricula,
            plano=plano_obj,
            valor_plano_pap=dados_mapeados.get("valor_mensal") or None,
            forma_pagamento=forma_pgto_obj,
            status_tratamento=status_tratamento,
            observacoes=obs,
            cep=dados_mapeados.get("cep"),
            logradouro=dados_mapeados.get("logradouro"),
            numero_residencia=dados_mapeados.get("numero"),
            complemento=dados_mapeados.get("complemento"),
            bairro=dados_mapeados.get("bairro"),
            cidade=dados_mapeados.get("cidade"),
            estado=dados_mapeados.get("uf"),
            ponto_referencia=dados_mapeados.get("ponto_referencia"),
            telefone1=dados_mapeados.get("celular_principal"),
            telefone2=dados_mapeados.get("celular_2"),
            nome_mae=dados_mapeados.get("nome_mae"),
            data_nascimento=data_nascimento,
            ordem_servico=dados_mapeados.get("os_instalacao"),
            data_pedido=data_pedido,
            data_agendamento=data_agendamento,
            periodo_agendamento=periodo_agendamento,
            # Se for DACC, poderíamos extrair banco, etc, mas map_pedido_api não exporta os dados bancários atualmente
        )

        if data_pedido:
            Venda.objects.filter(id=venda.id).update(data_criacao=data_pedido)

        return {"sucesso": True, "venda_id": venda.id, "mensagem": f"Venda {venda.id} criada com sucesso"}
