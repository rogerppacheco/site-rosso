# crm_app/historico_pap_service.py
"""Busca o histórico PAP (venda / interesse / pré-venda) com a sessão do usuário.

Ritmo igual à tela: 15 por página, pausa entre páginas. Não abre Detalhar.
Não grava Venda — só protocolos em HistoricoPapPedido.
"""
from __future__ import annotations

import base64
import json
import logging
import random
import re
import threading
import time
from datetime import date, datetime
from typing import Any, Optional, Tuple

import requests
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from crm_app.historico_pap import (
    LIMIT_PAGINA,
    MAX_DIAS_BUSCA,
    PAP_HISTORICO_URL,
    STATUS_LISTA_PADRAO,
    TIPO_API_ALIASES,
    extrair_lista_api,
    map_pedido_api,
    montar_url_vendas,
    montar_xlsx_historico,
    normalizar_pedido,
    parse_arquivo_exportacao,
    tipos_solicitados,
)

logger = logging.getLogger(__name__)

# Fallback em memória caso a tabela de cache (django_cache_table) não esteja inicializada
_IN_MEMORY_CACHE: dict[str, tuple[Any, float]] = {}


def _cache_get(key: str) -> Any:
    try:
        val = cache.get(key)
        if val is not None:
            return val
    except Exception:
        pass
    item = _IN_MEMORY_CACHE.get(key)
    if item:
        val, exp_ts = item
        if exp_ts > time.time():
            return val
        _IN_MEMORY_CACHE.pop(key, None)
    return None


def _cache_set(key: str, val: Any, timeout_seconds: int = 3600) -> None:
    exp_ts = time.time() + timeout_seconds
    _IN_MEMORY_CACHE[key] = (val, exp_ts)
    try:
        cache.set(key, val, timeout_seconds)
    except Exception:
        pass


def _cache_delete(key: str) -> None:
    _IN_MEMORY_CACHE.pop(key, None)
    try:
        cache.delete(key)
    except Exception:
        pass


def validar_e_decodificar_jwt(token: str) -> tuple[bool, Optional[dict], str]:
    """
    Valida formato de JWT e verifica se está expirado.
    Retorna (valido, payload_dict, motivo_ou_token_limpo).
    """
    if not token or not isinstance(token, str):
        return False, None, "Token vazio ou formato inválido."
    t = token.strip()
    if t.lower().startswith("bearer "):
        t = t[7:].strip()
    parts = t.split(".")
    if len(parts) != 3 or not parts[0].startswith("eyJ"):
        return False, None, "Token não possui estrutura de JWT válido (esperado eyJ...)."
    payload_b64 = parts[1]
    rem = len(payload_b64) % 4
    if rem > 0:
        payload_b64 += "=" * (4 - rem)
    try:
        decoded_bytes = base64.urlsafe_b64decode(payload_b64)
        payload = json.loads(decoded_bytes.decode("utf-8"))
    except Exception as exc:
        return False, None, f"Payload do JWT ilegível: {exc}"

    exp = payload.get("exp")
    if exp is not None:
        try:
            exp_ts = float(exp)
            agora = time.time()
            if exp_ts <= agora:
                dt_exp = datetime.fromtimestamp(exp_ts).strftime("%d/%m/%Y %H:%M:%S")
                return False, payload, f"Token expirado em {dt_exp}."
            if exp_ts - agora < 30:
                return False, payload, "Token expirando em menos de 30 segundos."
        except (ValueError, TypeError):
            pass
    return True, payload, t


def obter_token_cache(matricula: str) -> tuple[Optional[str], Optional[dict]]:
    """Obtém token em cache se ainda for válido e não expirado."""
    matricula_clean = (matricula or "").strip()
    keys_to_check = [f"pap_token_{matricula_clean}"] if matricula_clean else []
    keys_to_check.append("pap_token_global")
    for k in keys_to_check:
        tok = _cache_get(k)
        if tok:
            ok, payload, clean = validar_e_decodificar_jwt(tok)
            if ok:
                return clean, payload
            _cache_delete(k)
    return None, None


def salvar_token_cache(matricula: str, token: str, exp_ts: Optional[float] = None) -> None:
    """Salva token no cache com TTL baseado na expiração do JWT (máx 2 horas)."""
    ok, payload, clean = validar_e_decodificar_jwt(token)
    if not ok:
        return
    agora = time.time()
    exp = exp_ts or (payload.get("exp") if payload else None)
    if exp:
        ttl = max(60, int(float(exp) - agora - 60))
        ttl = min(ttl, 7200)
    else:
        ttl = 3600
    matricula_clean = (matricula or "").strip()
    if matricula_clean:
        _cache_set(f"pap_token_{matricula_clean}", clean, ttl)
    _cache_set("pap_token_global", clean, ttl)


def remover_token_cache(matricula: str) -> None:
    matricula_clean = (matricula or "").strip()
    if matricula_clean:
        _cache_delete(f"pap_token_{matricula_clean}")
    _cache_delete("pap_token_global")


def verificar_cooldown_login(matricula: str) -> tuple[bool, int]:
    """Retorna (esta_em_cooldown, segundos_restantes)."""
    matricula_clean = (matricula or "").strip()
    keys = [f"pap_cooldown_{matricula_clean}"] if matricula_clean else []
    keys.append("pap_cooldown_global")
    agora = time.time()
    for k in keys:
        until = _cache_get(k)
        if until:
            try:
                until_f = float(until)
                if until_f > agora:
                    return True, int(until_f - agora)
            except (ValueError, TypeError):
                pass
            _cache_delete(k)
    return False, 0


def registrar_cooldown_login(matricula: str, segundos: int = 900) -> None:
    """Ativa cooldown de login para evitar bloqueio por tentativas automáticas seguidas."""
    matricula_clean = (matricula or "").strip()
    until = time.time() + segundos
    if matricula_clean:
        _cache_set(f"pap_cooldown_{matricula_clean}", until, segundos)
    _cache_set("pap_cooldown_global", until, segundos)
    logger.warning("[HISTORICO PAP] Cooldown de login ativado por %s segundos para matrícula %s", segundos, matricula_clean)


def limpar_cooldown_login(matricula: str) -> None:
    matricula_clean = (matricula or "").strip()
    if matricula_clean:
        _cache_delete(f"pap_cooldown_{matricula_clean}")
    _cache_delete("pap_cooldown_global")


def obter_status_sessao_pap(matricula: str) -> dict:
    """Status resumido para a UI: token ativo, cooldown e expiração."""
    tok, payload = obter_token_cache(matricula)
    em_cooldown, seg_cooldown = verificar_cooldown_login(matricula)
    exp_min = 0
    if payload and payload.get("exp"):
        try:
            exp_min = max(0, int((float(payload["exp"]) - time.time()) // 60))
        except Exception:
            exp_min = 0
    return {
        "tem_token_valido": bool(tok),
        "expira_em_minutos": exp_min,
        "cooldown_ativo": em_cooldown,
        "cooldown_restante_minutos": max(1, seg_cooldown // 60) if em_cooldown else 0,
        "matricula": (matricula or "").strip(),
    }


# Extrai Bearer JWT do cookie/localStorage varrendo todas as chaves e Redux persist.
JS_TOKEN = """
() => {
  const cleanJwt = (s) => {
    if (!s || typeof s !== 'string') return '';
    const m = s.match(/eyJ[A-Za-z0-9_-]{10,}\\.[A-Za-z0-9_-]{10,}\\.[A-Za-z0-9_-]{10,}/);
    return m ? m[0] : '';
  };

  for (const store of [localStorage, sessionStorage]) {
    try {
      for (const key of ['token', 'accessToken', 'access_token', 'authToken', 'jwt', 'auth', 'user']) {
        const val = store.getItem(key);
        const jwt = cleanJwt(val);
        if (jwt) return jwt;
      }
      for (let i = 0; i < store.length; i++) {
        const k = store.key(i);
        const val = store.getItem(k);
        const jwt = cleanJwt(val);
        if (jwt) return jwt;

        if (val && (val.startsWith('{') || val.startsWith('['))) {
          const walk = (o, depth) => {
            if (!o || depth > 5) return '';
            if (typeof o === 'string') {
              const j = cleanJwt(o);
              if (j) return j;
              if (o.startsWith('{') || o.startsWith('[')) {
                try { return walk(JSON.parse(o), depth + 1); } catch (e) {}
              }
              return '';
            }
            if (typeof o === 'object') {
              for (const prop of Object.keys(o)) {
                const res = walk(o[prop], depth + 1);
                if (res) return res;
              }
            }
            return '';
          };
          try {
            const found = walk(JSON.parse(val), 0);
            if (found) return found;
          } catch (e) {}
        }
      }
    } catch (e) {}
  }

  try {
    const cookies = (document.cookie || '').split(';');
    for (const c of cookies) {
      const parts = c.trim().split('=');
      if (parts.length >= 2) {
        const val = decodeURIComponent(parts.slice(1).join('='));
        const jwt = cleanJwt(val);
        if (jwt) return jwt;
      }
    }
  } catch (e) {}

  return '';
}
"""

JS_FETCH = """
async (url) => {
  try {
    const raw = (document.cookie.split(';').map(c => c.trim()).find(c => c.startsWith('token=')) || '').slice(6);
    const headers = { Accept: 'application/json' };
    if (raw) {
      const t = decodeURIComponent(raw);
      headers.Authorization = t.startsWith('Bearer') ? t : ('Bearer ' + t);
    }
    const r = await fetch(url, { credentials: 'include', headers });
    const text = await r.text();
    let json = null;
    try { json = JSON.parse(text); } catch (e) {
      return { ok: false, status: r.status, error: 'parse', preview: text.slice(0, 280) };
    }
    return { ok: r.ok, status: r.status, json };
  } catch (e) {
    return { ok: false, status: 0, error: String((e && e.message) || e || 'fetch_failed') };
  }
}
"""


def _extrair_token(page) -> str:
    try:
        raw = page.evaluate(JS_TOKEN)
    except Exception as exc:
        logger.warning("[HISTORICO PAP] Não foi possível ler token da página: %s", exc)
        return ""
    return (raw or "").strip()


def _headers_auth(token: str) -> dict[str, str]:
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://pap.niointernet.com.br",
        "Referer": "https://pap.niointernet.com.br/administrativo/historico",
        "Origem": "BO",
    }
    if not token:
        return headers
    t = token.strip()
    if t.lower().startswith("bearer "):
        t = t[7:].strip()
    headers["Authorization"] = t
    return headers


def _fetch_json_http(url: str, headers: dict[str, str]) -> dict:
    try:
        resp = requests.get(url, headers=headers, timeout=60)
        status = resp.status_code
        text = resp.text
        try:
            json_body = resp.json()
        except Exception:
            json_body = None
            try:
                json_body = json.loads(text)
            except Exception:
                return {
                    "ok": False,
                    "status": status,
                    "error": "parse",
                    "preview": (text or "")[:280],
                }
        if status in (401, 403):
            logger.warning("[HISTORICO PAP] API HTTP %s — preview=%s", status, (text or "")[:180].replace("\n", " "))
        return {"ok": 200 <= status < 300, "status": status, "json": json_body}
    except Exception as exc:
        return {"ok": False, "status": 0, "error": f"requests: {exc}"}


def _fetch_json(page, url: str, token: str = "") -> dict:
    """
    Busca JSON da API do PAP.
    Prioriza fetch nativo no contexto Chromium da página (evita bloqueios de WAF TLS / CORS do F5).
    Fallback via context.request ou requests HTTP direto.
    """
    tok = (token or "").strip()
    if not tok and page:
        tok = _extrair_token(page)
    headers = _headers_auth(tok)

    # 1) Fetch nativo dentro da página Chromium aberta (imune a fingerprinting WAF)
    if page:
        try:
            auth_val = headers.get("Authorization", "")
            res = page.evaluate("""
            async ({ url, authVal }) => {
                try {
                    const hdrs = {
                        'Accept': 'application/json, text/plain, */*',
                        'Origem': 'BO'
                    };
                    if (authVal) {
                        hdrs['Authorization'] = authVal;
                    }
                    const r = await fetch(url, {
                        method: 'GET',
                        credentials: 'include',
                        headers: hdrs
                    });
                    const text = await r.text();
                    let json = null;
                    try { json = JSON.parse(text); } catch(e) {}
                    return { ok: r.ok, status: r.status, json: json, preview: text.slice(0, 280) };
                } catch(e) {
                    return { ok: false, status: 0, error: String((e && e.message) || e) };
                }
            }
            """, {"url": url, "authVal": auth_val})
            if isinstance(res, dict) and (res.get("ok") or res.get("status") in (401, 403, 404, 500)):
                if res.get("status") in (401, 403):
                    logger.warning(
                        "[HISTORICO PAP] API %s — preview=%s",
                        res.get("status"),
                        (res.get("preview") or "")[:180].replace("\n", " "),
                    )
                return res
        except Exception as exc:
            logger.warning("[HISTORICO PAP] fetch nativo browser falhou (%s); tentando context.request", exc)

    # 2) Fallback para APIRequestContext do Playwright
    if page:
        try:
            api = page.context.request
            resp = api.get(url, headers=headers, timeout=30000)
            status = resp.status
            text = resp.text()
            try:
                json_body = resp.json()
            except Exception:
                try:
                    json_body = json.loads(text)
                except Exception:
                    return {
                        "ok": False,
                        "status": status,
                        "error": "parse",
                        "preview": (text or "")[:280],
                    }
            if status in (401, 403):
                logger.warning(
                    "[HISTORICO PAP] API %s — preview=%s",
                    status,
                    (text or "")[:180].replace("\n", " "),
                )
            return {"ok": 200 <= status < 300, "status": status, "json": json_body}
        except Exception as exc:
            logger.warning("[HISTORICO PAP] context.request falhou (%s); tentando requests direto", exc)

    # 3) Fallback direto HTTP sem browser
    return _fetch_json_http(url, headers)


def _aguardar_token_spa(page, timeout_ms: int = 6000) -> str:
    """
    Vai ao Histórico e espera a própria SPA disparar chamada autenticada à API,
    ou extrai o token JWT das stores da página.
    """
    tok_imediato = _extrair_token(page)
    valido, _, clean = validar_e_decodificar_jwt(tok_imediato)
    if valido:
        logger.info("[HISTORICO PAP] Token JWT extraído imediatamente da sessão.")
        return clean

    captured: dict[str, str] = {"auth": ""}

    def _on_request(request):
        try:
            url = (request.url or "").lower()
            if "pap-api.niointernet.com.br" not in url:
                return
            auth = request.headers.get("authorization") or request.headers.get("Authorization") or ""
            if auth and len(auth) > 20:
                captured["auth"] = auth
        except Exception:
            pass

    page.on("request", _on_request)
    try:
        try:
            with page.expect_response(
                lambda r: "pap-api.niointernet.com.br" in (r.url or ""),
                timeout=timeout_ms,
            ) as ri:
                page.goto(PAP_HISTORICO_URL, wait_until="domcontentloaded", timeout=35000)
            try:
                resp = ri.value
                auth = resp.request.headers.get("authorization") or resp.request.headers.get("Authorization") or ""
                if auth:
                    captured["auth"] = auth
            except Exception:
                pass
        except Exception:
            try:
                page.goto(PAP_HISTORICO_URL, wait_until="domcontentloaded", timeout=35000)
            except Exception as exc2:
                logger.warning("[HISTORICO PAP] goto histórico: %s", exc2)

        page.wait_for_timeout(1000)

        if captured["auth"]:
            raw = captured["auth"]
            if raw.lower().startswith("bearer "):
                raw = raw[7:].strip()
            ok_cap, _, clean_cap = validar_e_decodificar_jwt(raw)
            if ok_cap:
                return clean_cap

        tok = _extrair_token(page)
        ok_t, _, clean_t = validar_e_decodificar_jwt(tok)
        return clean_t if ok_t else tok
    finally:
        try:
            page.remove_listener("request", _on_request)
        except Exception:
            pass


def _run_django_sync(func, timeout_seconds: int = 120):
    import queue

    import django.db

    q = queue.Queue()

    def worker():
        try:
            django.db.close_old_connections()
            q.put(("ok", func()))
        except Exception as e:
            q.put(("err", e))
        finally:
            django.db.close_old_connections()

    t = threading.Thread(target=worker, daemon=True, name="hist-pap-orm")
    t.start()
    t.join(timeout=timeout_seconds)
    if not q.empty():
        kind, payload = q.get()
        if kind == "err":
            raise payload
        return payload
    raise TimeoutError("django_sync_timeout")


def _intervalo() -> float:
    lo = float(getattr(settings, "HISTORICO_PAP_INTERVALO_MIN_SEG", 4))
    hi = float(getattr(settings, "HISTORICO_PAP_INTERVALO_MAX_SEG", 6))
    if hi < lo:
        hi = lo
    return random.uniform(lo, hi)


def _validar_credenciais(usuario) -> Tuple[bool, str]:
    matricula = (getattr(usuario, "matricula_pap", None) or "").strip()
    senha = (getattr(usuario, "senha_pap", None) or "").strip()
    if not matricula or not senha:
        return False, (
            "O login Diretoria selecionado não tem matrícula/senha PAP. "
            "Cadastre na Governança antes de buscar o histórico."
        )
    return True, matricula


def busca_em_andamento():
    from crm_app.models import HistoricoPapBusca

    return (
        HistoricoPapBusca.objects.filter(
            status__in=[
                HistoricoPapBusca.STATUS_PENDENTE,
                HistoricoPapBusca.STATUS_EM_ANDAMENTO,
            ]
        )
        .select_related("login_pap")
        .order_by("-iniciado_em")
        .first()
    )


def registrar_exportacao(usuario, nome: str, content: bytes) -> dict:
    from crm_app.models import HistoricoPapPedido

    pares = parse_arquivo_exportacao(nome, content)
    if not pares:
        raise ValueError("Não achei a coluna Pedido (protocolo) neste arquivo.")

    conhecidos = set(
        HistoricoPapPedido.objects.filter(
            numero_pedido__in=[p[0] for p in pares]
        ).values_list("numero_pedido", flat=True)
    )
    novos = 0
    objs = []
    for ped, tipo, payload in pares:
        if ped in conhecidos:
            continue
        conhecidos.add(ped)
        objs.append(
            HistoricoPapPedido(
                numero_pedido=ped,
                tipo_venda=tipo or HistoricoPapPedido.TIPO_VENDA,
                origem="exportacao",
                payload=payload if isinstance(payload, dict) else {"numeroPedido": ped},
                pdv="",
            )
        )
        novos += 1
        if len(objs) >= 500:
            HistoricoPapPedido.objects.bulk_create(objs, ignore_conflicts=True)
            objs = []
    if objs:
        HistoricoPapPedido.objects.bulk_create(objs, ignore_conflicts=True)
    return {
        "lidos": len(pares),
        "novos": novos,
        "ja_existiam": len(pares) - novos,
        "total_base": HistoricoPapPedido.objects.count(),
        "grava_venda": False,
    }


def serializar_busca(busca, *, em_andamento: bool) -> dict:
    login_user = getattr(busca, "login_pap", None)
    return {
        "id": busca.id,
        "status": busca.status,
        "em_andamento": em_andamento,
        "data_inicio": busca.data_inicio.isoformat() if busca.data_inicio else "",
        "data_fim": busca.data_fim.isoformat() if busca.data_fim else "",
        "pdv": busca.pdv or "",
        "tipos": busca.tipos or [],
        "encontrados": busca.encontrados,
        "novos": busca.novos,
        "ignorados": busca.ignorados,
        "por_tipo": busca.por_tipo or {},
        "mensagem": busca.mensagem or "",
        "grava_venda": False,
        "login_pap": getattr(login_user, "username", None) or "",
        "iniciado_em": busca.iniciado_em.isoformat() if busca.iniciado_em else "",
        "finalizado_em": busca.finalizado_em.isoformat() if busca.finalizado_em else "",
    }


def criar_e_iniciar_busca(
    usuario,
    *,
    data_inicio: date,
    data_fim: date,
    pdv: str,
    tipos: list[str],
    token_manual: str = "",
):
    from django.db import transaction

    from crm_app.models import HistoricoPapBusca
    from crm_app.pool_historico_pap import obter_login_historico_pap

    if data_fim < data_inicio:
        return None, "Data fim anterior à data início."
    if (data_fim - data_inicio).days > MAX_DIAS_BUSCA:
        return None, f"O intervalo máximo é {MAX_DIAS_BUSCA} dias."

    tipos_ok = tipos_solicitados(tipos)
    pdv = (pdv or "").strip()
    token_manual = (token_manual or "").strip()

    with transaction.atomic():
        login_pap, err_pool = obter_login_historico_pap()
        if err_pool:
            return None, err_pool

        ok, msg = _validar_credenciais(login_pap)
        if not ok and not token_manual:
            return None, msg

        busca = HistoricoPapBusca.objects.create(
            usuario=usuario,
            login_pap=login_pap,
            status=HistoricoPapBusca.STATUS_EM_ANDAMENTO,
            data_inicio=data_inicio,
            data_fim=data_fim,
            pdv=pdv,
            tipos=tipos_ok,
            mensagem=f"Usando login Diretoria: {login_pap.username}" + (" (Token manual)" if token_manual else ""),
            relatorio_json={"fase": "iniciando", "login_pap": login_pap.username, "token_manual": bool(token_manual)},
        )
        login_id = login_pap.id
        busca_id = busca.id

    t = threading.Thread(
        target=_runner,
        args=(busca_id, login_id, token_manual),
        name=f"hist-pap-{busca_id}",
        daemon=True,
    )
    t.start()
    return busca_id, None


def xlsx_novos_da_busca(busca_id: int) -> tuple[bytes, str]:
    from crm_app.models import HistoricoPapBusca, HistoricoPapPedido

    busca = HistoricoPapBusca.objects.get(pk=busca_id)
    numeros = [normalizar_pedido(n) for n in (busca.novos_numeros or [])]
    numeros = [n for n in numeros if n]
    linhas = []
    if numeros:
        qs = HistoricoPapPedido.objects.filter(numero_pedido__in=numeros)
        by_num = {p.numero_pedido: p for p in qs}
        for n in numeros:
            p = by_num.get(n)
            if not p:
                continue
            if p.payload:
                linhas.append(map_pedido_api(p.payload, p.tipo_venda))
            else:
                linhas.append({"tipo_venda": p.tipo_venda, "pedido": p.numero_pedido, "status": p.status})
    nome = f"Historico_PAP_{busca.data_inicio}_{busca.data_fim}.xlsx"
    return montar_xlsx_historico(linhas), nome


def _atualizar(busca_id: int, **kwargs):
    from crm_app.models import HistoricoPapBusca

    HistoricoPapBusca.objects.filter(pk=busca_id).update(**kwargs)


def _runner(busca_id: int, login_pap_id: int, token_manual: str = ""):
    import django.db

    django.db.close_old_connections()
    try:
        _executar_busca(busca_id, login_pap_id, token_manual=token_manual)
    except Exception as exc:
        logger.exception("[HISTORICO PAP] Falha no job %s", busca_id)
        msg = f"Falha ao buscar o histórico PAP: {exc}"[:500]
        try:
            _run_django_sync(
                lambda: _atualizar(
                    busca_id,
                    status="erro",
                    mensagem=msg,
                    finalizado_em=timezone.now(),
                )
            )
        except Exception:
            logger.exception("[HISTORICO PAP] Nem o status de erro pôde ser gravado.")
    finally:
        django.db.close_old_connections()


def _iso_inicio(d: date) -> str:
    return f"{d.isoformat()}T00:00:00-03:00"


def _iso_fim(d: date) -> str:
    return f"{d.isoformat()}T23:59:59-03:00"


def _pedido_conhecido(numero: str) -> bool:
    from crm_app.models import HistoricoPapPedido

    return HistoricoPapPedido.objects.filter(numero_pedido=numero).exists()


def _salvar_novo(numero: str, tipo: str, pdv: str, payload: dict) -> bool:
    from crm_app.models import HistoricoPapPedido

    if not numero:
        return False
    if HistoricoPapPedido.objects.filter(numero_pedido=numero).exists():
        return False
    data_criacao = None
    raw = payload.get("dataCriacao")
    if raw:
        try:
            data_criacao = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except Exception:
            data_criacao = None
    HistoricoPapPedido.objects.create(
        numero_pedido=numero,
        tipo_venda=tipo,
        pdv=pdv or "",
        status=str(payload.get("status") or payload.get("chaveStatusPrimario") or "")[:80],
        data_criacao_pap=data_criacao,
        origem="api",
        payload=payload,
    )
    return True


def _executar_loop_busca(page, *, busca_id: int, busca, token: str) -> tuple[bool, str]:
    encontrados = 0
    novos = 0
    ignorados = 0
    novos_numeros: list[str] = []
    por_tipo: dict[str, dict[str, int]] = {}

    data_ini = _iso_inicio(busca.data_inicio)
    data_fim = _iso_fim(busca.data_fim)
    pdv = busca.pdv
    tipos = list(busca.tipos or [])

    for tipo in tipos:
        if _job_cancelado(busca_id):
            break
        stats = _buscar_tipo(
            page,
            busca_id=busca_id,
            tipo=tipo,
            data_ini=data_ini,
            data_fim=data_fim,
            pdv=pdv,
            token=token,
        )
        if stats.get("erro_fatal"):
            msg_erro = str(stats.get("erro") or "Falha na API do PAP")
            _run_django_sync(
                lambda m=msg_erro: _atualizar(
                    busca_id,
                    status=HistoricoPapBusca.STATUS_ERRO,
                    mensagem=m[:500],
                    finalizado_em=timezone.now(),
                    por_tipo=por_tipo,
                )
            )
            return False, msg_erro

        por_tipo[tipo] = {
            "encontrados": stats["encontrados"],
            "novos": stats["novos"],
            "ignorados": stats["ignorados"],
            "tipo_api": stats.get("tipo_api") or tipo,
        }
        encontrados += stats["encontrados"]
        novos += stats["novos"]
        ignorados += stats["ignorados"]
        novos_numeros.extend(stats["novos_numeros"])
        _run_django_sync(
            lambda e=encontrados, n=novos, i=ignorados, pt=dict(por_tipo), nn=list(novos_numeros): _atualizar(
                busca_id,
                encontrados=e,
                novos=n,
                ignorados=i,
                por_tipo=pt,
                novos_numeros=nn,
                relatorio_json={"fase": f"tipo {tipo} ok"},
            )
        )

    status_final = (
        HistoricoPapBusca.STATUS_CANCELADO
        if _job_cancelado(busca_id)
        else HistoricoPapBusca.STATUS_CONCLUIDO
    )
    aviso = (
        "Nenhuma venda foi gravada. Pedidos já existentes na base (coluna Pedido) foram ignorados."
    )
    _run_django_sync(
        lambda: _atualizar(
            busca_id,
            status=status_final,
            encontrados=encontrados,
            novos=novos,
            ignorados=ignorados,
            por_tipo=por_tipo,
            novos_numeros=novos_numeros,
            mensagem=aviso,
            finalizado_em=timezone.now(),
            relatorio_json={"fase": "concluido", "por_tipo": por_tipo},
        )
    )
    return True, ""


def _executar_busca(busca_id: int, login_pap_id: int, token_manual: str = ""):
    from django.contrib.auth import get_user_model

    from crm_app.models import HistoricoPapBusca
    from crm_app.services_pap_nio import PAPNioAutomation

    User = get_user_model()
    login_pap = _run_django_sync(lambda: User.objects.get(pk=login_pap_id))
    busca = _run_django_sync(lambda: HistoricoPapBusca.objects.get(pk=busca_id))

    matricula = (getattr(login_pap, "matricula_pap", None) or "").strip()
    token = ""
    origem_token = ""

    # 1) Caso o usuário tenha informado Token Manual
    if token_manual:
        ok_jwt, pay_jwt, clean_jwt = validar_e_decodificar_jwt(token_manual)
        if not ok_jwt:
            msg_jwt = f"Token manual rejeitado: {clean_jwt}"
            _run_django_sync(
                lambda: _atualizar(
                    busca_id,
                    status=HistoricoPapBusca.STATUS_ERRO,
                    mensagem=msg_jwt,
                    finalizado_em=timezone.now(),
                )
            )
            return
        token = clean_jwt
        origem_token = "manual"
        salvar_token_cache(matricula, token, pay_jwt.get("exp") if pay_jwt else None)
        limpar_cooldown_login(matricula)
        logger.info("[HISTORICO PAP] Usando Token Manual fornecido pelo usuário.")

    # 2) Caso não tenha manual, verificar cache de token válido
    if not token:
        cached_tok, cached_pay = obter_token_cache(matricula)
        if cached_tok:
            token = cached_tok
            origem_token = "cache"
            logger.info("[HISTORICO PAP] Reutilizando Token PAP válido do cache.")

    # 3) Se já temos token válido (manual ou cache), rodar busca direta HTTP (sem Playwright)
    if token:
        logger.info("[HISTORICO PAP] Iniciando busca direta HTTP (sem Playwright, 0 risco de login)")
        sucesso, err_msg = _executar_loop_busca(
            page=None,
            busca_id=busca_id,
            busca=busca,
            token=token,
        )
        if sucesso:
            return
        # Se deu 401 com token em cache/manual, remove do cache
        remover_token_cache(matricula)
        if origem_token == "manual":
            _run_django_sync(
                lambda: _atualizar(
                    busca_id,
                    status=HistoricoPapBusca.STATUS_ERRO,
                    mensagem=f"{err_msg}. Verifique se o token manual copiado do PAP ainda é válido.",
                    finalizado_em=timezone.now(),
                )
            )
            return
        logger.warning("[HISTORICO PAP] Token em cache falhou (%s). Avaliando sessão no browser...", err_msg)

    # 4) Caso precise de sessão no browser: checar Circuit Breaker primeiro
    em_cooldown, seg_cooldown = verificar_cooldown_login(matricula)
    if em_cooldown:
        min_restantes = max(1, seg_cooldown // 60)
        msg_cd = (
            f"Cooldown de segurança ativo ({min_restantes} min restantes) para proteger "
            f"o usuário {login_pap.username} contra bloqueios de login na Nio. "
            f"Aguarde ou utilize a opção 'Usar token manual' no Funil para testar direto."
        )
        _run_django_sync(
            lambda: _atualizar(
                busca_id,
                status=HistoricoPapBusca.STATUS_ERRO,
                mensagem=msg_cd,
                finalizado_em=timezone.now(),
            )
        )
        return

    # 5) Browser Playwright com REÚSO ESTRITO de sessão salva (NÃO invalidar storage state)
    senha = (getattr(login_pap, "senha_pap", None) or "").strip()
    automacao = PAPNioAutomation(
        matricula_pap=matricula,
        senha_pap=senha,
        vendedor_nome=getattr(login_pap, "username", "Historico-PAP") or "Historico-PAP",
        headless=getattr(settings, "PAP_HEADLESS", True),
        capture_screenshots=False,
        optimize_for_credit=False,
    )
    try:
        ok, msg = automacao.iniciar_sessao()
        if not ok:
            # Login falhou ou travou: registrar cooldown para não insistir
            registrar_cooldown_login(matricula, 900)
            _run_django_sync(
                lambda: _atualizar(
                    busca_id,
                    status=HistoricoPapBusca.STATUS_ERRO,
                    mensagem=msg or "Falha ao logar no PAP. Cooldown anti-bloqueio ativado.",
                    finalizado_em=timezone.now(),
                )
            )
            return

        limpar_cooldown_login(matricula)
        page = automacao.page
        token = _aguardar_token_spa(page)
        if not token:
            registrar_cooldown_login(matricula, 600)
            _run_django_sync(
                lambda: _atualizar(
                    busca_id,
                    status=HistoricoPapBusca.STATUS_ERRO,
                    mensagem=(
                        "Login PAP ok, mas o token de API não foi localizado no navegador. "
                        "Para testar sem risco, copie o Bearer Token no PAP e cole no Funil."
                    ),
                    finalizado_em=timezone.now(),
                )
            )
            return

        # Salvar token no cache para próximas buscas
        ok_t, pay_t, limpo_t = validar_e_decodificar_jwt(token)
        salvar_token_cache(matricula, limpo_t if ok_t else token, pay_t.get("exp") if pay_t else None)

        # Executar busca com a página Playwright
        sucesso, err_msg = _executar_loop_busca(
            page=page,
            busca_id=busca_id,
            busca=busca,
            token=token,
        )
        if not sucesso and "401" in err_msg:
            # Se tomou 401 mesmo logado, ativar cooldown de segurança
            remover_token_cache(matricula)
            registrar_cooldown_login(matricula, 900)
    finally:
        try:
            automacao._fechar_sessao()
        except Exception:
            pass


def _job_cancelado(busca_id: int) -> bool:
    from crm_app.models import HistoricoPapBusca

    def _chk():
        st = HistoricoPapBusca.objects.filter(pk=busca_id).values_list("status", flat=True).first()
        return st == HistoricoPapBusca.STATUS_CANCELADO

    try:
        return bool(_run_django_sync(_chk))
    except Exception:
        return False


def _buscar_tipo(
    page, *, busca_id: int, tipo: str, data_ini: str, data_fim: str, pdv: str, token: str = ""
) -> dict:
    aliases = TIPO_API_ALIASES.get(tipo, (tipo,))
    last_err = ""
    for alias in aliases:
        if tipo == "PRE_VENDA":
            lista_status = ("PRE_VENDA", None)
        elif tipo in ("INTERESSE", "INTERESSE_SALVO"):
            lista_status = ("MINHAS_PENDENCIAS", None)
        else:
            lista_status = (STATUS_LISTA_PADRAO, None)

        for status in lista_status:
            url = montar_url_vendas(
                data_inicio=data_ini,
                data_fim=data_fim,
                pdv=pdv,
                tipo_api=alias,
                page=1,
                status=status,
            )
            resp = _fetch_json(page, url, token=token)
            if not isinstance(resp, dict):
                last_err = "resposta inválida"
                continue
            if not resp.get("ok"):
                last_err = f"HTTP {resp.get('status')} {resp.get('error') or ''}".strip()
                # 401/403: token/sessão inválidos — aborta todos os tipos
                if resp.get("status") in (401, 403):
                    return {
                        "encontrados": 0,
                        "novos": 0,
                        "ignorados": 0,
                        "novos_numeros": [],
                        "tipo_api": alias,
                        "erro": (
                            f"{last_err}. Sessão/token rejeitado pela API do PAP. "
                            "Não é bloqueio de login; verifique se a Ana abre o Histórico no PAP "
                            "e se a matrícula/senha estão corretas."
                        ),
                        "erro_fatal": True,
                    }
                continue
            lista, total = extrair_lista_api(resp.get("json"))
            if resp.get("status") == 200 and (lista is not None):
                # lista vazia com total 0 ainda é sucesso (período sem pedidos)
                return _paginar_tipo(
                    page,
                    busca_id=busca_id,
                    tipo=tipo,
                    tipo_api=alias,
                    data_ini=data_ini,
                    data_fim=data_fim,
                    pdv=pdv,
                    status=status,
                    primeira=lista or [],
                    total=total or 0,
                    token=token,
                )
        time.sleep(_intervalo())
    logger.warning("[HISTORICO PAP] Tipo %s não retornou dados (%s)", tipo, last_err)
    return {
        "encontrados": 0,
        "novos": 0,
        "ignorados": 0,
        "novos_numeros": [],
        "tipo_api": aliases[0],
        "erro": last_err,
    }


def _paginar_tipo(
    page,
    *,
    busca_id: int,
    tipo: str,
    tipo_api: str,
    data_ini: str,
    data_fim: str,
    pdv: str,
    status: Optional[str],
    primeira: list[dict],
    total: int,
    token: str = "",
) -> dict:
    encontrados = 0
    novos = 0
    ignorados = 0
    novos_numeros: list[str] = []
    paginas = max(1, (int(total or 0) + LIMIT_PAGINA - 1) // LIMIT_PAGINA) if total else 1
    paginas = min(paginas, 80)

    def _ingerir(lista: list[dict]):
        nonlocal encontrados, novos, ignorados
        for p in lista:
            ped = normalizar_pedido(p.get("numeroPedido") or p.get("pedido"))
            if not ped:
                continue
            encontrados += 1

            def _one():
                if _pedido_conhecido(ped):
                    return False
                return _salvar_novo(ped, tipo, pdv, p)

            if _run_django_sync(_one):
                novos += 1
                novos_numeros.append(ped)
            else:
                ignorados += 1

    _ingerir(primeira)
    for page_n in range(2, paginas + 1):
        if _job_cancelado(busca_id):
            break
        time.sleep(_intervalo())
        url = montar_url_vendas(
            data_inicio=data_ini,
            data_fim=data_fim,
            pdv=pdv,
            tipo_api=tipo_api,
            page=page_n,
            status=status,
        )
        resp = _fetch_json(page, url, token=token)
        if not isinstance(resp, dict) or not resp.get("ok"):
            logger.warning("[HISTORICO PAP] Falha página %s tipo %s: %s", page_n, tipo, resp)
            break
        lista, _ = extrair_lista_api(resp.get("json"))
        if not lista:
            break
        _ingerir(lista)
        _run_django_sync(
            lambda: _atualizar(
                busca_id,
                encontrados=encontrados,
                novos=novos,
                ignorados=ignorados,
                relatorio_json={"fase": f"{tipo} p.{page_n}/{paginas}"},
            )
        )
    return {
        "encontrados": encontrados,
        "novos": novos,
        "ignorados": ignorados,
        "novos_numeros": novos_numeros,
        "tipo_api": tipo_api,
    }
