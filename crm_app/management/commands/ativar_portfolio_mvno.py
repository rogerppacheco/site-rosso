"""
Troca do portfólio Nio para os planos com benefício móvel (MVNO, piloto 2026).

Uso (sempre rode primeiro sem --aplicar para revisar):
    python manage.py ativar_portfolio_mvno
    python manage.py ativar_portfolio_mvno --aplicar
    python manage.py ativar_portfolio_mvno --aplicar --desativar-antigos
    python manage.py ativar_portfolio_mvno --reverter --aplicar

- Cria/atualiza os planos novos (identificados por portfolio=MVNO_2026 + nome).
- Comissão dos planos novos: copia matriz faixa × plano, valores por vendedor,
  valores do plano e recebimento da operadora do plano antigo de mesma banda.
- --desativar-antigos inativa os demais planos ativos da operadora Nio e marca
  portfolio=PRE_MVNO_DESATIVADO para permitir --reverter.
- Nunca apaga planos: vendas antigas continuam apontando para o plano original.
"""
from __future__ import annotations

from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from crm_app.comissao_folha_service import _plano_nome_to_banda
from crm_app.models import (
    ComissaoOperadora,
    Operadora,
    Plano,
    PlanoValoresComissao,
    PlanoValoresComissaoVendedor,
    RegraComissaoFaixaPlano,
)

PORTFOLIO = 'MVNO_2026'
MARCA_DESATIVADO = 'PRE_MVNO_DESATIVADO'

_MOVEL = 'WhatsApp ilimitado (texto, áudio, voz e fotos); SMS ilimitado; Voz nacional ilimitada'
_B2B = 'Maquininha PagBank com taxas exclusivas; Proteção Digital McAfee'

PLANOS_MVNO = [
    {
        'nome': 'NIO FIBRA 600MB', 'segmento': 'B2C', 'valor': '110.00', 'valor_cartao': '95.00',
        'gdp_velocidade_mbps': 600, 'gdp_indice_oferta': 0, 'qtd_chips_moveis': 0, 'franquia_movel_gb': 0,
        'beneficios': 'Roteador Wi-Fi 5',
    },
    {
        'nome': 'NIO ESSENCIAL 700MB', 'segmento': 'B2C', 'valor': '140.00', 'valor_cartao': '125.00',
        'gdp_velocidade_mbps': 700, 'gdp_indice_oferta': 0, 'qtd_chips_moveis': 1, 'franquia_movel_gb': 10,
        'beneficios': f'Roteador Wi-Fi 6; 1 chip 10 GB internet 5G; {_MOVEL}',
    },
    {
        'nome': 'NIO SUPER 800MB', 'segmento': 'B2C', 'valor': '170.00', 'valor_cartao': '155.00',
        'gdp_velocidade_mbps': 800, 'gdp_indice_oferta': 0, 'qtd_chips_moveis': 1, 'franquia_movel_gb': 20,
        'beneficios': f'Roteador Wi-Fi 6; 1 chip 20 GB internet 5G; Waze ilimitado; {_MOVEL}',
    },
    {
        'nome': 'NIO ULTRA 1GB', 'segmento': 'B2C', 'valor': '200.00', 'valor_cartao': '185.00',
        'gdp_velocidade_mbps': 1000, 'gdp_indice_oferta': 1, 'qtd_chips_moveis': 2, 'franquia_movel_gb': 20,
        'beneficios': f'Roteador Wi-Fi 6; 2 chips 20 GB internet 5G; Waze ilimitado; {_MOVEL}',
    },
    {
        'nome': 'NIO FIBRA ESSENCIAL 400MB B2B', 'segmento': 'B2B', 'valor': '70.00', 'valor_cartao': None,
        'gdp_velocidade_mbps': 400, 'gdp_indice_oferta': 0, 'qtd_chips_moveis': 0, 'franquia_movel_gb': 0,
        'beneficios': f'Roteador Wi-Fi 5; {_B2B}',
    },
    {
        'nome': 'NIO SUPER 700MB B2B', 'segmento': 'B2B', 'valor': '110.00', 'valor_cartao': '95.00',
        'gdp_velocidade_mbps': 700, 'gdp_indice_oferta': 0, 'qtd_chips_moveis': 1, 'franquia_movel_gb': 10,
        'beneficios': f'Roteador Wi-Fi 6; 1 chip 10 GB internet 5G; {_MOVEL}; {_B2B}',
    },
    {
        'nome': 'NIO FIBRA ULTRA 900MB B2B', 'segmento': 'B2B', 'valor': '130.00', 'valor_cartao': '115.00',
        'gdp_velocidade_mbps': 900, 'gdp_indice_oferta': 0, 'qtd_chips_moveis': 0, 'franquia_movel_gb': 0,
        'beneficios': f'Roteador Wi-Fi 6; {_B2B}; Recurso de negociação (fora da folheteria)',
    },
    {
        'nome': 'NIO TOTAL 1GB B2B', 'segmento': 'B2B', 'valor': '180.00', 'valor_cartao': '165.00',
        'gdp_velocidade_mbps': 1000, 'gdp_indice_oferta': 0, 'qtd_chips_moveis': 2, 'franquia_movel_gb': 20,
        'beneficios': f'Roteador Wi-Fi 6; 2 chips 20 GB internet 5G; Waze ilimitado; {_MOVEL}; {_B2B}',
    },
]

# Banda do plano novo → bandas dos planos antigos usados como referência de comissão.
BANDAS_REFERENCIA = {
    '400MB': ['400MB', '500MB', '600MB'],
    '600MB': ['600MB', '500MB'],
    '700MB': ['700MB', '800MB'],
    '800MB': ['800MB', '700MB'],
    '900MB': ['900MB', '800MB', '700MB'],
    '1GB': ['1GB'],
}


def _dec(valor) -> Decimal | None:
    return Decimal(valor) if valor is not None else None


class Command(BaseCommand):
    help = 'Ativa o portfólio MVNO 2026 da Nio (simulação por padrão; use --aplicar para gravar).'

    def add_arguments(self, parser):
        parser.add_argument('--aplicar', action='store_true', help='Grava as alterações (sem isso é simulação).')
        parser.add_argument(
            '--desativar-antigos', action='store_true',
            help='Inativa os demais planos ativos da operadora (reversível com --reverter).',
        )
        parser.add_argument('--reverter', action='store_true', help='Desfaz a troca de portfólio.')
        parser.add_argument('--operadora-id', type=int, help='ID da operadora Nio (padrão: única com usa_pap_nio).')
        parser.add_argument(
            '--manter-ids', default='',
            help='IDs de planos antigos que não devem ser inativados (ex.: 12,15).',
        )

    def handle(self, *args, **opts):
        operadora = self._resolver_operadora(opts.get('operadora_id'))
        aplicar = opts['aplicar']
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"Operadora: {operadora.nome} (id={operadora.id}) — {'APLICANDO' if aplicar else 'SIMULAÇÃO (nada será gravado)'}"
        ))

        with transaction.atomic():
            if opts['reverter']:
                self._reverter(operadora)
            else:
                manter_ids = {int(i) for i in opts['manter_ids'].split(',') if i.strip().isdigit()}
                antigos = list(
                    Plano.objects.filter(operadora=operadora, ativo=True)
                    .exclude(portfolio=PORTFOLIO)
                    .order_by('id')
                )
                referencias_base = list(
                    Plano.objects.filter(operadora=operadora)
                    .exclude(portfolio=PORTFOLIO)
                    .select_related('valores_comissao')
                    .order_by('id')
                )
                self._criar_ou_atualizar_novos(operadora, referencias_base)
                if opts['desativar_antigos']:
                    self._desativar_antigos(antigos, manter_ids)
                else:
                    self.stdout.write(
                        f'\nPlanos antigos ativos ({len(antigos)}) permanecem ativos. '
                        'Use --desativar-antigos para inativá-los.'
                    )
                    for p in antigos:
                        self.stdout.write(f'  - id={p.id} {p.nome} (R$ {p.valor})')

            if not aplicar:
                transaction.set_rollback(True)
                self.stdout.write(self.style.WARNING('\nSimulação concluída. Rode com --aplicar para gravar.'))
            else:
                self.stdout.write(self.style.SUCCESS('\nAlterações gravadas.'))

    def _resolver_operadora(self, operadora_id: int | None) -> Operadora:
        if operadora_id:
            try:
                return Operadora.objects.get(id=operadora_id)
            except Operadora.DoesNotExist as exc:
                raise CommandError(f'Operadora id={operadora_id} não encontrada.') from exc
        candidatas = list(Operadora.objects.filter(usa_pap_nio=True))
        if len(candidatas) != 1:
            candidatas = list(Operadora.objects.filter(nome__iexact='NIO'))
        if len(candidatas) != 1:
            nomes = ', '.join(f'{o.id}={o.nome}' for o in Operadora.objects.all())
            raise CommandError(f'Não foi possível identificar a operadora Nio. Informe --operadora-id ({nomes}).')
        return candidatas[0]

    def _escolher_referencia(self, banda: str | None, referencias: list[Plano]) -> Plano | None:
        for banda_ref in BANDAS_REFERENCIA.get(banda or '', []):
            candidatos = [p for p in referencias if _plano_nome_to_banda(p) == banda_ref]
            if not candidatos:
                continue

            def prioridade(p: Plano):
                vc = getattr(p, 'valores_comissao', None)
                personalizado = bool(vc and vc.banda_comissao == 'PERSONALIZADO')
                return (not p.ativo, personalizado, 'SEM MESH' in (p.nome or '').upper(), p.id)

            return sorted(candidatos, key=prioridade)[0]
        return None

    def _criar_ou_atualizar_novos(self, operadora: Operadora, referencias: list[Plano]) -> None:
        from crm_app.services.comissao_matriz_service import sincronizar_plano_em_todas_faixas

        self.stdout.write('\nPlanos do portfólio MVNO:')
        for dados in PLANOS_MVNO:
            campos = {
                'valor': _dec(dados['valor']),
                'valor_cartao': _dec(dados['valor_cartao']),
                'segmento': dados['segmento'],
                'gdp_velocidade_mbps': dados['gdp_velocidade_mbps'],
                'gdp_indice_oferta': dados['gdp_indice_oferta'],
                'ignorar_preco_gdp': True,
                'qtd_chips_moveis': dados['qtd_chips_moveis'],
                'franquia_movel_gb': dados['franquia_movel_gb'],
                'beneficios': dados['beneficios'],
                'ativo': True,
            }
            plano = Plano.objects.filter(operadora=operadora, portfolio=PORTFOLIO, nome=dados['nome']).first()
            criado = plano is None
            if criado:
                plano = Plano(operadora=operadora, portfolio=PORTFOLIO, nome=dados['nome'], **campos)
            else:
                for attr, val in campos.items():
                    setattr(plano, attr, val)

            banda = _plano_nome_to_banda(plano)
            ref = self._escolher_referencia(banda, referencias)
            if criado and ref is not None:
                plano.comissao_base = ref.comissao_base
            plano.save()

            ref_txt = f'ref. comissão: id={ref.id} {ref.nome}' if ref else 'sem referência (usa colunas 500/700/1GB)'
            cartao = f'R$ {plano.valor_cartao}' if plano.valor_cartao is not None else 'desconto padrão'
            self.stdout.write(
                f"  {'+ criar ' if criado else '~ atualizar'} {plano.nome} [{plano.segmento}] "
                f'R$ {plano.valor} / cartão {cartao} | banda {banda} | {ref_txt}'
            )
            if plano.valor_cartao is None:
                self.stdout.write(self.style.WARNING('      Valor no cartão não informado na apresentação.'))

            if ref is not None:
                self._copiar_comissao(ref, plano)
            sincronizar_plano_em_todas_faixas(plano)
            if not ComissaoOperadora.objects.filter(plano=plano).exists():
                ComissaoOperadora.objects.create(plano=plano, valor_base=Decimal('0'))

    def _copiar_comissao(self, ref: Plano, plano: Plano) -> None:
        for row in RegraComissaoFaixaPlano.objects.filter(plano=ref):
            RegraComissaoFaixaPlano.objects.get_or_create(
                faixa_id=row.faixa_id, plano=plano,
                defaults={'valor_pap': row.valor_pap, 'valor_cnpj': row.valor_cnpj},
            )
        for row in PlanoValoresComissaoVendedor.objects.filter(plano=ref):
            PlanoValoresComissaoVendedor.objects.get_or_create(
                config_id=row.config_id, plano=plano,
                defaults={'valor_pap': row.valor_pap, 'valor_cnpj': row.valor_cnpj},
            )
        vc_ref = PlanoValoresComissao.objects.filter(plano=ref).first()
        if vc_ref and not PlanoValoresComissao.objects.filter(plano=plano).exists():
            PlanoValoresComissao.objects.create(
                plano=plano,
                banda_comissao=vc_ref.banda_comissao,
                valor_pap=vc_ref.valor_pap,
                valor_cnpj=vc_ref.valor_cnpj,
                usa_comissao_cidade_especial=vc_ref.usa_comissao_cidade_especial,
                valor_pap_cidade_especial=vc_ref.valor_pap_cidade_especial,
                valor_cnpj_cidade_especial=vc_ref.valor_cnpj_cidade_especial,
                propagar_faixas=False,
                propagar_vendedores=vc_ref.propagar_vendedores,
            )
        co_ref = ComissaoOperadora.objects.filter(plano=ref).first()
        if co_ref and not ComissaoOperadora.objects.filter(plano=plano).exists():
            ComissaoOperadora.objects.create(plano=plano, valor_base=co_ref.valor_base)

    def _desativar_antigos(self, antigos: list[Plano], manter_ids: set[int]) -> None:
        self.stdout.write('\nInativando planos antigos:')
        for p in antigos:
            if p.id in manter_ids:
                self.stdout.write(f'  = mantido id={p.id} {p.nome}')
                continue
            p.ativo = False
            if not p.portfolio:
                p.portfolio = MARCA_DESATIVADO
            p.save(update_fields=['ativo', 'portfolio'])
            self.stdout.write(f'  - inativado id={p.id} {p.nome}')

    def _reverter(self, operadora: Operadora) -> None:
        self.stdout.write('\nRevertendo troca de portfólio:')
        for p in Plano.objects.filter(operadora=operadora, portfolio=MARCA_DESATIVADO):
            p.ativo = True
            p.portfolio = ''
            p.save(update_fields=['ativo', 'portfolio'])
            self.stdout.write(f'  + reativado id={p.id} {p.nome}')
        for p in Plano.objects.filter(operadora=operadora, portfolio=PORTFOLIO, ativo=True):
            p.ativo = False
            p.save(update_fields=['ativo'])
            self.stdout.write(f'  - inativado (MVNO) id={p.id} {p.nome}')
