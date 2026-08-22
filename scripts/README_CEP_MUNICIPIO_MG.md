# Onde baixar relação de CEP / município (MG e Brasil)

## Salvar no banco local (recomendado)

Você pode **baixar uma base de CEP** (ex.: CEP Aberto) e **importar para o banco** do projeto.  
A partir daí, o sistema usa primeiro a tabela `CepLocalidade` e não depende de API para preencher a cidade.

### 1) Onde baixar uma base

| Fonte | Como obter |
|-------|------------|
| **CEP Aberto** | https://www.cepaberto.com/ — Cadastro gratuito, depois em “Baixar” escolha o estado (ex.: MG). Dump em CSV. |
| **Base dos Dados (DNE)** | https://basedosdados.org/dataset/9cb64a51-1a60-4162-8bc7-c86c1b6597a0 — Diretório Nacional de Endereços (Correios). |

### 2) Formato do CSV

- Primeira linha: **cabeçalho** com nomes das colunas.
- Colunas aceitas (qualquer um dos nomes):
  - **CEP:** `cep`, `CEP`, `codigo_postal`
  - **Cidade:** `localidade`, `cidade`, `municipio`, `município`
  - **UF:** `uf`, `UF`, `estado`
- Separador: **vírgula** ou **ponto-e-vírgula** (detectado automaticamente).
- CEP pode ter traço (ex.: 30130-100) ou só dígitos.

Exemplo:

```csv
cep,localidade,uf
30130100,Belo Horizonte,MG
30130-100,Belo Horizonte,MG
```

### 3) Importar para o banco

```bash
# Importar o arquivo (ex.: MG baixado do CEP Aberto)
python manage.py importar_base_cep C:\Downloads\cep_mg.csv

# Limpar a tabela e importar de novo
python manage.py importar_base_cep C:\Downloads\cep_mg.csv --sobrescrever

# Separador explícito e limite de linhas
python manage.py importar_base_cep C:\Downloads\ceps.csv --separador ";" --limite 50000
```

### 4) Ordem de consulta no sistema

Ao preencher a cidade a partir do CEP, o sistema usa nesta ordem:

1. **Banco local** (`CepLocalidade`) — o que você importou  
2. Cache em arquivo (`crm_app/data/cep_localidade_cache.json`)  
3. **ViaCEP** e **OpenCEP** (APIs) — e o resultado é salvo no cache em arquivo  

Assim, depois de importar uma base para MG (ou todo o Brasil), as exportações e telas passam a usar o banco e ficam mais rápidas e estáveis.

---

## Alternativa: preencher cache por API (sem baixar base)

Se não quiser baixar um CSV, pode preencher o **cache em arquivo** consultando ViaCEP e OpenCEP para cada CEP da sua base CNPJ:

```bash
python manage.py preencher_cache_cep --uf MG
```

Isso demora (há delay entre consultas). Depois disso, o sistema usa o cache em arquivo e as exportações ficam rápidas.

---

## Bases externas (se quiser baixar uma lista)

### Gratuitas

| Fonte | Descrição | Link |
|-------|-----------|------|
| **CEP Aberto** | Base colaborativa, >1 mi CEPs, cadastro gratuito para download | https://www.cepaberto.com/ |
| **Municípios Brasileiros (GitHub)** | CSV/JSON com municípios, código IBGE, UF (não é CEP, mas ajuda cruzamento) | https://github.com/kelvins/Municipios-Brasileiros |
| **ViaCEP** | Sem download em massa; só consulta por CEP (o sistema já usa na exportação) | https://viacep.com.br/ |

### Pagas (bases completas Correios)

- **QualoceP** – Base CEP Correios com código IBGE, Excel/CSV (pago).
- **ZipData** – Base CEP com código IBGE, vários formatos (pago).

---

## Conferir se o IBGE está carregado

Se o município não sai nem pelo código IBGE nem pelo CEP, confira:

```bash
python manage.py diagnostico_ibge_municipio
```

Se o mapa estiver vazio:

```bash
python manage.py download_ibge_municipios
```

Depois rode de novo a exportação (com ou sem `--preencher-cidade-por-cep`).
