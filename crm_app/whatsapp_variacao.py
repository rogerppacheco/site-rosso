# crm_app/whatsapp_variacao.py
"""
Variação de palavras/frases em mensagens enviadas pelo WhatsApp.
Objetivo: reduzir bloqueios ao não enviar sempre o mesmo texto igual (mesmo conceito, palavras diferentes).
Apenas frases mapeadas são alteradas; instruções, comandos e URLs não são tocados.
"""
import re
import random
import logging

logger = logging.getLogger(__name__)

# Mapeamento: frase original -> lista de alternativas (mesmo sentido).
# Ordem: frases mais longas primeiro, para não substituir parte de outra.
_VARIACOES = [
    # Saudações / abertura
    ("Olá boa tarde,", ["Olá, boa tarde,", "Boa tarde,", "Oi, boa tarde,"]),
    ("Olá boa noite,", ["Olá, boa noite,", "Boa noite,", "Oi, boa noite,"]),
    ("Olá bom dia,", ["Olá, bom dia,", "Bom dia,", "Oi, bom dia,"]),
    ("Olá,", ["Oi,", "Olá!", "Oi!"]),
    ("Boa tarde.", ["Boa tarde!", "À tarde."]),
    ("Boa noite.", ["Boa noite!", "À noite."]),
    ("Bom dia.", ["Bom dia!", "Pela manhã."]),
    # Disponibilidade / encerramento
    ("estamos à sua disposição", ["ficamos à sua disposição", "permanecemos à disposição", "estamos à disposição"]),
    ("Estamos à sua disposição", ["Ficamos à sua disposição", "Permanecemos à disposição", "Estamos à disposição"]),
    ("à sua disposição", ["à disposição", "disponíveis para você"]),
    ("Obrigado e tenha um boa tarde!", ["Agradecemos e tenha uma ótima tarde!", "Obrigado! Tenha uma boa tarde.", "Agradecemos o contato. Tenha uma ótima tarde."]),
    ("Obrigado e tenha um boa noite!", ["Agradecemos e tenha uma ótima noite!", "Obrigado! Tenha uma boa noite.", "Agradecemos o contato. Tenha uma ótima noite."]),
    ("Obrigado e tenha um bom dia!", ["Agradecemos e tenha um ótimo dia!", "Obrigado! Tenha um bom dia.", "Agradecemos o contato. Tenha um ótimo dia."]),
    ("Obrigado pela sua atenção.", ["Agradecemos pela sua atenção.", "Obrigado pelo contato.", "Agradecemos o contato."]),
    # Informações gerais (evitar texto idêntico em massa)
    ("Me chamo", ["Sou", "Aqui é", "Meu nome é"]),
    ("sou especialista de qualidade", ["sou especialista de qualidade", "atuo na qualidade", "faço parte da equipe de qualidade"]),
    ("parceiro Oficial da Nio Fibra", ["parceiro oficial da Nio Fibra", "parceiro da Nio Fibra", "parceiro Nio Fibra"]),
    ("Estou entrando em contato para informar que", ["Entro em contato para informar que", "Escrevo para informar que", "Contato para informar que"]),
    ("caso você precise tirar dúvidas", ["caso precise de alguma dúvida", "se precisar de alguma informação", "para qualquer dúvida"]),
    ("Sua primeira fatura irá vencer", ["A primeira fatura vence", "A primeira fatura irá vencer", "O vencimento da primeira fatura será"]),
    ("Você também pode acompanhar", ["Também é possível acompanhar", "Pode acompanhar", "Você pode acompanhar"]),
    ("através do app Nio", ["pelo app Nio", "no aplicativo Nio", "via app Nio"]),
    ("Instale o aplicativo", ["Baixe o aplicativo", "Instale o app", "Baixe o app"]),
    ("no seu aparelho celular", ["no seu celular", "em seu aparelho", "no seu dispositivo"]),
    ("Disponível para Android e iOS", ["Para Android e iOS", "Disponível em Android e iOS", "Para Android e iPhone"]),
    ("Você ainda pode realizar contato", ["Também pode entrar em contato", "Pode contatar", "Ainda pode contatar"]),
    ("pelos canais de comunicação oficiais", ["pelos canais oficiais", "pelos canais oficiais de comunicação", "pelos canais oficiais da Nio"]),
    ("Em breve um especialista irá falar contigo", ["Em breve um especialista entrará em contato.", "Um especialista retornará em breve.", "Nossa equipe retornará em breve."]),
    ("Em breve um de nossos analistas retornará", ["Um de nossos analistas retornará em breve.", "Nossa equipe retornará em breve.", "Em breve retornaremos o contato."]),
]

# Ordenar por tamanho decrescente para aplicar as mais longas primeiro
_VARIACOES.sort(key=lambda x: -len(x[0]))


def aplicar_variacao(texto: str, chance_substituir: float = 0.6) -> str:
    """
    Aplica variações aleatórias em frases mapeadas, mantendo o sentido da mensagem.
    chance_substituir: probabilidade (0 a 1) de substituir cada ocorrência; default 0.6.
    Retorna o texto com possíveis substituições (ou o original se nada for aplicado).
    """
    if not texto or not isinstance(texto, str):
        return texto
    resultado = texto
    for frase_original, alternativas in _VARIACOES:
        if frase_original not in resultado:
            continue
        # Escolher uma alternativa (pode ser a própria original se estiver na lista)
        opcoes = [frase_original] + [a for a in alternativas if a != frase_original]
        escolhida = random.choice(opcoes)
        # Aplicar com chance_substituir; senão manter original
        if random.random() > chance_substituir:
            continue
        # Substituir apenas a primeira ocorrência por envio (evita ficar repetitivo)
        resultado = resultado.replace(frase_original, escolhida, 1)
    if resultado != texto:
        logger.debug("[Variacao] Mensagem com variação aplicada (trecho alterado).")
    return resultado


def aplicar_variacao_lote(texto: str, chance_substituir: float = 0.5) -> str:
    """
    Versão que pode substituir várias ocorrências no texto (para mensagens longas, ex.: boas-vindas).
    chance_substituir: probabilidade de cada substituição.
    """
    if not texto or not isinstance(texto, str):
        return texto
    resultado = texto
    for frase_original, alternativas in _VARIACOES:
        opcoes = [frase_original] + [a for a in alternativas if a != frase_original]
        # Substituir cada ocorrência com probabilidade chance_substituir
        while frase_original in resultado and random.random() <= chance_substituir:
            escolhida = random.choice(opcoes)
            resultado = resultado.replace(frase_original, escolhida, 1)
    return resultado
