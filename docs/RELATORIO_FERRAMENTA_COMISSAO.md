# Relatório: Funcionamento da Ferramenta "Comissão"

Este documento descreve como a ferramenta **Comissão** (Comissionamento) funciona no sistema, para servir de base à reconstrução.

---

## 1. Visão geral

A ferramenta **Comissão** é um módulo de **gestão de comissionamento** que:

- Calcula comissão por consultor com base em vendas **instaladas**, regras por plano/tipo de venda/cliente e meta.
- Aplica descontos (boleto, inclusão/viabilidade, antecipação, adiantamento CNPJ) e bônus (campanhas).
- Permite **confirmar descontos** em massa (pendências) e **reverter** processamentos automáticos.
- Faz **fechamento** e **reabertura** de mês, gera **PDF**, envia **e-mail** e **WhatsApp**.

**Acesso:** área interna → card "Comissão" → `/comissionamento/`  
**API base:** `/api/crm/comissionamento/` (e outras rotas sob `/api/crm/`).

---

## 2. Modelos de dados envolvidos

### 2.1 RegraComissao

- **Tabela:** `crm_regra_comissao`
- **Campos:** `consultor` (FK Usuario), `plano` (FK Plano), `tipo_venda` (PAP | TELAG), `tipo_cliente` (CPF | CNPJ), `valor_base`, `valor_acelerado`
- **Unique:** (consultor, plano, tipo_venda, tipo_cliente)
- **Uso:** Para cada venda instalada, o sistema busca a regra que combina plano + tipo cliente (CPF/CNPJ pelo tamanho do documento) + canal do vendedor (PAP/TELAG). Se o consultor **bateu a meta** (qtd instaladas ≥ meta), usa `valor_acelerado`; senão, `valor_base`.

### 2.2 ComissaoOperadora

- **Tabela:** relacionada a `Plano` (OneToOne).
- **Campos:** `valor_base`, `bonus_transicao`, `data_inicio_bonus`, `data_fim_bonus`
- **Uso:** Visão **Diretoria**: quanto a empresa recebe da operadora por plano (base + bônus transição se dentro da validade). Não altera o valor pago ao consultor.

### 2.3 Venda (campos relevantes para comissão)

- `vendedor`, `plano`, `cliente`, `forma_pagamento`, `status_esteira`, `data_instalacao`, `data_criacao`
- `inclusao` (inclusão/viabilidade), `antecipou_instalacao`
- `status_comissionamento`, `data_pagamento_comissao`
- Flags de desconto já processado: `flag_adiant_cnpj`, `flag_desc_boleto`, `flag_desc_viabilidade`, `flag_desc_antecipacao`

### 2.4 LancamentoFinanceiro

- **Tipos:** ADIANTAMENTO_CNPJ, ADIANTAMENTO_COMISSAO, DESCONTO
- **Campos:** `usuario`, `tipo`, `data`, `valor`, `quantidade_vendas`, `descricao`, `metadados` (JSON com `ids_vendas`, `tipos_processados`, `origem: "automatico"`), `criado_por`, `data_criacao`
- **Uso:** Descontos e adiantamentos lançados (manuais ou via “Confirmar descontos”). O relatório mensal soma esses valores por consultor no mês. A reversão usa `metadados` para zerar as flags nas vendas.

### 2.5 PagamentoComissao

- **Tabela:** `crm_pagamento_comissao`
- **Campos:** `referencia_ano`, `referencia_mes`, `data_fechamento`, `total_pago_consultores`, `total_recebido_ciclo`, `observacoes`
- **Unique:** (referencia_ano, referencia_mes)
- **Uso:** Registro de fechamento do mês (mês “pago”). Reabrir exclui o registro e zera status/data nas vendas.

### 2.6 CicloPagamento

- Importação externa (arquivo ciclo). Campos incluem `valor_comissao_final`, `ano`, `mes`, etc.
- **Uso:** No histórico de pagamentos, “Total recebido (Ciclo)” é a soma de `valor_comissao_final` do CicloPagamento no mês.

### 2.7 Campanha

- Campanhas com meta de vendas e prêmio; elegibilidade por planos e formas de pagamento.
- **Uso:** Se o consultor atinge a meta da campanha no período, recebe o valor do prêmio como **bônus** no líquido.

### 2.8 Perfil do usuário (consultor)

- `meta_comissao`, `canal` (PAP/TELAG), `desconto_boleto`, `desconto_inclusao_viabilidade`, `desconto_instalacao_antecipada`, `adiantamento_cnpj`, `desconto_inss_fixo`, `tel_whatsapp`, etc.

---

## 3. Regras de negócio do cálculo

### 3.1 Base do cálculo

- Considera apenas vendas **ativas**, com **status_esteira = INSTALADA** e **data_instalacao** dentro do mês (ano/mês informados).
- Para cada venda:
  - Tipo cliente: CPF se documento ≤ 11 dígitos, CNPJ se > 11.
  - Canal: atributo `canal` do consultor (default PAP).
  - Busca **RegraComissao** com mesmo plano, tipo_cliente, tipo_venda e consultor. Há fallback para regra com `consultor is None` no código, mas o modelo exige `consultor` (FK), então esse fallback hoje não encontra nada.
  - Valor da venda na comissão: `valor_acelerado` se **bateu meta** (qtd instaladas no mês ≥ meta_comissao), senão `valor_base`.
- **Comissão bruta** = soma desses valores no mês.

### 3.2 Meta e acelerado

- **Meta:** `consultor.meta_comissao` (número de vendas).
- **Bateu meta:** `qtd_instaladas >= meta`.
- Se bateu meta, todas as vendas do mês do consultor usam `valor_acelerado`; se não, todas usam `valor_base`.

### 3.3 Descontos (previstos e já processados)

- **Previstos (automáticos no relatório):**  
  - Boleto: se forma de pagamento contém "BOLETO" e não `flag_desc_boleto` → usa `consultor.desconto_boleto`.  
  - Inclusão/Viabilidade: se `venda.inclusao` e não `flag_desc_viabilidade` → `consultor.desconto_inclusao_viabilidade`.  
  - Antecipação: se `venda.antecipou_instalacao` e não `flag_desc_antecipacao` → `consultor.desconto_instalacao_antecipada`.  
  - Adiant. CNPJ: se cliente CNPJ e não `flag_adiant_cnpj` → `consultor.adiantamento_cnpj`.
- **Já processados:** vêm dos **LancamentoFinanceiro** do mês (data dentro do período). Somados por consultor e exibidos no detalhe (ex.: “Adiant. CNPJ: -X”, “Desconto: -Y”).
- **Fixo:** `consultor.desconto_inss_fixo` é somado uma vez por consultor no mês.

### 3.4 Bônus (campanhas)

- Para cada **Campanha** ativa com `data_fim` no ano/mês:
  - Filtra vendas do consultor no período da campanha; conforme `tipo_meta` (ex.: LIQUIDA = só instaladas).
  - Aplica filtros de canal, planos elegíveis, formas de pagamento elegíveis.
  - Se total de vendas ≥ meta da campanha → soma `valor_premio` ao bônus do consultor.

### 3.5 Valor líquido

- **Líquido = (Comissão bruta + Total bônus) - Total descontos**  
(descontos = previstos ainda não lançados + lançamentos financeiros do mês + INSS fixo).

---

## 4. Quem vê valor de comissão

- **Diretoria / Admin:** `exibir_comissao = True` (incluindo no dashboard de resumo).
- **BackOffice:** `exibir_comissao = False` (não vê valores de comissão).
- **Demais perfis (ex.: vendedor, supervisor):** `exibir_comissao = True`.

---

## 5. Endpoints e fluxos da ferramenta

### 5.1 Relatório mensal (tela principal)

- **GET** `/api/crm/comissionamento/?ano=AAAA&mes=M`
- **View:** `ComissionamentoView`
- **Retorno:**  
  - `periodo`: "M/AAAA"  
  - `relatorio_consultores`: lista por consultor com `consultor_id`, `consultor_nome`, `qtd_instaladas`, `meta`, `atingimento_pct`, `comissao_bruta`, `total_descontos`, `total_bonus`, `valor_liquido`, `detalhes_planos`, `detalhes_descontos`, `detalhes_bonus`  
  - `historico_pagamentos`: últimos 6 meses com `ano_mes`, `total_pago_equipe`, `total_recebido_ciclo`, `status` (Aberto/Fechado)

### 5.2 Pendências de desconto

- **GET** `/api/crm/comissionamento/pendencias-desconto/`
- **View:** `PendenciasDescontoView`
- Lista vendas instaladas que ainda têm algum desconto “pendente” (valor > 0 no perfil e flag da venda ainda False). Cada item: venda, vendedor, cliente, tipo (CNPJ, BOLETO, VIABILIDADE, ANTECIPACAO), valor.

### 5.3 Confirmar descontos em massa

- **POST** `/api/crm/comissionamento/confirmar-descontos/`
- **Body:** `{ "data": "AAAA-MM-DD", "itens": [ { "venda_id", "vendedor_id", "tipo_codigo", "valor" }, ... ] }`
- **View:** `ConfirmarDescontosEmMassaView`
- Agrupa por vendedor; cria um ou mais `LancamentoFinanceiro` (tipo ADIANTAMENTO_CNPJ ou DESCONTO) com `metadados.ids_vendas` e `tipos_processados`; atualiza as flags nas vendas (`flag_adiant_cnpj`, `flag_desc_boleto`, etc.).

### 5.4 Histórico de processamentos automáticos

- **GET** `/api/crm/comissionamento/historico-auto/`
- **View:** `HistoricoDescontosAutoView`
- Lista até 50 últimos `LancamentoFinanceiro` com `descricao__startswith="Processamento Auto"` (data, vendedor, descrição, valor, criado_por).

### 5.5 Reverter processamento

- **POST** `/api/crm/comissionamento/reverter-auto/`
- **Body:** `{ "id": <id do LancamentoFinanceiro> }`
- **View:** `ReverterDescontoMassaView`
- Só para lançamentos “Processamento Auto”. Lê `metadados`, zera as flags nas vendas referenciadas e exclui o lançamento. Registros antigos sem `metadados` só têm o financeiro excluído.

### 5.6 Fechar pagamento do mês

- **POST** `/api/crm/fechar-pagamento/`  
- **Nota:** O frontend atual chama `POST /api/crm/comissionamento/fechar/` — **rota não existe**; a rota correta é `fechar-pagamento/`.
- **Body:** `{ "ano", "mes", "total_pago" }`
- **View:** `FecharPagamentoView`
- Atualiza vendas instaladas do mês: `status_comissionamento = PAGO`, `data_pagamento_comissao = hoje`. Cria/atualiza `PagamentoComissao` (referencia_ano/mes, total_pago_consultores).

### 5.7 Reabrir mês

- **POST** `/api/crm/reabrir-pagamento/`  
- **Nota:** O frontend chama `POST /api/crm/comissionamento/reabrir/` — **rota não existe**; a correta é `reabrir-pagamento/`.
- **Body:** `{ "ano", "mes" }`
- **View:** `ReabrirPagamentoView`
- Coloca vendas do mês em status comissionamento PENDENTE e `data_pagamento_comissao = None`; remove o registro de `PagamentoComissao` do mês.

### 5.8 Gerar PDF extrato

- **POST** `/api/crm/gerar-relatorio-pdf/`  
- **Nota:** O frontend chama `POST /api/crm/comissionamento/pdf/` — **rota não existe**; a correta é `gerar-relatorio-pdf/`.
- **Body:** `{ "ano", "mes", "consultores": [ids] }`
- **View:** `GerarRelatorioPDFView`
- Gera PDF (landscape) com vendas instaladas do mês (vendedor, CPF/CNPJ, DACC, cliente, plano, datas, OS, status, churn se houver). Resposta: arquivo PDF.

### 5.9 Enviar extrato por e-mail

- **POST** `/api/crm/enviar-extrato-email/`  
- **Nota:** O frontend chama `POST /api/crm/comissionamento/email/` — **rota não existe**; a correta é `enviar-extrato-email/`.
- **Body:** `{ "ano", "mes", "consultores", "email_destino" (opcional) }`
- **View:** `EnviarExtratoEmailView`
- Envia extrato (PDF/tabela) por e-mail para os consultores selecionados (ou e-mail destino quando um único consultor).

### 5.10 Enviar resumo comissão via WhatsApp

- **POST** `/api/crm/comissionamento/whatsapp/`
- **Body:** `{ "ano", "mes", "consultores": [ids] }`
- **View:** `enviar_comissao_whatsapp` (função)
- Para cada consultor: recalcula bruto/descontos/líquido (mesma lógica do relatório), monta texto/card e chama `WhatsAppService.enviar_resumo_comissao(telefone, dados_comissao)`. Usa `tel_whatsapp` do consultor.

---

## 6. Frontend (página Comissão)

- **Arquivo:** `frontend/public/comissionamento.html` (servida em `/comissionamento/`).
- **Base URL usada no JS:** `apiUrl = '/api/crm/comissionamento/'`

### 6.1 Abas

1. **Visão por Consultor**  
   - Filtro mês/ano; tabela com consultor, qtd, meta, %, comissão bruta, total descontos, líquido.  
   - Checkbox “selecionar todos” e por linha.  
   - Ações: Gerar PDF Extrato, Enviar E-mail, Enviar via WhatsApp.  
   - Expandir linha: detalhamento por plano e fechamento (bruto, bônus, descontos, a receber).  
   - Rodapé: status do mês (Aberto/Fechado), botão “Fechar Pagamento” ou “Reabrir Mês”.

2. **Confirmar Descontos**  
   - Tabela de pendências (vendedor, cliente, tipo, data inst., valor) com filtros e checkbox.  
   - Data do lançamento + “Confirmar Selecionados” → chama `confirmar-descontos/`.  
   - Tabela “Histórico de Processamentos” com botão reverter por linha → `reverter-auto/`.

3. **Histórico de Pagamentos**  
   - Tabela com mês/ano, total pago equipe, total recebido ciclo, status (Aberto/Fechado).

### 6.2 Inconsistência de URLs (bug atual)

O frontend usa sufixos relativos a `apiUrl` para fechar, reabrir, PDF e e-mail, mas no backend essas ações estão em rotas diferentes:

| Ação              | Chamada atual do frontend              | Rota real no backend              |
|-------------------|----------------------------------------|-----------------------------------|
| Fechar pagamento  | POST `.../comissionamento/fechar/`     | POST `.../fechar-pagamento/`      |
| Reabrir mês       | POST `.../comissionamento/reabrir/`    | POST `.../reabrir-pagamento/`     |
| Gerar PDF         | POST `.../comissionamento/pdf/`        | POST `.../gerar-relatorio-pdf/`   |
| Enviar e-mail     | POST `.../comissionamento/email/`     | POST `.../enviar-extrato-email/`   |
| WhatsApp          | POST `.../comissionamento/whatsapp/`  | OK (rota existe)                  |

Na reconstrução, ou se unificam as rotas sob `comissionamento/` (fechar, reabrir, pdf, email) ou se corrige o frontend para usar as rotas atuais.

---

## 7. Dashboard de resumo (card comissão no período)

- Usado em outro contexto (ex.: performance/resumo): **PerformanceVendasView** ou similar.
- Parâmetros: `data_inicio`, `data_fim`, opcional `consultor_id`.
- Para cada vendedor: vendas registradas no período, vendas instaladas no período, aplicação de `RegraComissao` (base/acelerado conforme meta), soma comissão.
- Se Diretoria: ainda calcula faturamento operadora (ComissaoOperadora) e mix plano/forma pagamento.
- Retorna totais, projeções e `exibir_comissao` conforme perfil.

---

## 8. Governança (configuração)

- **Regras de Comissão:** CRUD em Governança → “Regras de Comissão” (formulário + lista). API: `RegraComissaoListCreateView`, `RegraComissaoDetailView` (`/crm/regras-comissao/`).
- **Recebimento Operadora:** CRUD `ComissaoOperadora` (por plano: valor base, bônus transição, validade). API: `ComissaoOperadoraViewSet` (`/crm/comissoes-operadora/`).
- **Adiantamentos e descontos:** Lançamentos manuais via `LancamentoFinanceiro` (tipos ADIANTAMENTO_CNPJ, ADIANTAMENTO_COMISSAO, DESCONTO).
- **Campanhas:** definição de meta e prêmio; elegibilidade por planos e formas de pagamento; usado no cálculo de bônus do relatório.

---

## 9. Resumo para reconstrução

- **Entradas:** usuários (consultores) com meta e canal; vendas instaladas no mês; regras de comissão (por consultor, plano, tipo venda, tipo cliente); campanhas; lançamentos financeiros; configuração de descontos no perfil.
- **Cálculo:** para cada consultor no mês: comissão bruta (regras + meta), menos descontos (previstos + lançamentos + INSS fixo), mais bônus (campanhas) = líquido.
- **Fluxos:** relatório mensal, pendências → confirmar descontos (e opcionalmente reverter), fechar mês, reabrir mês, PDF, e-mail, WhatsApp.
- **Pontos de atenção:**  
  - Alinhar URLs do frontend com as rotas reais (fechar, reabrir, pdf, email).  
  - Regra “genérica” com `consultor is None` não existe no modelo atual; definir se haverá regra padrão por plano/canal/cliente sem consultor.  
  - Duplicidade de classe `PendenciasDescontoView` em `views.py` (duas definições); manter apenas uma na reconstrução.

---

*Documento gerado para apoio à reconstrução da ferramenta Comissão.*
