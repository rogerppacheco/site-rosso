# Relatório: Bônus M-10 & FPD – Funcionamento e Gaps

**Objetivo:** Documentar passo a passo como a ferramenta funciona e listar gaps (pontos que podem não estar funcionando corretamente).

---

## 1. Visão geral da ferramenta

- **Onde acessar:** Área Interna → card **"Bônus M-10"** (URL: `/bonus-m10/`).
- **Função:** Controlar bônus baseado nas **10 primeiras faturas pagas** (M-10) e no indicador **FPD (First Payment Default)** da primeira fatura.
- **Regra de bônus:** R$ 150,00 por contrato **elegível** (10 faturas pagas + ativo + sem downgrade).

---

## 2. Fluxo passo a passo (como a ferramenta funciona)

### 2.1 Modelos de dados (resumo)

| Modelo | Função |
|--------|--------|
| **SafraM10** | Agrupa contratos por mês de **instalação** (mes_referencia, total_instalados, total_ativos, total_elegivel_bonus, valor_bonus_total). |
| **ContratoM10** | Um contrato por O.S.: venda, numero_contrato, ordem_servico, dados FPD (data_vencimento_fpd, status_fatura_fpd, etc.), status_contrato (ATIVO/CANCELADO/DOWNGRADE), elegivel_bonus. |
| **FaturaM10** | Até 10 faturas por contrato (numero_fatura 1–10): valor, datas, status (PAGO, NAO_PAGO, AGUARDANDO, ATRASADO, OUTROS). |
| **ImportacaoFPD** | Registros da planilha FPD da operadora: nr_ordem, id_contrato, nr_fatura, dt_venc_orig, dt_pagamento, ds_status_fatura, vl_fatura, vínculo opcional com ContratoM10. |
| **LogImportacaoFPD** | Log de cada importação FPD (status, totais, mensagem_erro). |

### 2.2 Passo 1: Ter contratos na base (Popular Safra)

1. Usuário escolhe **Safra (mês/ano)** na tela.
2. Clica em **"Popular Safra"** (ou chama `POST /api/bonus-m10/safras/popular/` com `mes_referencia: "YYYY-MM"`).
3. Backend:
   - Filtra **Venda** com `data_instalacao` no mês, `ativo=True`, `status_esteira=INSTALADA`.
   - Ordena por `data_criacao` (mais antiga primeiro).
   - Para cada venda, se ainda não existir **ContratoM10** com a mesma `ordem_servico` (ou mesmo `numero_contrato` quando não há O.S.), **cria** ContratoM10 (safra, venda, cliente_nome, data_instalacao, plano, status_contrato=ATIVO).
   - Atualiza a **SafraM10**: `total_instalados` e `total_ativos` (não atualiza `total_elegivel_bonus` nem `valor_bonus_total` aqui).

**Resultado:** Contratos M-10 existem para todas as vendas INSTALADA do mês (por O.S.).

### 2.3 Passo 2: Importar planilha FPD

1. Usuário vai à **Central de Importações** (ou fluxo que chama a API) e envia a planilha FPD (Excel/CSV).
2. API: `POST /api/bonus-m10/importar-fpd/` com arquivo (multipart).
3. Backend (**ImportarFPDView**):
   - Cria **LogImportacaoFPD** com status PROCESSANDO.
   - Inicia **thread em background** que:
     - Lê o arquivo (colunas normalizadas em minúsculas: `id_contrato`, `nr_fatura`, `nr_ordem`, `dt_venc_orig`, `dt_pagamento`, `ds_status_fatura`, `nr_dias_atraso`, `vl_fatura`).
     - Para cada linha com `nr_ordem` válido:
       - **Match com ContratoM10:** usa dicionário em memória com várias formas da O.S. (exato, sem zeros, com prefixo `OS-`, etc.).
       - Se encontrar contrato:
         - Atualiza `ContratoM10.numero_contrato_definitivo` com `id_contrato`.
         - Cria ou atualiza **FaturaM10** número **1** com: numero_fatura_operadora, valor, data_vencimento, data_pagamento, dias_atraso, status (via `normalizar_status_fpd(ds_status_fatura)`), id_contrato_fpd, dt_pagamento_fpd, ds_status_fatura_fpd.
         - Cria ou atualiza **ImportacaoFPD** (nr_ordem, id_contrato, nr_fatura, dt_venc_orig, dt_pagamento, ds_status_fatura, vl_fatura, contrato_m10).
       - Se **não** encontrar contrato: mesmo assim cria/atualiza **ImportacaoFPD** com `contrato_m10=None` (para possível matching depois).
     - Usa **bulk_create** e **bulk_update** para FaturaM10 e ImportacaoFPD.
     - Atualiza em bulk apenas `ContratoM10.numero_contrato_definitivo` (não atualiza data_vencimento_fpd, status_fatura_fpd, etc. no ContratoM10).
   - Resposta HTTP imediata: “Importação iniciada em segundo plano; atualize a página em alguns minutos.”

**Resultado:** Fatura 1 preenchida (ou criada) por contrato encontrado; ImportacaoFPD preenchida; log com status SUCESSO/PARCIAL/ERRO.

### 2.4 Passo 3: Importar base Churn (cancelamentos)

1. Usuário importa planilha Churn pela **Central de Importações** ou pelo fluxo M-10 (importar churn).
2. API M-10: `POST /api/bonus-m10/importar-churn/` com arquivo.
3. Backend (**ImportarChurnView**):
   - Lê colunas: NR_ORDEM ou NUMERO_PEDIDO (O.S.), entre outras (DT_RETIRADA, MOTIVO_RETIRADA, etc.).
   - Normaliza O.S.: `nr_ordem = str(nr_ordem_raw).strip().zfill(8)`.
   - Para cada linha: grava/atualiza **ImportacaoChurn**; em seguida busca **ContratoM10** por `ordem_servico=nr_ordem` e, se achar, marca como **CANCELADO** (data_cancelamento, motivo_cancelamento, elegivel_bonus=False).
   - Depois: marca como **ATIVO** todos os ContratoM10 cuja `ordem_servico` **não** está na lista de O.S. do churn e que não estavam ATIVO.

**Resultado:** Contratos que constam no churn ficam CANCELADOS; os que não constam podem ser reativados para ATIVO.

### 2.5 Passo 4: Faturas 2 a 10 (manual ou busca Nio)

- **Manual:** usuário edita o contrato (botão ✏️) e preenche/salva as faturas 2–10.
- **Busca Nio:** “Buscar Faturas” (por safra) ou busca individual: o sistema chama API Nio (conforme implementação em views/serializers) e preenche dados da fatura quando disponível.

### 2.6 Passo 5: Cálculo de elegibilidade

- **Onde:** No model **ContratoM10**, método `calcular_elegibilidade()`.
- **Regra:**
  - Conta `total_faturas` e `faturas_pagas` (status PAGO).
  - Se não houver faturas cadastradas mas `status_fatura_fpd` começar com “paga”, considera 1/1.
  - Elegível se: `total_faturas > 0`, `faturas_pagas == total_faturas`, `teve_downgrade == False`, `status_contrato == 'ATIVO'`.
- **Quando é chamado:** Na edição de faturas em massa (AtualizarFaturasView) chama `fatura.contrato.calcular_elegibilidade()` por fatura alterada. **Não** é chamado ao final da importação FPD em lote.

### 2.7 Passo 6: Dashboard M-10 (aba “Bônus M-10”)

- **API:** `GET /api/bonus-m10/dashboard-m10/?safra=<id_safra>` (opcional: vendedor, status, elegivel, q).
- Backend filtra **ContratoM10** por `data_instalacao` no mês da safra, aplica filtros, anota `total_faturas` e `faturas_pagas` (Count), aplica fallback FPD (sem faturas mas status_fatura_fpd “paga” → 1/1).
- Calcula em memória: total, ativos, elegíveis (regra igual ao model), valor_total = elegíveis × 150.
- Para exibição da tabela: para cada contrato usa **fatura 1** se existir; senão usa `data_vencimento_fpd`, `data_pagamento_fpd`, `status_fatura_fpd` do ContratoM10 (fallback).

### 2.8 Passo 7: Dashboard FPD (aba “FPD”)

- **API:** `GET /api/bonus-m10/dashboard-fpd/?mes=YYYY-MM` (opcional).
- Filtra **FaturaM10** com `numero_fatura=1` (e por mês de vencimento se informado).
- Retorna: total_geradas, total_pagas, total_aberto, taxa_fpd (%), lista de faturas.

### 2.9 Passo 8: Exportar Excel

- **API:** `GET /api/bonus-m10/exportar/?safra=...`
- Gera planilha com contratos da safra e coluna “Bônus M-10”.

### 2.10 Signals (automação)

- **Venda salva** com ativo, INSTALADA, data_instalacao e ordem_servico → cria **ContratoM10** (se não existir por O.S.) e chama `sincronizar_com_fpd`.
- **ContratoM10 criado** → `sincronizar_com_fpd`: busca ImportacaoFPD por nr_ordem e preenche no ContratoM10: numero_contrato_definitivo, data_vencimento_fpd, data_pagamento_fpd, status_fatura_fpd, valor_fatura_fpd, nr_dias_atraso_fpd.
- **ImportacaoFPD criada** (post_save): se não tiver contrato_m10, busca ContratoM10 por ordem_servico e vincula; e preenche os campos FPD no ContratoM10.

Importante: **bulk_create** e **bulk_update** **não** disparam `post_save`. Por isso, na importação FPD em lote os signals **não** rodam.

---

## 3. Gaps identificados (o que pode não estar funcionando)

### GAP 1 – ContratoM10 não recebe campos FPD na importação em lote

- **Onde:** `ImportarFPDView._processar_fpd_interno`.
- **O que acontece:** A importação usa `bulk_create` e `bulk_update` em **ImportacaoFPD** e **FaturaM10**. O único campo do **ContratoM10** atualizado no código é `numero_contrato_definitivo`. Os campos `data_vencimento_fpd`, `data_pagamento_fpd`, `status_fatura_fpd`, `valor_fatura_fpd`, `nr_dias_atraso_fpd` **não** são preenchidos nesse fluxo.
- **Por quê:** Eles são preenchidos pelos **signals** em `post_save` de ImportacaoFPD, mas signals **não** são disparados em bulk.
- **Efeito:** Se um contrato ainda não tiver FaturaM10 número 1 (ou a tela usar fallback), a interface usa `ContratoM10.data_vencimento_fpd` e `status_fatura_fpd`. Esses campos podem continuar vazios mesmo após importar FPD com sucesso, e o fallback de elegibilidade (1/1 quando “paga” no FPD) pode falhar por falta de `status_fatura_fpd`.

**Sugestão:** Após o bulk da importação FPD, percorrer os contratos que tiveram FaturaM10 criada/atualizada (ou ImportacaoFPD vinculada) e atualizar explicitamente no ContratoM10: data_vencimento_fpd, data_pagamento_fpd, status_fatura_fpd, valor_fatura_fpd, nr_dias_atraso_fpd (e data_ultima_sincronizacao_fpd), a partir da FaturaM10 número 1 ou do último ImportacaoFPD do contrato.

---

### GAP 2 – Elegibilidade não recalculada após importação FPD

- **Onde:** Após `bulk_create`/`bulk_update` de FaturaM10 em `_processar_fpd_interno`.
- **O que acontece:** Nenhuma chamada a `contrato.calcular_elegibilidade()` (nem atualização de `elegivel_bonus`) para os contratos afetados.
- **Efeito:** O **dashboard** calcula elegíveis em tempo real (anotações e contagem em memória), então os **números exibidos** podem estar corretos. Porém o campo **ContratoM10.elegivel_bonus** fica desatualizado. Qualquer outro lugar que use só esse campo (relatórios, exportação, integrações) pode mostrar valor errado.

**Sugestão:** Após atualizar os contratos no GAP 1, chamar `calcular_elegibilidade()` para cada contrato afetado (ou em batch por safra).

---

### GAP 3 – SafraM10.total_elegivel_bonus e valor_bonus_total nunca atualizados

- **Onde:** Em todo o fluxo (Popular Safra, Importar FPD, Importar Churn, edição de faturas).
- **O que acontece:** `PopularSafraM10View` atualiza apenas `total_instalados` e `total_ativos`. Nenhum fluxo recalcula `total_elegivel_bonus` nem `valor_bonus_total` na **SafraM10**.
- **Efeito:** Se a listagem de safras ou algum relatório usar esses campos da SafraM10, os valores estarão desatualizados (geralmente zerados ou de uma população antiga).

**Sugestão:** Ter uma função/command que recalcule por safra: contar contratos elegíveis no mês e atualizar `total_elegivel_bonus` e `valor_bonus_total`. Opcionalmente chamar esse recálculo após Popular Safra, após importação FPD (por safras afetadas) e após importação Churn.

---

### GAP 4 – Match de O.S. no Churn pode falhar por formato diferente

- **Onde:** `ImportarChurnView`: busca ContratoM10 com `ordem_servico=nr_ordem`, onde `nr_ordem = str(nr_ordem_raw).strip().zfill(8)`.
- **O que acontece:** No M-10 a `ordem_servico` vem da **Venda** (pode ser "12345678", "01234567", "OS-12345678", etc.). No Churn só se usa uma forma: 8 dígitos com zeros à esquerda.
- **Efeito:** Se no banco o ContratoM10 tiver O.S. sem zeros ou com prefixo, o `get(ordem_servico=nr_ordem)` não acha e o contrato não é marcado como CANCELADO (e conta como “não encontrado”).

**Sugestão:** Usar a mesma estratégia do FPD: construir um dicionário de ContratoM10 indexado por várias formas da O.S. (exato, sem zeros, com/sem prefixo OS-, zfill(8)) e fazer o match por qualquer uma delas.

---

### GAP 5 – Duplicidade de método `calcular_duracao` em LogImportacaoFPD

- **Onde:** `crm_app/models.py`, modelo **LogImportacaoFPD**.
- **O que acontece:** O modelo define `calcular_duracao` duas vezes (uma usando `iniciado_em`/`finalizado_em`, outra usando `data_importacao`/`finalizado_em`). A segunda definição sobrescreve a primeira.
- **Efeito:** Comportamento confuso e dependente de qual implementação era a desejada (duração real da importação vs. diferença entre data_importacao e finalizado_em).

**Sugestão:** Manter uma única implementação clara (por exemplo, duração entre iniciado_em e finalizado_em quando ambos existirem) e remover a duplicata.

---

### GAP 6 – Reativação em massa no Churn pode ser indesejada

- **Onde:** `ImportarChurnView`: `ContratoM10.objects.exclude(ordem_servico__in=ordens_no_churn).exclude(status_contrato='ATIVO').update(status_contrato='ATIVO', ...)`.
- **O que acontece:** Todo contrato M-10 cuja O.S. **não** está na planilha de churn e que não está ATIVO é marcado como ATIVO.
- **Efeito:** Contratos cancelados por **outro** motivo (ex.: downgrade, cancelamento manual) ou com O.S. que não veio na planilha podem ser reativados incorretamente.

**Sugestão:** Revisar regra de negócio: por exemplo, só reativar se o contrato tiver sido cancelado “por churn” (ex.: motivo_cancelamento = 'CHURN') ou não reativar em massa e deixar apenas “marcar como cancelado” quem está no arquivo.

---

### GAP 7 – Planilha FPD sem coluna NR_ORDEM

- **Onde:** Leitura do DataFrame na importação FPD; colunas esperadas em minúsculas incluem `nr_ordem`.
- **O que acontece:** Se a planilha não tiver coluna NR_ORDEM (ou nome equivalente após normalização), todas as linhas são puladas (`nr_ordem` vazio) e o log pode indicar “Todas as X linhas foram puladas (NR_ORDEM vazio ou inválido)”.
- **Efeito:** Importação “zerada” sem explicar claramente que o problema é a falta da coluna de O.S.

**Sugestão:** Validar presença de coluna obrigatória (nr_ordem ou alias) no início do processamento e retornar mensagem explícita (“Coluna NR_ORDEM não encontrada no arquivo”).

---

### GAP 8 – Formato .xlsb e dependência pyxlsb

- **Onde:** ImportarFPDView e ImportarChurnView: tratamento para `.xlsb` com `engine='pyxlsb'`.
- **O que acontece:** Se `pyxlsb` não estiver instalado ou houver falha, o usuário recebe erro genérico.
- **Efeito:** Dificuldade de diagnóstico em ambiente onde .xlsb é usado.

**Sugestão:** Documentar dependência e mensagem de erro sugerindo “Use .xlsx ou .csv” ou instale pyxlsb; ou desabilitar .xlsb e exigir .xlsx/.csv.

---

## 4. Resumo dos fluxos e pontos de falha

| Fluxo | O que depende | Possível falha (gap) |
|-------|----------------|----------------------|
| Popular Safra | Venda INSTALADA, data_instalacao, ordem_servico | O.S. duplicada: só um ContratoM10 por O.S. |
| Importar FPD | Coluna NR_ORDEM; match O.S. com ContratoM10 | GAP 1 (campos FPD no contrato); GAP 2 (elegibilidade); GAP 7 (coluna); GAP 8 (.xlsb) |
| Importar Churn | NR_ORDEM ou NUMERO_PEDIDO; match exato O.S. | GAP 4 (formato O.S.); GAP 6 (reativação em massa) |
| Dashboard M-10 | Safra obrigatória; cálculos em tempo real | Safra sem total_elegivel_bonus atualizado (GAP 3) |
| Elegibilidade | Faturas + status + ContratoM10 | Fallback 1/1 depende de status_fatura_fpd (GAP 1) |

---

## 5. Ordem sugerida para correções

1. **GAP 1** – Atualizar campos FPD do ContratoM10 após importação em lote (e, se fizer sentido, preencher a partir da FaturaM10 nº 1 quando já existir).
2. **GAP 2** – Recalcular elegibilidade nos contratos afetados pela importação FPD.
3. **GAP 4** – Alinhar matching de O.S. no Churn ao mesmo critério de variações usado no FPD.
4. **GAP 3** – Implementar recálculo de total_elegivel_bonus e valor_bonus_total da SafraM10 (e chamar onde for adequado).
5. **GAP 5** – Unificar `calcular_duracao` em LogImportacaoFPD.
6. **GAP 6** – Ajustar regra de reativação no Churn conforme negócio.
7. **GAP 7** – Validação de coluna NR_ORDEM na importação FPD.
8. **GAP 8** – Documentação/tratamento de .xlsb.

---

## 6. Correções aplicadas (fev/2026)

- **GAP 1 e 2:** Após importação FPD em lote, o sistema atualiza os campos FPD no ContratoM10 (data_vencimento_fpd, status_fatura_fpd, etc.) a partir da FaturaM10 nº 1 e chama `calcular_elegibilidade()` nos contratos afetados.
- **GAP 3:** Função `_recalcular_totais_safra_m10(safra_str)` implementada; chamada após importação FPD (safras afetadas) e após Popular Safra.
- **GAP 4:** Importar Churn usa dicionário com várias formas da O.S. (exato, sem zeros, zfill(8), prefixo OS-), igual ao FPD.
- **GAP 5:** Método `calcular_duracao` em LogImportacaoFPD unificado (uma única implementação).
- **GAP 6:** Reativação no Churn apenas para contratos CANCELADO com `motivo_cancelamento` contendo "CHURN" e cuja O.S. não está na planilha atual.
- **GAP 7:** Validação da coluna NR_ORDEM no início da importação FPD; mensagem clara se a coluna não existir.
- **GAP 8:** Mensagem de erro para .xlsb orienta uso de .xlsx/.csv ou instalação de pyxlsb.
- **FPD = 1ª fatura:** Na interface, aba FPD e modal deixam explícito que FPD acompanha apenas o pagamento da primeira fatura; regra de vencimento documentada em IMPLEMENTACAO_VENCIMENTOS_FATURAS.md (dias 1-28: +25 dias; 29-31: dia 26 do mês seguinte).

---

**Documento gerado para suporte à análise e correção da ferramenta Bônus M-10 & FPD.**
