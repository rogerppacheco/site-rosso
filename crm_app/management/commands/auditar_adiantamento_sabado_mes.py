"""Auditoria de adiantamento sábado para um mês de comissão (folha)."""
from datetime import datetime

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from crm_app.comissao_folha_service import annotate_data_folha_comissao, calcular_folha_mes
from crm_app.models import PagamentoComissao, Venda
from crm_app.services.adiantamento_sabado_service import (
    _data_abertura_os_estorno,
    calcular_descontos_adiantamento_sabado_folha,
    coletar_vendas_adiantamento_sabado_sem_data_abertura,
    comissao_ja_adiantada_venda,
    status_esteira_eh_agendado_ou_pendenciada,
    status_esteira_eh_cancelada,
    status_esteira_eh_instalada,
    venda_elegivel_estorno_adiantamento_sabado,
    venda_entra_estorno_adiantamento_sabado_mes,
)

User = get_user_model()


class Command(BaseCommand):
    help = 'Audita vendas com adiantamento sábado para um mês de comissão (ex.: --ano 2026 --mes 5).'

    def add_arguments(self, parser):
        parser.add_argument('--ano', type=int, required=True)
        parser.add_argument('--mes', type=int, required=True)

    def handle(self, *args, **options):
        ano, mes = options['ano'], options['mes']
        if not (1 <= mes <= 12):
            self.stdout.write(self.style.ERROR('Mês inválido.'))
            return

        di = datetime(ano, mes, 1).date()
        df = datetime(ano + 1, 1, 1).date() if mes == 12 else datetime(ano, mes + 1, 1).date()
        data_inicio = datetime(ano, mes, 1)
        data_fim = datetime(ano, mes + 1, 1) if mes < 12 else datetime(ano + 1, 1, 1)

        self.stdout.write(self.style.MIGRATE_HEADING(f'\n=== Auditoria adiantamento sábado — {mes:02d}/{ano} ===\n'))

        pag = PagamentoComissao.objects.filter(referencia_ano=ano, referencia_mes=mes).first()
        if pag:
            self.stdout.write(
                f'Folha {mes:02d}/{ano}: FECHADA em {pag.data_fechamento} '
                f'(pago consultores R$ {pag.total_pago_consultores})'
            )
        else:
            self.stdout.write(f'Folha {mes:02d}/{ano}: ABERTA (sem PagamentoComissao)')

        qs_marcado = Venda.objects.filter(
            ativo=True,
            adiantamento_sabado_marcado=True,
        ).exclude(adiantamento_sabado_valor__isnull=True).exclude(
            adiantamento_sabado_valor=0
        ).select_related('status_esteira', 'vendedor', 'cliente')

        # Universo relevante ao mês
        relevantes = []
        for v in qs_marcado.order_by('id'):
            st = (v.status_esteira.nome if v.status_esteira else '') or ''
            motivo_rel = None
            if v.adiantamento_sabado_marcado_em:
                me = timezone.localtime(v.adiantamento_sabado_marcado_em).date()
                if di <= me < df:
                    motivo_rel = 'marcado_no_mes'
            if status_esteira_eh_instalada(v.status_esteira):
                v_ann = annotate_data_folha_comissao(Venda.objects.filter(pk=v.pk)).first()
                dfc = getattr(v_ann, 'data_folha_comissao', None)
                if dfc and di <= dfc < df:
                    motivo_rel = motivo_rel or 'instalada_folha_mes'
            if status_esteira_eh_cancelada(v.status_esteira) or status_esteira_eh_agendado_ou_pendenciada(
                v.status_esteira
            ):
                dab = _data_abertura_os_estorno(v)
                if dab and di <= dab < df:
                    motivo_rel = motivo_rel or 'abertura_os_no_mes'
                elif venda_elegivel_estorno_adiantamento_sabado(v) and not dab:
                    motivo_rel = motivo_rel or 'sem_data_abertura'
            if venda_entra_estorno_adiantamento_sabado_mes(v, di, df):
                motivo_rel = motivo_rel or 'estorno_folha_mes'
            if getattr(v, 'flag_desc_adiantamento_sabado', False):
                motivo_rel = motivo_rel or 'flag_estorno_ja'
            if motivo_rel:
                relevantes.append((v, motivo_rel, st))

        self.stdout.write(f'\nVendas com adiantamento sábado relevantes a {mes:02d}/{ano}: {len(relevantes)}')

        alertas_sem_abertura: list[dict] = []
        for consultor in User.objects.filter(is_active=True).order_by('username'):
            alertas_sem_abertura.extend(
                coletar_vendas_adiantamento_sabado_sem_data_abertura(consultor, di, df)
            )
        if alertas_sem_abertura:
            self.stdout.write(
                self.style.WARNING(
                    f'\nALERTAS — vendas sem data_abertura (não entram no estorno): {len(alertas_sem_abertura)}'
                )
            )
            for a in alertas_sem_abertura:
                self.stdout.write(
                    f'  #{a["venda_id"]} | OS {a.get("os") or "—"} | {a.get("nome") or "-"} | {a.get("situacao")}'
                )

        # Estornos calculados na folha
        estorno_por_venda = {}
        for consultor in User.objects.filter(is_active=True).order_by('username'):
            for item in calcular_descontos_adiantamento_sabado_folha(consultor, data_inicio, data_fim):
                estorno_por_venda[item['venda_id']] = item

        self.stdout.write(
            f'Estornos na folha {mes:02d}/{ano} (regra atual): {len(estorno_por_venda)} '
            f'(total R$ {sum(x["valor"] for x in estorno_por_venda.values()):,.2f})'
        )

        problemas = []
        ok = []

        for v, motivo_rel, st in relevantes:
            vendedor = v.vendedor.username if v.vendedor else '-'
            cliente = (v.cliente.nome_razao_social[:35] if v.cliente else '-')
            linha_base = (
                f'#{v.id} | {vendedor} | {st} | val=R${float(v.adiantamento_sabado_valor or 0):.2f} | '
                f'antecip={v.antecipacao_comissao} | quitado={bool(v.adiantamento_sabado_quitado_em)} | '
                f'flag_desc={v.flag_desc_adiantamento_sabado} | {motivo_rel}'
            )

            if status_esteira_eh_instalada(v.status_esteira):
                if (
                    v.adiantamento_sabado_marcado
                    and not v.adiantamento_sabado_quitado_em
                    and not v.flag_desc_adiantamento_sabado
                    and not v.antecipacao_comissao
                ):
                    problemas.append(('PAGARIA_2X', linha_base, 'Instalada com adiant. sábado sem quitação nem estorno'))
                elif v.adiantamento_sabado_quitado_em and not v.antecipacao_comissao:
                    problemas.append(('SYNC_ANTECIP', linha_base, 'quitado_em preenchido mas antecipacao_comissao=False'))
                elif v.flag_desc_adiantamento_sabado and comissao_ja_adiantada_venda(v):
                    problemas.append(
                        ('ESTORNO_BLOQUEIA_PAG', linha_base,
                         'Estornou na folha mas comissao_ja_adiantada ainda exclui da QTD A PAGAR')
                    )
                elif v.flag_desc_adiantamento_sabado and not comissao_ja_adiantada_venda(v):
                    ok.append(('ESTORNO_DEPOIS_INSTALA_OK', linha_base))
                elif comissao_ja_adiantada_venda(v) and not v.flag_desc_adiantamento_sabado:
                    ok.append(('QUITADA_OK', linha_base))
                else:
                    ok.append(('INSTALADA_OK', linha_base))
            elif venda_elegivel_estorno_adiantamento_sabado(v):
                if v.id in estorno_por_venda:
                    ok.append(('ESTORNO_FOLHA_OK', linha_base + f' | estorno={estorno_por_venda[v.id]["motivo"]}'))
                elif venda_entra_estorno_adiantamento_sabado_mes(v, di, df):
                    problemas.append(('ESTORNO_FALTANDO', linha_base, 'Elegível a estorno na folha mas não aparece no cálculo'))
                elif not _data_abertura_os_estorno(v):
                    problemas.append(
                        (
                            'SEM_DATA_ABERTURA',
                            linha_base,
                            'Sem data de abertura da O.S. — estorno não entra na folha até correção',
                        )
                    )
                else:
                    dab = _data_abertura_os_estorno(v)
                    problemas.append(
                        (
                            'ABERTURA_FORA_MES',
                            linha_base,
                            f'Abertura O.S. {dab} fora do mês da folha (safra = abertura)',
                        )
                    )
            else:
                ok.append(('OUTRO', linha_base))

        # Instaladas na folha May com adiantamento — resumo QTD A PAGAR
        vendas_folha = annotate_data_folha_comissao(
            Venda.objects.filter(ativo=True, status_esteira__nome__iexact='INSTALADA')
        ).filter(data_folha_comissao__gte=di, data_folha_comissao__lt=df).select_related(
            'status_esteira', 'vendedor'
        )
        folha_adiant = [v for v in vendas_folha if v.adiantamento_sabado_marcado]
        pagaria = [v for v in folha_adiant if not comissao_ja_adiantada_venda(v)]
        antecipada = [v for v in folha_adiant if comissao_ja_adiantada_venda(v)]

        self.stdout.write(f'\nInstaladas na folha {mes:02d}/{ano} com adiant. sábado: {len(folha_adiant)}')
        self.stdout.write(f'  - QTD A PAGAR (nao antecipada): {len(pagaria)}')
        self.stdout.write(f'  - QTD ANTECIPADA / quitada: {len(antecipada)}')

        if problemas:
            self.stdout.write(self.style.ERROR(f'\nPROBLEMAS ({len(problemas)}):'))
            for cod, linha, desc in problemas:
                self.stdout.write(f'  [{cod}] {linha}')
                self.stdout.write(f'         -> {desc}')
        else:
            self.stdout.write(self.style.SUCCESS('\nOK: Nenhum problema detectado nas regras auditadas.'))

        self.stdout.write(f'\n--- Detalhe estornos na folha ({len(estorno_por_venda)}) ---')
        for vid, item in sorted(estorno_por_venda.items()):
            v = Venda.objects.filter(pk=vid).select_related('vendedor', 'status_esteira').first()
            if not v:
                continue
            vend = v.vendedor.username if v.vendedor else '-'
            st = (v.status_esteira.nome if v.status_esteira else '-')
            self.stdout.write(
                f'  #{vid} | {vend} | {st} | R${item["valor"]:.2f} | {item["motivo"]}'
            )

        self.stdout.write(f'\n--- Amostra OK ({min(len(ok), 15)} de {len(ok)}) ---')
        for cod, linha in ok[:15]:
            self.stdout.write(f'  [{cod}] {linha}')

        # Resumo folha agregado
        folha = calcular_folha_mes(ano, mes)
        total_sab = sum(
            float(d.get('valor', 0))
            for vd in folha.get('vendedores', [])
            for d in vd.get('resumo', {}).get('detalhes_descontos', [])
            if 'adiantamento sábado' in (d.get('motivo') or '').lower()
        )
        self.stdout.write(f'\nTotal descontos adiant. sábado na folha agregada: R$ {total_sab:,.2f}')
        self.stdout.write('')
