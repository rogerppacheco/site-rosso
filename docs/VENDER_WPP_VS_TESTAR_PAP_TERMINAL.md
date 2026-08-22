# Vender no WhatsApp vs testar_pap_terminal

## Objetivo

Alinhar o fluxo de **Vender no WhatsApp** (produção) com o comando **testar_pap_terminal**, e corrigir erros que impediam o fluxo de múltiplos endereços e a etapa de CPF.

---

## 1. Erro corrigido: `SynchronousOnlyOperation` (async context)

### Sintoma

Ao escolher um endereço em CEP com múltiplos endereços e seguir para a etapa do CPF, o usuário recebia:

```
❌ Erro: You cannot call this from an async context - use a thread or sync_to_async.

Digite VENDER para tentar novamente.
```

### Causa

O **PAP worker** (`_pap_worker_loop`) roda na mesma thread que a automação Playwright. Em ambiente ASGI/async, chamadas **síncronas** do Django (ORM: `SessaoWhatsapp.objects.get()`, `.save()`) e do `WhatsAppService().enviar_mensagem_texto()` não podem ser feitas diretamente nessa thread, gerando `SynchronousOnlyOperation`.

### Solução aplicada

- **`_executar_ops_django_sync(func)`**  
  Executa uma função que faz apenas operações Django/WhatsApp em uma **thread separada** (com `django.db.close_old_connections()`), evitando uso de ORM/HTTP na thread do Playwright.

- **`_run_sync_returning(callable)`**  
  Mesma ideia, mas para **leituras** que precisam retornar valor (ex.: obter `sess` e `dados` da sessão).

No `_pap_worker_loop`, **todas** as operações que tocam Django ou WhatsApp passaram a ser executadas via uma dessas duas funções:

- `etapa3` (CPF → celular)
- `etapa4` (contato/crédito)
- `etapa5_forma`, `etapa5_debito`, `etapa5_plano`, `etapa5_fixo`, `etapa5_streaming_avancar`
- `selecionar_endereco` (múltiplos endereços + complementos + posse/indisponível)
- `modal_posse_voltar`, `modal_indisponivel_voltar`
- `selecionar_complemento`
- Bloco `except` que envia a mensagem de erro ao usuário

Assim, a lógica de negócio (incluindo múltiplos endereços e complementos) continua igual; apenas a **execução** de ORM e envio de WhatsApp foi movida para thread síncrona dedicada.

---

## 2. Fluxo de múltiplos endereços e complementos

### testar_pap_terminal

- **Viabilidade** retorna `MULTIPLOS_ENDERECOS` → etapa 24: usuário digita o número do endereço.
- Chama `etapa2_selecionar_endereco_instalacao(idx)` e `etapa2_preencher_referencia_e_continuar(...)`.
- Se der **COMPLEMENTOS** → etapa 25: usuário digita 0 / SEM COMPLEMENTO ou número do complemento.
- Se der **POSSE_ENCONTRADA** ou **INDISPONIVEL_TECNICO** → etapas 30/31: outro CEP ou CONCLUIR.
- Senão → segue para CPF (etapa 4).

### Produção (Vender no WhatsApp)

O fluxo em produção **já era o mesmo** em termos de etapas e chamadas ao PAP:

- `venda_referencia` → viabilidade → se `MULTIPLOS_ENDERECOS`: `venda_selecionar_endereco`.
- Worker: action `selecionar_endereco` → `etapa2_selecionar_endereco_instalacao(idx)` e `etapa2_preencher_referencia_e_continuar(...)`.
- Se **COMPLEMENTOS** → `venda_selecionar_complemento` (action `selecionar_complemento`).
- Se **POSSE** / **INDISPONÍVEL** → `venda_posse_consultar_outro` / `venda_indisponivel_voltar` (actions `modal_posse_voltar` / `modal_indisponivel_voltar`).
- Senão → `venda_cpf` e pedido de CPF.

Ou seja: a **função** (lógica e etapas) já estava alinhada com o terminal; o que quebrava era o uso de Django/WhatsApp na thread do worker. Com o uso de `_executar_ops_django_sync` e `_run_sync_returning`, o fluxo de múltiplos endereços e complementos passa a funcionar em produção sem o erro de async.

---

## 3. O que já estava igual (terminal vs produção)

- Viabilidade (etapa2), múltiplos endereços, complementos, posse, indisponível.
- Cadastro cliente (CPF), celular, e-mail, análise de crédito.
- Forma de pagamento (boleto/cartão/débito), débito (banco/agência/conta/dígito), plano, fixo, streaming.
- Avançar → etapa 6 (resumo, confirmação do cliente, biometria) e etapa 7 (agendamento).
- Uso do mesmo `PAPNioAutomation` (`services_pap_nio`) e mesmas etapas do PAP.

---

## 4. Diferenças de ambiente (sem mudar lógica)

| Aspecto | testar_pap_terminal | Vender no WhatsApp (produção) |
|--------|----------------------|-------------------------------|
| Entrada | Teclado (input no terminal) | Mensagens WhatsApp (webhook) |
| Sessão | Uma sessão local por execução | `SessaoWhatsapp` + pool de BO por vendedor |
| Confirmação “SIM” do cliente | `_verificar_sim_cliente_no_bd_thread` + BD | Evento por mensagem do cliente no webhook (`_pending_client_confirm`) |
| PapConfirmacaoCliente | Salvo em thread (`_salvar_pap_confirmacao_thread`) | Salvo em `_executar_venda_pap_etapa6_em_diante` (já em contexto que pode usar sync/thread conforme necessário) |
| Django/ORM na automação | Thread dedicada para operações de BD | `_executar_ops_django_sync` / `_run_sync_returning` no worker |

Nenhuma dessas diferenças altera a **regra de negócio** do PAP; apenas o canal (terminal vs WhatsApp) e a forma de rodar código síncrono (thread no terminal vs helpers no worker).

---

## 5. Resumo

- **Erro “You cannot call this from an async context”**  
  Corrigido ao executar **toda** interação com Django e WhatsApp do `_pap_worker_loop` em thread síncrona (`_executar_ops_django_sync` e `_run_sync_returning`).

- **Múltiplos endereços / complementos**  
  A lógica já era a mesma do `testar_pap_terminal`; com a correção de async, o fluxo passa a funcionar até o CPF e seguintes etapas sem esse erro.

- **Alinhamento com testar_pap_terminal**  
  As etapas e chamadas ao PAP (viabilidade, endereço, complemento, posse, indisponível, CPF, contato, pagamento, plano, fixo, streaming, avançar, etapa 6 e 7) estão equivalentes; as diferenças restantes são de canal (terminal vs WhatsApp) e de execução (threads no terminal vs helpers no worker).

Para validar: usar um CEP que retorne múltiplos endereços, escolher um, seguir até o CPF e conferir que não aparece mais o erro de async e que as mensagens seguem corretas.
