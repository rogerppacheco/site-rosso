"""
Sincroniza ContratoM10 com a base ImportacaoChurn já importada.

Quando o churn é importado via /import/churn/ (ImportacaoChurnView), os registros
vão só para ImportacaoChurn; o M-10 NÃO é atualizado. Apenas o upload pela tela
"Importar Churn" do Bônus M-10 (/api/bonus-m10/importar-churn/) atualiza ContratoM10.

Este comando lê os registros em ImportacaoChurn (opcionalmente filtrados por
anomes_gross = mês da instalação/safra, ex.: 202507 para jul/25) e marca os
ContratoM10 correspondentes como CANCELADO.

IMPORTANTE: Filtrar por ANOMES_GROSS (data de instalação), NÃO por anomes_retirada.
A safra M-10 é pelo mês de instalação; anomes_retirada é quando cancelou.

O.S.: usa nr_ordem ou numero_pedido do churn (nessa ordem).

Uso:
  python manage.py sync_m10_da_base_churn
  python manage.py sync_m10_da_base_churn --anomes 202507
  python manage.py sync_m10_da_base_churn --anomes 202507 --dry-run
  python manage.py sync_m10_da_base_churn --anomes 202507 --consultar   # listar sem alterar
"""
from datetime import datetime

from dateutil.relativedelta import relativedelta
from django.core.management.base import BaseCommand

from crm_app.models import ContratoM10, ImportacaoChurn, SafraM10


def _normalize_os(val):
    s = (val or '').strip()
    if not s:
        return None
    if isinstance(s, str) and s.endswith('.0'):
        s = s[:-2]
    return str(s)


def _os_variants(os_val):
    """Gera variações de O.S. para matching com ContratoM10.ordem_servico."""
    s = _normalize_os(os_val)
    if not s:
        return []
    variants = [s]
    if s.isdigit() or (s.lstrip('0') and s.lstrip('0').isdigit()):
        variants.append(s.zfill(8))
        stripped = s.lstrip('0') or '0'
        if stripped not in variants:
            variants.append(stripped)
    if '-' in s:
        part = s.split('-', 1)[1].strip()
        if part and part not in variants:
            variants.append(part)
            if part.isdigit() or (part.lstrip('0') and part.lstrip('0').isdigit()):
                p8 = part.zfill(8)
                if p8 not in variants:
                    variants.append(p8)
    return variants


def _find_contrato_m10(os_val):
    for v in _os_variants(os_val):
        c = ContratoM10.objects.filter(ordem_servico=v).first()
        if c:
            return c
    return None


class Command(BaseCommand):
    help = 'Atualiza ContratoM10 (CANCELADO) a partir da base ImportacaoChurn já importada'

    def add_arguments(self, parser):
        parser.add_argument(
            '--anomes',
            type=str,
            default=None,
            help='Filtrar churn por anomes_gross = mes da instalacao/safra (ex.: 202507)',
        )
        parser.add_argument('--dry-run', action='store_true', help='Apenas simular, não alterar')
        parser.add_argument(
            '--consultar',
            action='store_true',
            help='Só listar quantos churns tem no filtro e exemplos de nr_ordem (não atualiza)',
        )

    def handle(self, *args, **options):
        anomes = options.get('anomes')
        dry_run = options.get('dry_run', False)
        consultar = options.get('consultar', False)

        qs = ImportacaoChurn.objects.all().order_by('id')
        if anomes:
            anomes = str(anomes).strip().replace('-', '').replace('/', '')
            if len(anomes) != 6:
                self.stdout.write(self.style.ERROR('Use --anomes AAAAMM (ex.: 202507)'))
                return
            from django.db.models import Q
            qs = qs.filter(
                Q(anomes_gross=anomes) |
                Q(anomes_gross='{}-{}'.format(anomes[:4], anomes[4:6]))
            )
            self.stdout.write('Churn filtrado por anomes_gross={} (mes instalacao)'.format(anomes))

        total = qs.count()
        self.stdout.write('Registros em ImportacaoChurn: {}'.format(total))

        if consultar:
            self.stdout.write('(modo --consultar: apenas listagem)')
            if total == 0:
                self.stdout.write('Nenhum churn no filtro. Verifique se a planilha tem ANOMES_GROSS e se foi importada.')
                return
            amostra = list(qs.values_list('nr_ordem', 'anomes_gross', 'anomes_retirada')[:20])
            self.stdout.write('Exemplos (nr_ordem, anomes_gross, anomes_retirada):')
            for nr, ag, ar in amostra:
                self.stdout.write('  {} | gross={} | retirada={}'.format(nr or '-', ag or '-', ar or '-'))
            if total > 20:
                self.stdout.write('  ... e mais {}'.format(total - 20))
            return

        if total == 0:
            self.stdout.write('Nenhum registro para processar. Use --consultar para ver o que ha no filtro.')
            return

        cancelados = 0
        ja_cancelados = 0
        nao_encontrados = 0
        sem_os = 0
        affected_safras = set()

        for ch in qs.iterator():
            os_candidato = ch.nr_ordem or ch.numero_pedido
            if not os_candidato or not str(os_candidato).strip():
                sem_os += 1
                continue

            contrato = _find_contrato_m10(os_candidato)
            if not contrato:
                nao_encontrados += 1
                if nao_encontrados <= 10:
                    self.stdout.write('  Nao encontrado ContratoM10 para O.S. {} (churn id={})'.format(
                        _normalize_os(os_candidato), ch.id
                    ))
                continue

            if contrato.status_contrato == 'CANCELADO':
                ja_cancelados += 1
                continue

            if not dry_run:
                contrato.status_contrato = 'CANCELADO'
                contrato.data_cancelamento = ch.dt_retirada
                contrato.motivo_cancelamento = (ch.motivo_retirada or '').strip() or 'CHURN'
                contrato.elegivel_bonus = False
                contrato.save(update_fields=[
                    'status_contrato', 'data_cancelamento', 'motivo_cancelamento', 'elegivel_bonus'
                ])
            if contrato.safra:
                affected_safras.add(contrato.safra)
            cancelados += 1
            if cancelados <= 20:
                self.stdout.write('  OK OS {} -> CANCELADO (ContratoM10 id={})'.format(
                    contrato.ordem_servico, contrato.id
                ))

        if not dry_run and affected_safras and cancelados > 0:
            for safra_str in affected_safras:
                try:
                    y, m = int(safra_str[:4]), int(safra_str[5:7])
                    mes_ref = datetime(y, m, 1).date()
                except (ValueError, IndexError):
                    continue
                safra_obj = SafraM10.objects.filter(mes_referencia=mes_ref).first()
                if not safra_obj:
                    continue
                data_fim = mes_ref + relativedelta(months=1)
                total_ativos = ContratoM10.objects.filter(
                    data_instalacao__gte=mes_ref,
                    data_instalacao__lt=data_fim,
                    status_contrato='ATIVO',
                ).count()
                safra_obj.total_ativos = total_ativos
                safra_obj.save(update_fields=['total_ativos'])
            self.stdout.write('Safras com total_ativos recalculado: {}'.format(', '.join(sorted(affected_safras))))

        self.stdout.write('')
        self.stdout.write('=' * 60)
        self.stdout.write('RESUMO')
        self.stdout.write('=' * 60)
        self.stdout.write('Contratos marcados CANCELADO: {}'.format(cancelados))
        self.stdout.write('Ja cancelados (ignorados): {}'.format(ja_cancelados))
        self.stdout.write('Churn sem O.S. (nr_ordem/numero_pedido): {}'.format(sem_os))
        self.stdout.write('ContratoM10 nao encontrado: {}'.format(nao_encontrados))
        if dry_run:
            self.stdout.write(self.style.WARNING('(dry-run: nenhuma alteracao feita)'))
        self.stdout.write('=' * 60)
