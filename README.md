# CRM Rosso

Cópia exclusiva do sistema para a empresa Rosso. Produção: https://site-rosso-production.up.railway.app

# Estrutura do projeto

> Este README descreve onde estão os arquivos após a organização, sem alterar código ou execução do sistema.

## Pastas principais
- `gestao_equipes/`, `crm_app/`, `core/`, `usuarios/`, `presenca/`, `relatorios/`, `osab/`: código de produção Django (não mover).
- `static/`, `staticfiles/`, `media/`: assets do app (não mover manualmente).
- `frontend/`: recursos de frontend.
- `ferramentas/`: scripts utilitários (importação, diagnóstico, testes, depuração). Execute a partir da raiz: `python ferramentas/<script>.py`.

## Pastas criadas na organização
- `backups/`: dumps e backups (JSON/SQL, inclusive db.sqlite3* e deltas).
- `docs/`: guias, checklists e resumos (.md/.txt).
- `logs/`: arquivos de log e saídas de testes simples.
- `assets/`: imagens/HTML de apoio (debug/visual).
- `temp/`: arquivos soltos/estranhos que não são usados em runtime.

## Sobre os .py na raiz
Para não quebrar nada, não movemos os .py de utilidade pontual que ficam na raiz. Sugestão segura caso queira organizar depois:
- Criar `tools/` para scripts de diagnóstico/import/export (ex.: `comparar_backup_postgresql.py`, `verificar_*`, `debug_*`, `reprocessar_*`, `testar_*`).
- Manter na raiz apenas `manage.py`, `Procfile`, `requirements*.txt`, `runtime.txt`, `Aptfile`.

Se decidir mover scripts para `tools/`, faça em blocos pequenos e teste após cada movimentação. 
