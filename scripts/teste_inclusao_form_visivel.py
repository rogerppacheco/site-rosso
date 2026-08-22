"""
Teste manual: preenche o Google Form de Inclusão com navegador VISÍVEL.
Uso:
  set PAP_HEADLESS=false
  set DEBUG_INCLUSAO_FORM=1
  .venv\\Scripts\\python.exe scripts\\teste_inclusao_form_visivel.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Forçar modo visível + logs detalhados ANTES do Django carregar settings
os.environ["PAP_HEADLESS"] = "false"
os.environ["DEBUG_INCLUSAO_FORM"] = "1"
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gestao_equipes.settings")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# O serviço lê GOOGLE_FORM_* de os.environ (não do decouple).
# No .env local elas existem via config(), mas NÃO entram em os.environ sozinhas.
from decouple import config as env_config

for key in ("GOOGLE_FORM_EMAIL", "GOOGLE_FORM_PASSWORD", "GOOGLE_STREETVIEW_API_KEY"):
    val = env_config(key, default="")
    if val and key not in os.environ:
        os.environ[key] = str(val)

import django

django.setup()

from django.conf import settings

# Garantir navegador visível mesmo se .env tiver PAP_HEADLESS=true
settings.PAP_HEADLESS = False

from crm_app.services_inclusao_viabilidade import (
    _caminho_storage_state,
    preencher_formulario_inclusao,
)


def main() -> None:
    print("=" * 60)
    print("TESTE INCLUSÃO — navegador visível")
    print(f"PAP_HEADLESS (settings) = {settings.PAP_HEADLESS}")
    print(f"FORM email em os.environ = {bool(os.environ.get('GOOGLE_FORM_EMAIL'))}")
    print(f"FORM password em os.environ = {bool(os.environ.get('GOOGLE_FORM_PASSWORD'))}")
    state = _caminho_storage_state()
    print(f"Storage state = {state}")
    print(f"Storage existe = {os.path.isfile(state)}")
    print("=" * 60)
    print("Abrindo Chromium... acompanhe a janela.")
    print()

    # Endereço de exemplo (BH) — ajuste se quiser outro
    dados = {
        "cep": "30130100",
        "viacep": {
            "cep": "30130-100",
            "logradouro": "Avenida Afonso Pena",
            "bairro": "Centro",
            "localidade": "Belo Horizonte",
            "uf": "MG",
        },
        "numero_fachada": "1500",
        "complementos": "sem complementos",
        "fachadas_vizinhos": "Frente 1490, Direita 1502, Esquerda 1498",
        "coordenadas": "-19.92450100, -43.93521700",
        "observacoes": "TESTE AUTOMATIZADO — NÃO ENVIAR (se chegar no Enviar, cancele na tela)",
    }

    # Sem arquivos: testa preenchimento + login + campos (upload costuma falhar à parte)
    foto = ROOT / "scripts" / "_teste_inclusao_foto.jpg"
    arquivos = [str(foto)] if foto.is_file() else []
    if not arquivos:
        print("AVISO: sem foto de teste — o Enviar pode falhar se o arquivo for obrigatório.")
    sucesso, msg = preencher_formulario_inclusao(dados, arquivos_paths=arquivos)
    print()
    print("=" * 60)
    print("RESULTADO:", "OK" if sucesso else "FALHOU")
    # Evitar UnicodeEncodeError no console Windows (emoji ✅)
    print((msg or "").encode("ascii", "replace").decode("ascii"))
    print("=" * 60)
    if sucesso:
        print(
            "ATENÇÃO: o formulário pode ter sido ENVIADO de verdade. "
            "Confira no Google Forms se entrou uma resposta de teste."
        )


if __name__ == "__main__":
    main()
