# Análise: Arquivos Fora do Padrão Arquitetural

Este documento lista arquivos e trechos de código que estão **fora do padrão** definido no `.cursorrules`, com sugestão de destino (pastas/camada) para adequação.

---

## Padrão de referência (.cursorrules)

- **Fat Models, Skinny Views** ou **Arquitetura de Serviços**
- `views.py` devem ser **enxutas**: apenas receber requisição e devolver resposta
- **Regras de negócio complexas**, cálculos e integrações externas devem ficar em **`services/`**
- Uso de **Type Hints** e **Docstrings** em regras de negócio complexas

---

## 1. Core

### 1.1 `core/views.py`

| Trecho | Problema | Destino sugerido |
|--------|----------|------------------|
| **`calendario_fiscal_view`** (função, ~linhas 78–161) | Toda a lógica de montagem do calendário, persistência de `DiaFiscal`, tratamento de POST (pesos, observações), cálculo de totais, navegação e tratamento de `IntegrityError`/sequence está dentro da view. | **`core/services/calendario_fiscal_service.py`** — Criar um serviço que: (1) retorne a estrutura do calendário para um mês/ano; (2) processe o POST de atualização dos dias; (3) calcule totais e dados de navegação. A view apenas chama o serviço e faz `render()` com o context. |

**Observação:** As `TemplateView` (IndexView, AreaInternaView, etc.) e o `RegraAutomacaoViewSet` estão adequados (views enxutas).

---

## 2. CRM App

### 2.1 `crm_app/views.py` (arquivo muito grande e com muita lógica)

O arquivo tem **milhares de linhas** e concentra dezenas de views com regras de negócio, cálculos e integrações dentro das próprias views. Abaixo estão os trechos mais relevantes fora do padrão.

| Trecho / View | Problema | Destino sugerido |
|---------------|----------|------------------|
| **`api_verificar_email`** | Validação de e-mail (regex, domínios) na view. | **`crm_app/services/validacao_service.py`** (ou `usuarios/services/`) — Função `validar_email(email) -> dict`. |
| **`api_verificar_whatsapp`** | Lógica de limpeza de telefone, formatação e chamada ao WhatsApp na view. | **`crm_app/services/whatsapp_service.py`** (já existe) — View apenas chama algo como `WhatsAppService().validar_numero(telefone)` e monta a resposta. |
| **`serve_pdf_view`** | Decodificação de token, HMAC, validação de path e leitura de arquivo na view. | **`crm_app/services/arquivo_assinado_service.py`** — Funções `gerar_token_pdf(filename)`, `validar_e_abrir_pdf(token)`; view só chama e devolve `FileResponse` ou 404. |
| **`duplicar_venda`** | Cópia de modelo (loop em `_meta.get_fields()`), definição de status, salvamento e envio WhatsApp na view. | **`crm_app/services/reemissao_venda_service.py`** — Ex.: `ReemissaoVendaService.duplicar(id_venda, nova_os, nova_data, novo_turno)` retornando a nova venda; view só valida input e chama o serviço. |
| **`buscar_fatura_nio_bonus_m10`** | Consulta NIO, formatação de datas, montagem de payload e resposta dentro da view. | **`crm_app/services_busca_faturas.py`** ou **`crm_app/services/busca_fatura_nio_service.py`** — View só repassa CPF e devolve o resultado do serviço. |
| **`ComissionamentoView.get`** | Cálculo completo de comissão (regras, vendas, campanhas, lançamentos, descontos, bônus, histórico) em ~200 linhas na view. | **`crm_app/services/comissionamento_service.py`** — Ex.: `ComissionamentoService.gerar_relatorio(ano, mes)`; view só passa `ano`/`mes` e retorna `Response(dados)`. |
| **`FolhaComissionamentoView`** | Já delega para `calcular_folha_mes`; manter assim, mas garantir que toda a lógica esteja em **`comissao_folha_service.py`** (já no app). | Nenhuma mudança de pasta; apenas garantir que nenhuma lógica nova seja colocada na view. |
| **`FecharPagamentoView`** / **`ReabrirPagamentoView`** | Lógica de atualização em massa de vendas e criação de `PagamentoComissao` na view. | **`crm_app/services/comissionamento_service.py`** — Métodos `fechar_pagamento(ano, mes, total_pago)` e `reabrir_pagamento(ano, mes)`. |
| **`enviar_comissao_whatsapp`** | Cálculo de comissão por consultor (regras, descontos) + montagem de card + envio WhatsApp na view. | **`crm_app/services/comissao_whatsapp_service.py`** — Ex.: `EnviarComissaoWhatsAppService.enviar(ano, mes, consultores_ids)`; view só valida e chama. |
| **`enviar_folha_extrato_whatsapp`** | Cálculo de folha, geração de imagem/PDF e envio na view. | **`crm_app/services/comissao_whatsapp_service.py`** (ou serviço dedicado de “folha por WhatsApp”). |
| **`enviar_resultado_campanha_whatsapp`** | Lógica de campanha + envio na view. | **`crm_app/services/campanha_whatsapp_service.py`**. |
| **`ImportacaoOsabView`** | Métodos auxiliares (`_clean_key`, `_normalize_pedido`, `_normalize_text`, `_sincronizar_seq_*`, `_processar_osab_interno`) e toda a lógica de parsing/gravação dentro da classe. | **`crm_app/services/importacao_osab_service.py`** — A view apenas recebe o arquivo, chama `ImportacaoOsabService.processar(log_id, file_content, ...)` e retorna o response. |
| **`ImportacaoChurnView`** e outras importações (DFV, FPD, Agendamento, Recompra, Legado) | Mesmo padrão: parsing, validação e persistência dentro da view. | **`crm_app/services/`** — Um serviço por tipo: `importacao_churn_service.py`, `importacao_dfv_service.py` (já existe `dfv_import_service.py`), etc. A view só delega. |
| **`RelatorioFinanceiroView`** (presenca) | Ver seção Presença abaixo. | **`presenca/services/relatorio_financeiro_service.py`** |
| **`ConfirmacaoPresencaDiaView`** (presenca) | Upload OneDrive + envio WhatsApp na view. | **`presenca/services/confirmacao_presenca_service.py`** ou uso de **`crm_app/onedrive_service.py`** + **`crm_app/whatsapp_service.py`** em um serviço de confirmação. |

**Recomendação geral para `crm_app`:**  
- Criar **`crm_app/services/`** e ir migrando, por demanda, cada bloco de lógica das views para módulos como:  
  `comissionamento_service.py`, `importacao_osab_service.py`, `importacao_churn_service.py`, `reemissao_venda_service.py`, `validacao_service.py`, `arquivo_assinado_service.py`, etc.  
- Manter **`views.py`** apenas com: validação mínima de entrada, chamada ao serviço e montagem da `Response`/redirect.

---

## 3. Usuários

### 3.1 `usuarios/views.py`

| Trecho | Problema | Destino sugerido |
|--------|----------|------------------|
| **`PerfilViewSet.permissoes`** (GET/PUT) | Montagem de `codenames` a partir de `PermissaoPerfil` e atualização em lote (delete + create) na view. | **`usuarios/services/perfil_permissao_service.py`** — Ex.: `get_permissoes_codenames(perfil)`, `atualizar_permissoes(perfil, permissoes_data)`. View só chama e devolve/atualiza. |
| **`UsuarioViewSet.validar_whatsapp`** | Normalização de telefone e chamada ao WhatsApp na view. | **`crm_app/whatsapp_service.py`** (ou **`usuarios/services/validacao_whatsapp_service.py`**) — Método como `validar_telefone_whatsapp(telefone)`; view só repassa o telefone e formata a resposta HTTP. |
| **`RecursoViewSet.list`** | Lista fixa de recursos (app_model) na view. | Pode ficar na view (é apenas um mapeamento simples) ou em **`usuarios/services/recursos_service.py`** se crescer. |

---

## 4. Presença

### 4.1 `presenca/views.py`

| Trecho | Problema | Destino sugerido |
|--------|----------|------------------|
| **`get_dias_uteis_periodo(inicio, fim)`** | Função de domínio (dias úteis excluindo feriados) no módulo de views. | **`presenca/services/relatorio_financeiro_service.py`** (ou **`presenca/utils.py`**) — Função pura reutilizável. |
| **`RelatorioFinanceiroView.get`** | Cálculo de dias úteis, usuários, presenças, mapa de descontos, previsão e apuração real (~100 linhas) na view. | **`presenca/services/relatorio_financeiro_service.py`** — Ex.: `RelatorioFinanceiroService.gerar(inicio, fim)` retornando dict com `previsao` e `descontos`; view só valida parâmetros e retorna `Response(servico.gerar(...))`. |
| **`ExportarRelatorioFinanceiroExcelView`** | Herda o get e adiciona montagem de DataFrame e Excel na view. | Mesmo serviço — método `exportar_excel(inicio, fim)` ou a view chama `gerar()` e um **`presenca/services/export_excel_service.py`** monta o arquivo. |
| **`ConfirmacaoPresencaDiaView.post`** | Upload para OneDrive, construção de nome de pasta/arquivo, `update_or_create` de `ConfirmacaoPresencaDia` e envio de selfie por WhatsApp para Diretoria na view. | **`presenca/services/confirmacao_presenca_service.py`** — Ex.: `ConfirmacaoPresencaService.registrar_selfie(usuario, data, foto_file, lat, lng)`; view só valida e chama. |
| **`PresencaViewSet.create`** | Lógica de `update_or_create`, tratamento de `IntegrityError` e debug prints na view. | **`presenca/services/presenca_service.py`** — Método `registrar_presenca(colaborador_id, data, ...)`; view delega e retorna o serializer. |

---

## 5. Scripts e arquivos soltos na raiz do projeto

Estes arquivos não seguem a organização por app (Django) e podem dificultar manutenção e onboarding.

| Arquivo | Problema | Destino sugerido |
|---------|----------|------------------|
| **`analisar_html_debug.py`** | Script de debug na raiz. | **`scripts/`** ou **`ferramentas/`** — Ex.: `scripts/analisar_html_debug.py`. |
| **`descobrir_seletores.py`** | Idem. | **`scripts/`** ou **`ferramentas/`**. |
| **`limpar_prevendas.py`** | Lógica de limpeza na raiz. | **`scripts/`** ou **`crm_app/management/commands/limpar_prevendas.py`** (se for operação recorrente). |
| **`excluir_pagina_9_rapido.py`** | Idem. | **`scripts/`** ou **`crm_app/management/commands/`** (já existe `excluir_pagina_9.py` em mais de um lugar; unificar). |
| **`test_plano_a_pdf.py`**, **`test_captcha_config.py`** | Testes na raiz. | **`tests/`** na raiz ou dentro do app (ex.: **`crm_app/tests/test_plano_a_pdf.py`**). |
| **`apply_recordapoia_migration.py`**, **`check_recordapoia_table.py`**, **`fix_railway_migration.py`**, **`fix_migration_inconsistency.py`** | Scripts de migração/deploy na raiz. | **`scripts/`** ou **`scripts/deploy/`** / **`scripts/migrations/`**. |

---

## 6. Resumo de pastas sugeridas

| Pasta | Uso |
|-------|-----|
| **`core/services/`** | Serviços do core (ex.: calendário fiscal). |
| **`crm_app/services/`** | Comissionamento, importações (OSAB, Churn, DFV, FPD, etc.), reemissão de venda, validações, arquivo assinado, envio de comissão/folha/campanha por WhatsApp. Já existe **`crm_app/services/dfv_import_service.py`** — seguir o mesmo padrão. |
| **`usuarios/services/`** | Permissões de perfil, validação WhatsApp (ou delegar ao CRM), recursos. |
| **`presenca/services/`** | Relatório financeiro (dias úteis + apuração), confirmação de presença (selfie + OneDrive + WhatsApp), registro de presença. |
| **`scripts/`** | Scripts pontuais de debug, migração, deploy e limpeza (evitar raiz). |
| **`ferramentas/`** | Já existe; reunir scripts de ferramentas operacionais aqui quando fizer sentido. |
| **`tests/`** | Testes unitários/integração que estiverem na raiz; organizar por app se necessário. |

---

## 7. Próximos passos sugeridos

1. **Prioridade alta:** Extrair de **`crm_app/views.py`** as lógicas de **ComissionamentoView**, **enviar_comissao_whatsapp** e **duplicar_venda** para **`crm_app/services/`**.
2. **Prioridade alta:** Extrair **calendario_fiscal_view** para **`core/services/calendario_fiscal_service.py`**.
3. **Prioridade média:** Extrair **RelatorioFinanceiroView** e **ConfirmacaoPresencaDiaView** (presença) para **`presenca/services/`**.
4. **Prioridade média:** Mover scripts da **raiz** para **`scripts/`** ou **`ferramentas/`** e testes para **`tests/`**.
5. **Contínuo:** A cada nova feature em views, colocar regras de negócio e integrações em **services/** desde o início.

Documento gerado com base no `.cursorrules` e na análise do codebase.
