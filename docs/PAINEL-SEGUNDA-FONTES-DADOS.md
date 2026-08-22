# Painel Segunda — De onde vêm os dados

Resumo de onde obter cada coluna da tabela do Painel do Agente Financeiro (por usuário ativo, semana de referência seg–sáb).

---

## 1. Nome (lista de usuários ativos)

| Fonte | Detalhe |
|-------|--------|
| **usuarios (API)** | `GET /usuarios/?is_active=true` ou modelo `usuarios.models.Usuario` com `is_active=True`. |
| **Ordenação** | Por `first_name` ou `username`, conforme já usado em outros relatórios. |

---

## 2. Passagem e 3. Almoço

| Fonte | Detalhe |
|-------|--------|
| **Usuario** | Campos `valor_passagem` e `valor_almoco` em `usuarios.models.Usuario` (Decimal). |
| **Governança** | Já editáveis em Governança → Gestão de Usuários (valor_almoco, valor_passagem). |
| **Relatório existente** | `presenca.services.relatorio_financeiro_service` usa `user.valor_almoco` e `user.valor_passagem`; `relatorios.views.RelatorioPrevisaoView` e `RelatorioFinalView` também. |

---

## 4. Faltas da semana

| Fonte | Detalhe |
|-------|--------|
| **Presença** | `presenca.models.Presenca`: registros com `status=False` e `motivo.gera_desconto=True` (ou ausência em dia útil = falta). |
| **Período** | Filtrar `Presenca.data` na semana (segunda a sábado). |
| **Serviço** | `presenca.services.relatorio_financeiro_service.gerar_relatorio_financeiro(dt_ini, dt_fim)` retorna por usuário `qtd_faltas`, `datas_faltas`, `valor_desconto`. |
| **API** | `GET /api/presenca/relatorio-financeiro/?inicio=YYYY-MM-DD&fim=YYYY-MM-DD` (presenca.views.RelatorioFinanceiroView). |
| **Dias úteis** | Excluir sábado/domingo e `presenca.models.DiaNaoUtil` (feriados); considerar só seg–sex ou incluir sábado conforme regra. |

---

## 5. Retirada (desconto) passagem + almoço pelas faltas

| Fonte | Detalhe |
|-------|--------|
| **Cálculo** | `valor_diario = valor_almoco + valor_passagem`; `desconto = qtd_faltas_semana * valor_diario`. |
| **Já implementado** | `relatorio_financeiro_service`: `valor_desconto = qtd_faltas * valor_diario`; `RelatorioFinalView`: `total_a_descontar = dias_falta_com_desconto * auxilio_diario`. |

---

## 6. Valor total CNPJ da semana (adiantamento)

| Fonte | Detalhe |
|-------|--------|
| **Regra** | Vendas **instaladas** na semana (seg–sáb), tipo cliente = **CNPJ**, por vendedor → R$ 50,00 por venda (ou valor configurável). |
| **Vendas** | `crm_app.models.Venda`: `status_esteira__nome='INSTALADA'`, `data_instalacao` na semana. |
| **CNPJ** | Cliente: `cpf_cnpj` com 14 dígitos (após remover não-dígitos) = CNPJ. |
| **API existente** | `GET /crm/lancamentos-financeiros/vendas-instaladas-mes/?vendedor_id=&ano=&mes=&tipo_cliente=CNPJ` retorna vendas CNPJ do mês; para “semana” é preciso filtrar por intervalo de datas (seg–sáb) ou criar endpoint por período. |
| **Adesão** | Só incluir vendedores com adesão ao adiantamento CNPJ (ex.: `usuarios.models.Usuario` ou config com campo `adiantar_cnpj` / adesão; hoje há `ConfigComissaoVendedor.adiantar_cnpj`). |

---

## 7. Premiação cartão de crédito da semana

| Fonte | Detalhe |
|-------|--------|
| **Regra** | Vendas **instaladas** na semana (seg–sáb), **forma de pagamento = Cartão de Crédito** → R$ 30,00 por venda. |
| **Vendas** | `Venda`: `status_esteira__nome='INSTALADA'`, `data_instalacao` na semana, `forma_pagamento` com nome contendo "cartão", "crédito", "credito", "cartao" (já usado em `crm_app.views` com `Q(forma_pagamento__nome__icontains='CREDIT')` etc.). |
| **Cálculo** | Por vendedor: contar vendas elegíveis na semana × R$ 30,00. |

---

## 8. Adiantamento solicitado das vendas (500Mb/700/1Gb)

| Fonte | Detalhe |
|-------|--------|
| **Regra** | Valor já **registrado** como adiantamento de comissão (solicitação segunda-feira): 500Mb R$ 130, 700 R$ 150, 1Gb R$ 180. |
| **Modelo** | `crm_app.models.LancamentoFinanceiro`: `tipo='ADIANTAMENTO_COMISSAO'`, `data` na semana de referência. |
| **Cálculo** | Por usuário: soma de `LancamentoFinanceiro.objects.filter(usuario=..., tipo='ADIANTAMENTO_COMISSAO', data__range=(seg, sab)).aggregate(Sum('valor'))`. |

---

## 9. Valor avulso (selecionado pelo usuário na semana)

| Fonte | Detalhe |
|-------|--------|
| **Situação** | Hoje não existe tipo “valor avulso” positivo em `LancamentoFinanceiro` (existe apenas `DESCONTO` = desconto avulso). |
| **Opções** | (a) Criar novo tipo, ex.: `PAGAMENTO_AVULSO` ou `VALOR_AVULSO` em `LancamentoFinanceiro`, e o agente (ou o próprio usuário) lançar naquela semana; ou (b) usar outro cadastro (ex. tabela “valores avulsos” por usuário/semana). Para o painel: filtrar por `data` na semana e somar por usuário. |

---

## 10. Valor a pagar de campanha na semana

| Fonte | Detalhe |
|-------|--------|
| **Modelos** | `crm_app.models.Campanha` (data_inicio, data_fim, meta_vendas, valor_premio), `RegraCampanha` (meta, valor_premio por faixa). |
| **Regra** | Campanhas com a semana dentro de `data_inicio`–`data_fim`; para cada vendedor, verificar se atingiu a meta (vendas instaladas no período da campanha) e qual prêmio (valor_premio da campanha ou da regra por faixa). |
| **Código** | `crm_app.views` tem lógica de “atingiu meta” e `valor_premio` (ex. views de campanha); `comissionamento_service` usa campanhas por mês. Para “valor a pagar naquela semana” é preciso definir se o pagamento é na semana em que a campanha termina ou em outra regra (ex.: semana seguinte); depois filtrar campanhas que “pagam” naquela semana e somar prêmios por usuário. |

---

## 11. Total a receber na semana

| Fonte | Detalhe |
|-------|--------|
| **Cálculo** | Soma das colunas positivas menos as retiradas: **(Passagem+Almoço previsto)** ou **(valor diário × dias úteis da semana)** **− Retirada por faltas** **+ Total CNPJ adiantamento** **+ Premiação cartão** **+ Adiantamento solicitado (vendas)** **+ Valor avulso** **+ Valor campanha**. Definir se “passagem e almoço” entram como “valor bruto da semana” menos “retirada por faltas” (como no relatório financeiro de presença). |

---

## Resumo técnico

| Coluna | Origem principal |
|--------|-------------------|
| Nome | `Usuario` ativos |
| Passagem | `Usuario.valor_passagem` |
| Almoço | `Usuario.valor_almoco` |
| Faltas da semana | `Presenca` + `MotivoAusencia.gera_desconto` no período seg–sáb |
| Retirada passagem/almoco | `qtd_faltas * (valor_almoco + valor_passagem)` |
| Total CNPJ semana | Vendas instaladas CNPJ na semana × R$ 50 (e adesão) |
| Premiação cartão | Vendas instaladas forma_pagamento cartão na semana × R$ 30 |
| Adiant. solicitado | `LancamentoFinanceiro` tipo ADIANTAMENTO_COMISSAO, data na semana |
| Valor avulso | Novo tipo ou modelo (a definir) |
| Campanha | Campanha ativa + meta atingida, valor a pagar naquela semana |
| Total a receber | Soma das colunas conforme fórmula acima |

---

## APIs / serviços reutilizáveis

- **Usuários ativos e valores:** API de usuários (ex. `/usuarios/`) e `relatorios.views.RelatorioPrevisaoView` / `RelatorioFinalView`.
- **Faltas e descontos da semana:** `presenca.services.relatorio_financeiro_service.gerar_relatorio_financeiro(dt_ini, dt_fim)` ou `GET /api/presenca/relatorio-financeiro/?inicio=&fim=`.
- **Vendas instaladas (CNPJ ou cartão):** filtrar `Venda` por `status_esteira`, `data_instalacao` e `forma_pagamento` / tipo cliente CNPJ; hoje existe endpoint por mês, pode ser estendido para período arbitrário (seg–sáb).
- **Adiantamentos:** `LancamentoFinanceiro` filtrado por `usuario`, `tipo`, `data__range=(seg, sab)`.

Com isso, você consegue implementar o backend do Painel Segunda (por exemplo um endpoint único que devolve a tabela por semana) e o front só consome essa API e exibe as colunas.
