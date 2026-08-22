import requests
import re

# ---------------------------------------------------------
# 1. VALIDAÇÃO DE NÚMERO (Usado no Formulário)
# ---------------------------------------------------------
def verificar_whatsapp_existente(numero):
    """
    Recebe um número, limpa, adiciona DDI e consulta a API.
    Retorna True se o número existir no WhatsApp, False caso contrário.
    """
    # 1. Limpeza: remove tudo que não for número
    numero_limpo = re.sub(r'\D', '', str(numero))
    
    # 2. Validação básica
    if not numero_limpo:
        return False

    # 3. Adiciona DDI 55
    if len(numero_limpo) in [10, 11]:
        numero_limpo = f"55{numero_limpo}"

    # --- CONFIGURAÇÃO DA API ---
    BASE_URL = "http://localhost:8080"  
    API_KEY = "SUA_API_KEY_AQUI"        
    
    url = f"{BASE_URL}/chat/checkNumberStatus/{numero_limpo}"
    headers = {"apikey": API_KEY, "Content-Type": "application/json"}

    try:
        response = requests.get(url, headers=headers, timeout=3)
        if response.status_code == 200:
            dados = response.json()
            return dados.get('exists', False)
    except Exception as e:
        print(f"Erro ao verificar WhatsApp: {e}")
        return False 

    return False

# ---------------------------------------------------------
# 2. FUNÇÕES DE ENVIO (Nova Automação)
# ---------------------------------------------------------
def enviar_whatsapp_texto(numero, mensagem):
    """
    Envia mensagem de texto para um número ou grupo (JID).
    """
    BASE_URL = "http://localhost:8080"  
    API_KEY = "SUA_API_KEY_AQUI"
    INSTANCE = "NomeDaSuaInstancia" # Ajuste aqui

    url = f"{BASE_URL}/message/sendText/{INSTANCE}"
    headers = {"apikey": API_KEY, "Content-Type": "application/json"}
    payload = {"number": numero, "text": mensagem}
    
    try:
        # requests.post(url, json=payload, headers=headers)
        print(f" simulado >> Enviando para {numero}: {mensagem[:50]}...")
    except Exception as e:
        print(f"Erro envio WPP: {e}")

def processar_regra_automacao(evento, instancia):
    """
    Busca regras, substitui variáveis e dispara.
    """
    # Importação interna para evitar erro circular com models.py
    from .models import RegraAutomacao
    
    regras = RegraAutomacao.objects.filter(ativo=True, evento_gatilho=evento)
    if not regras.exists():
        return

    # --- Monta variáveis baseadas no Modelo do crm_app ---
    dados = {}
    
    if evento == 'NOVO_CDOI':
        # Mapeia os campos do CdoiSolicitacao (crm_app)
        dados = {
            'id': getattr(instancia, 'id', ''),
            'cliente': getattr(instancia, 'nome_condominio', 'N/A'),
            'sindico': getattr(instancia, 'nome_sindico', 'N/A'),
            'contato': getattr(instancia, 'contato_sindico', 'N/A'),
            'cidade': getattr(instancia, 'cidade', ''),
            'bairro': getattr(instancia, 'bairro', ''),
            'total_hps': getattr(instancia, 'total_hps', 0),
            # Pega o username se o usuário existir
            'usuario': instancia.criado_por.username if instancia.criado_por else 'Sistema',
            # Link fictício - ajuste para sua URL real
            'link': f"https://seusistema.com.br/admin/crm_app/cdoisolicitacao/{instancia.id}/"
        }

    # --- Dispara para cada Regra ---
    for regra in regras:
        try:
            # Troca as variáveis no texto
            texto_final = regra.template_mensagem.format(**dados)
            
            # Envia para Grupos
            if regra.destinos_grupos:
                for grupo_id in regra.destinos_grupos:
                    enviar_whatsapp_texto(grupo_id, texto_final)
            
            # Envia para Números
            if regra.destinos_numeros:
                for num in regra.destinos_numeros:
                    enviar_whatsapp_texto(num, texto_final)
                    
        except Exception as e:
            print(f"Erro ao processar regra {regra.nome}: {e}")