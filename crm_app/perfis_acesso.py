"""Constantes de perfis e grupos de acesso (visualização vs edição)."""
from __future__ import annotations

from typing import Any

from crm_app.utils import is_member

PERFIL_GERENTE_CONTAS = 'Gerente de Contas'

GRUPOS_SOMENTE_LEITURA: list[str] = [PERFIL_GERENTE_CONTAS]

GRUPOS_VISUALIZACAO_GESTAO: list[str] = [
    'Diretoria',
    'Admin',
    'BackOffice',
    'Auditoria',
    'Qualidade',
    PERFIL_GERENTE_CONTAS,
]

GRUPOS_FPD_DASHBOARD: list[str] = [
    'Diretoria',
    'Admin',
    'BackOffice',
    'Qualidade',
    'Auditoria',
    PERFIL_GERENTE_CONTAS,
]

GRUPOS_ESTEIRA_GESTAO_APROVEITAMENTO: list[str] = [
    'Diretoria',
    'Admin',
    'BackOffice',
    PERFIL_GERENTE_CONTAS,
]

GRUPOS_EXPORT_AGENDADOS_PENDENTES: list[str] = [
    'Diretoria',
    'Admin',
    'BackOffice',
    'Supervisor',
    PERFIL_GERENTE_CONTAS,
]


def is_somente_leitura(user: Any) -> bool:
    """True se o perfil do usuário é somente leitura (sem ações de escrita)."""
    return is_member(user, GRUPOS_SOMENTE_LEITURA)


def pode_acessar_fpd_dashboard(user: Any) -> bool:
    """Acesso ao Dashboard FPD (inclui Gerente de Contas)."""
    return is_member(user, GRUPOS_FPD_DASHBOARD)
