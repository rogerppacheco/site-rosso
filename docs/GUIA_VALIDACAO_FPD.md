# 🔍 Guia Rápido - Validação de Importações FPD

## Como Usar o Painel de Validação

### 1️⃣ Acessar o Painel
**Opção 1:** Menu Importações
- Entre em `/importacoes/`
- Clique no card **"Validar FPD"** (ícone de checklist)

**Opção 2:** Link Direto
- Acesse `/validacao-fpd/`

---

### 2️⃣ Entender as Estatísticas

O topo da página mostra 6 cards principais:

| Card | Significado |
|------|-------------|
| 📤 **Total de Importações** | Quantas vezes você importou arquivos FPD |
| ✅ **Com Sucesso** | Importações 100% bem-sucedidas (verde) |
| ❌ **Com Erro** | Importações que falharam completamente (vermelho) |
| ⚠️ **Parciais** | Importações com alguns erros (amarelo) |
| 📄 **Linhas Processadas** | Total de linhas lidas de todos os arquivos |
| 💰 **Valor Total** | Soma de todos os valores importados |

---

### 3️⃣ Filtrar Importações

Use os filtros para encontrar importações específicas:

**Filtro Status:**
- Selecione: Todos / Sucesso / Erro / Parcial / Processando

**Filtro Data:**
- Data Início: Buscar importações a partir de...
- Data Fim: Buscar importações até...

**Buscar Arquivo:**
- Digite parte do nome do arquivo
- Ex: "janeiro" para encontrar "fpd_janeiro_2025.xlsx"

Clique em **"Buscar"** para aplicar os filtros.  
Clique em **"Limpar"** para resetar.

---

### 4️⃣ Entender a Tabela

A tabela mostra todas as importações com estas colunas:

| Coluna | Descrição |
|--------|-----------|
| **Data/Hora** | Quando a importação começou |
| **Arquivo** | Nome do arquivo importado |
| **Usuário** | Quem fez a importação |
| **Status** | Badge colorido (Sucesso/Erro/Parcial) |
| **Total Linhas** | Quantas linhas o arquivo tinha |
| **Processadas** | Quantas foram salvas com sucesso (verde) |
| **Erros** | Quantas tiveram erro de formato (vermelho) |
| **Não Encontrados** | Quantas O.S não existem no banco (amarelo) |
| **Valor Total** | Soma dos valores daquela importação |
| **Duração** | Quanto tempo levou (em segundos) |
| **Ações** | Botão 👁️ para ver detalhes |

---

### 5️⃣ Ver Detalhes de uma Importação

1. Clique no botão **👁️** na coluna "Ações"
2. Uma seção expandível aparecerá mostrando:

**Métricas Detalhadas:**
- Tamanho do arquivo (KB)
- Taxa de sucesso (%)
- Horário de início
- Horário de fim

**Erros (se houver):**
- Mensagem de erro em destaque vermelho
- Explicação do que deu errado

**Ordens de Serviço Não Encontradas:**
- Lista com as primeiras 20 O.S que não existem no banco
- Ex: `OS-12345`, `OS-67890`, `OS-11111`...
- Contador de quantas faltam no total

---

### 6️⃣ Diagnosticar Problemas

#### ✅ Status: SUCESSO (Verde)
**Significa:** Tudo foi importado corretamente!
- 100% das linhas processadas
- Nenhum erro
- Nenhuma O.S não encontrada

**O que fazer:** Nada, está perfeito! 🎉

---

#### ⚠️ Status: PARCIAL (Amarelo)
**Significa:** Alguns registros falharam, mas outros foram salvos.

**Causas comuns:**
1. **O.S Não Encontradas** - As mais comuns
   - O arquivo FPD tem números de O.S que não existem na base CRM
   - Exemplos são listados na seção de detalhes

**Como resolver:**
1. Clique no botão 👁️ para ver detalhes
2. Na seção "Ordens de Serviço Não Encontradas", veja a lista
3. Verifique se:
   - Os números estão corretos no arquivo FPD
   - Esses contratos já foram importados no sistema M-10
   - Não há erros de digitação (espaços extras, caracteres especiais)

**Próximos passos:**
- Se as O.S estão corretas: Importe primeiro os contratos M-10 correspondentes
- Se estão erradas: Corrija o arquivo FPD e importe novamente

---

#### ❌ Status: ERRO (Vermelho)
**Significa:** A importação falhou completamente.

**Causas comuns:**
1. Formato de arquivo inválido (não é Excel/CSV válido)
2. Colunas obrigatórias faltando
3. Erro de servidor/banco de dados

**Como resolver:**
1. Clique no botão 👁️ para ver a mensagem de erro
2. Leia a mensagem (geralmente explica o problema)
3. Corrija o arquivo e tente novamente

**Exemplos de erros:**
- "nr_ordem não encontrado no arquivo" → Arquivo sem coluna nr_ordem
- "Formato de arquivo inválido" → Arquivo corrompido ou tipo errado

---

### 7️⃣ Atualizar a Página

**Manualmente:**
- Clique no botão flutuante azul no canto inferior direito 🔄
- A página atualiza com os dados mais recentes

**Automaticamente:**
- A página atualiza sozinha a cada 30 segundos
- Perfeito para monitorar importações em andamento

---

### 8️⃣ Navegar Entre Páginas

Se você tem muitas importações, use a paginação:

- **⬅️ Anterior** - Volta para a página anterior
- **➡️ Próxima** - Avança para próxima página
- **Página X de Y** - Mostra onde você está

---

## 🆘 Problemas Comuns

### "Não vejo minha importação recente"
1. Clique no botão 🔄 para atualizar
2. Verifique se os filtros não estão aplicados (clique em "Limpar")
3. Aguarde 30 segundos (auto-refresh)

### "Importei mas diz que 0 registros foram salvos"
Isso significa que **TODAS as O.S do arquivo não existem no banco M-10**.

**Solução:**
1. Clique no botão 👁️ da importação
2. Veja a lista de O.S não encontradas
3. Importe primeiro esses contratos no sistema M-10
4. Depois, reimporte o arquivo FPD

### "Status está em PROCESSANDO há muito tempo"
Se uma importação ficou travada:
1. Aguarde 5 minutos (arquivos grandes demoram)
2. Se continuar: Entre em contato com suporte técnico
3. Pode ter havido um erro no servidor

---

## 💡 Dicas Profissionais

### ✅ Boas Práticas

1. **Sempre verifique a validação após importar**
   - Não confie só na mensagem de sucesso
   - Veja os detalhes para conferir

2. **Monitore importações parciais**
   - Status amarelo precisa de atenção
   - Resolva as O.S faltantes

3. **Use filtros para análise**
   - Filtro "Erro" → Ver todas que falharam
   - Filtro de data → Verificar período específico

4. **Documente O.S problemáticas**
   - Copie a lista de O.S não encontradas
   - Cole num Excel para controle

5. **Importe em horários de baixa demanda**
   - Arquivos grandes podem demorar
   - Evite horários de pico

---

## 🎯 Fluxo de Trabalho Ideal

```
1. Preparar arquivo FPD
   ↓
2. Importar em /importar-fpd/
   ↓
3. Ir para /validacao-fpd/
   ↓
4. Verificar status da importação
   ↓
5a. SUCESSO → Continuar trabalho
5b. PARCIAL → Ver O.S faltantes → Corrigir → Reimportar
5c. ERRO → Ler mensagem → Corrigir arquivo → Reimportar
```

---

## 📞 Precisa de Ajuda?

**Para erros técnicos:**
- Entre no admin Django: `/admin/crm_app/logimportacaofpd/`
- Veja o log completo da importação

**Para dúvidas:**
- Consulte a documentação completa: `SISTEMA_VALIDACAO_FPD.md`
- Entre em contato com o administrador do sistema

---

**Última atualização:** Janeiro 2025
