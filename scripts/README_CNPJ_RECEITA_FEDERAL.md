# Processar base CNPJ Receita Federal – Condomínios BH

Script que processa CSVs da base de CNPJ da Receita Federal (separador `;`) e aplica os filtros:

| Filtro | Valor | Significado |
|--------|--------|-------------|
| **CNAE Fiscal Principal** | `8112500` | Condomínios Prediais |
| **Código do Município** | `4123` | Belo Horizonte (código Receita Federal) |
| **Situação Cadastral** | `02` | Ativos |

## Uso

1. Coloque os arquivos CSV na pasta (por padrão `%USERPROFILE%\Downloads\download`).
   - O script aceita tanto arquivos `.csv` quanto arquivos no **formato da Receita Federal**, por exemplo: `K3241.K03200Y9.D60214.ESTABELE` (nome contendo `ESTABELE`).
2. Execute:

```bash
python scripts/processar_cnpj_receita_federal.py
```

Com pasta e arquivo de saída customizados:

```bash
python scripts/processar_cnpj_receita_federal.py "C:\caminho\para\pasta\csv"
python scripts/processar_cnpj_receita_federal.py "C:\pasta" -o resultado_condominios_bh.csv
```

Para arquivos **sem cabeçalho** (formato oficial ESTABELE):

```bash
python scripts/processar_cnpj_receita_federal.py "C:\Users\rogge\Downloads\download" --sem-cabecalho -o cnpj_filtrado_condominios_bh.csv
```

## Opções

- **pasta** (opcional): Pasta onde estão os `.csv` ou arquivos ESTABELE. Default: `~/Downloads/download`
- **-o, --saida**: Nome do arquivo CSV de saída. Default: `cnpj_filtrado_condominios_bh.csv`
- **-s, --separador**: Separador de campos. Default: `;`
- **--sem-cabecalho**: Usar para arquivos no formato oficial da Receita **sem linha de cabeçalho** (ex.: `K3241.K03200Y9.D60214.ESTABELE`). O script usa a ordem fixa das colunas do layout.

## Formato esperado dos CSVs

- Separador: **ponto e vírgula** (`;`)
- Codificação: o script tenta **cp1252**, **utf-8** e **latin-1**
- **Primeira linha = cabeçalho** com nomes das colunas (ex.: “CNAE fiscal principal”, “Município”, “Situação cadastral”)

O script reconhece automaticamente colunas com nomes equivalentes (ex.: “CNAE fiscal principal”, “cnae_fiscal”, “Código do Município”, “Situação cadastral”).

Se os arquivos forem do layout oficial **sem cabeçalho**, use a opção `--sem-cabecalho`: o script usa a ordem fixa das colunas do layout da Receita (coluna 5 = Situação cadastral, 11 = CNAE fiscal, 20 = Código do Município).

## Saída

- Um único CSV em UTF-8 com todas as linhas que passaram nos três filtros.
- O cabeçalho é escrito uma vez; o caminho completo do arquivo de saída é exibido ao final.
