"""
Diagnóstico do cruzamento Churn x Vendas para comissão (desconto churn M0/M-1).

Lista registros na base de churn do mês, vendas instaladas no mês (por vendedor),
e indica quais O.S. batem e quais não (e por quê). Ajuda a descobrir por que o
desconto de churn não aparece para um vendedor (ex.: Alex).

Uso:
  python manage.py diagnosticar_churn 2025 12
  python manage.py diagnosticar_churn 2025 12 --username Alex
"""
from datetime import datetime
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model


def _norm_os(val):
    if val is None or (isinstance(val, str) and not val.strip()):
        return None
    s = str(val).strip()
    for prefix in ('OS-', 'OS', 'os-', 'os'):
        if s.upper().startswith(prefix) and len(s) > len(prefix):
            s = s[len(prefix):].strip()
            break
    if not s:
        return None
    return s.zfill(8) if len(s) <= 8 else s


def _norm_os_variantes(val):
    n = _norm_os(val)
    if not n:
        return set()
    return {n, n.lstrip('0') or '0'}


class Command(BaseCommand):
    help = 'Diagnóstico: churn do mês x vendas (cruzamento por O.S.)'

    def add_arguments(self, parser):
        parser.add_argument('ano', type=int, help='Ano (ex.: 2025)')
        parser.add_argument('mes', type=int, help='Mês 1-12 (ex.: 12)')
        parser.add_argument('--username', type=str, default=None, help='Filtrar por username do vendedor (ex.: Alex)')

    def handle(self, *args, **options):
        ano = options['ano']
        mes = options['mes']
        username = (options['username'] or '').strip()

        from crm_app.models import ImportacaoChurn, Venda

        User = get_user_model()
        ano_mes = ano * 100 + mes
        variantes_anomes = [str(ano_mes), f"{ano_mes // 100}-{ano_mes % 100:02d}", f"{ano_mes // 100}/{ano_mes % 100:02d}"]

        data_inicio = datetime(ano, mes, 1)
        if mes == 12:
            data_fim = datetime(ano + 1, 1, 1)
        else:
            data_fim = datetime(ano, mes + 1, 1)

        churns = list(
            ImportacaoChurn.objects.filter(anomes_gross__in=variantes_anomes)
            .exclude(nr_ordem__isnull=True).exclude(nr_ordem='')
            .values('id', 'nr_ordem', 'anomes_gross', 'numero_pedido')
        )
        set_os_churn = set()
        for c in churns:
            set_os_churn.update(_norm_os_variantes(str(c['nr_ordem']).strip()))

        self.stdout.write(f'\n=== Churn para comissão {mes}/{ano} (ANOMES_GROSS in {variantes_anomes}) ===')
        self.stdout.write(f'Total de registros na base churn: {len(churns)}')
        if churns:
            self.stdout.write('Exemplos anomes_gross no banco: %s' % list(set(c['anomes_gross'] for c in churns[:5])))
            self.stdout.write('Exemplos nr_ordem: %s' % [c['nr_ordem'] for c in churns[:5]])
        self.stdout.write('Variantes de O.S. (amostra): %s\n' % list(set_os_churn)[:10])

        consultores = User.objects.filter(is_active=True).order_by('username')
        if username:
            consultores = consultores.filter(username__iexact=username)
        if not consultores.exists():
            self.stdout.write(self.style.WARNING(f'Nenhum vendedor ativo encontrado' + (f' com username="{username}"' if username else '')))
            return

        for consultor in consultores:
            vendas = list(
                Venda.objects.filter(
                    vendedor=consultor,
                    ativo=True,
                    status_esteira__nome__iexact='INSTALADA',
                    data_instalacao__gte=data_inicio,
                    data_instalacao__lt=data_fim,
                ).values('id', 'ordem_servico', 'data_instalacao', 'desconto_churn_aplicado_em')
            )
            self.stdout.write(f'\n--- Vendedor: {consultor.username} (id={consultor.id}) ---')
            self.stdout.write(f'Vendas instaladas no mês (data_instalacao em {mes}/{ano}): {len(vendas)}')

            match_os = []
            sem_os = []
            nao_bate = []
            ja_descontado = []

            for v in vendas:
                os_crm = v.get('ordem_servico')
                if not os_crm or not str(os_crm).strip():
                    sem_os.append(v['id'])
                    continue
                if v.get('desconto_churn_aplicado_em'):
                    ja_descontado.append((v['id'], os_crm))
                    continue
                variantes = _norm_os_variantes(os_crm)
                if variantes & set_os_churn:
                    match_os.append((v['id'], os_crm))
                else:
                    nao_bate.append((v['id'], os_crm))

            if sem_os:
                self.stdout.write(self.style.WARNING(f'  Vendas sem ordem_servico (não entram no churn): {len(sem_os)} ids: {sem_os[:10]}...'))
            if ja_descontado:
                self.stdout.write(f'  Já com desconto churn aplicado: {len(ja_descontado)} (ex.: id={ja_descontado[0][0]} OS={ja_descontado[0][1]})')
            if match_os:
                self.stdout.write(self.style.SUCCESS(f'  Match churn (devem descontar): {len(match_os)} (ex.: id={match_os[0][0]} OS={match_os[0][1]})'))
                # Verificar se o plano das vendas que deram match tem chave (500MB/700MB/1GB) - senão o valor não entra na folha
                from crm_app.comissao_folha_service import plano_tipo_to_chave
                match_ids = [m[0] for m in match_os]
                vendas_match = Venda.objects.filter(id__in=match_ids).select_related('plano', 'cliente')
                sem_chave = []
                for vm in vendas_match:
                    doc = (vm.cliente.cpf_cnpj or '') if vm.cliente else ''
                    doc_limpo = ''.join(filter(str.isdigit, doc))
                    tipo_cliente = 'CNPJ' if len(doc_limpo) > 11 else 'CPF'
                    plano_nome = vm.plano.nome if vm.plano else ''
                    chave = plano_tipo_to_chave(plano_nome, tipo_cliente)
                    if not chave:
                        sem_chave.append((vm.id, plano_nome or '(sem plano)'))
                if sem_chave:
                    self.stdout.write(self.style.WARNING(f'  Atenção: %s venda(s) com match mas plano sem chave (500/700/1GB) -> valor 0 na folha: %s' % (len(sem_chave), sem_chave[:5])))
                else:
                    self.stdout.write('  Todas as vendas com match têm plano 500MB/700MB/1GB -> valor será descontado na folha.')
            if nao_bate:
                self.stdout.write(f'  O.S. não encontrada na base churn: {len(nao_bate)} (ex.: id={nao_bate[0][0]} OS={nao_bate[0][1]})')
                self.stdout.write('    Variantes da primeira O.S. que não bateu: %s' % _norm_os_variantes(nao_bate[0][1]))

        self.stdout.write('\n')
