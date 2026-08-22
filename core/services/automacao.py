"""
Serviços de automação (regras de automação, WhatsApp).
Mantido para compatibilidade com core.signals e formulários.
"""
import re

import requests


def verificar_whatsapp_existente(numero):
    """
    Recebe um número, limpa, adiciona DDI e consulta a API.
    Retorna True se o número existir no WhatsApp, False caso contrário.
    """
    numero_limpo = re.sub(r"\D", "", str(numero))
    if not numero_limpo:
        return False
    if len(numero_limpo) in [10, 11]:
        numero_limpo = f"55{numero_limpo}"

    BASE_URL = "http://localhost:8080"
    API_KEY = "SUA_API_KEY_AQUI"

    url = f"{BASE_URL}/chat/checkNumberStatus/{numero_limpo}"
    headers = {"apikey": API_KEY, "Content-Type": "application/json"}

    try:
        response = requests.get(url, headers=headers, timeout=3)
        if response.status_code == 200:
            dados = response.json()
            return dados.get("exists", False)
    except Exception as e:
        print(f"Erro ao verificar WhatsApp: {e}")
        return False
    return False


def enviar_whatsapp_texto(numero, mensagem):
    """Envia mensagem de texto para um número ou grupo (JID)."""
    BASE_URL = "http://localhost:8080"
    API_KEY = "SUA_API_KEY_AQUI"
    INSTANCE = "NomeDaSuaInstancia"

    url = f"{BASE_URL}/message/sendText/{INSTANCE}"
    headers = {"apikey": API_KEY, "Content-Type": "application/json"}
    payload = {"number": numero, "text": mensagem}

    try:
        print(f" simulado >> Enviando para {numero}: {mensagem[:50]}...")
    except Exception as e:
        print(f"Erro envio WPP: {e}")


def processar_regra_automacao(evento, instancia):
    """
    Busca regras, substitui variáveis e dispara.
    """
    from ..models import RegraAutomacao

    regras = RegraAutomacao.objects.filter(ativo=True, evento_gatilho=evento)
    if not regras.exists():
        return

    dados = {}
    if evento == "NOVO_CDOI":
        dados = {
            "id": getattr(instancia, "id", ""),
            "cliente": getattr(instancia, "nome_condominio", "N/A"),
            "sindico": getattr(instancia, "nome_sindico", "N/A"),
            "contato": getattr(instancia, "contato_sindico", "N/A"),
            "cidade": getattr(instancia, "cidade", ""),
            "bairro": getattr(instancia, "bairro", ""),
            "total_hps": getattr(instancia, "total_hps", 0),
            "usuario": instancia.criado_por.username if instancia.criado_por else "Sistema",
            "link": f"https://seusistema.com.br/admin/crm_app/cdoisolicitacao/{instancia.id}/",
        }

    for regra in regras:
        try:
            texto_final = regra.template_mensagem.format(**dados)
            if regra.destinos_grupos:
                for grupo_id in regra.destinos_grupos:
                    enviar_whatsapp_texto(grupo_id, texto_final)
            if regra.destinos_numeros:
                for num in regra.destinos_numeros:
                    enviar_whatsapp_texto(num, texto_final)
        except Exception as e:
            print(f"Erro ao processar regra {regra.nome}: {e}")
