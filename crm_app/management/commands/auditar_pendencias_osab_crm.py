"""
Auditoria: códigos de pendência presentes na base OSAB importada vs cadastro MotivoPendencia.

Usa a mesma lógica de resolução da importação OSAB (dígitos, zfill(4), primeiros 4 se valor longo).

Uso:
  python manage.py auditar_pendencias_osab_crm
  python manage.py auditar_pendencias_osab_crm --escopo situacao_pendencia
  python manage.py auditar_pendencias_osab_crm --json relatorio.json
  python manage.py auditar_pendencias_osab_crm --fail-on-missing
"""
import json
import re
from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db.models import Q


def _build_motivo_map():
    """Igual à importação OSAB: chave = primeiro bloco de dígitos no início do nome."""
    from crm_app.models import MotivoPendencia

    out = {}
    for m in MotivoPendencia.objects.all().only('id', 'nome'):
        match = re.match(r'^(\d+)', m.nome.strip())
        if match:
            out[match.group(1)] = m
    return out


def _digits_only(cod_raw):
    cod_str = str(cod_raw if cod_raw is not None else '').replace('.0', '').strip()
    return re.sub(r'\D', '', cod_str)


def _resolve_motivo(motivo_map, digits_only):
    if not digits_only:
        return None
    m = motivo_map.get(digits_only)
    if not m and len(digits_only) <= 4:
        m = motivo_map.get(digits_only.zfill(4))
    if not m and len(digits_only) >= 4:
        m = motivo_map.get(digits_only[:4])
    return m


class Command(BaseCommand):
    help = 'Lista códigos COD_PENDENCIA na base OSAB e verifica se existem em MotivoPendencia (mesma regra da importação).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--escopo',
            choices=['com_codigo', 'situacao_pendencia'],
            default='com_codigo',
            help=(
                'com_codigo: todas as linhas OSAB com COD_PENDENCIA preenchido. '
                'situacao_pendencia: apenas linhas cuja situação indica pendência (cliente/técnica).'
            ),
        )
        parser.add_argument(
            '--json',
            type=str,
            default=None,
            help='Gravar relatório estruturado neste arquivo (UTF-8).',
        )
        parser.add_argument(
            '--fail-on-missing',
            action='store_true',
            help='Exit code 1 se houver algum código OSAB sem motivo correspondente no CRM.',
        )

    def handle(self, *args, **options):
        from crm_app.models import ImportacaoOsab

        escopo = options['escopo']
        qs = ImportacaoOsab.objects.all()

        if escopo == 'situacao_pendencia':
            qs = qs.filter(
                Q(situacao__icontains='PENDÊNCIA')
                | Q(situacao__icontains='PENDENCIA')
            )

        motivo_map = _build_motivo_map()

        # Agrega por código normalizado (dígitos)
        agg = defaultdict(lambda: {'count': 0, 'raw_exemplos': set(), 'desc_exemplos': set(), 'documentos': []})

        for cod_raw, desc_raw, doc in qs.values_list('cod_pendencia', 'desc_pendencia', 'documento').iterator(
            chunk_size=5000
        ):
            digits = _digits_only(cod_raw)
            if not digits:
                continue
            key = digits
            a = agg[key]
            a['count'] += 1
            if cod_raw is not None and str(cod_raw).strip():
                raw_s = str(cod_raw).strip()
                if len(a['raw_exemplos']) < 5:
                    a['raw_exemplos'].add(raw_s)
            if desc_raw and str(desc_raw).strip():
                d = str(desc_raw).strip()[:120]
                if len(a['desc_exemplos']) < 3:
                    a['desc_exemplos'].add(d)
            if doc and len(a['documentos']) < 5:
                a['documentos'].append(str(doc).strip())

        if not agg:
            self.stdout.write(self.style.WARNING('Nenhum registro OSAB com COD_PENDENCIA (dígitos) no escopo selecionado.'))
            return

        linhas = []
        faltando = []

        for digits_key in sorted(agg.keys(), key=lambda x: (len(x), x)):
            info = agg[digits_key]
            motivo = _resolve_motivo(motivo_map, digits_key)
            ok = motivo is not None
            linha = {
                'codigo_digitos': digits_key,
                'qtd_linhas_osab': info['count'],
                'cadastrado_no_crm': ok,
                'motivo_pendencia_id': motivo.id if motivo else None,
                'motivo_pendencia_nome': motivo.nome if motivo else None,
                'exemplos_codigo_bruto': sorted(info['raw_exemplos']),
                'exemplos_desc_osab': sorted(info['desc_exemplos']),
                'exemplos_documento': info['documentos'],
                'na_importacao_usaria': motivo.nome if motivo else 'VALIDAR OSAB',
            }
            linhas.append(linha)
            if not ok:
                faltando.append(linha)

        # Saída texto
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(f'Escopo: {escopo} | Códigos distintos (dígitos): {len(linhas)}'))
        self.stdout.write(f'Cadastrados no CRM (mesma regra da importação): {len(linhas) - len(faltando)}')
        self.stdout.write(self.style.WARNING(f'Sem match no CRM (cairiam em VALIDAR OSAB): {len(faltando)}'))
        self.stdout.write('')

        w = self.stdout.write
        for linha in linhas:
            status = 'OK ' if linha['cadastrado_no_crm'] else 'FALTA'
            cor = self.style.SUCCESS if linha['cadastrado_no_crm'] else self.style.ERROR
            w(cor(f"[{status}] {linha['codigo_digitos']}  ({linha['qtd_linhas_osab']} linhas) -> {linha['na_importacao_usaria']}"))
            if linha['exemplos_desc_osab']:
                w(f"       desc OSAB (amostra): {', '.join(linha['exemplos_desc_osab'][:2])}")

        if options['json']:
            path = options['json']
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(
                    {
                        'escopo': escopo,
                        'totais': {
                            'codigos_distintos': len(linhas),
                            'cadastrados': len(linhas) - len(faltando),
                            'sem_match': len(faltando),
                        },
                        'itens': linhas,
                        'sem_match': faltando,
                    },
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
            self.stdout.write('')
            self.stdout.write(self.style.SUCCESS(f'JSON gravado em: {path}'))

        if options['fail_on_missing'] and faltando:
            self.stderr.write(self.style.ERROR(f'Encerrando com erro: {len(faltando)} código(s) sem cadastro.'))
            raise SystemExit(1)
