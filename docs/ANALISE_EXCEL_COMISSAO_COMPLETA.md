# Análise completa do Excel de Comissão (RECORD AGF)

Com base nos arquivos exportados de **FOLHA PAGAMENTO (2)**, **REGRAS_FAIXAS** e **REGRAS_VENDEDORES**.

---

## 1. REGRAS_FAIXAS – Regras por perfil e faixa de vendas

### 1.1 Estrutura (colunas)

| Coluna            | Tipo   | Descrição |
|-------------------|--------|-----------|
| PERFIL            | texto  | "Supervisor", "Vendedor" ou **nome do vendedor** (ex.: ALEX) para regra individual |
| FAIXA_NOME        | texto  | Nome da faixa (ex.: "1 a 39 Vendas", "Faixa 1") |
| MIN_VENDAS        | número | Mínimo de vendas (inclusive) para entrar na faixa |
| MAX_VENDAS        | número | Máximo de vendas (inclusive). 9999 ou 99999 = sem teto |
| VALOR_500MB_PAP   | número | Valor comissão por venda 500MB PAP (CPF) |
| VALOR_700MB_PAP   | número | Valor 700MB PAP |
| VALOR_1GB_PAP     | número | Valor 1GB PAP |
| VALOR_500MB_CNPJ  | número | Valor 500MB CNPJ |
| VALOR_700MB_CNPJ  | número | Valor 700MB CNPJ |
| VALOR_1GB_CNPJ    | número | Valor 1GB CNPJ |

### 1.2 Dados atuais (resumo)

- **Supervisor:** 3 faixas (1–39, 40–49, 50+). Valores por plano variam por faixa (ex.: 500MB PAP 200 → 220 → 230).
- **Vendedor:** 4 faixas (1–20, 21–39, até 50, 51–99999). Valores por plano por faixa (ex.: 500MB PAP 150 → 180 → 190 → 200).
- **ALEX (individual):** 2 faixas (0–39 e 40–99999) com valores vazios → usa valores manuais da aba REGRAS_VENDEDORES.

### 1.3 Regra de negócio

- O **perfil** (Supervisor / Vendedor) vem do vendedor na aba REGRAS_VENDEDORES (`PERFIL_COMISSAO`).
- A **faixa** é definida pela **quantidade de vendas instaladas a pagar** no mês: cai na linha em que `MIN_VENDAS ≤ qtd ≤ MAX_VENDAS`.
- O valor da comissão por venda é o da coluna do **plano** correspondente (500MB/700MB/1GB + PAP ou CNPJ).
- Se o perfil for um **nome de vendedor** (ex.: ALEX), a regra vale só para esse vendedor; valores vazios indicam que se usa valor manual do vendedor.

---

## 2. REGRAS_VENDEDORES – Cadastro por vendedor

### 2.1 Estrutura (colunas principais)

| Coluna                | Tipo   | Descrição |
|-----------------------|--------|-----------|
| VENDEDOR              | texto  | Nome do vendedor (ex.: RAMALHO, ALEX) |
| PERFIL_COMISSAO       | texto  | "Vendedor" ou "Supervisor" → liga à REGRAS_FAIXAS |
| USAR_VALOR_MANUAL?    | SIM/NÃO | Se SIM, ignora faixa e usa os valores manuais abaixo |
| 500MB_PAP_MANUAL      | número | Valor fixo 500MB PAP (quando manual) |
| 700MB_PAP_MANUAL      | número | 700MB PAP |
| 1GB_PAP_MANUAL        | número | 1GB PAP |
| 500MB_CNPJ_MANUAL     | número | 500MB CNPJ |
| 700MB_CNPJ_MANUAL     | número | 700MB CNPJ |
| 1GB_CNPJ_MANUAL       | número | 1GB CNPJ |
| DESCONTA DACC PAP?    | SIM/NÃO | Se aplica desconto em vendas DACC PAP |
| VENDAS BOLETO         | número | Desconto por venda boleto (ex.: -20) |
| INCLUSÃO              | número | Desconto inclusão/viabilidade (ex.: -40) |
| INSTALAÇÃO            | número | Desconto instalação (ex.: -25) |
| ADIANTAR CNPJ         | número | Desconto adiant. CNPJ (ex.: -50) |
| INSS_DESCONTA         | SIM/vazio | Se desconta INSS |
| INSS_VALOR            | número | Valor fixo INSS |
| ADIANTAMENTO          | número | Adiantamento (valor a descontar) |
| DESCONTAR CHURN       | texto  | Se considera churn no cálculo |
| PREMIAÇÃO             | número | Bônus premiação |
| BÔNUS CARTÃO DE CRÉDITO | número | Bônus ou ajuste cartão |
| CARTÃO TRAFEGO        | número | Valor cartão tráfego (pode ser negativo, ex.: -500) |
| GESTOR TRAFEGO        | número | Valor gestor tráfego |

### 2.2 Regra de negócio

- **Cálculo do valor por venda:**  
  - Se `USAR_VALOR_MANUAL? = SIM` → usa o valor da coluna do plano (500MB_PAP_MANUAL, etc.) para aquela venda.  
  - Se `USAR_VALOR_MANUAL? = NÃO` → usa REGRAS_FAIXAS: perfil = `PERFIL_COMISSAO`, faixa = qtd vendas no mês, coluna = plano da venda (500MB PAP, 1GB CNPJ, etc.).
- **Descontos:** aplicados por venda ou uma vez conforme o tipo (Boleto, Inclusão, Instalação, Adiantar CNPJ, INSS, Adiantamento, Cartão Tráfego, etc.).
- **Bônus:** PREMIAÇÃO, BÔNUS CARTÃO, etc. somados ao líquido quando aplicável.

---

## 3. FOLHA PAGAMENTO (2) – Layout da folha por vendedor

### 3.1 Bloco 1 – Cabeçalho e totais do mês

- **Cabeçalho:** ANO_MES (ex.: 202601), VENDEDOR (ex.: RAMALHO), ANOMES_PEDIDO, ANOMES_PEDIDO_ANTERIOR.
- **Tabela por plano:**

| Coluna                     | Descrição |
|----------------------------|-----------|
| PLANO                      | 500MB PAP, 700MB PAP, 1GB PAP, 500MB CNPJ, 700MB CNPJ, 1GB CNPJ |
| QTD INSTALADA A PAGAR      | Quantidade de vendas instaladas a pagar no mês |
| QTD INSTALADA JÁ PAGO      | Já pago em meses anteriores |
| QTD CHURN 30 DIAS          | Churn em até 30 dias |
| FAIXA                      | Nome da faixa aplicada (ex.: "MANUAL") |
| VALOR UNITÁRIO INSTALADOS  | Valor unitário usado para instalados |
| VALOR UNITÁRIO CHURN       | Valor unitário para churn (quando houver) |
| VALOR TOTAL - INSTALADOS   | Soma (qtd × valor unit.) instalados |
| VALOR TOTAL - CHURN        | Soma churn |
| COMISSÃO TOTAL             | Total comissão (ex.: 650) |

- **Linha TOTAL:** soma das quantidades (ex.: 3 instaladas a pagar, 0 já pago, 0 churn).
- **Linhas de ajustes (créditos/descontos/bônus):**  
  PREMIAÇÃO, INSTALAÇÃO, ADIANTAR CNPJ, DESCONTO BOLETO, GESTOR DE TRAFÉGO, CARTÃO TRAFEGO, ADIANTAR MÊS, CHURN ATÉ 30 DIAS, CHURN ACIMA 30 DIAS (valores numéricos ou vazios).

### 3.2 Bloco 2 – Extrato do mês (detalhe por venda)

Tabela com colunas:

| Coluna   | Descrição |
|----------|-----------|
| NOME     | Nome do cliente |
| DACC     | SIM/NÃO (débito em conta) |
| CNPJ     | SIM/NÃO (é CNPJ) |
| PLANO    | 500MB, 700MB, 1GB (PAP ou CNPJ conforme cliente) |
| DT PEDIDO| Data do pedido |
| DT INST  | Data instalação |
| OS       | Ordem de serviço |
| SITUAÇÃO | INSTALADA, CANCELADA, etc. |
| VENDEDOR | Nome do vendedor |
| CHURN    | ATIVO, etc. |

Ou seja: **resumo por vendedor** (totais por plano + ajustes) + **extrato** (lista de vendas do mês).

---

## 4. Planos no Excel (mapeamento)

Os “planos” no Excel são **6 combinações**:

| Planos no Excel | Equivalente no sistema atual |
|-----------------|------------------------------|
| 500MB PAP       | Plano (ex.: 500MB) + tipo cliente CPF + canal PAP |
| 700MB PAP       | Plano 700MB + CPF + PAP |
| 1GB PAP         | Plano 1GB + CPF + PAP |
| 500MB CNPJ      | Plano 500MB + tipo cliente CNPJ |
| 700MB CNPJ      | Plano 700MB + CNPJ |
| 1GB CNPJ        | Plano 1GB + CNPJ |

No sistema atual: **Plano** (FK) + **tipo_cliente** (CPF/CNPJ) + **tipo_venda** (PAP/TELAG). É necessário manter um mapeamento **nome do plano no Excel** (ex.: "500MB PAP") ↔ (Plano_id + tipo_cliente + canal) no banco.

---

## 5. Especificação para a reconstrução

### 5.1 Regras de Comissão (cadastro “como no Excel”)

**Tela 1 – Regras por faixa (REGRAS_FAIXAS)**

- Grid com colunas: **PERFIL**, **FAIXA_NOME**, **MIN_VENDAS**, **MAX_VENDAS**, **VALOR_500MB_PAP**, **VALOR_700MB_PAP**, **VALOR_1GB_PAP**, **VALOR_500MB_CNPJ**, **VALOR_700MB_CNPJ**, **VALOR_1GB_CNPJ**.
- PERFIL: dropdown ou texto (Supervisor, Vendedor, ou seleção de vendedor para regra individual).
- Edição em linha ou modal; ordenação por PERFIL e MIN_VENDAS.
- Importar/exportar Excel com essas colunas.

**Tela 2 – Regras por vendedor (REGRAS_VENDEDORES)**

- Grid com colunas: **VENDEDOR**, **PERFIL_COMISSAO**, **USAR_VALOR_MANUAL?**, **500MB_PAP_MANUAL** … **1GB_CNPJ_MANUAL**, **DESCONTA DACC PAP?**, **VENDAS BOLETO**, **INCLUSÃO**, **INSTALAÇÃO**, **ADIANTAR CNPJ**, **INSS_VALOR**, **ADIANTAMENTO**, **PREMIAÇÃO**, **CARTÃO TRAFEGO**, **GESTOR TRAFEGO**, etc.
- Uma linha por vendedor; edição em linha ou modal.
- Importar/exportar Excel no mesmo layout.

**Modelo de dados sugerido**

- Manter ou estender **RegraComissao** para “valor manual” por vendedor + plano (6 colunas por vendedor = 6 linhas ou 1 linha com 6 campos).
- Novo modelo **RegraComissaoFaixa**: perfil (ou vendedor nullable), faixa_nome, min_vendas, max_vendas, valor_500mb_pap, valor_700mb_pap, valor_1gb_pap, valor_500mb_cnpj, valor_700mb_cnpj, valor_1gb_cnpj.
- **Perfil/vendedor:** no usuário (ex.: campo `perfil_comissao` = Supervisor/Vendedor); “USAR_VALOR_MANUAL” e valores manuais podem ser no usuário ou em tabela de “regras manuais” por vendedor e plano.

### 5.2 Folha de pagamento (“como no Excel”)

- **Filtros:** ANO_MES (ou mês/ano), opcionalmente vendedor.
- **Por vendedor:**
  - Bloco resumo: tabela por **PLANO** (500MB PAP, 700MB PAP, …) com **QTD INSTALADA A PAGAR**, **QTD JÁ PAGO**, **QTD CHURN 30 DIAS**, **FAIXA**, **VALOR UNITÁRIO INSTALADOS**, **VALOR UNITÁRIO CHURN**, **VALOR TOTAL INSTALADOS**, **VALOR TOTAL CHURN**, **COMISSÃO TOTAL**.
  - Linha **TOTAL**.
  - Linhas de ajustes: **PREMIAÇÃO**, **INSTALAÇÃO**, **ADIANTAR CNPJ**, **DESCONTO BOLETO**, **GESTOR TRAFÉGO**, **CARTÃO TRAFEGO**, **ADIANTAR MÊS**, **CHURN ATÉ 30 DIAS**, **CHURN ACIMA 30 DIAS**.
- **Extrato:** tabela com **NOME**, **DACC**, **CNPJ**, **PLANO**, **DT PEDIDO**, **DT INST**, **OS**, **SITUAÇÃO**, **VENDEDOR**, **CHURN** para cada venda do mês (expandível por vendedor ou em aba separada).
- **Exportar Excel:** mesma estrutura (resumo por plano + ajustes + extrato por vendedor).
- **Exportar PDF:** resumo + extrato por vendedor, no mesmo “formato” da planilha.

### 5.3 Cálculo (alinhado ao Excel)

1. Para o mês: listar vendas **instaladas** com data de instalação no mês (e critério “a pagar” se houver status de comissionamento).
2. Por vendedor:  
   - Contar **qtd instalada a pagar**; definir **faixa** (REGRAS_FAIXAS por perfil e qtd).  
   - Se **USAR_VALOR_MANUAL** → valor por venda = valor manual do plano (REGRAS_VENDEDORES).  
   - Senão → valor por venda = valor da faixa para aquele plano (REGRAS_FAIXAS).  
   - Somar por plano e total (COMISSÃO TOTAL).  
3. Aplicar descontos (Boleto, Inclusão, Instalação, Adiantar CNPJ, INSS, Adiantamento, Cartão Tráfego, Gestor Tráfego) conforme REGRAS_VENDEDORES.  
4. Aplicar bônus (PREMIAÇÃO, etc.).  
5. Líquido = Comissão total + bônus - descontos.

---

## 6. Resumo das colunas para implementação

### REGRAS_FAIXAS (grid)

- PERFIL, FAIXA_NOME, MIN_VENDAS, MAX_VENDAS  
- VALOR_500MB_PAP, VALOR_700MB_PAP, VALOR_1GB_PAP  
- VALOR_500MB_CNPJ, VALOR_700MB_CNPJ, VALOR_1GB_CNPJ  

### REGRAS_VENDEDORES (grid)

- VENDEDOR, PERFIL_COMISSAO, USAR_VALOR_MANUAL?  
- 500MB_PAP_MANUAL, 700MB_PAP_MANUAL, 1GB_PAP_MANUAL, 500MB_CNPJ_MANUAL, 700MB_CNPJ_MANUAL, 1GB_CNPJ_MANUAL  
- DESCONTA DACC PAP?, VENDAS BOLETO, INCLUSÃO, INSTALAÇÃO, ADIANTAR CNPJ  
- INSS_VALOR, ADIANTAMENTO, PREMIAÇÃO, CARTÃO TRAFEGO, GESTOR TRAFEGO (e demais se necessário)

### FOLHA PAGAMENTO (tela e export)

- Cabeçalho: ANO_MES, VENDEDOR  
- Tabela plano: PLANO, QTD INSTALADA A PAGAR, QTD JÁ PAGO, QTD CHURN 30 DIAS, FAIXA, VALOR UNIT. INSTALADOS, VALOR UNIT. CHURN, VALOR TOTAL INSTALADOS, VALOR TOTAL CHURN, COMISSÃO TOTAL  
- Ajustes: PREMIAÇÃO, INSTALAÇÃO, ADIANTAR CNPJ, DESCONTO BOLETO, GESTOR TRAFÉGO, CARTÃO TRAFEGO, ADIANTAR MÊS, CHURN ATÉ 30 DIAS, CHURN ACIMA 30 DIAS  
- Extrato: NOME, DACC, CNPJ, PLANO, DT PEDIDO, DT INST, OS, SITUAÇÃO, VENDEDOR, CHURN  

Com isso, a reconstrução da **Gestão de Comissionamento** (Regras de Comissão + Folha de Pagamento) fica alinhada ao Excel nas duas abas de regras e na folha de pagamento.
