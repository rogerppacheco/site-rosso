"""
Setup do número oficial na Cloud API Meta (Graph API) para o site-rosso.

Lê META_CLOUD_ACCESS_TOKEN / META_CLOUD_WABA_ID / META_CLOUD_PHONE_NUMBER_ID
do ambiente ou do .env (token de usuário do sistema com
whatsapp_business_management + whatsapp_business_messaging).

Fluxo típico:
  python ferramentas/meta_cloud_setup.py status
  python ferramentas/meta_cloud_setup.py add-number --phone 31984199207 --nome "Rosso Telecom"
  python ferramentas/meta_cloud_setup.py request-code --metodo SMS
  python ferramentas/meta_cloud_setup.py verify-code --codigo 123456
  python ferramentas/meta_cloud_setup.py register --pin 654321
  python ferramentas/meta_cloud_setup.py subscribe
  python ferramentas/meta_cloud_setup.py templates-criar [--so nio_boas_vindas_v1]
  python ferramentas/meta_cloud_setup.py templates-status
  python ferramentas/meta_cloud_setup.py teste-texto --para 31999999999
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

import requests

BASE_DIR = Path(__file__).resolve().parent.parent
GRAPH = "https://graph.facebook.com"


def _env(nome: str, default: str = "") -> str:
    val = os.environ.get(nome)
    if val:
        return val.strip()
    env_file = BASE_DIR / ".env"
    if env_file.exists():
        try:
            from decouple import Config, RepositoryEnv

            return str(Config(RepositoryEnv(str(env_file))).get(nome, default=default)).strip()
        except Exception:
            pass
    return default


TOKEN = _env("META_CLOUD_ACCESS_TOKEN")
WABA_ID = _env("META_CLOUD_WABA_ID")
PHONE_NUMBER_ID = _env("META_CLOUD_PHONE_NUMBER_ID")
VERSION = _env("META_CLOUD_API_VERSION", "v21.0") or "v21.0"


def _url(path: str) -> str:
    return f"{GRAPH}/{VERSION}/{path.lstrip('/')}"


def _req(metodo: str, path: str, **kwargs: Any) -> Dict[str, Any]:
    if not TOKEN:
        sys.exit("META_CLOUD_ACCESS_TOKEN ausente (ambiente ou .env).")
    headers = {"Authorization": f"Bearer {TOKEN}"}
    resp = requests.request(metodo, _url(path), headers=headers, timeout=60, **kwargs)
    try:
        data = resp.json()
    except ValueError:
        data = {"raw": resp.text[:500]}
    if resp.status_code >= 400:
        print(f"[HTTP {resp.status_code}] {json.dumps(data, ensure_ascii=False, indent=2)}")
    return data


def _exigir(valor: str, nome: str) -> str:
    if not valor:
        sys.exit(f"{nome} ausente (ambiente ou .env).")
    return valor


def _print(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


# --- Templates (mesmos textos de docs/gerar_docx_templates_meta_nio.py) ---

_RODAPE = "SAC: 0800 001 1000 | WhatsApp: 21 3605-1000"
_BOTOES_COBRANCA = ["Quero a 2ª via", "Já paguei", "Falar com suporte"]

TEMPLATES: List[Dict[str, Any]] = [
    {
        "name": "nio_confirmacao_pedido_v1",
        "body": [
            "Olá, {{1}}!", "", "{{2}},", "",
            "📋 *RESUMO DO PEDIDO NIO FIBRA*", "",
            "👤 Cliente: {{3}}", "CPF: {{4}}", "E-mail: {{5}}", "",
            "📍 Endereço:", "CEP: {{6}}", "Logradouro: {{7}}", "Número: {{8}}",
            "Complemento: {{9}}", "Bairro: {{10}}", "Cidade: {{11}}", "",
            "💳 Pagamento: {{12}}", "📦 Plano: {{13}}", "📅 Fidelidade: {{14}}", "",
            "💰 Taxa de habilitação:",
            "Conforme o contrato, a taxa de habilitação fica isenta",
            "quando cumprida a fidelidade indicada acima.", "",
            "A primeira fatura vence 25 dias após a instalação;",
            "nos demais meses, o vencimento segue o ciclo de 30 em 30 dias.", "",
            "✅ Confirma os dados do pedido?", "",
            "Toque em um dos botões abaixo:", "",
            "Parceiro oficial da Nio Fibra.", _RODAPE,
        ],
        "exemplo": [
            "Bom dia", "Maria", "Maria Silva", "***.456.789-**", "m***a@email.com",
            "30140-000", "Rua Exemplo", "100", "Apto 101", "Centro",
            "Belo Horizonte - MG", "Boleto", "500 Mega - R$ 100,00/mês", "12 meses",
        ],
        "botoes": ["CORRETO", "CORRIGIR", "Falar com atendente"],
    },
    {
        "name": "nio_lembrete_instalacao_v1",
        "body": [
            "Olá, {{1}}!", "", "{{2}}, tudo bem?", "",
            "Parceiro oficial da Nio Fibra.",
            "Sua instalação da Nio Fibra está agendada para *{{3}}*,",
            "no período das *{{4}}*.", "",
            "Se você não puder estar presente, é necessário que",
            "uma pessoa maior de 18 anos esteja no local.", "",
            "A instalação é gratuita.", "Não realizamos instalações em dias de chuva.", "",
            "Toque em um dos botões abaixo:", "", _RODAPE,
        ],
        "exemplo": ["Bom dia", "Maria", "15/10/2026", "08:00 às 12:00"],
        "botoes": ["Confirmar", "Reagendar", "Suporte"],
    },
    {
        "name": "nio_instalacao_confirmada_v1_2",
        "body": [
            "Confirmação registrada. ✅", "",
            "Sua instalação Nio Fibra está confirmada para *{{1}}*,", "das *{{2}}*.", "",
            "O técnico entrará em contato por ligação e WhatsApp",
            "quando estiver a caminho.", "",
            "Se precisar de algo, use os botões abaixo.", "",
            "Parceiro oficial da Nio Fibra.",
        ],
        "exemplo": ["15/10/2026", "08:00 às 12:00"],
        "botoes": ["Entendi", "Reagendar", "Suporte"],
    },
    {
        "name": "nio_fatura_lembrete_5d_antes_v1",
        "body": [
            "Olá, {{1}}!", "", "{{2}},", "",
            "Parceiro oficial da Nio Fibra.",
            "Este é um lembrete da sua fatura Nio Fibra.", "",
            "Referência: *{{3}}*", "Valor: *{{4}}*", "Vencimento: *{{5}}* (em 5 dias).", "",
            "Toque em um dos botões abaixo para continuar.",
            "Se o pagamento já foi feito, escolha *Já paguei*.", "", _RODAPE,
        ],
        "exemplo": ["Bom dia", "Maria", "Outubro/2026", "R$ 99,90", "10/10/2026"],
        "botoes": _BOTOES_COBRANCA,
    },
    {
        "name": "nio_fatura_vencida_5d_v1",
        "body": [
            "Olá, {{1}}!", "", "{{2}},", "",
            "Parceiro oficial da Nio Fibra.",
            "Identificamos que sua fatura Nio Fibra está em atraso.", "",
            "Referência: *{{3}}*", "Valor: *{{4}}*", "Vencimento: *{{5}}* (há 5 dias).", "",
            "A confirmação do pagamento pode levar até 5 dias úteis.", "",
            "Toque em um dos botões abaixo para continuar.", "", _RODAPE,
        ],
        "exemplo": ["Boa tarde", "Maria", "Setembro/2026", "R$ 99,90", "25/09/2026"],
        "botoes": _BOTOES_COBRANCA,
    },
    {
        "name": "nio_fatura_cobranca_recorrente_v1",
        "body": [
            "Olá, {{1}}!", "", "{{2}},", "",
            "Parceiro oficial da Nio Fibra.",
            "Sua fatura Nio Fibra permanece em aberto.", "",
            "Referência: *{{3}}*", "Valor: *{{4}}*", "Vencimento: *{{5}}*",
            "Dias em atraso: *{{6}}*", "",
            "Toque em um dos botões abaixo para regularizar",
            "ou informar que o pagamento já foi feito.", "", _RODAPE,
        ],
        "exemplo": ["Boa noite", "Maria", "Setembro/2026", "R$ 99,90", "18/09/2026", "12"],
        "botoes": _BOTOES_COBRANCA,
    },
    {
        "name": "nio_pendencia_reagendamento_v1",
        "body": [
            "Olá, {{1}}!", "", "{{2}},", "",
            "Parceiro oficial da Nio Fibra.",
            "Identificamos uma pendência no agendamento",
            "da sua instalação Nio Fibra.",
            "Na maioria dos casos isso não depende de você.", "",
            "Para reagendar, entre em contato pelo",
            "WhatsApp oficial da Nio: {{3}}.", "",
            "Toque em um dos botões abaixo se precisar",
            "de ajuda com o reagendamento ou tiver dúvidas.", "",
            "Obrigado por escolher a Nio Fibra.", "SAC: 0800 001 1000",
        ],
        "exemplo": ["Bom dia", "Maria", "21 3605-1000"],
        "botoes": ["Reagendar", "Falar com atendente", "Entendi"],
    },
    {
        "name": "nio_boas_vindas_v1",
        "body": [
            "Olá, {{1}}!", "", "{{2}},", "",
            "Parceiro oficial da Nio Fibra.",
            "Sua instalação Nio Fibra foi concluída.", "Seja bem-vindo(a)!", "",
            "Guarde este WhatsApp para suporte e", "dúvidas sobre sua conexão.", "",
            _RODAPE, "",
            "Toque em um dos botões abaixo se precisar", "de ajuda agora.",
        ],
        "exemplo": ["Bom dia", "Maria"],
        "botoes": ["Entendi", "Falar com atendente", "Suporte"],
    },
    {
        "name": "nio_fatura_reducao_sinal_v1",
        "body": [
            "Olá, {{1}}!", "", "{{2}},", "",
            "Parceiro oficial da Nio Fibra.",
            "Sua internet está com a velocidade reduzida",
            "devido a uma pendência de pagamento.", "",
            "Referência: *{{3}}*", "Valor: *{{4}}*", "Vencimento: *{{5}}*", "",
            "Precisamos do seu retorno para programar a",
            "regularização e liberar novamente 100% do",
            "seu sinal de fibra óptica.", "",
            "Informe sua previsão de pagamento pelos", "botões abaixo.", "", _RODAPE,
        ],
        "exemplo": ["Bom dia", "Maria", "Agosto/2026", "R$ 99,90", "10/08/2026"],
        "botoes": ["Informar previsão", "Já paguei", "Falar com suporte"],
    },
]


def _payload_template(t: Dict[str, Any]) -> Dict[str, Any]:
    texto = "\n".join(t["body"])
    if len(texto) > 1024:
        sys.exit(f"{t['name']}: corpo com {len(texto)} caracteres (limite Meta 1024).")
    return {
        "name": t["name"],
        "language": "pt_BR",
        "category": "UTILITY",
        "components": [
            {"type": "BODY", "text": texto, "example": {"body_text": [t["exemplo"]]}},
            {
                "type": "BUTTONS",
                "buttons": [{"type": "QUICK_REPLY", "text": b} for b in t["botoes"]],
            },
        ],
    }


# --- Comandos ---

def cmd_status(_: argparse.Namespace) -> None:
    waba = _exigir(WABA_ID, "META_CLOUD_WABA_ID")
    _print(_req("GET", waba, params={"fields": "id,name,currency,timezone_id,message_template_namespace"}))
    _print(_req(
        "GET",
        f"{waba}/phone_numbers",
        params={
            "fields": "id,display_phone_number,verified_name,code_verification_status,"
                      "name_status,status,quality_rating,messaging_limit_tier,platform_type",
        },
    ))
    _print(_req("GET", f"{waba}/subscribed_apps"))


def cmd_add_number(a: argparse.Namespace) -> None:
    waba = _exigir(WABA_ID, "META_CLOUD_WABA_ID")
    data = _req(
        "POST",
        f"{waba}/phone_numbers",
        data={"cc": a.cc, "phone_number": a.phone, "verified_name": a.nome},
    )
    _print(data)
    if data.get("id"):
        print(f"\nDefina META_CLOUD_PHONE_NUMBER_ID={data['id']} e rode request-code.")


def cmd_request_code(a: argparse.Namespace) -> None:
    pnid = _exigir(a.phone_number_id or PHONE_NUMBER_ID, "META_CLOUD_PHONE_NUMBER_ID")
    _print(_req("POST", f"{pnid}/request_code", data={"code_method": a.metodo, "language": "pt_BR"}))


def cmd_verify_code(a: argparse.Namespace) -> None:
    pnid = _exigir(a.phone_number_id or PHONE_NUMBER_ID, "META_CLOUD_PHONE_NUMBER_ID")
    _print(_req("POST", f"{pnid}/verify_code", data={"code": a.codigo}))


def cmd_register(a: argparse.Namespace) -> None:
    pnid = _exigir(a.phone_number_id or PHONE_NUMBER_ID, "META_CLOUD_PHONE_NUMBER_ID")
    _print(_req("POST", f"{pnid}/register", json={"messaging_product": "whatsapp", "pin": a.pin}))


def cmd_subscribe(_: argparse.Namespace) -> None:
    waba = _exigir(WABA_ID, "META_CLOUD_WABA_ID")
    _print(_req("POST", f"{waba}/subscribed_apps"))


def cmd_templates_criar(a: argparse.Namespace) -> None:
    waba = WABA_ID if a.dry_run else _exigir(WABA_ID, "META_CLOUD_WABA_ID")
    alvo = [t for t in TEMPLATES if not a.so or t["name"] in a.so]
    for t in alvo:
        payload = _payload_template(t)
        if a.dry_run:
            _print(payload)
            continue
        data = _req("POST", f"{waba}/message_templates", json=payload)
        print(f"{t['name']}: {data.get('status') or data.get('error', {}).get('message', data)}")


def cmd_templates_status(_: argparse.Namespace) -> None:
    waba = _exigir(WABA_ID, "META_CLOUD_WABA_ID")
    data = _req(
        "GET",
        f"{waba}/message_templates",
        params={"fields": "name,status,category,language,rejected_reason", "limit": 200},
    )
    for t in data.get("data", []):
        motivo = t.get("rejected_reason")
        extra = f" ({motivo})" if motivo and motivo != "NONE" else ""
        print(f"{t['name']:<40} {t['language']:<6} {t['category']:<10} {t['status']}{extra}")


def cmd_teste_texto(a: argparse.Namespace) -> None:
    pnid = _exigir(PHONE_NUMBER_ID, "META_CLOUD_PHONE_NUMBER_ID")
    digitos = "".join(c for c in a.para if c.isdigit())
    if not digitos.startswith("55"):
        digitos = "55" + digitos
    _print(_req(
        "POST",
        f"{pnid}/messages",
        json={
            "messaging_product": "whatsapp",
            "to": digitos,
            "type": "text",
            "text": {"body": a.texto},
        },
    ))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status").set_defaults(func=cmd_status)

    s = sub.add_parser("add-number")
    s.add_argument("--phone", required=True, help="DDD + número, sem 55")
    s.add_argument("--nome", required=True, help="Nome de exibição (verified_name)")
    s.add_argument("--cc", default="55")
    s.set_defaults(func=cmd_add_number)

    s = sub.add_parser("request-code")
    s.add_argument("--metodo", choices=["SMS", "VOICE"], default="SMS")
    s.add_argument("--phone-number-id", default="")
    s.set_defaults(func=cmd_request_code)

    s = sub.add_parser("verify-code")
    s.add_argument("--codigo", required=True)
    s.add_argument("--phone-number-id", default="")
    s.set_defaults(func=cmd_verify_code)

    s = sub.add_parser("register")
    s.add_argument("--pin", required=True, help="PIN de 6 dígitos da verificação em duas etapas")
    s.add_argument("--phone-number-id", default="")
    s.set_defaults(func=cmd_register)

    sub.add_parser("subscribe").set_defaults(func=cmd_subscribe)

    s = sub.add_parser("templates-criar")
    s.add_argument("--so", nargs="*", help="Somente estes nomes de template")
    s.add_argument("--dry-run", action="store_true", help="Só imprime o payload")
    s.set_defaults(func=cmd_templates_criar)

    sub.add_parser("templates-status").set_defaults(func=cmd_templates_status)

    s = sub.add_parser("teste-texto")
    s.add_argument("--para", required=True)
    s.add_argument("--texto", default="Teste Cloud API Meta - site-rosso")
    s.set_defaults(func=cmd_teste_texto)

    a = p.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
