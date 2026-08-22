# Especificação: APIs e telas – Comissão (reconstrução)

Desenho das APIs e das telas para Regras de Comissão (faixas + vendedores) e Folha de Pagamento no formato Excel.

---

## 1. Mapeamento plano Excel ↔ sistema

Os 6 “planos” do Excel são chaves lógicas (nome do plano + tipo cliente). O sistema tem `Plano` (FK em Venda) com `nome` (ex.: "500MB", "700MB", "1GB"). Para cálculo:

| Chave Excel | Uso no cálculo |
|-------------|----------------|
| 500MB_PAP   | Plano cujo nome contém "500" + tipo_cliente CPF (PAP) |
| 700MB_PAP   | Plano nome "700" + CPF |
| 1GB_PAP     | Plano nome "1GB" + CPF |
| 500MB_CNPJ  | Plano "500" + tipo_cliente CNPJ |
| 700MB_CNPJ  | Plano "700" + CNPJ |
| 1GB_CNPJ    | Plano "1GB" + CNPJ |

Sugestão: criar em `crm_app` um helper que, dado `Plano` + `tipo_cliente` (CPF/CNPJ), retorne a chave `500MB_PAP`, `700MB_CNPJ`, etc., com base em convenção no `Plano.nome` (ex.: "500", "500MB", "1GB") ou em um campo opcional `chave_comissao` no `Plano` (valor: 500MB, 700MB, 1GB). Assim as regras de faixa e os manuais continuam com as 6 colunas fixas do Excel.

---

## 2. APIs – Regras por faixa (REGRAS_FAIXAS)

### 2.1 Listar / filtrar

- **GET** `/api/crm/regras-comissao-faixa/`
- **Query params (opcionais):** `perfil`, `vendedor_id`
- **Resposta:** lista de objetos com:  
  `id`, `perfil`, `vendedor` (id + username), `faixa_nome`, `min_vendas`, `max_vendas`,  
  `valor_500mb_pap`, `valor_700mb_pap`, `valor_1gb_pap`,  
  `valor_500mb_cnpj`, `valor_700mb_cnpj`, `valor_1gb_cnpj`.

### 2.2 Criar / atualizar / excluir

- **POST** `/api/crm/regras-comissao-faixa/` – criar
- **GET** `/api/crm/regras-comissao-faixa/<id>/` – detalhe
- **PUT** `/api/crm/regras-comissao-faixa/<id>/` – atualizar
- **PATCH** `/api/crm/regras-comissao-faixa/<id>/` – parcial
- **DELETE** `/api/crm/regras-comissao-faixa/<id>/` – excluir

Payload de criação/atualização (JSON): mesmo formato da listagem; `vendedor` pode ser `null`; quando `vendedor` preenchido, `perfil` pode ser vazio.

### 2.3 Importar / exportar Excel

- **POST** `/api/crm/regras-comissao-faixa/importar/`  
  - Body: multipart, arquivo `.xlsx` ou `.csv`.  
  - Colunas esperadas: PERFIL, FAIXA_NOME, MIN_VENDAS, MAX_VENDAS, VALOR_500MB_PAP, VALOR_700MB_PAP, VALOR_1GB_PAP, VALOR_500MB_CNPJ, VALOR_700MB_CNPJ, VALOR_1GB_CNPJ.  
  - PERFIL pode ser "Supervisor", "Vendedor" ou username (para regra individual).  
  - Resposta: `{ "importados": N, "erros": [...] }`.

- **GET** `/api/crm/regras-comissao-faixa/exportar/`  
  - Query: opcional `formato= xlsx | csv`.  
  - Resposta: arquivo download (mesmo layout do Excel).

---

## 3. APIs – Regras por vendedor (REGRAS_VENDEDORES)

### 3.1 Listar (grid “como no Excel”)

- **GET** `/api/crm/config-comissao-vendedor/`
- **Resposta:** uma entrada por usuário que tenha configuração OU todos os usuários ativos (vendedores) com config default vazia. Campos:  
  `usuario_id`, `username` (VENDEDOR), `perfil_comissao`, `usar_valor_manual`,  
  `valor_500mb_pap_manual`, … `valor_1gb_cnpj_manual`,  
  `desconta_dacc_pap`, `desconto_boleto`, `desconto_inclusao`, `desconto_instalacao`, `adiantar_cnpj`,  
  `inss_valor`, `adiantamento`, `premiação`, `bonus_cartao_credito`, `cartao_trafego`, `gestor_trafego`.

### 3.2 Criar / atualizar

- **GET** `/api/crm/config-comissao-vendedor/<user_id>/` – detalhe (ou 404)
- **PUT** `/api/crm/config-comissao-vendedor/<user_id>/` – criar ou atualizar (upsert por user_id)
- **PATCH** `/api/crm/config-comissao-vendedor/<user_id>/` – atualização parcial

Payload: mesmo conjunto de campos; valores numéricos podem ser `null`.

### 3.3 Importar / exportar Excel

- **POST** `/api/crm/config-comissao-vendedor/importar/`  
  - Body: arquivo `.xlsx`/`.csv` com colunas alinhadas ao REGRAS_VENDEDORES (VENDEDOR = username).  
  - Resposta: `{ "importados": N, "erros": [...] }`.

- **GET** `/api/crm/config-comissao-vendedor/exportar/`  
  - Resposta: arquivo no layout do Excel (uma linha por vendedor).

---

## 4. API – Folha de pagamento (formato Excel)

### 4.1 Dados da folha (resumo + extrato)

- **GET** `/api/crm/comissionamento/folha/?ano=AAAA&mes=M&vendedor_id=opcional`
- **Resposta (por vendedor):**

```json
{
  "periodo": "01/2026",
  "ano_mes": 202601,
  "vendedores": [
    {
      "vendedor_id": 1,
      "vendedor_nome": "RAMALHO",
      "resumo": {
        "total_qtd_instalada_a_pagar": 3,
        "total_qtd_ja_pago": 0,
        "total_qtd_churn_30": 0,
        "faixa_aplicada": "MANUAL",
        "por_plano": [
          {
            "plano": "500MB PAP",
            "qtd_instalada_a_pagar": 2,
            "qtd_ja_pago": 0,
            "qtd_churn_30": 0,
            "valor_unitario_instalados": 200,
            "valor_unitario_churn": null,
            "valor_total_instalados": 400,
            "valor_total_churn": 0,
            "comissao_total": 650
          }
        ],
        "comissao_total_geral": 650,
        "ajustes": {
          "premiacao": 0,
          "instalacao": 0,
          "adiantar_cnpj": 0,
          "desconto_boleto": 0,
          "gestor_trafego": 0,
          "cartao_trafego": 0,
          "adiantar_mes": 0,
          "churn_ate_30_dias": 0,
          "churn_acima_30_dias": 0
        },
        "liquido": 650
      },
      "extrato": [
        {
          "venda_id": 1,
          "nome": "ROSANGELA MARIA DE OLIVEIRA SANTOS",
          "dacc": "NÃO",
          "cnpj": "SIM",
          "plano": "500MB",
          "dt_pedido": "2026-01-14",
          "dt_inst": "2026-01-15",
          "os": "08084308",
          "situacao": "INSTALADA",
          "vendedor": "RAMALHO",
          "churn": "ATIVO"
        }
      ]
    }
  ]
}
```

A lógica de cálculo deve usar, por vendedor:

1. Buscar `ConfigComissaoVendedor` (ou defaults).
2. Se `usar_valor_manual` → valor por venda = valor_*_manual do plano correspondente.
3. Senão → obter faixa por `perfil_comissao` e qtd instaladas no mês; usar `RegraComissaoFaixa` (ou regra individual por `vendedor`) e valor do plano.
4. Somar descontos e bônus conforme config e lançamentos financeiros.

### 4.2 Exportar folha Excel / PDF

- **GET** ou **POST** `/api/crm/comissionamento/folha/exportar/?ano=AAAA&mes=M&formato=xlsx|pdf&vendedor_id=opcional`  
  - Gera arquivo no layout da aba “FOLHA PAGAMENTO (2)”: um bloco por vendedor (resumo por plano + ajustes) + extrato (tabela de vendas).  
  - PDF: mesmo conteúdo, formato impressão.

As rotas atuais de fechar/reabrir, PDF e e-mail podem permanecer; a nova rota `folha/` e `folha/exportar/` passam a ser o contrato “oficial” do layout Excel.

---

## 5. Telas – Onde fica cada coisa

### 5.1 Governança (ou Comissionamento – Regras)

- **Aba “Regras por Faixa”**  
  - Grid: colunas PERFIL, FAIXA_NOME, MIN_VENDAS, MAX_VENDAS, VALOR_500MB_PAP, VALOR_700MB_PAP, VALOR_1GB_PAP, VALOR_500MB_CNPJ, VALOR_700MB_CNPJ, VALOR_1GB_CNPJ.  
  - Ações: adicionar linha, editar em linha ou modal, excluir.  
  - Botões: **Importar Excel**, **Exportar Excel**.

- **Aba “Regras por Vendedor”**  
  - Grid: uma linha por vendedor; colunas como no Excel (VENDEDOR, PERFIL_COMISSAO, USAR_VALOR_MANUAL?, 6 manuais, DESCONTA DACC PAP?, descontos, INSS, PREMIAÇÃO, CARTÃO TRAFEGO, GESTOR TRAFEGO, etc.).  
  - Edição em linha ou modal.  
  - Botões: **Importar Excel**, **Exportar Excel**.

Sugestão: manter a aba atual “Regras de Comissão” (RegraComissao antiga) como “Regras legado” ou migrar gradualmente; as novas abas “Regras por Faixa” e “Regras por Vendedor” usam os novos modelos e o layout do Excel.

### 5.2 Comissionamento – Folha de pagamento

- **Filtros:** Mês, Ano, opcionalmente Vendedor.
- **Conteúdo:**
  - Para cada vendedor (ou um só se filtrado):
    - **Bloco resumo:** tabela por plano (500MB PAP, 700MB PAP, …) com QTD INSTALADA A PAGAR, QTD JÁ PAGO, QTD CHURN 30 DIAS, FAIXA, VALOR UNIT., VALOR TOTAL INSTALADOS, VALOR TOTAL CHURN, COMISSÃO TOTAL; linha TOTAL; em seguida linhas de ajustes (PREMIAÇÃO, INSTALAÇÃO, ADIANTAR CNPJ, DESCONTO BOLETO, GESTOR TRAFÉGO, CARTÃO TRAFEGO, ADIANTAR MÊS, CHURN ATÉ 30, CHURN ACIMA 30).
    - **Extrato:** tabela NOME, DACC, CNPJ, PLANO, DT PEDIDO, DT INST, OS, SITUAÇÃO, VENDEDOR, CHURN (expandível ou em aba “Extrato”).
  - Rodapé: totalizadores gerais e botões **Fechar mês** / **Reabrir mês** (como hoje).
- **Ações:** **Exportar Excel** (layout igual ao da planilha), **Exportar PDF**, **Enviar e-mail**, **Enviar WhatsApp** (resumo), mantendo o que já existir.

---

## 6. Ordem sugerida de implementação

1. **Backend**
   - Serializers e ViewSets/Views para `RegraComissaoFaixa` e `ConfigComissaoVendedor` (CRUD + list).
   - Endpoints de importar/exportar Excel para ambas as regras.
   - Helper de mapeamento plano (nome + tipo_cliente) → chave 500MB_PAP, etc.
   - Serviço de cálculo da folha (resumo por plano + ajustes + extrato) usando faixas e config vendedor.
   - Endpoint GET `comissionamento/folha/` e GET/POST `comissionamento/folha/exportar/`.

2. **Frontend**
   - Em Governança (ou em Comissionamento): abas “Regras por Faixa” e “Regras por Vendedor” com grids editáveis e botões Importar/Exportar.
   - Em Comissionamento: tela “Folha de pagamento” com filtros, blocos resumo + extrato por vendedor e botões de exportar/enviar.

3. **Migração de dados**
   - Script para popular `RegraComissaoFaixa` e `ConfigComissaoVendedor` a partir dos JSON/CSV exportados do Excel (ou importação em massa pela nova tela).

---

## 7. Resumo dos novos endpoints

| Método | Rota | Descrição |
|--------|------|-----------|
| GET    | `/api/crm/regras-comissao-faixa/` | Lista regras por faixa |
| POST   | `/api/crm/regras-comissao-faixa/` | Cria regra faixa |
| GET/PUT/PATCH/DELETE | `/api/crm/regras-comissao-faixa/<id>/` | Detalhe e alterações |
| POST   | `/api/crm/regras-comissao-faixa/importar/` | Importar Excel/CSV |
| GET    | `/api/crm/regras-comissao-faixa/exportar/` | Exportar Excel/CSV |
| GET    | `/api/crm/config-comissao-vendedor/` | Lista config por vendedor |
| GET | `/api/crm/config-comissao-vendedor/<user_id>/` | Detalhe (404 se não existir) |
| PUT | `/api/crm/config-comissao-vendedor/<user_id>/` | Criar ou atualizar (upsert) |
| PATCH | `/api/crm/config-comissao-vendedor/<user_id>/` | Atualização parcial |
| POST   | `/api/crm/config-comissao-vendedor/importar/` | Importar Excel/CSV |
| GET    | `/api/crm/config-comissao-vendedor/exportar/` | Exportar Excel/CSV |
| GET    | `/api/crm/comissionamento/folha/` | Dados folha (resumo + extrato) |
| GET    | `/api/crm/comissionamento/folha/exportar/` | Download Excel/PDF folha |

Com isso, o próximo passo é implementar as views/serializers e, em seguida, as telas em HTML/JS.
