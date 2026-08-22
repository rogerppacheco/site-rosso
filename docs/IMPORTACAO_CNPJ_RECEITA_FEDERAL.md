# Importação CNPJ Receita Federal (ESTABELE)

Processo de importação de arquivos ESTABELE da Receita Federal na Central de Importações.

## Layout oficial (30 colunas)

| # | Campo | Descrição |
|---|-------|-----------|
| 1 | cnpj_raiz | 8 primeiros dígitos do CNPJ |
| 2 | cnpj_ordem | Dígitos 9-12 |
| 3 | cnpj_dv | Dígitos verificadores |
| 4 | identificador_matriz_filial | 1=Matriz, 2=Filial |
| 5 | nome_fantasia | Nome fantasia |
| 6 | situacao_cadastral | 02=Ativa, 08=Baixada, etc. |
| 7 | data_situacao_cadastral | AAAAMMDD |
| 8 | motivo_situacao_cadastral | Código do motivo |
| 9 | nome_cidade_exterior | Cidade no exterior |
| 10 | codigo_pais | Código do país |
| 11 | data_inicio_atividade | AAAAMMDD |
| 12 | cnae_fiscal | CNAE principal (7 dígitos) |
| 13 | cnae_secundarios | Lista separada por vírgula |
| 14 | tipo_logradouro | Rua, Av, etc. |
| 15 | logradouro | Nome do logradouro |
| 16 | numero | Número (ou S/N) |
| 17 | complemento | Complemento |
| 18 | bairro | Bairro |
| 19 | cep | CEP |
| 20 | uf | UF |
| 21 | codigo_municipio | Código IBGE/Receita |
| 22-27 | telefones, fax, email | Contatos |
| 28-30 | situacao_especial, data | Situação especial |

- **Separador:** ponto e vírgula (`;`)
- **Cabeçalho:** não há (arquivo sem linha de cabeçalho)
- **Encoding:** latin-1, cp1252 ou utf-8 (detectado automaticamente)

## Restrições de banco de dados online

### Tamanho dos arquivos

Os arquivos ESTABELE da Receita Federal são **muito grandes**:

| Arquivo | Tamanho típico | Linhas estimadas |
|---------|----------------|------------------|
| K3241.K03200Y0.D60214.ESTABELE | ~6 GB | ~40 milhões |
| Outros blocos (Y1-Y9) | ~1 GB cada | ~7 milhões |
| **Total base completa** | ~14 GB | ~100+ milhões |

### Limites de hospedagem

| Serviço | Plano gratuito | Planos pagos |
|---------|----------------|--------------|
| **Railway PostgreSQL** | ~500 MB | até 32 GB+ |

### Recomendações

1. **Use filtros** na importação para reduzir o volume:
   - CNAE (ex: 8112500 = Condomínios)
   - Código do município (ex: 4123 = Belo Horizonte)
   - Situação cadastral (02 = Ativos)

2. **Para arquivos muito grandes**, use o script local primeiro:
   ```bash
   python scripts/processar_cnpj_receita_federal.py "C:\caminho\pasta" --sem-cabecalho -o filtrado.csv
   ```
   Depois importe o CSV filtrado pela Central.

3. **Upload via HTTP** pode ter limites (ex: 100 MB no nginx). Para arquivos > 100 MB, considere:
   - Colocar o arquivo no servidor e processar via script/cron
   - Ou filtrar localmente antes do upload

4. **Memória**: O processamento é em **streaming** (linha a linha), então não carrega o arquivo inteiro na RAM. O consumo de memória permanece baixo.

## Uso na Central de Importações

1. Acesse **Central de Importações** → **Importar CNPJ**
2. (Opcional) Marque "Aplicar filtros" e preencha CNAE, Município, Situação
3. Faça upload do arquivo .ESTABELE ou .csv
4. Acompanhe o progresso no histórico

## API

- **POST** `/api/crm/importar-cnpj/` — Upload e início da importação
- **GET** `/api/crm/logs-importacao-cnpj/` — Lista logs de importação

Corpo do POST (multipart/form-data):
- `file` — Arquivo obrigatório
- `aplicar_filtros` — true/false
- `cnae_fiscal` — ex: 8112500
- `codigo_municipio` — ex: 4123
- `situacao_cadastral` — ex: 02
