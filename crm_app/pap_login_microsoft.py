"""Classificação da tela de login Microsoft do PAP, sem enviar credencial."""

from __future__ import annotations

import re

DOMINIO_EMAIL_PAP = "vtalcorp.onmicrosoft.com"
ESPERA_APROVACAO_MFA_SEGUNDOS = 120

_ERROS_CREDENCIAL = (
    "password is incorrect",
    "account or password is incorrect",
    "senha está incorreta",
    "senha esta incorreta",
    "conta ou senha",
    "couldn't find an account",
    "couldn’t find an account",
    "não encontramos uma conta",
    "nao encontramos uma conta",
    "username may be incorrect",
    "nome de usuário pode estar incorreto",
    "nome de usuario pode estar incorreto",
    "account has been locked",
    "conta foi bloqueada",
    "conta bloqueada",
    "muitas tentativas",
    "too many attempts",
    "aadsts50126",
    "aadsts50053",
)

_KMSI = (
    "stay signed in",
    "permanecer conectado",
    "manter conectado",
    "continuar conectado",
)

_CADASTRO = (
    "more information required",
    "mais informações necessárias",
    "mais informacoes necessarias",
    "keep your account secure",
    "mantenha sua conta segura",
    "scan the qr code",
    "escaneie o código qr",
    "escaneie o codigo qr",
)

_MFA = (
    "authenticator",
    "approve a request",
    "approve sign in",
    "aprovar uma solicitação",
    "aprovar uma solicitacao",
    "enter the number",
    "digite o número",
    "digite o numero",
    "enter the code",
    "insira o código",
    "insira o codigo",
    "verify your identity",
    "verificar sua identidade",
    "we'll call",
    "we’ll call",
    "vamos ligar",
    "atenda a chamada",
)


def email_acesso_microsoft(matricula: str) -> str:
    """TT123456 vira TT123456@vtalcorp.onmicrosoft.com. Não duplica o domínio."""
    bruto = (matricula or "").strip()
    if not bruto:
        return ""
    if "@" in bruto:
        return bruto
    return f"{bruto}@{DOMINIO_EMAIL_PAP}"


def extrair_numero_mfa(texto: str) -> str:
    """Número de 2 dígitos que o Authenticator pede para digitar no celular."""
    for linha in (texto or "").splitlines():
        item = linha.strip()
        if re.fullmatch(r"\d{2}", item):
            return item
    return ""


def _texto_pede_senha(visivel: str) -> bool:
    """A primeira tela da Microsoft traz o campo de senha no HTML, sem pedir senha."""
    return any(
        sinal in visivel
        for sinal in (
            "enter password",
            "enter the password",
            "insira a senha",
            "digite a senha",
            "senha",
            "password",
        )
    )


def classificar_tela_microsoft(
    *,
    url: str,
    texto: str,
    email_visivel: bool,
    senha_visivel: bool,
) -> str:
    """
    Estado da tela visível.

    O campo de senha já vem no HTML da etapa do e-mail e o Playwright pode
    marcá-lo como visível. Sem o texto pedindo a senha, a etapa continua sendo o e-mail.
    """
    url_l = (url or "").lower()
    visivel = (texto or "").lower()
    no_pap = "pap.niointernet.com.br" in url_l and "login.microsoft" not in url_l
    if no_pap and not ("/login" in url_l and "administrativo" not in url_l):
        return "pap_ok"
    if any(erro in visivel for erro in _ERROS_CREDENCIAL):
        return "erro_credencial"
    if any(sinal in visivel for sinal in _KMSI):
        return "kmsi"
    if any(sinal in visivel for sinal in _CADASTRO):
        return "cadastro"
    if any(sinal in visivel for sinal in _MFA):
        return "mfa"
    if email_visivel and not _texto_pede_senha(visivel):
        return "email"
    if senha_visivel:
        return "senha"
    if email_visivel:
        return "email"
    if "login.microsoftonline.com" in url_l or "login.microsoft.com" in url_l:
        return "aguardando"
    return "outro"
