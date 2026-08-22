# Teste Local do Fluxo VENDER

## Teste com navegador visível (ver etapas no PAP)

Para **ver cada etapa acontecendo** no site https://pap.niointernet.com.br/:

```bash
python manage.py testar_pap_visivel
```

**Modo interativo (padrão):** o comando pede todos os dados no terminal:
- Matrícula e senha BackOffice
- Matrícula do vendedor
- CEP, número, referência
- CPF, celular, e-mail do cliente
- Forma de pagamento, plano, turno

Entre cada etapa, pressione ENTER para continuar e observe o navegador.

```bash
python manage.py testar_pap_visivel --auto
```

**Modo automático:** usa dados de teste (ou do banco). Pausa de 2s entre etapas.

### Opções (modo --auto)

| Opção | Descrição |
|-------|-----------|
| `--matricula-bo X` | Matrícula do BackOffice (login PAP) |
| `--senha-bo X` | Senha do BackOffice |
| `--matricula-vendedor Y` | Matrícula do vendedor no pedido |
| `--cep`, `--numero`, `--referencia` | Dados do endereço |
| `--cpf`, `--celular`, `--email` | Dados do cliente |
| `--velocidade N` | Segundos de pausa entre etapas (default: 2) |

---

## Teste PAP + Terminal (digite como WhatsApp e veja no site)

Para **digitar no terminal e ver cada etapa no site** pap.niointernet.com.br:

```bash
python manage.py testar_pap_terminal
```

O navegador abre em modo visível. Você digita uma mensagem por vez no terminal
(exatamente como no WhatsApp) e acompanha a automação executando no site.

Fluxo: VENDER → SIM → CEP → Número → Referência → CPF → Celular → E-mail
       → 1/2/3 (pagamento) → 1/2/3 (plano) → 1/2 (turno) → CONFIRMAR

Comando: `/sair` ou `CANCELAR` para encerrar.

---

## Teste interativo (digite como no WhatsApp)

Para **mapear falhas** e melhorar o processo etapa a etapa:

```bash
python manage.py testar_vender_interativo --telefone 5531988804000
```

Você digita **uma mensagem por vez**, como no WhatsApp. O sistema mostra a etapa atual e a resposta.

**Comandos especiais:**
- `/etapa` – mostra etapa e dados atuais
- `/reset` – reinicia o fluxo
- `/sair` – encerra
- `/log` – lista falhas mapeadas na sessão

Use para identificar onde o processo falha, etapas não mapeadas e melhorias.

---

## Teste via webhook (simula WhatsApp)

```bash
python manage.py testar_vender_etapas
```

### Opções

| Opção | Descrição |
|-------|-----------|
| `--telefone 5511999999999` | Telefone do vendedor (deve estar em `Usuario.tel_whatsapp`) |
| `--auto` | Executa com dados de teste automáticos (CANCELAR no final) |

## Modo interativo (padrão)

1. Execute o comando sem `--auto`
2. Em cada etapa, você pode:
   - Pressionar **Enter** para usar o valor sugerido
   - Digitar outra mensagem para testar
   - Digitar `n` para encerrar antes do fim

## Modo automático

```bash
python manage.py testar_vender_etapas --auto
```

Executa todas as etapas com dados fictícios e finaliza com CANCELAR (não envia ao PAP).

## Pré-requisitos

1. **Migrações aplicadas:** `python manage.py migrate`

2. **Usuário vendedor** com:
   - `autorizar_venda_sem_auditoria = True`
   - `matricula_pap` preenchida
   - `tel_whatsapp` preenchido (para busca automática ou usar `--telefone`)

3. **Usuário BackOffice** (para pool) com:
   - Perfil `cod_perfil = 'backoffice'`
   - `matricula_pap` e `senha_pap` preenchidos

## Etapas testadas

1. VENDER – inicia fluxo
2. SIM – confirma e obtém BO do pool
3. CEP – endereço
4. Número – número ou S/N
5. Referência – texto de referência
6. CPF – 11 dígitos
7. Celular – com DDD
8. E-mail – válido
9. Forma pagamento – 1, 2 ou 3
10. Plano – 1, 2 ou 3
11. Turno – 1 ou 2
12. CONFIRMAR ou CANCELAR

## Observação

O comando **não envia mensagens reais** pelo WhatsApp. As respostas são exibidas no terminal.
