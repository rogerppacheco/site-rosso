# Relatório Completo: Automação WhatsApp "VENDER"

**Data:** 07/02/2025  
**Objetivo:** Documentar a função de venda via WhatsApp (PAP Nio) para posterior teste etapa por etapa.

---

## 1. Visão Geral

A automação **VENDER** permite que vendedores autorizados realizem vendas de internet Nio Fibra diretamente pelo WhatsApp. O fluxo coleta dados do cliente via chat e, ao final, executa uma automação com **Playwright** no sistema PAP Nio (https://pap.niointernet.com.br/) para registrar a venda.

### 1.1 Comandos de Inicialização

- **VENDER**
- **VENDA**
- **NOVA VENDA**

### 1.2 Arquivos Principais

| Arquivo | Função |
|---------|--------|
| `crm_app/whatsapp_webhook_handler.py` | Handler do webhook, fluxo de etapas, processamento de mensagens |
| `crm_app/services_pap_nio.py` | Automação Playwright no PAP Nio |
| `crm_app/models.py` | `SessaoWhatsapp` (etapa + dados_temp), `Venda`, `Cliente` |
| `usuarios.models` | `Usuario` (matricula_pap, senha_pap, tel_whatsapp, autorizar_venda_sem_auditoria) |

---

## 2. Pré-requisitos do Vendedor

Para usar a automação VENDER, o usuário deve:

1. **Telefone cadastrado:** O número que envia a mensagem deve estar em `Usuario.tel_whatsapp`
2. **Autorização:** `Usuario.autorizar_venda_sem_auditoria = True`
3. **Credenciais PAP:** `Usuario.matricula_pap` e `Usuario.senha_pap` preenchidos
4. **Usuário ativo:** `Usuario.is_active = True`

---

## 3. Fluxo de Etapas (WhatsApp ↔ Sessão)

O fluxo é controlado pelo campo `SessaoWhatsapp.etapa` e pelos dados em `SessaoWhatsapp.dados_temp`.

### 3.1 Diagrama do Fluxo

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ INÍCIO: Usuário digita VENDER/VENDA/NOVA VENDA                              │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ _iniciar_fluxo_venda()                                                       │
│ • Valida telefone → Usuario (tel_whatsapp)                                   │
│ • Valida autorizar_venda_sem_auditoria                                       │
│ • Valida matricula_pap e senha_pap                                           │
│ • Seta etapa = venda_confirmar_matricula                                     │
│ • dados_temp = {vendedor_id, vendedor_nome, matricula_pap}                   │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ ETAPA: venda_confirmar_matricula                                             │
│ • Usuário digita SIM → login_pap_thread() [em background]                    │
│ • Usuário digita CANCELAR/SAIR/PARAR → cancela                               │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │ SIM
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ login_pap_thread() - Thread separada                                         │
│ • PAPNioAutomation.iniciar_sessao() → login no PAP                           │
│ • Envia: "Digite o CEP do endereço de instalação"                            │
│ ⚠️ BUG: sessao.etapa='inicial', dados_temp={} (deveria ser venda_cep)        │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ ETAPA: venda_cep        │ ETAPA: venda_numero   │ ETAPA: venda_referencia   │
│ • CEP (8 dígitos)       │ • Número ou SN        │ • Referência (≥3 chars)   │
│ • Salva cep em dados    │ • Salva numero        │ • Chama etapa2_viabilidade │
│ • Próximo: venda_numero │ • Próximo: venda_ref  │   em thread (nova sessão)  │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ ETAPA: venda_cpf        │ ETAPA: venda_celular  │ ETAPA: venda_email        │
│ • CPF (11 dígitos)      │ • Celular (10-11 dig) │ • E-mail válido           │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ ETAPA: venda_forma_pagamento  │ ETAPA: venda_plano   │ ETAPA: venda_turno   │
│ • 1=Boleto, 2=Cartão, 3=Débito│ • 1=1Giga, 2=700M,   │ • 1=Manhã, 2=Tarde   │
│                               │   3=500Mega          │                      │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ ETAPA: venda_confirmar                                                       │
│ • Mostra resumo completo                                                     │
│ • Usuário digita CONFIRMAR → _executar_venda_pap()                           │
│ • Usuário digita CANCELAR → cancela                                          │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │ CONFIRMAR
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ _executar_venda_pap() → inicia thread _executar_venda_pap_background()       │
│ • etapa = venda_processando                                                  │
│ • Executa TODAS as etapas PAP em sequência (0 a 7)                           │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ ETAPA: venda_aguardando_biometria (se biometria pendente)                    │
│ • Usuário digita VERIFICAR/STATUS → _verificar_biometria_venda()             │
│ • Quando biometria OK → etapa7_abrir_os → cadastro CRM → sucesso             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Etapas do PAP Nio (Playwright)

A classe `PAPNioAutomation` em `services_pap_nio.py` implementa:

| Etapa | Método | Descrição |
|-------|--------|-----------|
| 0 | `iniciar_sessao()` | Abre Chromium headless, login em pap.niointernet.com.br (via login.vtal.com) |
| 1 | `iniciar_novo_pedido(matricula)` | Navega para /novo-pedido, seleciona vendedor pela matrícula |
| 2 | `etapa2_viabilidade(cep, numero, ref)` | Preenche CEP, número, clica Buscar, preenche referência |
| 3 | `etapa3_cadastro_cliente(cpf)` | Preenche CPF, clica Buscar, carrega dados do cliente |
| 4 | `etapa4_contato(celular, email)` | Preenche celular, email, aguarda análise de crédito, clica Continuar |
| 5 | `etapa5_pagamento_plano(forma, plano)` | Seleciona boleto/cartão/débito e plano (1giga/700mega/500mega) |
| 6 | `etapa6_verificar_biometria()` | Verifica se biometria está aprovada (texto na página) |
| 7 | `etapa7_abrir_os(turno)` | Clica Abrir OS, escolhe data/turno, extrai número da O.S. |

### 4.1 URLs e Seletores

- **Login:** https://pap.niointernet.com.br/ e https://login.vtal.com/nidp/saml2/sso
- **Novo pedido:** https://pap.niointernet.com.br/administrativo/novo-pedido
- **Timeout padrão:** 30 segundos
- **Sessões simultâneas:** Máximo 2 (semáforo `_pap_semaphore`)

---

## 5. Dados Coletados e Enviados ao PAP

| Campo | Origem | Validação |
|-------|--------|-----------|
| cep | venda_cep | 8 dígitos |
| numero | venda_numero | Qualquer ou "S/N" |
| referencia | venda_referencia | Mínimo 3 caracteres |
| cpf_cliente | venda_cpf | 11 dígitos |
| celular | venda_celular | 10 ou 11 dígitos |
| email | venda_email | Deve conter @ e . |
| forma_pagamento | venda_forma_pagamento | 1, 2 ou 3 |
| plano | venda_plano | 1, 2 ou 3 |
| turno | venda_turno | 1 ou 2 |
| vendedor_id, vendedor_nome, matricula_pap | _iniciar_fluxo_venda | Do Usuario |

---

## 6. Tempo de Sessão e Prorrogação

- **Timeout:** Se o usuário ficar **10 minutos** sem enviar nenhuma mensagem (nem dado nem comando), a sessão é encerrada e a mensagem "Sessão expirada. Digite *VENDER* para iniciar novamente." é exibida.
- **Comando ESTENDER:** Durante o fluxo de venda, o vendedor pode digitar **ESTENDER** a qualquer momento para prorrogar o tempo em **5 minutos**. Há um limite de **3 prorrogações** por sessão (após isso, "Limite de prorrogações atingido").
- **Por que "Sessão expirada" aparece?** (1) 10 min sem comando; (2) o site PAP deslogou e a automação encerrou; (3) a requisição caiu em outro servidor/réplica (o contexto da automação fica em memória por processo). Quando há dados já preenchidos (CEP, CPF, etc.), o sistema salva o estado e oferece *REPETIR* (tentar a última etapa de novo) ou *VENDER* (começar do zero).

---

## 7. Cadastro no CRM

Após sucesso no PAP, `_cadastrar_venda_crm()`:

1. Busca ou cria `Cliente` por CPF
2. Busca `Plano` e `FormaPagamento` por nome
3. Busca `StatusEsteira` com nome contendo "AGENDAD"
4. Cria `Venda` com: cliente, vendedor, plano, forma_pagamento, ordem_servico (O.S.), CEP, número, referência

---

## 8. Problemas Identificados (para correção nos testes)

### 7.1 Crítico: Bug na etapa venda_confirmar_matricula

**Arquivo:** `whatsapp_webhook_handler.py`, linhas 484-487

Após login bem-sucedido no PAP, o código faz:

```python
sessao.etapa = 'inicial'
sessao.dados_temp = {}
sessao.save()
```

**Efeito:** A sessão é resetada. Quando o usuário digita o CEP, a etapa é `inicial` e a mensagem **não** é tratada como etapa de venda (`etapa_atual.startswith('venda_')` é False). O fluxo quebra.

**Correção sugerida:** Manter etapa e dados:

```python
sessao.etapa = 'venda_cep'
sessao.dados_temp = {
    'vendedor_id': vendedor_id,
    'vendedor_nome': vendedor_nome,
    'matricula_pap': vendedor_matricula,
}
sessao.save()
```

### 7.2 Possível problema: etapa venda_referencia e viabilidade

Na etapa `venda_referencia`, é criada uma **nova** instância de `PAPNioAutomation` e chamado `etapa2_viabilidade`. Porém:

- A automação anterior (login) encerra quando `login_pap_thread` termina (o objeto sai de escopo e `__del__` fecha a sessão).
- Esta nova automação não chama `iniciar_sessao()` nem `iniciar_novo_pedido()` antes de `etapa2_viabilidade`.
- `etapa2_viabilidade` espera estar na tela de novo pedido, após etapa 1.

**Consequência:** A consulta de viabilidade em `venda_referencia` pode falhar por falta de sessão logada e etapa 1 não concluída.

**Observação:** O fluxo principal de venda (após CONFIRMAR) faz tudo em sequência na mesma automação; o problema afeta apenas a **pré-consulta de viabilidade** no meio do fluxo.

### 7.3 etapa venda_aguardando_biometria

A função `_verificar_biometria_venda` usa `dados.get('automacao_instancia')`, mas em `_executar_venda_pap_background` a instância da automação **não** é salva em `sessao.dados_temp`. Quando a biometria fica pendente, a sessão é resetada (`resetar_sessao()`), então `venda_aguardando_biometria` nunca seria a etapa ativa com `automacao_instancia` disponível. O fluxo atual informa: "Quando a biometria for aprovada, digite *VENDER* novamente" — ou seja, não há continuação automática; o usuário precisa iniciar de novo. Isso pode ser intencional.

---

## 9. Sugestão de Ordem para Testes

1. **Teste 1 – Pré-requisitos**  
   Verificar usuário com `tel_whatsapp`, `autorizar_venda_sem_auditoria`, `matricula_pap` e `senha_pap`.

2. **Teste 2 – Comando VENDER**  
   Enviar "VENDER" e validar resposta de confirmação de matrícula.

3. **Teste 3 – Confirmação e login (com correção do bug)**  
   Enviar "SIM" e validar login no PAP e mensagem pedindo CEP. Verificar se etapa e dados_temp estão corretos.

4. **Teste 4 – Coleta de endereço**  
   CEP → Número → Referência e validar respostas e transição de etapas.

5. **Teste 5 – Viabilidade (venda_referencia)**  
   Verificar se a consulta de viabilidade funciona ou se precisa de ajuste (nova sessão + etapa 1).

6. **Teste 6 – Dados do cliente**  
   CPF → Celular → E-mail e validar validações.

7. **Teste 7 – Pagamento, plano e turno**  
   Forma de pagamento → Plano → Turno.

8. **Teste 8 – Resumo e confirmação**  
   Conferir resumo e enviar "CONFIRMAR".

9. **Teste 9 – Automação PAP completa**  
   Executar todo o fluxo PAP (etapas 0–7) em ambiente de teste.

10. **Teste 10 – Cadastro no CRM**  
    Validar criação de Cliente e Venda após sucesso.

---

## 10. Comandos de Cancelamento

Em qualquer etapa de venda, o usuário pode digitar:

- **CANCELAR**
- **SAIR**
- **PARAR**

Isso reseta a sessão para `inicial` e limpa `dados_temp`.

---

## 11. Planos e Valores (configurados no fluxo)

| Código | Plano | Valor |
|--------|-------|-------|
| 1 | Nio Fibra Ultra 1 Giga | R$ 160,00/mês |
| 2 | Nio Fibra Super 700 Mega | R$ 130,00/mês |
| 3 | Nio Fibra Essencial 500 Mega | R$ 100,00/mês |

---

## 12. Dependências Técnicas

- **Playwright** (Chromium) – automação do PAP
- **Django** – models, sessões
- **Z-API** (ou similar) – envio de mensagens WhatsApp
- Diretório de sessões: `pap_sessions/` (storage state do navegador)

---

*Relatório gerado para suporte aos testes etapa por etapa da automação VENDER.*
