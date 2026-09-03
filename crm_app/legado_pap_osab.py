# crm_app/legado_pap_osab.py
"""
Monta a planilha de Importar Vendas Históricas (modelo_v5) cruzando PAP × OSAB.

Segurança:
  - Não cria, atualiza nem apaga Venda/Cliente.
  - Só devolve DataFrames / bytes Excel para revisão e download.
  - A gravação no CRM continua exclusiva de ImportacaoLegadoView.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from io import BytesIO
from typing import Any

import pandas as pd

COLUNAS_MODELO = [
    "DATA_VENDA",
    "DATA_ABERTURA",
    "DATA_INSTALACAO",
    "LOGIN_VENDEDOR",
    "NOME_PLANO",
    "FORMA_PAGAMENTO",
    "OS",
    "STATUS_ESTEIRA",
    "STATUS_TRATAMENTO",
    "MOTIVO_PENDENCIA",
    "DATA_AGENDAMENTO",
    "PERIODO_AGENDAMENTO",
    "CPF_CNPJ_CLIENTE",
    "NOME_CLIENTE",
    "DATA_NASCIMENTO",
    "NOME_MAE",
    "TELEFONE_1",
    "TELEFONE_2",
    "EMAIL_CLIENTE",
    "CEP",
    "NUMERO",
    "COMPLEMENTO",
    "PONTO_REFERENCIA",
    "LOGRADOURO",
    "BAIRRO",
    "CIDADE",
    "UF",
    "OBSERVACOES",
]

SPEED_ORDER = ["500MB", "600MB", "700MB", "800MB", "1GB"]
PLANO_POR_VELOCIDADE = {
    "500MB": "NIO FIBRA ESSENCIAL 500MB",
    "600MB": "NIO FIBRA ESSENCIAL 600MB",
    "700MB": "NIO FIBRA SUPER 700MB",
    "800MB": "NIO FIBRA SUPER 800MB",
    "1GB": "NIO FIBRA ULTRA 1GB (SEM MESH)",
}
PLANO_1GB_MESH = "NIO FIBRA ULTRA 1GB"

STATUS_MAP = {
    "CONCLUIDO": "INSTALADA",
    "EXECUTADO": "INSTALADA",
    "PENDENCIA CLIENTE": "PENDENCIADA",
    "PENDENCIA TECNICA": "PENDENCIADA",
    "CANCELADO": "CANCELADA",
    "EM CANCELAMENTO": "CANCELADA",
    "AGENDADO": "AGENDADO",
    "EM APROVISIONAMENTO": "AGENDADO",
    "DRAFT": "PENDENCIADA",
    "AGUARDANDO PAGAMENTO": "PENDENCIADA",
}

PAP_COL_MAP = {
    "MES": "mes",
    "PEDIDO": "pedido_pap",
    "DATA DO PEDIDO": "data_pedido",
    "STATUS": "status_pap",
    "MATRICULA VENDEDOR": "matricula",
    "VENDEDOR": "vendedor",
    "CLIENTE": "cliente",
    "CPF": "cpf",
    "DATA DE NASCIMENTO": "data_nascimento",
    "NOME DA MAE": "nome_mae",
    "E-MAIL": "email",
    "EMAIL": "email",
    "E MAIL": "email",
    "CELULAR PRINCIPAL": "tel1",
    "CELULAR 2": "tel2",
    "CEP": "cep",
    "LOGRADOURO": "logradouro",
    "NUMERO": "numero",
    "COMPLEMENTO": "complemento",
    "BAIRRO": "bairro",
    "CIDADE": "cidade",
    "UF": "uf",
    "PONTO DE REFERENCIA": "ponto_referencia",
    "PLANO": "plano_pap",
    "VELOCIDADE": "velocidade_pap",
    "FORMA DE PAGAMENTO": "pagamento_pap",
    "PREFERENCIA INSTALACAO (DATA)": "pref_data",
    "PREFERENCIA INSTALACAO (PERIODO)": "pref_periodo",
    "PREFERENCIA INSTALACAO DATA": "pref_data",
    "PREFERENCIA INSTALACAO PERIODO": "pref_periodo",
    "OS INSTALACAO": "os_pap",
    "DATA INSTALACAO": "data_inst_pap",
    "PERIODO INSTALACAO": "periodo_inst_pap",
    "OBSERVACAO VENDEDOR": "obs_vend",
    "OBSERVACAO OPERADOR": "obs_op",
}

MAX_UPLOAD_BYTES = 30 * 1024 * 1024
MAX_OSAB_FILES = 8
ALLOWED_EXT = {".xlsx", ".xls", ".xlsb"}

PARCEIRO_DEFAULT_POR_MARCA = {
    "CLICKUP": ("IGOR CRISTIANO", "1069321"),
    "CLICK": ("IGOR CRISTIANO", "1069321"),
    "ROSSO": ("ROSSO TELECOM", "1009270"),
    "RECORD": ("RECORD", "1068561"),
    "VELOX": ("NOVA VELOX", "1069324"),
    "FUTURA": ("NOVA VELOX", "1069324"),
}


def strip_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFD", str(text))
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")


def norm_key(val) -> str:
    return re.sub(r"\s+", " ", strip_accents(str(val or "")).upper().strip())


def blank(val) -> bool:
    if val is None:
        return True
    if isinstance(val, float) and pd.isna(val):
        return True
    s = str(val).strip()
    return s == "" or s.lower() in ("nan", "none", "nat", "<na>")


def as_text(val) -> str:
    if blank(val):
        return ""
    s = str(val).strip()
    if s.endswith(".0") and s[:-2].replace("-", "").isdigit():
        s = s[:-2]
    return s


def digits(val) -> str:
    return re.sub(r"\D", "", as_text(val))


def upper_txt(val) -> str:
    if blank(val):
        return ""
    return as_text(val).upper()


def normalize_os(val) -> str:
    d = digits(val)
    return d if d else ""


def os_variants(val) -> list[str]:
    s = normalize_os(val)
    if not s:
        return []
    out = {s, s.lstrip("0") or s}
    if len(s) == 7:
        out.add("1" + s)
        out.add(s.zfill(8))
    if len(s) == 8 and s.startswith("0"):
        out.add("1" + s[1:])
        out.add(s.lstrip("0"))
    return [x for x in out if x]


def smart_datetime(val):
    if blank(val):
        return None
    if isinstance(val, pd.Timestamp):
        if pd.isna(val):
            return None
        return val.to_pydatetime()
    if isinstance(val, datetime):
        return val
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        try:
            f = float(val)
            if 20000 < f < 80000:
                dt = pd.Timestamp("1899-12-30") + pd.Timedelta(days=f)
                if pd.isna(dt):
                    return None
                return dt.to_pydatetime()
        except Exception:
            return None
    s = as_text(val)
    try:
        f = float(s.replace(",", "."))
        if 20000 < f < 80000:
            dt = pd.Timestamp("1899-12-30") + pd.Timedelta(days=f)
            if pd.isna(dt):
                return None
            return dt.to_pydatetime()
    except Exception:
        pass
    dt = pd.to_datetime(s, errors="coerce")
    if pd.isna(dt):
        dt = pd.to_datetime(s, dayfirst=True, errors="coerce")
    if pd.isna(dt):
        return None
    return dt.to_pydatetime()


def fmt_date(val) -> str:
    dt = smart_datetime(val)
    if not dt:
        return ""
    try:
        return dt.strftime("%d/%m/%Y")
    except (ValueError, AttributeError):
        return ""


def fmt_datetime(val) -> str:
    dt = smart_datetime(val)
    if not dt:
        return ""
    try:
        if dt.hour or dt.minute or dt.second:
            return dt.strftime("%d/%m/%Y %H:%M")
        return dt.strftime("%d/%m/%Y 00:00")
    except (ValueError, AttributeError):
        return ""


def map_pagamento(*vals) -> str:
    for val in vals:
        mp = strip_accents(as_text(val)).upper()
        if not mp:
            continue
        if "BOLETO" in mp:
            return "BOLETO"
        if "CART" in mp or "CREDIT" in mp:
            return "CARTÃO DE CRÉDITO"
        if "DEBIT" in mp:
            return "DÉBITO EM CONTA"
    return ""


def speed_from_osab(val) -> str | None:
    if blank(val):
        return None
    upper = strip_accents(as_text(val)).upper()
    upper = upper.replace("GIGA", "GB").replace("MEGA", "MB")
    for speed in SPEED_ORDER:
        if speed == upper or speed in upper:
            return speed
    match = re.search(r"(\d+)\s*(GB|MB)", upper)
    if match:
        return f"{match.group(1)}{match.group(2)}"
    return None


def has_mesh_oferta(oferta) -> bool:
    if blank(oferta):
        return False
    upper = as_text(oferta).upper()
    if "FIBRAX_MESH" in upper:
        return True
    if "MESH" in upper and "SEM MESH" not in upper:
        return True
    return False


def plano_por_velocidade(velocidade, campanha, plano_pap="") -> str:
    speed = speed_from_osab(velocidade) or speed_from_osab(plano_pap)
    if not speed:
        return upper_txt(plano_pap)
    if speed == "1GB":
        if has_mesh_oferta(campanha):
            return PLANO_1GB_MESH
        return PLANO_POR_VELOCIDADE["1GB"]
    return PLANO_POR_VELOCIDADE.get(speed, upper_txt(plano_pap))


def map_status_esteira(situacao, data_agendamento) -> str:
    raw = strip_accents(as_text(situacao)).upper()
    if not raw:
        return "PENDENCIADA"
    if "PAYMENT_NOT_AUTHORIZED" in raw or "REPROVADO" in raw:
        return "PENDENCIADA"
    if raw.startswith("DRAFT"):
        return "PENDENCIADA"
    if raw == "EM APROVISIONAMENTO":
        return "AGENDADO" if fmt_date(data_agendamento) else "PENDENCIADA"
    if raw in STATUS_MAP:
        return STATUS_MAP[raw]
    if raw.startswith("CONCLU"):
        return "INSTALADA"
    if "PENDEN" in raw:
        return "PENDENCIADA"
    if "CANCEL" in raw:
        return "CANCELADA"
    if "AGEND" in raw:
        return "AGENDADO"
    return "PENDENCIADA"


def map_status_tratamento(esteira: str) -> str:
    if esteira == "INSTALADA":
        return "CADASTRADA"
    if esteira == "CANCELADA":
        return "FECHADO"
    return "SEM TRATAMENTO"


def map_periodo(*vals) -> str:
    for val in vals:
        v = strip_accents(as_text(val)).upper()
        if not v:
            continue
        if "MANH" in v:
            return "MANHÃ"
        if "TARDE" in v:
            return "TARDE"
        if "NOITE" in v:
            return "NOITE"
    return ""


def cpf_limpo(val) -> str:
    d = digits(val)
    if not d:
        return ""
    if len(d) < 11:
        d = d.zfill(11)
    return d if len(d) in (11, 14) else d


def cep_limpo(val) -> str:
    d = digits(val)
    return d[:8] if len(d) >= 8 else d


def tel_limpo(val) -> str:
    d = digits(val)
    return d[-11:] if len(d) > 11 else d


def default_parceiro_por_marca(marca: str) -> tuple[str, str]:
    raw = strip_accents(marca or "").upper()
    for key, pair in PARCEIRO_DEFAULT_POR_MARCA.items():
        if key in raw:
            return pair
    return ("", "")


def is_parceiro_row(row: pd.Series, parceiro: str, pdv_sap: str = "") -> bool:
    alvo = strip_accents(parceiro or "").upper().strip()
    pdv = digits(pdv_sap)
    if pdv:
        for col in ("PDV_SAP", "cd_rede", "CD_REDE"):
            if col in row.index and digits(row.get(col)) == pdv:
                return True
    if not alvo:
        return False
    for col in ("DESCRICAO", "nm_pdv_rel", "NM_PDV_REL"):
        if col in row.index and alvo in strip_accents(as_text(row.get(col))).upper():
            return True
    return False


def pick_sheet(sheets: dict[str, pd.DataFrame], prefer: tuple[str, ...]) -> pd.DataFrame:
    for name in prefer:
        if name in sheets and sheets[name] is not None and len(sheets[name].columns) > 0:
            return sheets[name]
    for df in sheets.values():
        if df is not None and len(df.columns) > 0:
            return df
    raise ValueError("Nenhuma aba válida no arquivo.")


def rename_pap(df: pd.DataFrame) -> pd.DataFrame:
    rename = {}
    for col in df.columns:
        key = re.sub(r"[^A-Z0-9]+", " ", norm_key(col)).strip()
        key = re.sub(r"\s+", " ", key)
        if key in PAP_COL_MAP:
            rename[col] = PAP_COL_MAP[key]
    return df.rename(columns=rename)


def preparar_pap(df: pd.DataFrame) -> pd.DataFrame:
    out = rename_pap(df.copy())
    missing = [c for c in ("pedido_pap", "cpf", "cliente") if c not in out.columns]
    if missing:
        raise ValueError(
            "Planilha PAP sem colunas obrigatórias "
            f"({', '.join(missing)}). Use o histórico PAP com Cliente, CPF e Pedido."
        )
    if "os_pap" not in out.columns:
        out["os_pap"] = ""
    if "status_pap" not in out.columns:
        out["status_pap"] = "Pedido Gerado"
    out["_os_raw"] = out["os_pap"].map(normalize_os)
    out["_pedido_pap"] = out["pedido_pap"].map(as_text)
    if "data_pedido" in out.columns:
        out["_dt_pap"] = out["data_pedido"].apply(smart_datetime)
    else:
        out["_dt_pap"] = pd.NaT
    return out


def preparar_osab(df: pd.DataFrame, fonte: str, parceiro: str, pdv_sap: str) -> pd.DataFrame:
    out = df.copy()
    out["_fonte"] = fonte
    if out.empty:
        return out
    mask = out.apply(lambda row: is_parceiro_row(row, parceiro, pdv_sap), axis=1)
    out = out[mask].copy()
    if out.empty:
        return out
    if "PEDIDO" not in out.columns:
        raise ValueError(f"OSAB ({fonte}) sem coluna PEDIDO.")
    out["_pedido"] = out["PEDIDO"].map(normalize_os)
    out["_dt_ref"] = out["DT_REF"].apply(smart_datetime) if "DT_REF" in out.columns else None
    out["_dt_ab"] = out["DATA_ABERTURA"].apply(smart_datetime) if "DATA_ABERTURA" in out.columns else None
    out = out[out["_pedido"] != ""]
    return out


def match_os(os_raw: str, idx: dict[str, str]) -> str:
    for v in os_variants(os_raw):
        if v in idx:
            return idx[v]
    return ""


def _linha_legado(pap: pd.Series, osab: pd.Series, parceiro: str) -> dict:
    out = {col: "" for col in COLUNAS_MODELO}
    dt_venda = pap.get("data_pedido")
    dt_ab = osab.get("DATA_ABERTURA")
    dt_fech = osab.get("DATA_FECHAMENTO")
    dt_ag = osab.get("DATA_AGENDAMENTO")
    dt_inst_pap = pap.get("data_inst_pap")
    dt_pref = pap.get("pref_data")
    situacao = osab.get("SITUACAO")

    os_val = normalize_os(osab.get("PEDIDO")) or normalize_os(pap.get("os_pap"))
    out["OS"] = os_val
    out["DATA_VENDA"] = fmt_date(dt_venda) or fmt_date(dt_ab)
    out["DATA_ABERTURA"] = fmt_datetime(dt_ab) or fmt_datetime(dt_venda)

    esteira = map_status_esteira(situacao, dt_ag)
    if esteira == "INSTALADA":
        out["DATA_INSTALACAO"] = (
            fmt_date(dt_fech) or fmt_date(dt_inst_pap) or fmt_date(dt_ab) or fmt_date(dt_venda)
        )
    else:
        out["DATA_INSTALACAO"] = fmt_date(dt_fech)

    out["DATA_AGENDAMENTO"] = fmt_date(dt_ag) or fmt_date(dt_pref)
    out["PERIODO_AGENDAMENTO"] = map_periodo(pap.get("periodo_inst_pap"), pap.get("pref_periodo"))
    out["LOGIN_VENDEDOR"] = upper_txt(pap.get("matricula")) or upper_txt(osab.get("MATRICULA_VENDEDOR"))

    vel = osab.get("VELOCIDADE") if "VELOCIDADE" in osab.index else pap.get("velocidade_pap")
    camp = osab.get("CAMPANHA") if "CAMPANHA" in osab.index else ""
    out["NOME_PLANO"] = upper_txt(plano_por_velocidade(vel, camp, pap.get("plano_pap")))
    out["FORMA_PAGAMENTO"] = map_pagamento(osab.get("meio_pagamento") if "meio_pagamento" in osab.index else "", pap.get("pagamento_pap"))
    if not out["FORMA_PAGAMENTO"]:
        out["FORMA_PAGAMENTO"] = map_pagamento(osab.get("MEIO_PAGAMENTO") if "MEIO_PAGAMENTO" in osab.index else "")

    out["STATUS_ESTEIRA"] = esteira
    out["STATUS_TRATAMENTO"] = map_status_tratamento(esteira)
    if esteira == "PENDENCIADA":
        motivo = (
            as_text(osab.get("DESC_PENDENCIA"))
            or as_text(osab.get("desc_motivo_ordem"))
            or as_text(situacao)
        )
        if motivo and strip_accents(motivo).upper() not in ("OK", "NAN", "NONE"):
            out["MOTIVO_PENDENCIA"] = upper_txt(motivo)

    out["CPF_CNPJ_CLIENTE"] = cpf_limpo(pap.get("cpf"))
    out["NOME_CLIENTE"] = upper_txt(pap.get("cliente"))
    out["DATA_NASCIMENTO"] = fmt_date(pap.get("data_nascimento"))
    out["NOME_MAE"] = upper_txt(pap.get("nome_mae"))
    out["TELEFONE_1"] = tel_limpo(pap.get("tel1"))
    out["TELEFONE_2"] = tel_limpo(pap.get("tel2"))
    out["EMAIL_CLIENTE"] = upper_txt(pap.get("email"))
    out["CEP"] = cep_limpo(pap.get("cep"))
    out["NUMERO"] = upper_txt(pap.get("numero"))
    out["COMPLEMENTO"] = upper_txt(pap.get("complemento"))
    out["PONTO_REFERENCIA"] = upper_txt(pap.get("ponto_referencia"))
    out["LOGRADOURO"] = upper_txt(pap.get("logradouro"))
    cidade_osab = upper_txt(osab.get("LOCALIDADE")) if "LOCALIDADE" in osab.index else ""
    uf_osab = upper_txt(osab.get("UF")) if "UF" in osab.index else ""
    out["CIDADE"] = cidade_osab or upper_txt(pap.get("cidade"))
    out["UF"] = (uf_osab or upper_txt(pap.get("uf")))[:2]
    out["BAIRRO"] = upper_txt(pap.get("bairro"))

    obs_bits = [
        f"IMPORTAÇÃO LEGADO {upper_txt(parceiro)}".strip(),
        f"PEDIDO PAP {as_text(pap.get('pedido_pap'))}" if as_text(pap.get("pedido_pap")) else "",
        f"VENDEDOR {upper_txt(pap.get('vendedor'))}" if as_text(pap.get("vendedor")) else "",
        f"OSAB {upper_txt(situacao)}" if as_text(situacao) else "",
        upper_txt(pap.get("obs_vend")),
        upper_txt(pap.get("obs_op")),
    ]
    out["OBSERVACOES"] = " | ".join(b for b in obs_bits if b)[:500]
    return out


def _upper_text_cols(df: pd.DataFrame) -> pd.DataFrame:
    skip = {"CPF_CNPJ_CLIENTE", "TELEFONE_1", "TELEFONE_2", "CEP", "OS", "NUMERO"}
    out = df.copy()
    for col in COLUNAS_MODELO:
        if col in skip or col.startswith("DATA_"):
            continue
        out[col] = out[col].map(lambda v: "" if blank(v) else str(v).upper())
    return out


def cruzar_pap_osab(
    pap_df: pd.DataFrame,
    osab_frames: list[tuple[str, pd.DataFrame]],
    parceiro: str,
    pdv_sap: str = "",
    somente_instalada: bool = False,
) -> dict[str, Any]:
    """
    Cruza PAP (Pedido Gerado) com OSAB do parceiro.
    Retorna dataframes e métricas. Não grava no banco.
    """
    parceiro = as_text(parceiro)
    if not parceiro and not digits(pdv_sap):
        raise ValueError("Informe o nome do parceiro (DESCRICAO OSAB) ou o PDV SAP.")

    pap = preparar_pap(pap_df)
    status_ok = pap["status_pap"].map(lambda v: "GERADO" in strip_accents(as_text(v)).upper())
    pap_vendas = pap[status_ok].copy()
    if pap_vendas.empty:
        pap_vendas = pap.copy()

    fonte_stats = []
    osab_parts = []
    for fonte, raw in osab_frames:
        filtrado = preparar_osab(raw, fonte, parceiro, pdv_sap)
        fonte_stats.append({"fonte": fonte, "total": int(len(raw)), "parceiro": int(len(filtrado))})
        osab_parts.append(filtrado)

    osab = pd.concat(osab_parts, ignore_index=True) if osab_parts else pd.DataFrame()
    if osab.empty:
        osab = pd.DataFrame(columns=["_pedido"])
        osab["_pedido"] = []

    if len(osab):
        sort_cols = [c for c in ["_pedido", "_dt_ref", "_dt_ab"] if c in osab.columns]
        osab = osab.sort_values(sort_cols, ascending=[True] + [False] * (len(sort_cols) - 1))
        osab = osab.drop_duplicates(subset=["_pedido"], keep="first")

    idx: dict[str, str] = {}
    for _, row in osab.iterrows():
        for v in os_variants(row["_pedido"]):
            idx.setdefault(v, row["_pedido"])

    pap_vendas = pap_vendas.copy()
    pap_vendas["_os_match"] = pap_vendas["_os_raw"].map(lambda v: match_os(v, idx))
    matched = pap_vendas[pap_vendas["_os_match"] != ""].copy()
    unmatched = pap_vendas[pap_vendas["_os_match"] == ""].copy()
    if len(matched):
        matched = matched.sort_values(["_os_match", "_dt_pap"], ascending=[True, False])
        matched = matched.drop_duplicates(subset=["_os_match"], keep="first")

    osab_by = {r["_pedido"]: r for _, r in osab.iterrows()} if len(osab) else {}
    rows = []
    for _, prow in matched.iterrows():
        rows.append(_linha_legado(prow, osab_by[prow["_os_match"]], parceiro))

    df_legado = pd.DataFrame(rows, columns=COLUNAS_MODELO)
    if len(df_legado):
        df_legado = _upper_text_cols(df_legado)
        sem_cpf = df_legado["CPF_CNPJ_CLIENTE"].map(lambda v: len(digits(v)) < 11)
        df_sem_cpf = df_legado[sem_cpf].copy()
        df_legado = df_legado[~sem_cpf].copy()
    else:
        df_sem_cpf = df_legado.copy()

    df_instaladas = df_legado[df_legado["STATUS_ESTEIRA"] == "INSTALADA"].copy() if len(df_legado) else df_legado
    df_outros = df_legado[df_legado["STATUS_ESTEIRA"] != "INSTALADA"].copy() if len(df_legado) else df_legado
    modelo = df_instaladas if somente_instalada else df_legado

    osab_sem_pap = osab[~osab["_pedido"].isin(set(matched["_os_match"]))] if len(osab) else osab

    resumo = {
        "parceiro": upper_txt(parceiro),
        "pdv_sap": digits(pdv_sap),
        "somente_instalada": bool(somente_instalada),
        "grava_venda": False,
        "osab_fontes": fonte_stats,
        "pap_pedido_gerado": int(len(pap_vendas)),
        "osab_parceiro_dedup": int(len(osab)),
        "cruzados": int(len(matched)),
        "modelo_legado": int(len(modelo)),
        "instalada": int(len(df_instaladas)),
        "cancelada": int((df_legado["STATUS_ESTEIRA"] == "CANCELADA").sum()) if len(df_legado) else 0,
        "pendenciada": int((df_legado["STATUS_ESTEIRA"] == "PENDENCIADA").sum()) if len(df_legado) else 0,
        "agendado": int((df_legado["STATUS_ESTEIRA"] == "AGENDADO").sum()) if len(df_legado) else 0,
        "pap_sem_osab": int(len(unmatched)),
        "osab_sem_pap": int(len(osab_sem_pap)),
        "cpf_invalido": int(len(df_sem_cpf)),
    }
    return {
        "modelo": modelo.reset_index(drop=True),
        "todos": df_legado.reset_index(drop=True),
        "outros": df_outros.reset_index(drop=True),
        "resumo": resumo,
    }


def montar_xlsx(resultado: dict[str, Any]) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        resultado["modelo"].to_excel(writer, index=False, sheet_name="Modelo Legado")
        pd.DataFrame([resultado["resumo"]]).to_excel(writer, index=False, sheet_name="Resumo")
        if len(resultado["outros"]) and not resultado["resumo"].get("somente_instalada"):
            resultado["outros"].to_excel(writer, index=False, sheet_name="Outros status")
        elif resultado["resumo"].get("somente_instalada") and len(resultado["outros"]):
            resultado["outros"].to_excel(writer, index=False, sheet_name="Outros status")
    output.seek(0)
    return output.getvalue()


def validar_upload(nome: str, tamanho: int) -> None:
    ext = ""
    lower = (nome or "").lower()
    for cand in ALLOWED_EXT:
        if lower.endswith(cand):
            ext = cand
            break
    if not ext:
        raise ValueError("Use Excel .xlsx, .xls ou .xlsb.")
    if tamanho > MAX_UPLOAD_BYTES:
        raise ValueError(f"Arquivo maior que {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")


def ler_excel_bytes(nome: str, content: bytes) -> dict[str, pd.DataFrame]:
    bio = BytesIO(content)
    lower = (nome or "").lower()
    engine = "pyxlsb" if lower.endswith(".xlsb") else None
    kwargs = {"dtype": str, "sheet_name": None}
    if engine:
        kwargs["engine"] = engine
    sheets = pd.read_excel(bio, **kwargs)
    if isinstance(sheets, pd.DataFrame):
        return {"Planilha": sheets}
    return {str(k): v for k, v in sheets.items()}
