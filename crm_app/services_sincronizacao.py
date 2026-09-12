import logging
from typing import Dict, Any
from django.db import transaction
from django.db.models import Q
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


def _normalizar_texto_plano(valor: str) -> str:
    t = (valor or "").strip().upper()
    t = (
        t.replace("Á", "A")
        .replace("À", "A")
        .replace("Ã", "A")
        .replace("Â", "A")
        .replace("É", "E")
        .replace("Ê", "E")
        .replace("Í", "I")
        .replace("Ó", "O")
        .replace("Ô", "O")
        .replace("Õ", "O")
        .replace("Ú", "U")
        .replace("Ç", "C")
    )
    return re.sub(r"\s+", " ", t)


def _familia_plano_pap(nome_plano: str) -> str:
    n = _normalizar_texto_plano(nome_plano)
    if "ULTRA" in n:
        return "ULTRA"
    if "SUPER" in n:
        return "SUPER"
    if "ESSENCIAL" in n:
        return "ESSENCIAL"
    return ""


def _velocidade_mb_pap(velocidade: str, nome_plano: str = "") -> int | None:
    """Extrai MB do campo velocidade PAP (ex.: '600 Mega', '1 Giga')."""
    blob = _normalizar_texto_plano(f"{velocidade} {nome_plano}")
    if not blob.strip():
        return None
    if "1 GIGA" in blob or "1GB" in blob or re.search(r"\b1000\b", blob):
        return 1000
    m = re.search(r"(\d+)\s*(GIGA|GB|MEGA|MB)", blob)
    if not m:
        m = re.search(r"\b(500|600|700|800|1000)\b", blob)
        if m:
            return int(m.group(1))
        return None
    num = int(m.group(1))
    unidade = m.group(2)
    if unidade in ("GIGA", "GB"):
        return num * 1000 if num < 100 else num
    return num


def _parse_valor_mensal_pap(valor) -> float | None:
    if valor is None or valor == "":
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    s = str(valor).strip()
    if not s:
        return None
    s = re.sub(r"[^\d,.\-]", "", s)
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _escolher_plano_1gb(candidatos: list[Plano], nome_plano: str, valor_mensal=None) -> Plano | None:
    """
    Distingue ULTRA 1GB (mesh ~R$160) de ULTRA 1GB (SEM MESH ~R$150).

    - Nome com ESPECIAL → mesh (promo do plano full; não é sem mesh).
    - Nome/código com SEM MESH → sem mesh.
    - Valor mensal PAP → candidato com valor de catálogo mais próximo.
    - Default do Ultra comum no PAP → SEM MESH (legado OSAB).
    """
    if not candidatos:
        return None

    nome_n = _normalizar_texto_plano(nome_plano)
    com_mesh = [p for p in candidatos if "SEM MESH" not in _normalizar_texto_plano(p.nome)]
    sem_mesh = [p for p in candidatos if "SEM MESH" in _normalizar_texto_plano(p.nome)]

    if "ESPECIAL" in nome_n:
        return (com_mesh or candidatos)[0]
    if "SEM MESH" in nome_n:
        return (sem_mesh or candidatos)[0]

    valor = _parse_valor_mensal_pap(valor_mensal)
    if valor is not None and len(candidatos) > 1:
        return min(candidatos, key=lambda p: abs(float(p.valor) - valor))

    # Ultra regular no PAP costuma ser a oferta SEM MESH (150 / 135), não o mesh 160.
    return (sem_mesh or com_mesh or candidatos)[0]


def resolver_plano_pap(nome_plano: str, velocidade: str = "", valor_mensal=None) -> Plano | None:
    """
    Casa plano CRM com nome + velocidade (+ valor mensal) do PAP.

    Bug antigo: filtrava só por nome ('Nio Fibra Essencial') e pegava o primeiro
    do catálogo (500MB) em vez do 600MB indicado em Velocidade.
    1GB: não preferir sempre o mesh — SEM MESH (150) é oferta distinta.
    """
    familia = _familia_plano_pap(nome_plano)
    vel_mb = _velocidade_mb_pap(velocidade, nome_plano)
    if not familia and not vel_mb:
        return None

    qs = Plano.objects.filter(ativo=True)
    if familia:
        qs = qs.filter(nome__icontains=familia)

    if vel_mb:
        if vel_mb >= 1000:
            candidatos = list(
                qs.filter(Q(nome__icontains="1GB") | Q(nome__icontains="1 GB") | Q(nome__icontains="1000"))
            )
            return _escolher_plano_1gb(candidatos, nome_plano, valor_mensal)
        for p in qs:
            n = _normalizar_texto_plano(p.nome)
            if re.search(rf"\b{vel_mb}\s*(MB|MEGA)?\b", n) or f"{vel_mb}MB" in n.replace(" ", ""):
                return p

    # Fallback: familia ativa; evita planos legados inativos (500/700)
    return qs.order_by("id").first() if familia else None


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

        # Match de Plano (nome + velocidade + valor mensal) e Forma de Pagamento
        plano_obj = resolver_plano_pap(
            dados_mapeados.get("plano") or "",
            dados_mapeados.get("velocidade") or "",
            dados_mapeados.get("valor_mensal"),
        )

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
