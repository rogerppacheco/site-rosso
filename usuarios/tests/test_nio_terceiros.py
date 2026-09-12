import tempfile
from pathlib import Path

from django.contrib.auth.models import Group
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from usuarios.models import Perfil, Usuario
from usuarios.services_nio_terceiros import (
    SessaoNioExpirada,
    _garantir_html_autenticado,
    email_cadastro,
    importar_terceiros,
    mapear_canal,
    mapear_perfil,
    mesclar_terceiro,
    normalizar_celular,
    parse_cadastro_html,
    parse_lista_html,
    terceiros_para_preview,
    username_candidato,
)


LISTA_HTML = """
<div class="col-md-11 col-xs-10">
  <div class="col-xs-6 col-md-3">
    <a href="?pagina=colaboradores&amp;id=370721&amp;colaborador=644150&amp;ac=editar">CAUA FELIPE FERREIRA DA SILVA</a>
    <div><b class="text-gray">Chave de Acesso:</b> TT835595</div>
  </div>
  <div class="col-xs-6 col-md-2">MG</div>
  <div class="col-xs-6 col-md-2">OPERADOR BACK-OFFICE&nbsp;</div>
  <div class="col-xs-6 col-md-1">Ativado<div class="small text-success">Aprovado</div></div>
</div>
<div class="col-md-11 col-xs-10">
  <div class="col-xs-6 col-md-3">
    <a href="?pagina=colaboradores&amp;id=370721&amp;colaborador=641340&amp;ac=editar">JESSICA CRISTINA ROQUE DA SILVA</a>
    <div><b class="text-gray">Chave de Acesso:</b> TT833384</div>
  </div>
  <div class="col-xs-6 col-md-2">MG</div>
  <div class="col-xs-6 col-md-2">VENDEDOR</div>
  <div class="col-xs-6 col-md-1">Ativado</div>
</div>
"""

CADASTRO_HTML = """
<form>
  <input type="text" name="cpf" value="108.575.226-71">
  <input type="text" value="TT833384" readonly>
  <input type="text" name="nome" value="JESSICA CRISTINA ROQUE DA SILVA">
  <input type="email" name="email" value="">
  <input type="text" name="mobile_phone" value="(31) 9 9917-4111">
  <select name="funcao_ctps"><option selected>VENDEDOR</option></select>
  <select name="tipo_vinculo"><option selected>CLT</option></select>
  <select name="perfil"><option selected>Operacional</option></select>
  <select name="status"><option selected value="1">Ativado</option></select>
</form>
"""


class NioTerceirosNormalizacaoTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.perfil_vend = Perfil.objects.create(cod_perfil="vendedor", nome="Vendedor")
        cls.perfil_bo = Perfil.objects.create(cod_perfil="backoffice", nome="BackOffice")
        Group.objects.create(name="Vendedor")
        Group.objects.create(name="BackOffice")
        cls.existente = Usuario.objects.create_user(
            username="ROBERTO",
            password="SenhaSegura123",
            email="roberto@example.com",
            first_name="Roberto",
            last_name="Dias Borges",
            cpf="03786487219",
        )

    def test_parse_lista_extrai_matricula_e_funcao(self):
        itens = parse_lista_html(LISTA_HTML)
        self.assertEqual(len(itens), 2)
        caua = next(i for i in itens if i["nio_id"] == "644150")
        self.assertEqual(caua["matricula"], "TT835595")
        self.assertIn("BACK-OFFICE", caua["funcao"].upper())
        self.assertEqual(mapear_perfil(caua["funcao"]), "BackOffice")
        self.assertEqual(mapear_canal(caua["funcao"]), "PARCEIRO")

    def test_parse_cadastro_normaliza_cpf_e_celular(self):
        dados = parse_cadastro_html(CADASTRO_HTML, nio_id="641340")
        self.assertEqual(dados["cpf"], "10857522671")
        self.assertEqual(dados["matricula"], "TT833384")
        self.assertEqual(dados["celular"], "31999174111")
        self.assertEqual(dados["funcao"], "VENDEDOR")
        self.assertEqual(mapear_canal(dados["funcao"]), "PAP")

    def test_sessao_expirada_nao_tenta_login(self):
        with self.assertRaises(SessaoNioExpirada):
            _garantir_html_autenticado("<html>Efetuar login Senha + OTP</html>", "https://login.vtal.com/nidp/saml2/sso")

    def test_preview_marca_existente_por_cpf(self):
        terceiro = mesclar_terceiro(
            {"nio_id": "644147", "nome": "ROBERTO DIAS BORGES", "matricula": "TT835597", "funcao": "OPERADOR BACK-OFFICE"},
            {"cpf": "03786487219", "celular": "3199665969"},
        )
        preview = terceiros_para_preview([terceiro])
        self.assertEqual(preview[0]["acao"], "atualizar")
        self.assertEqual(preview[0]["usuario_username"], "ROBERTO")

    def test_importar_cria_novo_e_atualiza_matricula(self):
        terceiros = [
            mesclar_terceiro(
                {"nio_id": "644147", "nome": "ROBERTO DIAS BORGES", "matricula": "TT835597", "funcao": "OPERADOR BACK-OFFICE"},
                {"cpf": "03786487219", "celular": "3199665969"},
            ),
            mesclar_terceiro(
                {"nio_id": "641340", "nome": "JESSICA CRISTINA ROQUE DA SILVA", "matricula": "TT833384", "funcao": "VENDEDOR"},
                {"cpf": "10857522671", "celular": "31999174111"},
            ),
        ]
        resultado = importar_terceiros(["644147", "641340"], terceiros=terceiros)
        self.assertEqual(len(resultado["atualizados"]), 1)
        self.assertEqual(len(resultado["criados"]), 1)
        roberto = Usuario.objects.get(username="ROBERTO")
        self.assertEqual(roberto.matricula_pap, "TT835597")
        jessica = Usuario.objects.get(id=resultado["criados"][0]["usuario_id"])
        self.assertEqual(jessica.matricula_pap, "TT833384")
        self.assertEqual(jessica.cpf, "10857522671")
        self.assertEqual(jessica.canal, "PAP")
        self.assertEqual(jessica.perfil.nome, "Vendedor")
        self.assertTrue(jessica.obriga_troca_senha)
        self.assertTrue(jessica.check_password(resultado["criados"][0]["senha_temporaria"]))

    def test_username_e_email_fallback(self):
        usados = {"jessica"}
        nome = username_candidato("JESSICA CRISTINA", "TT833384", usados)
        self.assertNotEqual(nome.lower(), "jessica")
        self.assertEqual(email_cadastro({"matricula": "TT833384", "email": ""}), "tt833384@pendente.local")

    def test_api_preview_usa_cache_e_api_importa(self):
        admin = Usuario.objects.create_superuser(
            username="admin_nio",
            email="admin_nio@example.com",
            password="SenhaSegura123",
        )
        self.client.force_authenticate(user=admin)
        from usuarios.services_nio_terceiros import salvar_cache

        with tempfile.TemporaryDirectory() as tmp:
            cache = str(Path(tmp) / "nio_terceiros_cache.json")
            with override_settings(NIO_TERCEIROS_CACHE=cache):
                salvar_cache(
                    [
                        mesclar_terceiro(
                            {
                                "nio_id": "641340",
                                "nome": "JESSICA CRISTINA ROQUE DA SILVA",
                                "matricula": "TT833384",
                                "funcao": "VENDEDOR",
                            },
                            {"cpf": "10857522671", "celular": "31999174111"},
                        )
                    ]
                )
                preview = self.client.get("/api/usuarios/nio-terceiros/")
                self.assertEqual(preview.status_code, status.HTTP_200_OK, preview.data)
                self.assertEqual(preview.data["terceiros"][0]["acao"], "criar")

                resposta = self.client.post(
                    "/api/usuarios/nio-terceiros/importar/",
                    {"nio_ids": ["641340"]},
                    format="json",
                )
                self.assertEqual(resposta.status_code, status.HTTP_200_OK, resposta.data)
                self.assertEqual(len(resposta.data["criados"]), 1)
                self.assertTrue(Usuario.objects.filter(matricula_pap="TT833384").exists())

    def test_api_recusa_quem_nao_tem_permissao(self):
        comum = Usuario.objects.create_user(username="comum", password="SenhaSegura123", email="c@example.com")
        self.client.force_authenticate(user=comum)
        resposta = self.client.get("/api/usuarios/nio-terceiros/")
        self.assertEqual(resposta.status_code, status.HTTP_403_FORBIDDEN)

    def test_api_aceita_flag_pode_importar_nio_terceiros(self):
        autorizado = Usuario.objects.create_user(
            username="nio_ok",
            password="SenhaSegura123",
            email="nio_ok@example.com",
            pode_importar_nio_terceiros=True,
        )
        self.client.force_authenticate(user=autorizado)
        from usuarios.services_nio_terceiros import salvar_cache

        with tempfile.TemporaryDirectory() as tmp:
            cache = str(Path(tmp) / "nio_terceiros_cache.json")
            with override_settings(NIO_TERCEIROS_CACHE=cache):
                salvar_cache([])
                resposta = self.client.get("/api/usuarios/nio-terceiros/")
                self.assertEqual(resposta.status_code, status.HTTP_200_OK, resposta.data)

    def test_celular_dez_digitos_ganha_nono(self):
        self.assertEqual(normalizar_celular("3188804000"), "31988804000")
