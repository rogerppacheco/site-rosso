# Sincronizar repositório local com a versão em produção (após rollback)

Quando você faz um **rollback no Railway**, a produção volta para um deploy anterior. O seu repositório local (e o `origin/main`) continuam no commit mais recente. Para **alinhar o código local à versão que está rodando em produção**, siga estes passos.

## 1. Descobrir qual versão está rodando no Railway

No **Railway**, a versão em produção é o **deploy ativo** do serviço. O commit desse deploy é a referência para sincronizar o local.

### Opção A: Dashboard (recomendado)

1. Acesse [railway.app](https://railway.app) e faça login.
2. Abra o **projeto** do site-record.
3. Clique no **serviço** (app) que está em produção.
4. Vá em **Deployments** (ou na timeline de deploys na página do serviço).
5. O deploy marcado como **Active** (ou o que está “rodando agora”) mostra o **commit** (hash curto, ex.: `a01625b`).

Anote esse hash.

### Opção B: Pelo terminal

Com o [Railway CLI](https://docs.railway.com/guides/cli) instalado e o projeto linkado (`railway link`):

```powershell
railway open
```

Isso abre o dashboard no navegador; use os passos da Opção A para ver o deploy ativo e o commit.

## 2. Sincronizar o repositório local com esse commit

No diretório do projeto:

```powershell
cd c:\site-record

# Buscar referências do remoto (caso o commit já exista no origin)
git fetch origin

# Fazer o main local ficar exatamente nesse commit (recomendado para espelhar produção)
git checkout main
git reset --hard <COMMIT_HASH>
```

Substitua `<COMMIT_HASH>` pelo hash que você anotou no Railway (ex.: `a01625b`).

### Exemplo

Se o deploy ativo em produção for o commit `a01625b`:

```powershell
git fetch origin
git checkout main
git reset --hard a01625b
```

Agora o seu `main` local está **igual ao código que está rodando em produção**.

## 3. (Opcional) Atualizar o GitHub com essa versão

Se quiser que o `origin/main` também aponte para essa versão (para outros devs ou para futuros deploys):

```powershell
git push origin main --force
```

**Cuidado:** `--force` reescreve o histórico do `main` no GitHub. Use só se for realmente a versão que você quer como referência.

## 4. Script auxiliar

Há um script que ajuda a sincronizar (ele pede o commit ou você pode passar direto):

```powershell
.\scripts\sync_local_com_producao.ps1
```

Ou passando o commit já conhecido (pegue no dashboard do Railway):

```powershell
.\scripts\sync_local_com_producao.ps1 -Commit a01625b
```

---

**Resumo:** depois de um rollback no **Railway**, veja no dashboard qual é o deploy ativo e anote o **commit**. Use `git fetch origin` e `git reset --hard <commit>` no `main` local para ficar igual à produção.
