# Tabelas das abas removidas (Gestão de Comissionamento)

Em 2026 foram removidas as seguintes abas:

- **Regras de Comissão** (Governança > Gestão de Comissionamento)
- **Configurações do Mês** (Governança > Gestão de Comissionamento)
- **Visão por Consultor** (página Comissionamento)

## Podemos deletar as tabelas com segurança?

### 1. Regras de Comissão (aba removida)

- **Modelo:** `RegraComissao` (tabela `crm_regra_comissao`).
- **Uso atual no backend:** Ainda referenciado em `crm_app/views.py` nas views de comissionamento que montam o relatório (ex.: `relatorio_consultores`) e em outras views que usam `RegraComissao.objects.filter(...)`.
- **Conclusão:** **Não deletar a tabela ainda.** Para remover com segurança é preciso:
  1. Remover ou refatorar todas as views que usam `RegraComissao` (relatório antigo, fechar/reabrir se usarem esse modelo, etc.).
  2. Depois criar uma migração Django que apague a tabela `crm_regra_comissao`.
- O cálculo da **Folha (formato Excel)** usa **RegraComissaoFaixa** e **ConfigComissaoVendedor**, não `RegraComissao`. Essas tabelas **não** devem ser removidas.

### 2. Configurações do Mês (aba removida)

- **Tabela dedicada:** Não existe. A aba apenas chamava a API de comissionamento (`GET comissionamento/?ano=&mes=`) para status do mês e usava fechar/reabrir pagamento.
- **Conclusão:** Nada a deletar. O fechamento/reabertura pode continuar sendo usado por outras telas ou APIs se existirem.

### 3. Visão por Consultor (aba removida)

- **Tabela dedicada:** Não havia; era só a tela que exibia o resultado da API de comissionamento (`relatorio_consultores`), que usa `RegraComissao` e outras fontes.
- **Conclusão:** Nenhuma tabela específica para excluir. Se no futuro o backend do relatório antigo e todas as referências a `RegraComissao` forem removidas, aí sim pode-se planejar a exclusão da tabela `crm_regra_comissao` (conforme item 1).

---

**Resumo:** A única tabela que um dia poderia ser removida é `crm_regra_comissao`, e só depois de eliminar todo o código que ainda usa o model `RegraComissao`. As tabelas **RegraComissaoFaixa** e **ConfigComissaoVendedor** são usadas pela Folha Excel e **não** devem ser deletadas.
