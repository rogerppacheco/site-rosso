"""A esteira não reenvia a senha quando a Microsoft recusa o login."""

from django.test import SimpleTestCase

from crm_app.esteira_consulta_status_pap_service import (
    _SessaoPapUsuarioHolder,
    _recusa_microsoft_sem_retry as recusa_consulta,
)
from crm_app.esteira_sync_status_pap_service import (
    _SessaoPapSyncHolder,
    _recusa_microsoft_sem_retry as recusa_sync,
)

_MSG = (
    "A Microsoft recusou o acesso e a tentativa foi interrompida "
    "para não bloquear a conta. Confira a senha do PAP dessa matrícula."
)


class RecusaMicrosoftEsteiraTests(SimpleTestCase):
    def test_mensagem_da_microsoft_nao_repete(self) -> None:
        self.assertTrue(recusa_consulta(_MSG))
        self.assertTrue(recusa_sync(_MSG))
        self.assertFalse(recusa_consulta("OS não encontrada no PAP"))

    def test_consulta_nao_abre_outro_login(self) -> None:
        holder = _SessaoPapUsuarioHolder.__new__(_SessaoPapUsuarioHolder)
        holder.recusa_microsoft = _MSG
        ok, msg = holder._garantir_sessao()
        self.assertFalse(ok)
        self.assertEqual(msg, _MSG)

    def test_sync_nao_abre_outro_login(self) -> None:
        holder = _SessaoPapSyncHolder.__new__(_SessaoPapSyncHolder)
        holder.recusa_microsoft = _MSG
        ok, msg = holder._garantir_sessao()
        self.assertFalse(ok)
        self.assertEqual(msg, _MSG)
