# Relatório de Análise – Governança (Record PAP)

**Data:** 22/02/2025  
**Escopo:** Página `/governanca/` – interface de administração (Gestão de Usuários, Perfis, Comissionamento, Cadastros Gerais, etc.)

---

## 1. Resumo executivo

- **O que funciona:** Navegação entre seções, Gestão de Usuários (lista, paginação, filtro, edição/inativação), Perfis de Acesso, Comissionamento (regras por faixa/vendedor, adiantamentos/descontos), Cadastros Gerais (operadoras, planos, pagamentos, status, pendências), Motivos de Ausência, Feriados, Automação WhatsApp, Relatórios.
- **Problemas identificados:** Exibição de **"undefined"** em nomes/email/líder na tabela de usuários; **lentidão** na Gestão de Usuários; alguns botões dependem de carregamento sob demanda (abas) e podem parecer “não fazer nada” se a aba não carregou dados ainda; elemento **"Olá, usuário"** não existe no header (código preparado mas sem `#welcome-user`).
- **Recomendações:** Corrigir fallbacks de exibição, otimizar carregamento de usuários (evitar carregar todas as páginas para o cache) e reduzir `console.log` em produção.

---

## 2. O que está falhando ou pode melhorar

### 2.1 Exibição "undefined" na Gestão de Usuários

| Local | Causa provável | Correção |
|-------|----------------|----------|
| **Coluna Nome** | `user.nome_completo` pode vir vazio ou não existir na resposta; o código usa `nomeCell.textContent = user.nome_completo` sem fallback. | Usar `(user.nome_completo \|\| user.username \|\| '-')`. |
| **Coluna E-mail** | `user.email` pode ser `null`/indefinido. | Usar `(user.email \|\| '-')`. |
| **Coluna Líder** | `buscarNomeSupervisor()` pode retornar `undefined` se `supervisor_detalhe.username` for indefinido. | Garantir que a função sempre retorne string (ex.: `\|\| '-'`) e que a célula use `(supervisorNome \|\| '-')`. |

**Arquivo:** `frontend/public/governanca.html`  
- Função `renderizarTabelaUsuarios`: células Nome e E-mail sem fallback.  
- Função `buscarNomeSupervisor`: retorno sem garantia de string.

---

### 2.2 Botões que “não fazem nada” ao clicar

A maioria dos botões está ligada corretamente (onclick ou addEventListener). O que pode acontecer:

| Situação | Explicação |
|----------|------------|
| **Abas (Comissionamento, Cadastros Gerais)** | Ao clicar na aba (ex.: "Recebimento Operadora", "Campanhas", "Planos", "Pagamentos"), a função `openTab()` chama o `carregar*` correspondente. Se a API falhar ou demorar, a tabela fica vazia ou em "Carregando..." – não é que o botão não funcione, e sim que o resultado não aparece ou dá erro. |
| **Salvar (formulários)** | Formulários usam `onsubmit` ou botões com `id` em `document.addEventListener('click', ...)`. Botões como "Registrar" (adiantamento/desconto), "Listar vendas", "Registrar adiantamento" estão tratados nesse listener. Verificar no console se há erro de rede ou 401. |
| **Header "Olá, usuário"** | O código faz `document.getElementById('welcome-user')` e, se existir, define o texto com o username do JWT. No HTML do header **não existe** o elemento com `id="welcome-user"`, então nada é exibido (não é "undefined" na tela, só a saudação que não aparece). |

**Recomendações:**  
- Incluir no header um elemento `<span id="welcome-user"></span>` onde a saudação deve aparecer.  
- Em abas que carregam dados (Recebimento Operadora, Campanhas, etc.), exibir mensagem de erro amigável em caso de falha na API e manter estado "Carregando..." até a resposta.

---

### 2.3 Lentidão na Gestão de Usuários

| Causa | Impacto | Solução recomendada |
|-------|---------|----------------------|
| **Carregamento de todas as páginas para o cache** | Ao abrir "Gestão de Usuários", o código carrega a página 1 e depois, em loop, as demais páginas (`page=2`, `page=3`, …) para preencher `todosUsuariosCache`. Com muitos usuários (ex.: 200), são várias requisições sequenciais antes de exibir a primeira tela. | Carregar apenas a página atual para exibir na tabela. Manter o cache apenas para a **busca** (filtro): ao digitar no filtro, aí sim carregar todas as páginas ou usar um endpoint de busca no backend (`?search=termo`) em vez de filtrar no front em cima de um cache completo. |
| **Enriquecimento + muitos `console.log`** | `enriquecerDadosUsuarios()` percorre todos os usuários e faz `console.log` por usuário; há outros logs em `carregarUsuarios` e `renderizarControlesPaginacao`. | Reduzir ou eliminar `console.log` em produção; enriquecer apenas a lista da página atual (não o cache inteiro) quando o objetivo for só exibir a tabela. |
| **Carregar líderes + grupos em toda abertura** | Para cada carga de usuários, são carregados grupos e líderes. Isso é necessário, mas pode ser feito uma vez (cache) e reutilizado. | Manter e respeitar os caches de `gruposCache` e `lideresCache` (já existem); evitar recarregar quando já válidos. |
| **Pré-carregar dados do modal** | `setTimeout(..., 1000)` chama `carregarDadosParaFormulario()` 1 s após o load. Isso pode competir com a lista. | Opcional: executar `carregarDadosParaFormulario()` apenas ao abrir o modal (Novo/Editar usuário), em vez de no init da página. |

---

## 3. O que funciona corretamente

- **Navegação lateral:** `mostrarSecao(event, idSecao, menuItem)` – troca de seção e carrega Perfis / Permissões quando aplicável.
- **Gestão de Usuários:** Lista (ativos/inativos), paginação, filtro por texto, seleção em massa e alteração de perfil, abrir modal (novo/editar), salvar, inativar/reativar.
- **Perfis de Acesso:** Listar, novo perfil, editar, excluir, salvar permissões.
- **Todas as Permissões:** Listagem e filtro por texto.
- **Comissionamento:**  
  - Regras por Faixa: listar, importar, exportar.  
  - Regras por Vendedor: mês, vendedor, salvar, replicar, importar, exportar.  
  - Recebimento Operadora: listar, formulário Salvar, editar.  
  - Campanhas: formulário, faixas, listar.  
  - Adiantamentos e Descontos: registrar adiantamento/desconto, listar vendas, registrar adiantamento de comissão, histórico.
- **Cadastros Gerais:** Operadoras, Planos, Formas de Pagamento, Status, Pendências – abas que disparam o `carregar*` ao clicar.
- **Motivos de Ausência:** Adicionar, listar, excluir.
- **Feriados:** Lista, adicionar, excluir; aba Calendário de Pesos (iframe).
- **Automação WhatsApp:** Regras, salvar, editar, excluir, carregar grupos.
- **Relatórios:** Financeiro (presença), Resultado de Campanhas, Excel.

---

## 4. Melhorias implementadas (recomendações técnicas)

1. **Correções de exibição (undefined)**  
   - Em `renderizarTabelaUsuarios`: usar fallbacks para nome (`nome_completo || username || '-'`), email (`email || '-'`) e líder (`supervisorNome || '-'`).  
   - Em `buscarNomeSupervisor`: garantir retorno sempre string (ex.: `return (x || '-')`).

2. **Performance – Gestão de Usuários**  
   - Exibir apenas a página atual da API (sem loop de todas as páginas no primeiro load).  
   - Manter cache completo apenas quando o usuário usar o filtro de busca; nesse caso, considerar:  
     - carregar todas as páginas em background, ou  
     - usar `?search=termo` na API (se existir) e preencher a tabela com esse resultado.  
   - Reduzir/remover `console.log` em produção.

3. **UX**  
   - Adicionar no header o elemento `#welcome-user` para exibir "Olá, {username}".  
   - Em abas que dependem de API, mostrar mensagem clara em caso de erro ("Não foi possível carregar. Tente novamente.") em vez de tabela vazia sem feedback.

4. **Backend (opcional)**  
   - Endpoint de usuários: garantir que `nome_completo` (get_full_name) e `email` existam na resposta (mesmo que vazios), para evitar undefined no front.  
   - Endpoint `/usuarios/lideres/`: garantir que cada item tenha `username` ou `nome_exibicao` para evitar "undefined" na coluna Líder.

---

## 5. Arquivos principais envolvidos

| Arquivo | Papel |
|---------|--------|
| `frontend/public/governanca.html` | Template e todo o JS da governança (listagens, abas, modais, fetch). |
| `core/views.py` | `GovernancaView` – renderiza `public/governanca.html`. |
| `usuarios/views.py` | API de usuários e líderes (`UsuarioViewSet`, action `lideres`). |
| `usuarios/serializers.py` | `UsuarioSerializer` (nome_completo, supervisor_detalhe, etc.). |

---

## 6. Conclusão

A governança está funcional na maior parte dos fluxos. Os principais pontos a corrigir são:  
- **Exibição "undefined"** na tabela de usuários (fallbacks no front e, se necessário, garantia de campos no backend).  
- **Lentidão** na Gestão de Usuários (parar de carregar todas as páginas no primeiro load; usar cache completo só para busca ou busca via API).  
- **Botões:** em geral estão ligados; a sensação de "não fazer nada" costuma ser falha de API ou abas que só carregam ao clicar – melhorar feedback de erro e "Carregando...".  
- **Saudação no header:** adicionar o elemento `#welcome-user` no HTML para exibir o nome do usuário logado.

---

## 7. Alterações já aplicadas (22/02/2025)

- **undefined na tabela:** Em `renderizarTabelaUsuarios`, Nome passou a usar `(user.nome_completo \|\| user.username \|\| '-')`, E-mail `(user.email \|\| '-')` e Líder `(supervisorNome \|\| '-')`. Em `buscarNomeSupervisor` todos os retornos garantem string (evitando `undefined`).
- **Performance – Gestão de Usuários:** O carregamento de usuários passou a buscar **apenas a página atual** da API (removido o loop que puxava todas as páginas). A **busca** passou a usar o parâmetro `?search=` da API em vez de filtrar um cache completo no front. Redução de `console.log` no fluxo de lista, enriquecimento e paginação.
- **Paginação com busca:** Os links de paginação repassam o termo do campo “Pesquisar usuário”, mantendo o filtro ao mudar de página.
