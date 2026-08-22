"""Importação e consulta de preços Nio por município (planilha GDP)."""
from __future__ import annotations

import logging
import re
import unicodedata
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

import pandas as pd
from django.db import transaction
from django.utils import timezone

from crm_app.models import (
    FormaPagamento,
    GdpPrecoMunicipio,
    LogImportacaoGdpPreco,
    Plano,
    Venda,
)

logger = logging.getLogger(__name__)

SHEET_PAP_LOCAL = 'PAP (Local)'
COLUNAS_MEIO_PAGAMENTO = {
    'OFERTA PRINCIPAL CARTAO': 'CARTAO',
    'OFERTA PRINCIPAL DACC': 'DACC',
    'OFERTA PRINCIPAL BOLETO': 'BOLETO',
}
REGEX_OFERTA = re.compile(r'(\d+)\s*\(R\$\s*([\d,\.]+)\)', re.IGNORECASE)
DESCONTO_CARTAO_LEGADO = Decimal('10.00')
DESCONTO_CARTAO_600 = Decimal('10.00')
DESCONTO_CARTAO_800_1GB = Decimal('15.00')
VALOR_FIXO_NIO_MENSAL = Decimal('30.00')


class GdpPrecoImportError(Exception):
    """Erro de validação ou parse na importação GDP."""


def normalizar_municipio(nome: str) -> str:
    """Remove acentos e padroniza para comparação de municípios."""
    if not nome:
        return ''
    texto = unicodedata.normalize('NFKD', str(nome))
    texto = ''.join(ch for ch in texto if not unicodedata.combining(ch))
    return re.sub(r'\s+', ' ', texto).strip().upper()


def parse_oferta_string(oferta: str) -> list[tuple[int, int, Decimal]]:
    """
    Converte string GDP em lista (velocidade_mbps, indice_oferta, valor).

    Ex.: "500 (R$90,00) 600 (R$95,00) 1000 (R$135,00) 1000 (R$145,00)"
    """
    if not oferta or (isinstance(oferta, float) and pd.isna(oferta)):
        return []

    contagem_velocidade: dict[int, int] = {}
    resultado: list[tuple[int, int, Decimal]] = []

    for match in REGEX_OFERTA.finditer(str(oferta)):
        velocidade = int(match.group(1))
        valor_bruto = match.group(2).replace('.', '').replace(',', '.')
        try:
            valor = Decimal(valor_bruto).quantize(Decimal('0.01'))
        except InvalidOperation as exc:
            raise GdpPrecoImportError(f'Valor inválido na oferta: {match.group(0)}') from exc

        indice = contagem_velocidade.get(velocidade, 0)
        contagem_velocidade[velocidade] = indice + 1
        resultado.append((velocidade, indice, valor))

    return resultado


def mapear_forma_pagamento_gdp(nome_forma: str) -> Optional[str]:
    """Mapeia nome da forma de pagamento para chave GDP."""
    if not nome_forma:
        return None
    nome = nome_forma.upper()
    if 'CRÉDITO' in nome or 'CREDITO' in nome or 'CART' in nome:
        return 'CARTAO'
    if 'DÉBITO' in nome or 'DEBITO' in nome or 'DACC' in nome:
        return 'DACC'
    if 'BOLETO' in nome:
        return 'BOLETO'
    return None


def resolver_chave_gdp_plano(plano: Plano) -> tuple[int, int]:
    """Retorna (velocidade_mbps, indice_oferta) para lookup na tabela GDP."""
    if plano.gdp_velocidade_mbps:
        return int(plano.gdp_velocidade_mbps), int(plano.gdp_indice_oferta or 0)

    nome = (plano.nome or '').upper()
    if '500' in nome:
        return 500, 0
    if '600' in nome:
        return 600, 0
    if '800' in nome:
        return 800, 0
    if '700' in nome or 'SUPER' in nome:
        return 800, 0
    if 'ULTRA' in nome or '1GB' in nome or '1 GB' in nome:
        return 1000, 1
    if '1000' in nome or '1G' in nome:
        return 1000, 0
    return 1000, 0


def desconto_cartao_legado_plano(plano: Plano) -> Decimal:
    """Desconto fixo no cartão quando não há preço GDP para o município."""
    velocidade, _ = resolver_chave_gdp_plano(plano)
    if velocidade in (800, 1000):
        return DESCONTO_CARTAO_800_1GB
    if velocidade == 600:
        return DESCONTO_CARTAO_600
    return DESCONTO_CARTAO_LEGADO


def _log_vigente_id() -> Optional[int]:
    log = (
        LogImportacaoGdpPreco.objects.filter(status='SUCESSO', vigente=True)
        .order_by('-finalizado_em', '-id')
        .values_list('id', flat=True)
        .first()
    )
    return log


def buscar_preco_gdp(
    *,
    cidade: str,
    uf: str = '',
    cod_ibge: str = '',
    plano: Plano,
    meio_pagamento: str,
    log_id: Optional[int] = None,
) -> Optional[Decimal]:
    """Busca preço na importação GDP vigente."""
    log_id = log_id or _log_vigente_id()
    if not log_id:
        return None

    meio = mapear_forma_pagamento_gdp(meio_pagamento)
    if not meio:
        return None

    velocidade, indice = resolver_chave_gdp_plano(plano)
    qs = GdpPrecoMunicipio.objects.filter(
        log_importacao_id=log_id,
        meio_pagamento=meio,
        velocidade_mbps=velocidade,
        indice_oferta=indice,
    )

    if cod_ibge:
        preco = qs.filter(cod_ibge=str(cod_ibge).strip()).values_list('valor', flat=True).first()
        if preco is not None:
            return preco

    municipio_norm = normalizar_municipio(cidade)
    uf_norm = (uf or '').strip().upper()
    if municipio_norm:
        filtro = qs.filter(municipio_normalizado=municipio_norm)
        if uf_norm:
            filtro = filtro.filter(uf=uf_norm)
        preco = filtro.values_list('valor', flat=True).first()
        if preco is not None:
            return preco

    return None


def calcular_valor_plano_legado(plano: Plano, forma_pagamento: Optional[FormaPagamento]) -> Decimal:
    """Fallback: valor cadastrado no plano com desconto por velocidade no cartão."""
    valor = Decimal(str(plano.valor))
    nome_fp = (forma_pagamento.nome or '') if forma_pagamento else ''
    if mapear_forma_pagamento_gdp(nome_fp) == 'CARTAO':
        valor = max(Decimal('0'), valor - desconto_cartao_legado_plano(plano))
    return valor.quantize(Decimal('0.01'))


def formatar_moeda_br(valor: Decimal | float) -> str:
    return f'R$ {float(valor):.2f}'.replace('.', ',')


def montar_texto_script_plano_auditoria(
    nome_plano: str,
    valor_plano: Decimal | float,
    forma_pagamento: str,
    *,
    tem_fixo: bool = False,
) -> str:
    """Texto do roteiro de auditoria (etapa Oferta & Pagto)."""
    nome = (nome_plano or '').strip().upper()
    forma = (forma_pagamento or '').strip().upper()
    valor_dec = Decimal(str(valor_plano)).quantize(Decimal('0.01'))
    valor_txt = formatar_moeda_br(valor_dec)
    if tem_fixo:
        total = valor_dec + VALOR_FIXO_NIO_MENSAL
        return (
            f'O plano que você contratou foi o {nome} com o valor de {valor_txt}, '
            f'mais o telefone fixo de {formatar_moeda_br(VALOR_FIXO_NIO_MENSAL)}, '
            f'totalizando {formatar_moeda_br(total)}, '
            f'e a forma de pagamento foi {forma}.'
        )
    return (
        f'O plano que você contratou foi o {nome} com o valor de {valor_txt} '
        f'e a forma de pagamento foi {forma}.'
    )


def resolver_valor_plano_venda(
    venda: Venda,
    *,
    log_id: Optional[int] = None,
) -> tuple[Decimal, dict[str, Any]]:
    """
    Resolve valor mensal do plano para uma venda.

    Retorna (valor, metadados) onde metadados indica se veio do GDP ou fallback legado.
    """
    if not venda.plano:
        return Decimal('0.00'), {'origem': 'sem_plano'}

    forma = venda.forma_pagamento
    nome_fp = (forma.nome or '') if forma else ''

    preco_gdp = buscar_preco_gdp(
        cidade=venda.cidade or '',
        uf=venda.estado or '',
        cod_ibge='',
        plano=venda.plano,
        meio_pagamento=nome_fp,
        log_id=log_id,
    )
    if preco_gdp is not None:
        return preco_gdp, {'origem': 'gdp', 'meio_pagamento': mapear_forma_pagamento_gdp(nome_fp)}

    valor_legado = calcular_valor_plano_legado(venda.plano, forma)
    return valor_legado, {
        'origem': 'legado',
        'desconto_cartao': desconto_cartao_legado_plano(venda.plano),
    }


def resolver_valor_plano_params(
    *,
    plano_id: int,
    forma_pagamento_id: Optional[int],
    cidade: str,
    uf: str = '',
    cod_ibge: str = '',
) -> dict[str, Any]:
    """Endpoint helper: resolve valor e retorna payload JSON-friendly."""
    plano = Plano.objects.filter(id=plano_id, ativo=True).select_related('operadora').first()
    if not plano:
        return {'encontrado': False, 'erro': 'Plano não encontrado'}

    forma: Optional[FormaPagamento] = None
    if forma_pagamento_id:
        forma = FormaPagamento.objects.filter(id=forma_pagamento_id, ativo=True).first()

    nome_fp = (forma.nome or '') if forma else ''
    preco_gdp = buscar_preco_gdp(
        cidade=cidade,
        uf=uf,
        cod_ibge=cod_ibge,
        plano=plano,
        meio_pagamento=nome_fp,
    )

    velocidade, indice = resolver_chave_gdp_plano(plano)
    if preco_gdp is not None:
        valor = preco_gdp
        origem = 'gdp'
    else:
        valor = calcular_valor_plano_legado(plano, forma)
        origem = 'legado'

    return {
        'encontrado': True,
        'valor': float(valor),
        'valor_formatado': f'R$ {valor:.2f}'.replace('.', ','),
        'origem': origem,
        'gdp_disponivel': _log_vigente_id() is not None,
        'velocidade_mbps': velocidade,
        'indice_oferta': indice,
        'meio_pagamento_gdp': mapear_forma_pagamento_gdp(nome_fp),
        'cidade_normalizada': normalizar_municipio(cidade),
    }


class GdpPrecoImportService:
    """Processa planilha GDP e substitui a base vigente de preços."""

    def __init__(self, log_id: int) -> None:
        self.log_id = log_id
        self.log: Optional[LogImportacaoGdpPreco] = None

    def _carregar_log(self) -> LogImportacaoGdpPreco:
        if self.log is None:
            self.log = LogImportacaoGdpPreco.objects.get(id=self.log_id)
        return self.log

    def processar_arquivo(self, arquivo_path: str) -> None:
        """Lê xlsx, persiste preços e marca importação como vigente."""
        log = self._carregar_log()
        inicio = timezone.now()

        try:
            df = pd.read_excel(arquivo_path, sheet_name=SHEET_PAP_LOCAL)
        except Exception as exc:
            self._finalizar_erro(log, f'Aba "{SHEET_PAP_LOCAL}" não encontrada ou ilegível: {exc}')
            return

        colunas_faltantes = [c for c in COLUNAS_MEIO_PAGAMENTO if c not in df.columns]
        if colunas_faltantes:
            self._finalizar_erro(log, f'Colunas ausentes: {", ".join(colunas_faltantes)}')
            return

        if 'MUNICIPIO' not in df.columns or 'UF' not in df.columns:
            self._finalizar_erro(log, 'Colunas MUNICIPIO e UF são obrigatórias.')
            return

        registros: list[GdpPrecoMunicipio] = []
        municipios_processados = 0

        for _, row in df.iterrows():
            municipio = str(row.get('MUNICIPIO') or '').strip()
            uf = str(row.get('UF') or '').strip().upper()
            if not municipio or not uf:
                continue

            cod_ibge_raw = row.get('COD_IBGE')
            cod_ibge = ''
            if cod_ibge_raw is not None and not (isinstance(cod_ibge_raw, float) and pd.isna(cod_ibge_raw)):
                cod_ibge = str(int(cod_ibge_raw)) if str(cod_ibge_raw).replace('.', '').isdigit() else str(cod_ibge_raw).strip()

            municipio_norm = normalizar_municipio(municipio)
            municipios_processados += 1

            for coluna, meio in COLUNAS_MEIO_PAGAMENTO.items():
                ofertas = parse_oferta_string(row.get(coluna))
                for velocidade, indice, valor in ofertas:
                    registros.append(
                        GdpPrecoMunicipio(
                            log_importacao_id=log.id,
                            uf=uf,
                            municipio=municipio.upper(),
                            municipio_normalizado=municipio_norm,
                            cod_ibge=cod_ibge or None,
                            meio_pagamento=meio,
                            velocidade_mbps=velocidade,
                            indice_oferta=indice,
                            valor=valor,
                        )
                    )

        if not registros:
            self._finalizar_erro(log, 'Nenhum preço válido encontrado na planilha.')
            return

        try:
            with transaction.atomic():
                LogImportacaoGdpPreco.objects.filter(vigente=True).update(vigente=False)
                GdpPrecoMunicipio.objects.filter(log_importacao_id=log.id).delete()
                GdpPrecoMunicipio.objects.bulk_create(registros, batch_size=1000)

                log.status = 'SUCESSO'
                log.vigente = True
                log.finalizado_em = timezone.now()
                log.total_municipios = municipios_processados
                log.total_precos = len(registros)
                log.mensagem = (
                    f'Importados {municipios_processados} municípios '
                    f'({len(registros)} preços).'
                )
                log.save(
                    update_fields=[
                        'status',
                        'vigente',
                        'finalizado_em',
                        'total_municipios',
                        'total_precos',
                        'mensagem',
                    ]
                )
        except Exception as exc:
            logger.exception('[GDP] Erro ao persistir preços')
            self._finalizar_erro(log, str(exc))
            return

        log.calcular_duracao()
        logger.info(
            '[GDP] Importação %s concluída em %ss (%s municípios, %s preços)',
            log.id,
            (timezone.now() - inicio).total_seconds(),
            municipios_processados,
            len(registros),
        )

    def _finalizar_erro(self, log: LogImportacaoGdpPreco, mensagem: str) -> None:
        log.status = 'ERRO'
        log.vigente = False
        log.finalizado_em = timezone.now()
        log.mensagem_erro = mensagem
        log.save(update_fields=['status', 'vigente', 'finalizado_em', 'mensagem_erro'])
        log.calcular_duracao()
        logger.error('[GDP] Importação %s falhou: %s', log.id, mensagem)
