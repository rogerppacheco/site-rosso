# crm_app/ai_context.py
"""
Contexto unificado para a IA do bot WhatsApp: prompt base + base de conhecimento
(conhecimento.md, Nio, planos, tabelas do banco). Usado por Groq e Gemini.
"""
import os
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Pasta de conhecimento (ao lado de ai_context.py)
_AI_KNOWLEDGE_DIR = Path(__file__).resolve().parent / "ai_knowledge"
_CONHECIMENTO_FILE = _AI_KNOWLEDGE_DIR / "conhecimento.md"
_SCHEMA_FILE = _AI_KNOWLEDGE_DIR / "schema_tabelas.md"

def _limite_chars(name: str, default: int) -> int:
    """Lê limite de caracteres da variável de ambiente (ex: IA_MAX_CHARS_DOCS)."""
    val = os.environ.get(name, "").strip()
    if val.isdigit():
        return int(val)
    return default


# Limites configuráveis por variáveis de ambiente. Valores altos causam 413 no Groq; ao dar 413, o fallback
# remove documentos/URLs e a IA fica sem o conhecimento. Mantemos defaults bem baixos para a 1ª tentativa passar.
_MAX_CHARS_DOCUMENTOS_UPLOAD = _limite_chars("IA_MAX_CHARS_DOCS", 8_000)
_MAX_CHARS_URLS = _limite_chars("IA_MAX_CHARS_URLS", 8_000)
_MAX_CHARS_CONHECIMENTO_MD = _limite_chars("IA_MAX_CHARS_CONHECIMENTO", 18_000)
_MAX_CHARS_SCHEMA = _limite_chars("IA_MAX_CHARS_SCHEMA", 3_000)


def _prompt_base() -> str:
    """Instruções fixas do bot: comandos e regras de resposta."""
    return """
Você é um assistente do sistema interno (CRM/gestão) usado por vendedores da operadora de internet.
O bot do WhatsApp oferece estes comandos e fluxos:

- *Fachada*: consultar fachadas por CEP
- *Viabilidade*: consultar viabilidade por CEP e número (mapa/mancha)
- *Inclusão*: solicitar viabilidade via formulário
- *Status*: consultar status de pedido
- *Fatura*: consultar fatura por CPF (Nio Negociar)
- *Conta*: 2ª via de conta por CPF
- *Material* / *Apoia*: buscar materiais e documentos por palavra-chave (Record Apoia)
- *Andamento*: ver agendamentos do dia
- *Crédito*: análise de crédito por CPF
- *Pedido*: consultar pedido/O.S. por CPF no PAP
- *Vender*: realizar venda pelo WhatsApp (fluxo completo)
- *Nova Venda*: cadastrar venda no CRM (Via APP ou Sem APP)
- *MENU* ou *AJUDA*: listar opções

Regras para suas respostas:
- Seja objetivo e cordial. Responda em português.
- Se a dúvida for sobre como usar o bot, indique o comando ou diga para digitar MENU.
- Para perguntas sobre planos da Nio, planos de internet, produtos ou processos: responda SEMPRE com base na seção "Base de conhecimento" abaixo. Se lá houver lista de planos, valores ou benefícios, cite-os na resposta. Se a seção estiver vaga, diga que o vendedor pode ver os planos no sistema ou digitar MENU.
- Quando o vendedor pedir "planos Nio", "Plano Nio - Varejo", "liste os planos", "planos com características" ou similar: liste os planos da seção "Base de conhecimento" com nome, velocidade, valor e principais características (roteador, benefícios), de forma objetiva e curta. Não apenas diga "consulte a base" — inclua a lista na resposta.
- Use APENAS as informações da seção "Base de conhecimento" para responder sobre planos, Nio, processos e tabelas. Não invente dados.
- Respostas devem ser curtas (ideais para WhatsApp). Evite parágrafos longos.
- Não invente dados de clientes, vendas ou faturas; oriente a usar o comando correto (Fatura, Pedido, Status, etc.).

Linguagem e tom (padronização Nio – manual jornada cliente):
Você fala com consultores/vendedores que, por sua vez, falam com clientes. Use a mesma padronização da Nio em suas respostas e, ao orientar o vendedor sobre o que dizer ao cliente, sugira o tom do manual.
- Use linguagem completa, sem abreviações: escreva "você", "porque", "tudo bem", nunca "vc", "pq", "blz".
- Tom leve e humano, mas profissional: cordial e respeitoso, sem gírias nem expressões informais ("rapidinho", "beleza?", "okzinho", "saquei", "tranquilo").
- Prefira: "Bom dia/Boa tarde, como você está?"; "Perfeito." / "Entendido."; "Ficarei responsável por essa solicitação."; "Está correto." / "Compreendido."; "Permaneço à disposição para qualquer necessidade."; "Farei a verificação e retorno com as informações."; "Nossa equipe providenciará a solução."; "Obrigado pela sua atenção. Desejo um excelente dia."
- Evite: "Oi, blza?"; "Deixa pra mim."; "Tá certo."; "Qualquer coisa prende o grito."; "Vou dar uma olhadinha."; "A gente vai resolver."; expressões religiosas ("fique com Deus"); excesso de pontos de exclamação; palavras de pressão ("imperdível", "exclusivo", "última chance"); formalidade excessiva ("Prezado cliente", "Solicitamos que...").
- Ao sugerir frases para o vendedor usar com o cliente, use os exemplos do manual: chamar pelo nome, ser proativo, confirmar entendimento ("Posso confirmar se entendi corretamente?"), finalizar com gratidão e disponibilidade.
"""


def _carregar_arquivo(path: Path, nome: str) -> str:
    """Carrega conteúdo de um arquivo de texto; retorna string vazia se não existir ou der erro."""
    try:
        if path.exists():
            return path.read_text(encoding="utf-8", errors="replace").strip()
    except Exception as e:
        logger.warning("[IA] Erro ao carregar %s: %s", nome, e)
    return ""


def _carregar_conhecimento() -> str:
    """Carrega o conteúdo de conhecimento.md (empresa, Nio, planos, processos)."""
    s = _carregar_arquivo(_CONHECIMENTO_FILE, "conhecimento.md")
    if len(s) > _MAX_CHARS_CONHECIMENTO_MD:
        s = s[:_MAX_CHARS_CONHECIMENTO_MD] + "\n\n... (conteúdo truncado)"
    return s


def _carregar_schema_tabelas() -> str:
    """Carrega descrição das tabelas (schema_tabelas.md) se existir."""
    s = _carregar_arquivo(_SCHEMA_FILE, "schema_tabelas.md")
    if len(s) > _MAX_CHARS_SCHEMA:
        s = s[:_MAX_CHARS_SCHEMA] + "\n... (truncado)"
    return s


def _carregar_documentos_uploadados() -> str:
    """Carrega texto dos documentos enviados pela área interna (PDF/Excel/PPT) que alimentam a IA."""
    try:
        from .models import DocumentoConhecimentoIA
        docs = DocumentoConhecimentoIA.objects.filter(ativo=True).order_by("-data_upload")
        partes = []
        total = 0
        for d in docs:
            texto = (d.conteudo_extraido or "").strip()
            if not texto:
                continue
            if total + len(texto) > _MAX_CHARS_DOCUMENTOS_UPLOAD:
                resto = _MAX_CHARS_DOCUMENTOS_UPLOAD - total
                if resto > 500:
                    partes.append(f"[Documento: {d.titulo}]\n{texto[:resto]}\n... (texto truncado)")
                break
            partes.append(f"[Documento: {d.titulo}]\n{texto}")
            total += len(texto)
        if partes:
            return "\n\n---\n\n".join(partes)
    except Exception as e:
        logger.debug("[IA] Não foi possível carregar documentos uploadados: %s", e)
    return ""


def _carregar_urls_salvas() -> str:
    """Carrega texto das URLs de sites adicionadas pela área interna."""
    try:
        from .models import UrlConhecimentoIA
        urls = UrlConhecimentoIA.objects.filter(ativo=True).order_by("-data_upload")
        partes = []
        total = 0
        for u in urls:
            texto = (u.conteudo_extraido or "").strip()
            if not texto:
                continue
            if total + len(texto) > _MAX_CHARS_URLS:
                resto = _MAX_CHARS_URLS - total
                if resto > 500:
                    partes.append(f"[Site: {u.titulo}]\n{texto[:resto]}\n... (texto truncado)")
                break
            partes.append(f"[Site: {u.titulo}]\n{texto}")
            total += len(texto)
        if partes:
            return "\n\n---\n\n".join(partes)
    except Exception as e:
        logger.debug("[IA] Não foi possível carregar URLs: %s", e)
    return ""


def _gerar_resumo_tabelas_django() -> str:
    """Gera um resumo das tabelas do banco a partir dos models Django (para a IA entender o sistema)."""
    try:
        from django.apps import apps

        lines = []
        for model in apps.get_app_config("crm_app").get_models():
            try:
                table = model._meta.db_table
                verbose = getattr(model._meta, "verbose_name", table)
                lines.append(f"- {table}: {verbose}")
            except Exception:
                continue
        if lines:
            texto = "Tabelas do sistema (banco de dados):\n" + "\n".join(sorted(lines))
            if len(texto) > _MAX_CHARS_SCHEMA:
                texto = texto[:_MAX_CHARS_SCHEMA] + "\n... (truncado)"
            return texto
    except Exception as e:
        logger.debug("[IA] Não foi possível gerar resumo de tabelas: %s", e)
    return ""


def get_contexto_sistema(reduzido: bool = False, contexto_externo: bool = False) -> str:
    """
    Retorna o contexto para a IA.
    reduzido=True: só prompt base + conhecimento.md + schema (sem documentos/URLs), para caber no payload quando der 413.
    contexto_externo=True: prompt curto para contatos não cadastrados (número externo); resposta acolhedora e profissional.
    """
    if contexto_externo:
        return """
Você é o atendimento do Record PAP, parceiro da Nio Fibra. Esta mensagem veio de um contato externo (número não cadastrado como vendedor interno no sistema).

Responda de forma acolhedora e profissional:
- Coloque-se à disposição.
- Se a mensagem for uma dúvida ou solicitação, diga que um analista retornará em breve.
- Seja breve, cordial e use português correto (sem abreviações como "vc", "pq").
- Não invente informações sobre planos ou processos; prefira dizer que um analista retornará com as informações.
- Encerre com agradecimento e disponibilidade.
""".strip()

    base = _prompt_base().strip()
    conhecimento = _carregar_conhecimento()
    schema_file = _carregar_schema_tabelas()
    schema_django = _gerar_resumo_tabelas_django()

    partes = [base]
    if conhecimento:
        partes.append("\n\n---\n\nBase de conhecimento (use apenas isso para planos, Nio, processos):\n\n")
        partes.append(conhecimento)
    if not reduzido:
        docs_upload = _carregar_documentos_uploadados()
        if docs_upload:
            partes.append("\n\n---\n\nConteúdo de documentos enviados (PDFs, planilhas, apresentações):\n\n")
            partes.append(docs_upload)
        urls_sites = _carregar_urls_salvas()
        if urls_sites:
            partes.append("\n\n---\n\nConteúdo de sites adicionados:\n\n")
            partes.append(urls_sites)
    if schema_file:
        partes.append("\n\n---\n\nDescrição das tabelas:\n\n")
        partes.append(schema_file)
    elif schema_django:
        partes.append("\n\n---\n\n")
        partes.append(schema_django)

    return "\n".join(partes).strip()
