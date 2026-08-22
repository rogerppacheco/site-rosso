# -*- coding: utf-8 -*-
"""
Processa CSVs da base CNPJ da Receita Federal (separador ;)
aplicando filtros:
  - CNAE Fiscal Principal: 8112500 (Condomínios Prediais)
  - Código do Município: 4123 (Belo Horizonte)
  - Situação Cadastral: 02 (Ativos)

Uso:
  python scripts/processar_cnpj_receita_federal.py
  python scripts/processar_cnpj_receita_federal.py "C:/caminho/para/pasta/csv"
  python scripts/processar_cnpj_receita_federal.py "C:/pasta" --saida resultado.csv
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path


# Filtros desejados
CNAE_FISCAL = "8112500"       # Condomínios Prediais
CODIGO_MUNICIPIO = "4123"     # Belo Horizonte (Receita Federal)
SITUACAO_CADASTRAL = "02"     # Ativos

# Layout oficial dos arquivos ESTABELE (sem cabeçalho) - ordem das colunas no CSV (;)
# Fonte: Receita Federal "NOVO LAYOUT DOS DADOS ABERTOS DO CNPJ" (metadados) e
#        https://github.com/libercapital/dados_publicos_cnpj_receita_federal (model Company, N_RAW_COLUMNS=30)
# Índice 0-based no arquivo:
LAYOUT_ESTABELE_SEM_CABECALHO = {
    "cnpj_raiz": 0,
    "cnpj_ordem": 1,
    "cnpj_dv": 2,
    "identificador_matriz_filial": 3,
    "nome_fantasia": 4,
    "situacao_cadastral": 5,   # 02 = Ativa
    "data_situacao_cadastral": 6,
    "motivo_situacao_cadastral": 7,
    "nome_cidade_exterior": 8,
    "codigo_pais": 9,
    "data_inicio_atividade": 10,
    "cnae_fiscal": 11,         # CNAE principal (ex: 8112500)
    "cnae_secundarios": 12,
    "tipo_logradouro": 13,
    "logradouro": 14,
    "numero": 15,
    "complemento": 16,
    "bairro": 17,
    "cep": 18,
    "uf": 19,
    "codigo_municipio": 20,    # Código Receita (ex: 4123 = BH)
    "ddd_telefone_1": 21,
    "telefone_1": 22,
    "ddd_telefone_2": 23,
    "telefone_2": 24,
    "ddd_fax": 25,
    "fax": 26,
    "email": 27,
    "situacao_especial": 28,
    "data_situacao_especial": 29,
}
IDX_SITUACAO = LAYOUT_ESTABELE_SEM_CABECALHO["situacao_cadastral"]
IDX_CNAE = LAYOUT_ESTABELE_SEM_CABECALHO["cnae_fiscal"]
IDX_MUNICIPIO = LAYOUT_ESTABELE_SEM_CABECALHO["codigo_municipio"]


def _normalize_header(name: str) -> str:
    """Normaliza nome de coluna para comparação."""
    if not name:
        return ""
    return " ".join(name.strip().lower().split())


def _find_column_index(headers: list[str], candidates: list[str]) -> int | None:
    """Retorna o índice da coluna que bate com algum dos candidatos (nome normalizado)."""
    normalized = [_normalize_header(h) for h in headers]
    candidates_norm = [_normalize_header(c) for c in candidates]
    for i, h in enumerate(normalized):
        for c in candidates_norm:
            if c in h or h in c:
                return i
    return None


def detect_encoding(path: Path) -> str:
    """Tenta latin-1 primeiro (base RFB aceita qualquer byte), depois cp1252, utf-8."""
    for enc in ("latin-1", "cp1252", "utf-8"):
        try:
            with open(path, "r", encoding=enc) as f:
                f.readline()
            return enc
        except (UnicodeDecodeError, UnicodeError):
            continue
    return "latin-1"  # fallback: aceita qualquer byte 0x00-0xff


def read_headers(path: Path, encoding: str, sep: str = ";") -> list[str]:
    """Lê apenas a primeira linha e retorna os nomes das colunas."""
    with open(path, "r", encoding=encoding, newline="") as f:
        reader = csv.reader(f, delimiter=sep)
        row = next(reader)
    return [h.strip() for h in row]


def map_columns(headers: list[str]) -> dict[str, int]:
    """Mapeia nomes lógicos para índice da coluna no CSV."""
    mapping = {}
    # CNAE Fiscal Principal
    idx = _find_column_index(
        headers,
        [
            "cnae fiscal principal",
            "cnae_fiscal",
            "cnae fiscal",
            "cnae",
        ],
    )
    if idx is not None:
        mapping["cnae_fiscal"] = idx

    # Código do Município
    idx = _find_column_index(
        headers,
        [
            "código município",
            "codigo_municipio",
            "codigo municipio",
            "município",
            "municipio",
        ],
    )
    if idx is not None:
        mapping["codigo_municipio"] = idx

    # Situação Cadastral
    idx = _find_column_index(
        headers,
        [
            "situação cadastral",
            "situacao_cadastral",
            "situacao cadastral",
        ],
    )
    if idx is not None:
        mapping["situacao_cadastral"] = idx

    return mapping


def row_passes_filter(row: list[str], col_map: dict[str, int]) -> bool:
    """Verifica se a linha passa nos filtros (valores normalizados: strip)."""
    def get(key: str) -> str:
        i = col_map.get(key)
        if i is None or i >= len(row):
            return ""
        return (row[i] or "").strip()

    # CNAE pode vir com menos de 7 dígitos; normalizar para 7
    cnae = get("cnae_fiscal").zfill(7) if get("cnae_fiscal") else ""
    municipio = get("codigo_municipio")
    situacao = get("situacao_cadastral").zfill(2) if get("situacao_cadastral") else get("situacao_cadastral")

    if cnae != CNAE_FISCAL:
        return False
    if municipio != CODIGO_MUNICIPIO:
        return False
    if situacao != SITUACAO_CADASTRAL:
        return False
    return True


def process_file(
    path: Path,
    encoding: str,
    sep: str,
    col_map: dict[str, int],
    writer: csv.writer,
    stats: dict,
    sem_cabecalho: bool = False,
    header_row: list[str] | None = None,
) -> None:
    """Processa um único CSV e escreve linhas que passam no filtro."""
    with open(path, "r", encoding=encoding, newline="") as f:
        reader = csv.reader(f, delimiter=sep)
        if sem_cabecalho:
            # Arquivo sem linha de cabeçalho: todas as linhas são dados
            if header_row is not None and not stats.get("header_written", False):
                writer.writerow(header_row)
                stats["header_written"] = True
            for row in reader:
                stats["read"] += 1
                if row_passes_filter(row, col_map):
                    writer.writerow(row)
                    stats["written"] += 1
        else:
            header = next(reader)
            if not col_map:
                return
            wrote_header = stats.get("header_written", False)
            if not wrote_header:
                writer.writerow(header)
                stats["header_written"] = True

            for row in reader:
                stats["read"] += 1
                if row_passes_filter(row, col_map):
                    writer.writerow(row)
                    stats["written"] += 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Filtra CSVs da base CNPJ (Receita Federal) por CNAE 8112500, Município 4123, Situação 02.",
    )
    parser.add_argument(
        "pasta",
        nargs="?",
        default=os.path.join(os.path.expanduser("~"), "Downloads", "download"),
        help="Pasta com os arquivos CSV (default: ~/Downloads/download)",
    )
    parser.add_argument(
        "-o", "--saida",
        default="cnpj_filtrado_condominios_bh.csv",
        help="Arquivo CSV de saída",
    )
    parser.add_argument(
        "-s", "--separador",
        default=";",
        help="Separador de campo (default: ;)",
    )
    parser.add_argument(
        "--sem-cabecalho",
        action="store_true",
        help="Arquivos no layout oficial da Receita SEM linha de cabeçalho (ex: K3241...ESTABELE). Usa ordem fixa das colunas.",
    )
    args = parser.parse_args()

    pasta = Path(args.pasta)
    if not pasta.is_dir():
        print(f"Erro: pasta não encontrada: {pasta}", file=sys.stderr)
        return 1

    # Arquivos na pasta: CSV e arquivos no formato da Receita (ex: K3241.K03200Y9.D60214.ESTABELE)
    csv_files = sorted(pasta.glob("*.csv")) + sorted(pasta.glob("*.CSV"))
    estabele_files = [f for f in pasta.iterdir() if f.is_file() and "ESTABELE" in f.name.upper()]
    csv_files = sorted(set(csv_files + estabele_files))

    if not csv_files:
        print(f"Nenhum arquivo .csv ou *ESTABELE* encontrado em: {pasta}", file=sys.stderr)
        return 1

    print(f"Encontrados {len(csv_files)} arquivo(s) em {pasta}")
    print(f"Filtros: CNAE={CNAE_FISCAL}, Município={CODIGO_MUNICIPIO}, Situação={SITUACAO_CADASTRAL}")
    if args.sem_cabecalho:
        print("Modo: arquivos SEM cabeçalho (layout oficial Receita Federal)")
    print()

    if args.sem_cabecalho:
        # Usar índices fixos do layout Estabelecimentos
        col_map = {
            "situacao_cadastral": IDX_SITUACAO,
            "cnae_fiscal": IDX_CNAE,
            "codigo_municipio": IDX_MUNICIPIO,
        }
        header_row = list(LAYOUT_ESTABELE_SEM_CABECALHO.keys())
    else:
        # Usar primeiro arquivo para detectar encoding e mapear colunas pelo cabeçalho
        first = csv_files[0]
        enc = detect_encoding(first)
        headers = read_headers(first, enc, args.separador)
        col_map = map_columns(headers)

        missing = []
        if "cnae_fiscal" not in col_map:
            missing.append("CNAE fiscal principal")
        if "codigo_municipio" not in col_map:
            missing.append("Código do Município")
        if "situacao_cadastral" not in col_map:
            missing.append("Situação cadastral")

        if missing:
            print("Colunas encontradas:", headers[:15], "..." if len(headers) > 15 else "")
            print("Dica: use --sem-cabecalho para arquivos no formato da Receita (ex: K3241...ESTABELE) sem linha de cabeçalho.", file=sys.stderr)
            print("Erro: não foi possível identificar as colunas:", ", ".join(missing), file=sys.stderr)
            return 1
        header_row = None

    stats = {"read": 0, "written": 0, "header_written": False}
    saida = Path(args.saida)

    with open(saida, "w", encoding="utf-8", newline="") as out:
        writer = csv.writer(out, delimiter=args.separador)
        for path in csv_files:
            enc = detect_encoding(path)
            process_file(
                path, enc, args.separador, col_map, writer, stats,
                sem_cabecalho=args.sem_cabecalho,
                header_row=header_row,
            )

    print(f"Linhas lidas: {stats['read']}")
    print(f"Linhas que passaram no filtro: {stats['written']}")
    print(f"Saída salva em: {saida.absolute()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
