# 📝 Exemplos de Uso: Cruzamento FPD com BONUS M10

## 1. Importar Arquivo FPD

### Usando cURL:

```bash
curl -X POST http://localhost:8000/api/bonus-m10/importar-fpd/ \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -F "file=@fpd_janeiro_2025.xlsx"
```

### Usando Python:

```python
import requests

url = "http://localhost:8000/api/bonus-m10/importar-fpd/"
headers = {"Authorization": f"Bearer {access_token}"}

with open("fpd_janeiro_2025.xlsx", "rb") as f:
    files = {"file": f}
    response = requests.post(url, headers=headers, files=files)

resultado = response.json()
print(f"Importados: {resultado['atualizados']}")
print(f"Não encontrados: {resultado['nao_encontrados']}")
print(f"Histórico: {resultado['importacoes_fpd']}")
```

### Resposta Esperada:

```json
{
  "message": "Importação FPD concluída! 125 contratos atualizados, 5 não encontrados.",
  "atualizados": 125,
  "nao_encontrados": 5,
  "importacoes_fpd": 125
}
```

---

## 2. Buscar Dados FPD de uma O.S Específica

### Usando cURL:

```bash
curl -X GET "http://localhost:8000/api/bonus-m10/dados-fpd/?os=OS-00123" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### Usando Python:

```python
import requests

url = "http://localhost:8000/api/bonus-m10/dados-fpd/"
headers = {"Authorization": f"Bearer {access_token}"}
params = {"os": "OS-00123"}

response = requests.get(url, headers=headers, params=params)
dados = response.json()

# Dados do Contrato
print(f"Contrato: {dados['contrato']['numero_contrato']}")
print(f"Cliente: {dados['contrato']['cliente_nome']}")
print(f"O.S: {dados['contrato']['ordem_servico']}")

# Histórico de Importações FPD
for imp in dados['importacoes_fpd']:
    print(f"\nID Contrato: {imp['id_contrato']}")
    print(f"Fatura: {imp['nr_fatura']}")
    print(f"Status: {imp['ds_status_fatura']}")
    print(f"Data Pagamento: {imp['dt_pagamento']}")
    print(f"Valor: R$ {imp['vl_fatura']}")
    print(f"Dias Atraso: {imp['nr_dias_atraso']}")
```

### Resposta Esperada:

```json
{
  "contrato": {
    "numero_contrato": "CONT-123456",
    "numero_contrato_definitivo": "C-000123",
    "cliente_nome": "Empresa XYZ Ltda",
    "cpf_cliente": "12.345.678/0001-90",
    "ordem_servico": "OS-00123",
    "vendedor": "João Silva",
    "data_instalacao": "2024-11-15",
    "status_contrato": "Ativo"
  },
  "importacoes_fpd": [
    {
      "id_contrato": "ID-789",
      "nr_fatura": "FT-001",
      "dt_venc_orig": "2025-01-20",
      "dt_pagamento": "2025-01-15",
      "ds_status_fatura": "PAGO",
      "vl_fatura": "150.00",
      "nr_dias_atraso": 0,
      "importada_em": "2025-12-31T10:30:00Z"
    }
  ],
  "faturas_m10": [
    {
      "numero_fatura": 1,
      "id_contrato_fpd": "ID-789",
      "dt_pagamento_fpd": "2025-01-15",
      "ds_status_fatura_fpd": "PAGO",
      "status": "PAGO",
      "valor": "150.00",
      "data_vencimento": "2025-01-20",
      "data_pagamento": "2025-01-15",
      "data_importacao_fpd": "2025-12-31T10:30:00Z"
    }
  ]
}
```

---

## 3. Listar Importações FPD com Filtros

### 3.1 Listar Todas as Faturas PAGAS

```bash
curl -X GET "http://localhost:8000/api/bonus-m10/importacoes-fpd/?status=PAGO" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### 3.2 Listar Faturas de Janeiro/2025

```bash
curl -X GET "http://localhost:8000/api/bonus-m10/importacoes-fpd/?mes=2025-01" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### 3.3 Listar Faturas VENCIDAS de Janeiro/2025 (Página 2)

```bash
curl -X GET "http://localhost:8000/api/bonus-m10/importacoes-fpd/?status=VENCIDO&mes=2025-01&page=2&limit=50" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### 3.4 Usando Python:

```python
import requests

url = "http://localhost:8000/api/bonus-m10/importacoes-fpd/"
headers = {"Authorization": f"Bearer {access_token}"}

# Filtrar por status
params = {
    "status": "PAGO",
    "mes": "2025-01",
    "page": 1,
    "limit": 100
}

response = requests.get(url, headers=headers, params=params)
resultado = response.json()

print(f"Total de registros: {resultado['total']}")
print(f"Valor total: R$ {resultado['total_valor']}")
print(f"Página: {resultado['pagina']} de {(resultado['total'] // resultado['limit']) + 1}")

for fatura in resultado['dados']:
    print(f"\nO.S: {fatura['nr_ordem']}")
    print(f"Contrato: {fatura['contrato_m10']}")
    print(f"Status: {fatura['ds_status_fatura']}")
    print(f"Valor: R$ {fatura['vl_fatura']}")
    print(f"Vencimento: {fatura['dt_venc_orig']}")
    print(f"Pagamento: {fatura['dt_pagamento']}")
```

### Resposta Esperada:

```json
{
  "total": 250,
  "total_valor": "37500.00",
  "pagina": 1,
  "limit": 100,
  "dados": [
    {
      "nr_ordem": "OS-00001",
      "id_contrato": "ID-001",
      "nr_fatura": "FT-001",
      "dt_venc_orig": "2025-01-20",
      "dt_pagamento": "2025-01-15",
      "ds_status_fatura": "PAGO",
      "vl_fatura": "150.00",
      "nr_dias_atraso": 0,
      "contrato_m10": "CONT-000001 - Cliente A",
      "importada_em": "2025-12-31T10:30:00Z"
    },
    {
      "nr_ordem": "OS-00002",
      "id_contrato": "ID-002",
      "nr_fatura": "FT-002",
      "dt_venc_orig": "2025-01-20",
      "dt_pagamento": "2025-01-18",
      "ds_status_fatura": "PAGO",
      "vl_fatura": "150.00",
      "nr_dias_atraso": 0,
      "contrato_m10": "CONT-000002 - Cliente B",
      "importada_em": "2025-12-31T10:30:00Z"
    }
  ]
}
```

---

## 4. Acessar Dados via Admin Django

Após fazer login no painel admin:

```
http://localhost:8000/admin/crm_app/importacaofpd/
```

### Funcionalidades:
- ✅ Listar todas as importações FPD
- ✅ Filtrar por `ds_status_fatura`, `dt_venc_orig`, `importada_em`
- ✅ Buscar por `nr_ordem`, `id_contrato`, `nr_fatura`
- ✅ Ver histórico completo de importações
- ✅ Visualizar contrato M10 vinculado

---

## 5. Query Direto no Banco (Django Shell)

```bash
python manage.py shell
```

```python
from crm_app.models import ImportacaoFPD, ContratoM10

# Buscar importações de uma O.S específica
importacoes = ImportacaoFPD.objects.filter(nr_ordem="OS-00123")
for imp in importacoes:
    print(f"Fatura {imp.nr_fatura}: {imp.ds_status_fatura} - R$ {imp.vl_fatura}")

# Estatísticas por status
stats = ImportacaoFPD.objects.values('ds_status_fatura').annotate(
    total=Count('id'),
    valor_total=Sum('vl_fatura')
).order_by('ds_status_fatura')
for stat in stats:
    print(f"{stat['ds_status_fatura']}: {stat['total']} faturas - R$ {stat['valor_total']}")

# Importações do mês de janeiro de 2025
from datetime import date
import_janeiro = ImportacaoFPD.objects.filter(
    dt_venc_orig__month=1,
    dt_venc_orig__year=2025
)
print(f"Total jan/2025: {import_janeiro.count()} registros")
print(f"Valor total: R$ {import_janeiro.aggregate(Sum('vl_fatura'))['vl_fatura__sum']}")

# Encontrar faturas com atraso
atrasadas = ImportacaoFPD.objects.filter(
    ds_status_fatura__in=['VENCIDO', 'ATRASADO'],
    nr_dias_atraso__gt=0
).order_by('-nr_dias_atraso')[:10]

for fat in atrasadas:
    print(f"O.S {fat.nr_ordem}: {fat.nr_dias_atraso} dias de atraso")
```

---

## 6. Visualização dos Dados em Tabelas

### Tabela: FaturaM10 (com campos FPD)

| numero_fatura | id_contrato_fpd | dt_pagamento_fpd | ds_status_fatura_fpd | status | valor | data_importacao_fpd |
|---|---|---|---|---|---|---|
| 1 | ID-789 | 2025-01-15 | PAGO | PAGO | 150.00 | 2025-12-31 10:30:00 |
| 2 | ID-790 | NULL | ABERTO | NAO_PAGO | 150.00 | NULL |
| 3 | ID-791 | 2025-02-10 | PAGO | PAGO | 150.00 | 2025-12-31 10:30:00 |

### Tabela: ImportacaoFPD (Histórico)

| nr_ordem | id_contrato | nr_fatura | dt_venc_orig | dt_pagamento | ds_status_fatura | vl_fatura | nr_dias_atraso | contrato_m10_id | importada_em |
|---|---|---|---|---|---|---|---|---|---|
| OS-00123 | ID-789 | FT-001 | 2025-01-20 | 2025-01-15 | PAGO | 150.00 | 0 | 1 | 2025-12-31 10:30:00 |
| OS-00123 | ID-789 | FT-002 | 2025-02-20 | 2025-02-10 | PAGO | 150.00 | 0 | 1 | 2025-12-31 10:30:00 |
| OS-00124 | ID-790 | FT-003 | 2025-01-25 | NULL | ABERTO | 150.00 | 7 | 2 | 2025-12-31 10:30:00 |

---

## 7. Tratamento de Erros

### Erro: Contrato não encontrado

```bash
GET /api/bonus-m10/dados-fpd/?os=OS-INVALIDA
```

**Resposta:**
```json
{
  "error": "Contrato com O.S OS-INVALIDA não encontrado"
}
```

**Status:** 404

---

### Erro: Parâmetro obrigatório faltando

```bash
GET /api/bonus-m10/dados-fpd/
```

**Resposta:**
```json
{
  "error": "Parâmetro os (Ordem de Serviço) é obrigatório"
}
```

**Status:** 400

---

### Erro: Formato de mês inválido

```bash
GET /api/bonus-m10/importacoes-fpd/?mes=2025/01
```

**Resposta:**
```json
{
  "error": "Formato de mês inválido (use YYYY-MM)"
}
```

**Status:** 400

---

## 8. Fluxo Completo de Integração

```python
# Passo 1: Importar arquivo FPD
response = importar_fpd(arquivo="fpd_janeiro_2025.xlsx")
print(f"✅ {response['atualizados']} contratos atualizados")

# Passo 2: Buscar dados de uma O.S específica
dados = buscar_dados_fpd(nr_ordem="OS-00123")
print(f"✅ Contrato: {dados['contrato']['numero_contrato']}")

# Passo 3: Listar importações de janeiro
importacoes = listar_importacoes_fpd(mes="2025-01", limit=50)
print(f"✅ {importacoes['total']} faturas em janeiro/2025")

# Passo 4: Analisar dados
pagas = sum(1 for f in importacoes['dados'] if f['ds_status_fatura'] == 'PAGO')
atrasadas = sum(1 for f in importacoes['dados'] if f['nr_dias_atraso'] > 0)

print(f"\n📊 Análise Rápida:")
print(f"  Total: {importacoes['total']}")
print(f"  Pagas: {pagas}")
print(f"  Atrasadas: {atrasadas}")
print(f"  Valor Total: R$ {importacoes['total_valor']}")
```

---

## 🔒 Autenticação

Todas as views requerem autenticação JWT:

```python
headers = {
    "Authorization": f"Bearer {access_token}",
    "Content-Type": "application/json"
}

response = requests.get(url, headers=headers)
```

Para obter o token:

```bash
curl -X POST http://localhost:8000/api/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "password": "senha123"}'
```

---

## ✅ Checklist de Validação

- [ ] Arquivo FPD importado com sucesso
- [ ] Dados exibidos na view `DadosFPDView`
- [ ] Histórico registrado em `ImportacaoFPD`
- [ ] Campos FPD preenchidos em `FaturaM10`
- [ ] Filtros funcionando corretamente
- [ ] Admin acessível para gerenciar dados
- [ ] Relatórios gerando corretamente
