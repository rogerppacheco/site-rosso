"""Funções compartilhadas entre API e webhook WhatsApp — Antecipar Instalação / Reparo / Instalação física."""
import re


def normalizar_os_apenas_digitos(s):
    return re.sub(r'\D', '', s or '')


def mensagem_resposta_gc_para_vendedor(os_num, resposta_gc, tipo_solicitacao=None, complemento=None):
    """Mensagem enviada ao vendedor quando o GC responde (API ou WhatsApp)."""
    comp = (complemento or '').strip()
    sufixo = f"\n\n{comp}" if comp else ""
    os_txt = (os_num or 'O.S').strip()
    tipo = (tipo_solicitacao or 'antecipacao') or 'antecipacao'

    if resposta_gc == 'solicitado':
        if tipo == 'reparo':
            msg = (
                f"Olá! Sobre a *{os_txt}*: Sua solicitação de reparo foi tratada pelo GC e encaminhada para Vtal."
            )
        elif tipo == 'instalacao_fisica':
            msg = (
                f"Olá! Sobre a *{os_txt}*: Sua solicitação sobre *instalação física / pendência no sistema* "
                f"foi tratada pelo GC e encaminhada à Vtal."
            )
        else:
            msg = (
                f"Olá! Sobre a *{os_txt}*: Sua solicitação de antecipação foi tratada pelo GC e encaminhada para Vtal."
            )
        return msg + sufixo

    if resposta_gc == 'antecipada':
        if tipo == 'instalacao_fisica':
            msg = (
                f"Olá! Sobre a *{os_txt}*: O retorno do GC/Vtal confirma evolução favorável quanto à instalação física "
                f"/ pendência registrada."
            )
        else:
            msg = (
                f"Olá! Sobre a *{os_txt}*: Vtal conseguiu antecipar essa instalação para o período solicitado."
            )
        return msg + sufixo

    if resposta_gc == 'nao_antecipada':
        if tipo == 'instalacao_fisica':
            msg = (
                f"Olá! Sobre a *{os_txt}*: No momento não foi possível concluir a tratativa da instalação física "
                f"/ pendência (conforme retorno GC/Vtal)."
            )
        else:
            msg = (
                f"Olá! Sobre a *{os_txt}*: Vtal não tem espaço na agenda para antecipar este pedido."
            )
        return msg + sufixo
    return None


def _linhas_sem_citacao_whatsapp(msg):
    out = []
    for ln in (msg or '').replace('\r\n', '\n').split('\n'):
        t = ln.strip()
        if not t or t.startswith('>'):
            continue
        out.append(t)
    return out


def _resolver_resposta_gc_por_keyword(grupo2):
    g2 = (grupo2 or '').strip().lower()
    if 'solicitado' in g2:
        return 'solicitado'
    if 'nao' in g2 or 'não' in g2:
        return 'nao_antecipada'
    if 'antecipada' in g2:
        return 'antecipada'
    return None


def parse_mensagem_resposta_gc_antecipar(msg):
    """
    Extrai (dígitos da OS, código resposta_gc, complemento ao vendedor) ou None.
    Aceita resposta com citação, texto após ':' na mesma linha ou linhas seguintes.
    """
    if not (msg or '').strip():
        return None

    # Ordem: "não antecipada" antes de "antecipada" para não casar só o final da string.
    pat_virgula = re.compile(
        r'^(?:O\.?S\.?)?\s*(\d+)\s*[,]\s*((?:nao|não)\s*antecipada|antecipada|solicitado)'
        r'(?:\s*:\s*(.*))?$',
        re.IGNORECASE | re.DOTALL,
    )
    pat_espaco = re.compile(
        r'^(?:O\.?S\.?)?\s*(\d+)\s+((?:nao|não)\s*antecipada|antecipada|solicitado)'
        r'(?:\s*:\s*(.*))?$',
        re.IGNORECASE | re.DOTALL,
    )

    def _try_linha(linha, i, linhas, pat):
        m = pat.match(linha.strip())
        if not m:
            return None
        os_digits = m.group(1).strip()
        resposta_gc = _resolver_resposta_gc_por_keyword(m.group(2))
        if not resposta_gc:
            return None
        extra_same = (m.group(3) or '').strip()
        extra = extra_same
        if not extra and i + 1 < len(linhas):
            rest = []
            for j in range(i + 1, len(linhas)):
                if pat_virgula.match(linhas[j].strip()) or pat_espaco.match(linhas[j].strip()):
                    break
                rest.append(linhas[j])
            extra = '\n'.join(rest).strip()
        return os_digits, resposta_gc, extra

    linhas = _linhas_sem_citacao_whatsapp(msg)
    # Preferir a última linha que casa (resposta nova em conversas com citação)
    for i in range(len(linhas) - 1, -1, -1):
        linha = linhas[i].strip()
        for pat in (pat_virgula, pat_espaco):
            out = _try_linha(linha, i, linhas, pat)
            if out:
                return out

    return None


def buscar_solicitacao_gc_pendente_por_os(os_digits):
    """Localiza a solicitação mais recente ainda sem resposta GC, comparando O.S. só pelos dígitos."""
    from crm_app.models import AnteciparInstalacaoSolicitacao

    if not os_digits:
        return None
    alvo = normalizar_os_apenas_digitos(os_digits)
    if not alvo:
        return None

    qs = (
        AnteciparInstalacaoSolicitacao.objects.filter(resposta_gc__isnull=True)
        .select_related('venda', 'venda__vendedor')
        .order_by('-data_solicitacao')[:80]
    )
    for sol in qs:
        if normalizar_os_apenas_digitos(sol.ordem_servico) == alvo:
            return sol
    return None
