# Análise do Excel de Comissão e Especificação da Reconstrução

## Situação atual

O arquivo **COMISSÃO_RECORD_AGF.xlsx** está no OneDrive e não foi possível acessá-lo daqui. Para fazer a **análise completa das três abas** e alinhar a reconstrução ao Excel, é necessário ter o conteúdo no projeto.

### Como enviar o conteúdo do Excel

**Opção A – Recomendada: exportar para o projeto**

1. No seu PC, abra o terminal na pasta do projeto e execute (ajuste o caminho do arquivo):

   ```bash
   python scripts/export_excel_comissao.py "c:\Users\rogge\OneDrive - Parceiros Oi\Oi Corp\Record\BASE_COMISSÃO\COMISSÃO_RECORD_AGF.xlsx"
   ```

2. Serão gerados em `data/comissao_export/`:
   - `FOLHA_PAGAMENTO_2.json` e `.csv`
   - `REGRAS_FAIXAS.json` e `.csv`
   - `REGRAS_VENDEDORES.json` e `.csv`

3. Envie ou commite esses arquivos (pode ser só os `.json`) para que eu possa analisar e fechar a especificação.

**Opção B – Copiar o Excel para o projeto**

- Copie **COMISSÃO_RECORD_AGF.xlsx** para `c:\site-record\data\COMISSÃO_RECORD_AGF.xlsx`.
- Avise quando estiver lá; daqui em diante usarei esse caminho para ler o arquivo (se o ambiente tiver acesso).

---

## Estrutura esperada das abas (a confirmar com o Excel real)

Com base em padrões de “folha de pagamento” e “regras de comissão”, abaixo está o que costuma existir em cada aba. Assim que tivermos o export (ou o arquivo no projeto), a análise será ajustada ao layout exato do seu Excel.

### 1. FOLHA PAGAMENTO (2)

Objetivo: **folha mensal de comissão** (quem recebe quanto).

Colunas típicas (nomes podem variar):

| Tipo | Exemplo de coluna | Uso |
|------|-------------------|-----|
| Identificação | Vendedor / Consultor / Nome | Quem |
| Período | Mês / Ano / Referência | Mês de pagamento |
| Quantidade | Qtd Vendas / Qtd Instaladas / Meta | Base do cálculo |
| Meta | Meta / Meta do Mês | Comparação (bateu ou não) |
| Valores | Comissão Bruta / Base / Acelerado | Soma das comissões por venda |
| Descontos | Boleto, Viabilidade, Antecipação, Adiant. CNPJ, INSS, Outros | Itens que reduzem |
| Bônus | Prêmios / Campanhas | Itens que aumentam |
| Total | Líquido / A Pagar / Total | Valor final |
| Observações | Obs / Status | Texto livre ou status |

Possíveis variações no Excel:

- Uma linha por vendedor no mês.
- Ou uma linha por venda + totais por vendedor.
- Ou blocos (cabeçalho do vendedor + linhas de detalhe + total).

Na reconstrução, a tela **Gestão de Comissionamento → Folha de Pagamento** deve:

- Permitir escolher **mês/ano**.
- Mostrar uma **tabela** com colunas equivalentes às do Excel (vendedor, qtd, meta, bruto, descontos, bônus, líquido, etc.).
- Opcional: linhas expansíveis com **detalhamento por venda** (plano, valor unitário, data, etc.), como no Excel quando há detalhe.
- Exportar **Excel** e/ou **PDF** no mesmo “formato” da aba (um resumo por vendedor + opção de detalhe).

### 2. REGRAS_FAIXAS

Objetivo: **regras por faixa** (ex.: de 1 a 5 vendas = valor X; de 6 a 10 = valor Y).

Colunas típicas:

| Tipo | Exemplo | Uso |
|------|---------|-----|
| Escopo | Plano / Produto / Canal / Tipo Cliente | A que se aplica a faixa |
| Faixa | De / Até / Mín / Máx / Faixa 1, 2, 3 | Intervalo de quantidade (ou valor) |
| Valor | Valor / Comissão / R$ | Valor da comissão naquela faixa |

Possíveis formatos no Excel:

- **Por faixa de quantidade:**  
  Ex.: Plano A, CPF, 1–5 vendas → R$ 150; 6–10 → R$ 180; 11+ → R$ 200.
- **Por faixa de valor (faturamento):**  
  Ex.: até R$ 10k → 5%; de 10k a 20k → 7%.
- Tabela com colunas **Plano | Tipo Cliente | Canal | De | Até | Valor**.

Na reconstrução, a tela **Regras de Comissão → Regras por Faixa** deve:

- Cadastro em **tabela** (como no Excel): linhas com Plano (ou “Todos”), Tipo Cliente (CPF/CNPJ), Canal (PAP/TELAG), Faixa (De–Até) e Valor.
- Ordenação e filtros por plano/canal/tipo cliente.
- Edição em linha ou formulário (modal) para cada linha.
- Importação em lote a partir de planilha (colunas alinhadas ao cadastro).

### 3. REGRAS_VENDEDORES

Objetivo: **regras por vendedor** (e plano/tipo venda/tipo cliente): valor base e valor acelerado (ou equivalente).

Colunas típicas:

| Tipo | Exemplo | Uso |
|------|---------|-----|
| Vendedor | Nome / Consultor / ID | Quem tem a regra |
| Plano | Plano / Produto | O que vendeu |
| Tipo venda | PAP / TELAG / Canal | Canal da venda |
| Tipo cliente | CPF / CNPJ | Tipo do cliente |
| Base | Valor Base / Sem Meta | Comissão quando não bate meta |
| Acelerado | Valor Acelerado / Com Meta | Comissão quando bate meta |

Isso já existe no sistema como **RegraComissao** (consultor + plano + tipo_venda + tipo_cliente + valor_base + valor_acelerado). A diferença desejada é a **forma de cadastro**: “como no Excel”.

Na reconstrução, a tela **Regras de Comissão → Regras por Vendedor** deve:

- Exibir uma **tabela** (grid) com colunas: Vendedor, Plano, Tipo Venda, Tipo Cliente, Valor Base, Valor Acelerado (e outras que existirem no Excel).
- Permitir **edição em linha** (clicar e alterar) e/ou formulário (modal) para adicionar/editar.
- **Importar planilha**: upload de Excel/CSV com as mesmas colunas; validação e criação/atualização em lote.
- **Exportar** para Excel com o mesmo layout, para o usuário ajustar fora e reimportar.
- Manter a unicidade: (Vendedor, Plano, Tipo Venda, Tipo Cliente) = uma regra por combinação.

---

## Reconstrução: resumo do que será entregue

### A. Gestão de Comissionamento – Regras de Comissão

1. **Regras por Vendedor (tabela “como no Excel”)**
   - Grid com: Vendedor, Plano, Tipo Venda, Tipo Cliente, Valor Base, Valor Acelerado.
   - Edição em linha e/ou modal; filtros por vendedor/plano; importar/exportar Excel.

2. **Regras por Faixa (se o Excel tiver essa aba)**  
   - Se no Excel existir **REGRAS_FAIXAS** com faixas de quantidade (ou valor), haverá:
   - Cadastro em tabela: Plano (ou genérico), Tipo Cliente, Canal, Faixa (De–Até), Valor.
   - Cálculo da folha poderá usar **faixa** em vez de (ou junto com) base/acelerado por vendedor, conforme análise da planilha.

3. **Compatibilidade com o modelo atual**
   - **RegraComissao** continua sendo a tabela “por vendedor” (consultor + plano + tipo_venda + tipo_cliente + valor_base + valor_acelerado).
   - Se houver regras por faixa, pode ser um novo modelo (ex.: `RegraComissaoFaixa`) e a lógica de cálculo será ajustada para usar faixa quando aplicável.

### B. Gestão de Comissionamento – Folha de Pagamento

1. **Tela “como o Excel”**
   - Filtro: mês/ano (e opcionalmente vendedor).
   - Tabela principal: uma linha por vendedor com colunas alinhadas à aba **FOLHA PAGAMENTO (2)** (vendedor, qtd, meta, bruto, descontos, bônus, líquido, etc.).
   - Detalhe expansível (por vendedor): vendas do mês com plano, data, valor unitário, etc.
   - Totalizadores no rodapé (soma bruto, descontos, líquido).

2. **Ações**
   - Fechar mês / Reabrir mês (como hoje).
   - Exportar para **Excel** no mesmo formato da folha (uma aba “Resumo” por vendedor, opcional aba “Detalhe” com vendas).
   - Exportar **PDF** (extrato por vendedor ou folha única).
   - Envio por e-mail e WhatsApp (resumo/comprovante), mantendo o que já existe onde fizer sentido.

3. **Cálculo**
   - Manter a lógica atual (vendas instaladas no mês, regras por vendedor, meta para acelerado, descontos, bônus campanhas, lançamentos financeiros).
   - Se após a análise do Excel surgir **REGRAS_FAIXAS**, o cálculo poderá ter uma variante “por faixa” (por plano/canal/tipo cliente) além ou em vez do base/acelerado.

---

## Próximos passos

1. **Você:** Executar o script de export (ou copiar o xlsx para `c:\site-record\data\`) e disponibilizar os arquivos em `data/comissao_export/` (ou o próprio xlsx no projeto).
2. **Eu:** Com o conteúdo real das abas:
   - Analisar **FOLHA PAGAMENTO (2)**: cabeçalhos, linhas, fórmulas (quando possível), totais.
   - Analisar **REGRAS_FAIXAS**: colunas, significado de cada faixa, como se relaciona com plano/vendedor.
   - Analisar **REGRAS_VENDEDORES**: colunas exatas e como mapear para RegraComissao (e se há mais campos).
3. **Especificação final:** Atualizar este documento com:
   - Nomes exatos das colunas de cada aba.
   - Regras de negócio (como “acelerado” é aplicado, como faixas se aplicam, etc.).
   - Wireframes/texto das telas (Regras + Folha) e da exportação Excel/PDF.
4. **Implementação:** Ajustar backend (APIs, modelos se necessário) e frontend (Regras em tabela + Folha em tabela + exportação) conforme essa especificação.

Assim que os arquivos exportados (ou o xlsx) estiverem no projeto, a análise completa das duas abas (e a terceira, se for o caso) será feita e a reconstrução ficará alinhada ao Excel no cadastro das regras e na geração da folha de pagamento.
