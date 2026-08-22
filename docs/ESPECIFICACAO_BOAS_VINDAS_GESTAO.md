# Especificação: Boas-Vindas em Gestão à Vista

**Data:** 06/03/2026  
**Objetivo:** Mover a função Boas-Vindas do Record Vendas para uma ferramenta dedicada em gestão, com histórico completo de mensagens, status tratáveis pelo BO e modelo anti-spam.

---

## 1. Resumo das Mudanças

| Antes | Depois |
|-------|--------|
| Boas-vindas dentro do Record Vendas | Nova ferramenta "Boas Vindas" na área interna (gestão à vista) |
| Só grava 1ª resposta do cliente | Grava **todas** as mensagens do cliente no chat |
| Sem status de tratamento | Status: Erro de vendas, Erro técnico, OK, etc. |
| Envio manual em lotes | Envio distribuído automaticamente até 16h |
| Sem IA | IA sugere status a partir da mensagem original |

---

## 2. Nova Ferramenta na Área Interna

- **Card:** "Boas Vindas" (ícone: chat-heart ou similar)
- **Rota:** `/boas-vindas/`
- **Visibilidade:** BackOffice, Diretoria, Admin, Auditoria, Qualidade
- **Conteúdo:**
  - Lista de **instalações do dia anterior** (data_instalacao = ontem, status INSTALADA)
  - Botão/função para **enviar boas-vindas** (com modelo anti-spam)
  - Lista de **clientes que receberam boas-vindas** com retorno
  - Para cada um: histórico de mensagens + status atribuível pelo BO

---

## 3. Modelo de Dados

### 3.1 Novo modelo: `MensagemClienteBoasVindas`

Registra **cada mensagem** enviada pelo cliente no chat daquele número que recebeu boas-vindas.

```python
class MensagemClienteBoasVindas(models.Model):
    boas_vindas_enviado = models.ForeignKey(BoasVindasEnviado, on_delete=models.CASCADE)
    texto = models.TextField()  # Mensagem original do cliente
    data_hora = models.DateTimeField(auto_now_add=True)
    direcao = models.CharField(choices=[('ENTRADA', 'Cliente'), ('SAIDA', 'Sistema')], default='ENTRADA')
```

### 3.2 Novo modelo: `StatusBoasVindas` (ou usar StatusCRM tipo "BoasVindas")

Status específicos para respostas às boas-vindas:
- **OK** – Cliente satisfeito, sem reclamação
- **ERRO_VENDAS** – Insatisfação causada pelo vendedor (promessa não cumprida, atendimento ruim, etc.)
- **ERRO_TECNICO** – Reclama da internet (velocidade, instabilidade, não entrega o prometido)
- **PENDENTE** – Ainda não tratado pelo BO
- **OUTROS** – Outro tipo de retorno

### 3.3 Alterações em `BoasVindasEnviado`

- Adicionar `status_boas_vindas` (FK para StatusBoasVindas ou StatusCRM)
- Adicionar `status_definido_por` (usuário BO que atribuiu)
- Adicionar `status_definido_em` (datetime)
- Adicionar `sugestao_status_ia` (texto – sugestão da IA antes do BO confirmar)
- Manter `cliente_resposta_boas_vindas` na Venda como "última resposta" (retrocompatibilidade) OU migrar para histórico completo

### 3.4 Alterações na Venda

- Manter `cliente_resposta_boas_vindas` e `data_resposta_boas_vindas` para a **última** mensagem (ou primeira significativa)
- O histórico completo fica em `MensagemClienteBoasVindas` vinculado a `BoasVindasEnviado`

---

## 4. Webhook: Registrar Todas as Mensagens

**Atual:** O webhook grava só a primeira resposta em `venda.cliente_resposta_boas_vindas`.

**Novo:** Para todo número que tem `BoasVindasEnviado` com `respondido_em` null OU já respondido (para continuar recebendo):
- Criar registro em `MensagemClienteBoasVindas` com o texto
- Atualizar `venda.cliente_resposta_boas_vindas` com a última mensagem (para exibição rápida)
- Marcar `respondido_em` no primeiro retorno; mensagens subsequentes só vão para o histórico

**Janela:** Considerar mensagens do cliente por até 30 dias após o envio (já existe `limite_bv`).

---

## 5. Modelo de Envio Anti-Spam

### 5.1 Parâmetros (baseados em melhores práticas Meta/WhatsApp)

| Parâmetro | Valor | Justificativa |
|-----------|-------|---------------|
| Intervalo entre mensagens | 20–30 min (aleatório) | Evita burst; Meta detecta padrões fixos |
| Horário limite | 16h | Tudo enviado até 16h |
| Início | 8h (ou 9h) | Horário comercial |
| Personalização | Nome do cliente em cada msg | Mensagens idênticas disparam filtros após 20–30 envios |
| Ordem | Aleatória dentro do lote | Evita padrão previsível |

### 5.2 Distribuição Automática

1. **Entrada:** Data = ontem (instalações do dia anterior)
2. **Total:** N = quantidade de vendas instaladas ontem sem boas-vindas
3. **Janela:** 8h às 16h = 8 horas = 480 min
4. **Intervalo médio:** 480 / N (mín. 20 min, máx. 30 min)
5. **Exemplo:** 24 clientes → 480/24 = 20 min entre cada → slots: 8:00, 8:20, 8:40, 9:00...
6. **Aleatoriedade:** Adicionar ±2 a ±5 min em cada slot para não parecer robótico

### 5.3 Por que NÃO é spam (para a IA da Meta)

- **Consentimento implícito:** Cliente acabou de instalar; é esperado contato pós-venda
- **Relevância:** Informações sobre fatura, app Nio, canais oficiais
- **Volume controlado:** Distribuído ao longo do dia, não burst
- **Personalização:** Nome do cliente em cada mensagem
- **Contexto:** Pós-instalação = relação comercial estabelecida

---

## 6. Interface do BO

### 6.1 Tela Principal (`/boas-vindas/`)

1. **Seção "Instalações do dia anterior"**
   - Tabela: Cliente, Telefone, Vendedor, Plano, Data instalação, Status boas-vindas (Enviado/Pendente)
   - Filtro por data (padrão: ontem)
   - Botão "Enviar boas-vindas" (abre modal ou inicia envio distribuído)

2. **Seção "Retornos dos clientes"**
   - Lista de clientes que receberam boas-vindas e enviaram mensagem
   - Colunas: Cliente, Telefone, Última mensagem (preview), Status, Data resposta
   - Clique na linha → abre painel lateral ou modal com:
     - Histórico completo de mensagens (chat)
     - Sugestão da IA (se houver)
     - Select para atribuir status (Erro vendas, Erro técnico, OK, etc.)
     - Campo com mensagem original (e todas as mensagens)

### 6.2 IA para Sugestão de Status

- **Input:** Texto da(s) mensagem(ns) do cliente
- **Output:** Sugestão de status (ERRO_VENDAS, ERRO_TECNICO, OK, OUTROS)
- **Regras:**
  - Palavras como "internet lenta", "caiu", "velocidade", "não funciona" → ERRO_TECNICO
  - Palavras como "vendedor mentiu", "prometeu e não cumpriu", "atendimento ruim" → ERRO_VENDAS
  - "Obrigado", "Ok", "Tudo bem" → OK
- O BO pode aceitar ou alterar a sugestão
- Sempre exibir a mensagem original do cliente

---

## 7. Implementação Realizada (06/03/2026)

- **Modelos:** `StatusBoasVindas`, `MensagemClienteBoasVindas`, `FilaEnvioBoasVindas`, campos em `BoasVindasEnviado`
- **Página:** `/boas-vindas/` com abas Instalações e Retornos
- **Card:** "Boas Vindas" na área interna (BackOffice, Diretoria, Admin)
- **APIs:** `instalacoes/`, `retornos/`, `retornos/<id>/`, `status/`, `sugestao-ia/`, `enviar/`, `agendar/`, `fila-status/`
- **Fila automática:** Botão "Agendar na fila" → cria registros em `FilaEnvioBoasVindas` com horários 8h-16h. O **scheduler** (APScheduler) roda a cada 5 min e processa a fila.
- **Webhook:** Grava todas as mensagens em `MensagemClienteBoasVindas`, sugere status via IA na primeira resposta

---

## 8. Fluxo Original (referência)

1. **Fase 1 – Estrutura**
   - Criar modelo `MensagemClienteBoasVindas`
   - Criar modelo `StatusBoasVindas` (ou cadastro em StatusCRM tipo BoasVindas)
   - Adicionar campos em `BoasVindasEnviado`: status, definido_por, sugestao_ia

2. **Fase 2 – Nova ferramenta**
   - Página `/boas-vindas/` e card na área interna
   - API: listar instalações dia anterior
   - API: listar retornos (BoasVindasEnviado com respondido_em preenchido)

3. **Fase 3 – Envio distribuído**
   - API ou job que calcula slots 8h–16h
   - Envio com intervalo 20–30 min
   - Remover botão Boas-Vindas do Record Vendas (ou manter como redirect)

4. **Fase 4 – Webhook**
   - Alterar webhook para gravar todas as mensagens em `MensagemClienteBoasVindas`

5. **Fase 5 – Interface BO**
   - Painel de retornos com histórico de mensagens
   - Atribuição de status
   - Integração IA para sugestão

---

## 9. Referências

- [WhatsApp API Rate Limits (Wati)](https://www.wati.io/en/blog/whatsapp-business-api/whatsapp-api-rate-limits/)
- Código atual: `EnviarBoasVindasView`, `BoasVindasEnviado`, webhook em `whatsapp_webhook_handler.py`
- Constantes atuais: `WHATSAPP_ENVIO_MIN_SEG=30`, `WHATSAPP_ENVIO_MAX_SEG=65`, `WHATSAPP_LOTE_TAMANHO=5`
