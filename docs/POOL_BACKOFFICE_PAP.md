# Pool de Logins BackOffice para Automação PAP

## Contexto

Vendedores (perfil Vendedor) não conseguem realizar vendas pelo site [pap.niointernet.com.br](https://pap.niointernet.com.br/) diretamente. Usuários com **"Autorizar venda sem auditoria"** passam a usar credenciais de perfil **BackOffice** via pool, com seleção randômica e controle de uso.

## Fluxo

1. **Vendedor** digita VENDER no WhatsApp
2. Sistema verifica: `autorizar_venda_sem_auditoria` + `matricula_pap` (vendedor só precisa da matrícula)
3. Ao confirmar (SIM), o sistema obtém um login BackOffice disponível do pool
4. Login no PAP é feito com **credenciais do BO** (matrícula + senha)
5. No formulário de novo pedido, o **vendedor** é selecionado pela **matrícula do vendedor** (para atribuição da venda)
6. Ao finalizar (sucesso, erro ou cancelamento), o BO é liberado para o pool

## Segurança e Distribuição

- **Seleção randômica:** entre os BOs disponíveis
- **Exclusão de conflitos:** um BO em uso não é oferecido a outro vendedor
- **Timeout:** locks com mais de 30 minutos são liberados automaticamente (sessões travadas)
- **Mensagem quando todos ocupados:** "TODOS OS ACESSOS BACKOFFICE ESTÃO EM USO - Aguarde alguns minutos"

## Quando as sessões são limpas

1. **Automático (a cada VENDER)**  
   Ao chamar `obter_login_bo()` (quando o vendedor confirma com SIM), o sistema remove **locks com mais de 30 minutos**. Ou seja: toda vez que alguém tenta VENDER, locks expirados são limpos antes de ver se há BO livre.

2. **Manual (comando)**  
   Use quando quiser liberar **agora** sem esperar 30 min ou quando todos os BOs estão ocupados e você quer liberar todos:
   ```bash
   python manage.py liberar_pap_bo --listar      # ver quem está usando
   python manage.py liberar_pap_bo --expirados    # remove só locks > 30 min
   python manage.py liberar_pap_bo --todos        # libera TODOS os BOs
   python manage.py liberar_pap_bo --telefone=553188804000  # libera um vendedor
   ```

3. **Função em código**  
   - `crm_app.pool_bo_pap.limpar_sessoes_expiradas()` — remove locks > 30 min e retorna quantos foram removidos (pode ser chamada em cron ou em tarefas periódicas).

## Requisitos

### Vendedor (com autorizar_venda_sem_auditoria)
- `matricula_pap` preenchida (para ser selecionado como vendedor no pedido)
- `tel_whatsapp` para identificação

### BackOffice (para o pool)
- Perfil com `cod_perfil = 'backoffice'`
- `matricula_pap` e `senha_pap` preenchidos
- `is_active = True`
- `login_pap_disponivel_para_automacao = True`
- **Por automação:** cada login BO pode ser liberado só para as automações desejadas:
  - `pap_automacao_vender` – automação VENDER (nova venda pelo WhatsApp)
  - `pap_automacao_credito` – automação CRÉDITO (análise de crédito)
  - `pap_automacao_pedido` – automação PEDIDO (consulta de pedido/O.S.)
  - `pap_automacao_status` – automação STATUS (consulta online no PAP)

Se nenhum login BO tiver a automação marcada, o usuário recebe mensagem orientando a falar com o administrador (Governança → Logins PAP).

## Modelo e Serviço

- **Modelo:** `PapBoEmUso` – controla qual BO está em uso, por qual telefone e por qual tipo de automação (`tipo_automacao`: vender, credito, pedido, status)
- **Serviço:** `crm_app.pool_bo_pap`
  - `obter_login_bo(telefone, sessao_id, tipo_automacao=None)` – obtém BO livre para a automação; retorna `(Usuario, None)` ou `(None, mensagem_erro)`. `tipo_automacao`: `'vender'`, `'credito'`, `'pedido'`, `'status'`.
  - `liberar_bo(bo_usuario_id, telefone)` – libera o BO ao finalizar

## Migração

```bash
python manage.py migrate crm_app
```
