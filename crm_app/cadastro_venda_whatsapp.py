# crm_app/cadastro_venda_whatsapp.py
"""
Cadastro de vendas no CRM via fluxo WhatsApp.
Replica os passos do site: origem (APP/SEM_APP), tem fixo, gerada O.S., depois dados do cliente/venda.
Validações: CPF/CNPJ, telefone (11 dígitos, DDD válido), ViaCEP para endereço.
O vendedor é identificado pelo número de WhatsApp que iniciou o fluxo.
"""
import re
import logging
from datetime import date, datetime
from typing import Tuple, Optional, Dict, Any

logger = logging.getLogger(__name__)

# DDDs válidos no Brasil (lista oficial)
_DDD_VALIDOS = {
    11, 12, 13, 14, 15, 16, 17, 18, 19, 21, 22, 24, 27, 28, 31, 32, 33, 34, 35, 37, 38,
    41, 42, 43, 44, 45, 46, 47, 48, 49, 51, 52, 53, 54, 61, 62, 63, 64, 65, 66, 67, 68, 69,
    71, 73, 74, 75, 79, 81, 82, 83, 84, 85, 86, 87, 88, 89, 91, 92, 93, 94, 95, 96, 97, 98, 99,
}


def validar_telefone_brasil(val: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Valida telefone: 11 dígitos (DDD + número), DDD válido no Brasil.
    Retorna (telefone_limpo, None) se válido ou (None, mensagem_erro).
    """
    if not val:
        return None, "Telefone é obrigatório."
    telefone_limpo = re.sub(r"\D", "", str(val))
    if len(telefone_limpo) != 11:
        return None, "O telefone deve ter 11 dígitos (DDD + número)."
    try:
        ddd = int(telefone_limpo[:2])
    except ValueError:
        return None, "DDD inválido."
    if ddd not in _DDD_VALIDOS:
        return None, "DDD inválido. Informe um DDD válido do Brasil (não use código 55)."
    return telefone_limpo, None


def validar_cpf_ou_cnpj_whatsapp(doc: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Valida CPF ou CNPJ usando core.validators.
    Retorna (doc_limpo, None) ou (None, mensagem_erro).
    """
    if not doc:
        return None, "CPF ou CNPJ é obrigatório."
    try:
        from core.validators import validar_cpf_ou_cnpj
        from django.core.exceptions import ValidationError
        doc_limpo, _ = validar_cpf_ou_cnpj(doc)
        return doc_limpo, None
    except Exception as e:
        msg = str(e)
        if "ValidationError" in type(e).__name__ or hasattr(e, "message_list"):
            msg = getattr(e, "message_list", [str(e)])[0] if hasattr(e, "message_list") else str(e)
        return None, msg


def consultar_viacep_whatsapp(cep: str) -> Optional[Dict[str, str]]:
    """Consulta ViaCEP e retorna dict com logradouro, bairro, localidade, uf, cep."""
    from crm_app.services_inclusao_viabilidade import consultar_viacep
    cep_limpo = re.sub(r"\D", "", str(cep or ""))[:8]
    if len(cep_limpo) != 8:
        return None
    return consultar_viacep(cep_limpo)


def cadastrar_venda_crm(dados: Dict[str, Any], vendedor) -> Tuple[Optional[int], Optional[str]]:
    """
    Cria Cliente (get_or_create) e Venda no CRM com os dados coletados pelo fluxo WhatsApp.
    vendedor: instância de usuarios.models.Usuario (quem iniciou o cadastro pelo WhatsApp).
    Retorna (id_venda, None) em sucesso ou (None, mensagem_erro).
    """
    try:
        from django.utils import timezone
        from crm_app.models import Venda, Cliente, Plano, FormaPagamento, StatusCRM

        cpf_cnpj = (dados.get("cliente_cpf_cnpj") or "").strip()
        cpf_limpo = re.sub(r"\D", "", cpf_cnpj)
        if not cpf_limpo:
            return None, "CPF/CNPJ é obrigatório."

        nome = (dados.get("cliente_nome_razao_social") or "").strip().upper() or f"Cliente {cpf_limpo}"
        email = (dados.get("cliente_email") or "").strip() or None

        cliente, created = Cliente.objects.get_or_create(
            cpf_cnpj=cpf_limpo,
            defaults={"nome_razao_social": nome, "email": email},
        )
        if not created:
            cliente.nome_razao_social = nome
            if email:
                cliente.email = email
            cliente.save()

        status_inicial = StatusCRM.objects.filter(
            nome__iexact="SEM TRATAMENTO", tipo__iexact="Tratamento"
        ).first()
        if not status_inicial:
            status_inicial = StatusCRM.objects.filter(tipo__iexact="Tratamento").first()

        plano_id = dados.get("plano")
        forma_pagamento_id = dados.get("forma_pagamento")
        plano = Plano.objects.filter(pk=plano_id).first() if plano_id else None
        forma_pagamento = FormaPagamento.objects.filter(pk=forma_pagamento_id).first() if forma_pagamento_id else None

        # Data de nascimento
        data_nasc = None
        dn = dados.get("data_nascimento")
        if dn:
            if isinstance(dn, date):
                data_nasc = dn
            elif isinstance(dn, str) and dn.strip():
                for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
                    try:
                        data_nasc = datetime.strptime(dn.strip()[:10], fmt).date()
                        break
                    except ValueError:
                        continue

        venda = Venda.objects.create(
            cliente=cliente,
            vendedor=vendedor,
            plano=plano,
            forma_pagamento=forma_pagamento,
            status_tratamento=status_inicial,
            forma_entrada=(dados.get("forma_entrada") or "APP").upper()[:10],
            tem_fixo=bool(dados.get("tem_fixo", False)),
            gerada_os_automatica=bool(dados.get("gerada_os_automatica", False)),
            telefone1=dados.get("telefone1"),
            telefone2=dados.get("telefone2"),
            nome_mae=(dados.get("nome_mae") or "").strip().upper() or None,
            data_nascimento=data_nasc,
            cpf_representante_legal=(dados.get("cpf_representante_legal") or "").strip() or None,
            nome_representante_legal=(dados.get("nome_representante_legal") or "").strip().upper() or None,
            cep=dados.get("cep"),
            logradouro=(dados.get("logradouro") or "").strip().upper() or None,
            numero_residencia=(dados.get("numero_residencia") or "").strip().upper() or None,
            complemento=(dados.get("complemento") or "").strip().upper() or None,
            bairro=(dados.get("bairro") or "").strip().upper() or None,
            cidade=(dados.get("cidade") or "").strip().upper() or None,
            estado=(dados.get("estado") or "").strip().upper()[:2] if dados.get("estado") else None,
            ponto_referencia=(dados.get("ponto_referencia") or "").strip().upper() or None,
            observacoes=(dados.get("observacoes") or "").strip() or None,
            ativo=True,
        )
        try:
            from crm_app.services.cnpj_mei_service import persistir_classificacao_mei
            persistir_classificacao_mei(cliente, venda)
        except Exception:
            logger.exception('[CRM WhatsApp] Erro ao classificar MEI/NMEI venda #%s', venda.id)
        logger.info(f"[CRM WhatsApp] Venda #{venda.id} cadastrada para vendedor {vendedor.username}")
        return venda.id, None
    except Exception as e:
        logger.exception(f"[CRM WhatsApp] Erro ao cadastrar venda: {e}")
        return None, str(e)
