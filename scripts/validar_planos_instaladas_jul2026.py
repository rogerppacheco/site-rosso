"""Valida planos das vendas INSTALADA (jul/2026) cruzando CRM x OSAB."""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

SRC = Path(r"c:\Users\rogge\Downloads\Base_Vendas_Filtrada_20260802_1940.xlsx")
OUT = Path(r"c:\Users\rogge\Downloads\Correcao_Planos_Instaladas_Jul2026.xlsx")

SPEED_ORDER = ["500MB", "600MB", "700MB", "800MB", "1GB"]

PLANO_POR_VELOCIDADE = {
    "500MB": "NIO FIBRA ESSENCIAL 500MB",
    "600MB": "NIO FIBRA ESSENCIAL 600MB",
    "700MB": "NIO FIBRA SUPER 700MB",
    "800MB": "NIO FIBRA SUPER 800MB",
    "1GB": "NIO FIBRA ULTRA 1GB (SEM MESH)",
}
PLANO_1GB_MESH = "NIO FIBRA ULTRA 1GB"


def speed_from_plano(nome: object) -> str | None:
    if pd.isna(nome) or str(nome).strip() in ("", "-"):
        return None
    upper = str(nome).upper()
    for speed in SPEED_ORDER:
        if speed in upper:
            return speed
    return None


def speed_from_osab(val: object) -> str | None:
    if pd.isna(val):
        return None
    upper = str(val).strip().upper()
    if upper in ("", "-", "NAN", "NONE"):
        return None
    for speed in SPEED_ORDER:
        if speed == upper or speed in upper:
            return speed
    match = re.search(r"(\d+)\s*(GB|MB)", upper)
    if match:
        number, unit = int(match.group(1)), match.group(2)
        return f"{number}{unit}"
    return upper


def has_mesh_oferta(oferta: object) -> bool:
    if pd.isna(oferta):
        return False
    upper = str(oferta).upper()
    if "FIBRAX_MESH" in upper:
        return True
    if "MESH" in upper and "SEM MESH" not in upper:
        return True
    return False


def crm_tem_mesh(plano: object) -> bool | None:
    if pd.isna(plano):
        return None
    upper = str(plano).upper()
    if "SEM MESH" in upper:
        return False
    if "MESH" in upper:
        return True
    # Cadastro "ULTRA 1GB" sem sufixo = variante com mesh
    if "1GB" in upper and "ULTRA" in upper:
        return True
    return None


def plano_sugerido(speed_osab: str | None, oferta: object) -> str | None:
    if not speed_osab:
        return None
    if speed_osab == "1GB":
        return PLANO_1GB_MESH if has_mesh_oferta(oferta) else PLANO_POR_VELOCIDADE["1GB"]
    return PLANO_POR_VELOCIDADE.get(speed_osab)


def motivo_linha(row: pd.Series) -> str:
    if pd.isna(row["velocidade_osab"]):
        return "SEM PLANO OSAB"
    if row["velocidade_crm"] != row["velocidade_osab"]:
        return "VELOCIDADE DIVERGENTE"
    if (
        row["velocidade_osab"] == "1GB"
        and row["mesh_crm"] is not None
        and row["mesh_osab"] is not None
        and row["mesh_crm"] != row["mesh_osab"]
    ):
        return "MESH DIVERGENTE (1GB)"
    if str(row["Plano"]).strip() != str(row["plano_correto"]).strip():
        return "NOME/VARIANTE DIFERENTE"
    return "OK"


def main() -> None:
    df = pd.read_excel(SRC)
    df = df.rename(
        columns={
            df.columns[1]: "Reemissao",
            df.columns[2]: "Data Criacao",
            df.columns[3]: "Data Abertura (OS)",
            df.columns[22]: "Validacao OSAB",
            df.columns[25]: "Data Instalacao",
            df.columns[26]: "Data Fisica",
            df.columns[28]: "Adiantamento Comissao",
            df.columns[32]: "Motivo Pendencia",
            df.columns[33]: "Observacoes",
            df.columns[36]: "Numero",
        }
    )

    inst = df[df["Status Esteira"] == "INSTALADA"].copy()
    inst["dt_inst"] = pd.to_datetime(inst["Data Instalacao"], dayfirst=True, errors="coerce")
    jul = inst[(inst["dt_inst"].dt.year == 2026) & (inst["dt_inst"].dt.month == 7)].copy()

    jul["velocidade_crm"] = jul["Plano"].map(speed_from_plano)
    jul["velocidade_osab"] = jul["Plano OSAB"].map(speed_from_osab)
    jul["mesh_osab"] = jul.apply(
        lambda r: has_mesh_oferta(r["Oferta"]) if r["velocidade_osab"] == "1GB" else None,
        axis=1,
    )
    jul["mesh_crm"] = jul["Plano"].map(crm_tem_mesh)
    jul["plano_correto"] = jul.apply(
        lambda r: plano_sugerido(r["velocidade_osab"], r["Oferta"]),
        axis=1,
    )
    jul["motivo"] = jul.apply(motivo_linha, axis=1)

    corrigir = jul[jul["motivo"] != "OK"].copy()
    vd = corrigir[corrigir["motivo"] == "VELOCIDADE DIVERGENTE"]
    md = corrigir[corrigir["motivo"] == "MESH DIVERGENTE (1GB)"]
    nv = corrigir[corrigir["motivo"] == "NOME/VARIANTE DIFERENTE"]
    sem_osab = corrigir[corrigir["motivo"] == "SEM PLANO OSAB"]

    print(f"Instaladas jul/2026: {len(jul)}")
    print(f"Com Plano OSAB: {jul['velocidade_osab'].notna().sum()}")
    print(f"Sem Plano OSAB: {jul['velocidade_osab'].isna().sum()}")
    print(f"OK: {(jul['motivo'] == 'OK').sum()}")
    print(f"Precisam revisao: {len(corrigir)}")
    print("\nPor motivo:")
    print(corrigir["motivo"].value_counts().to_string())
    print("\nVelocidade divergente (CRM x OSAB):")
    if len(vd):
        print(pd.crosstab(vd["Plano"], vd["Plano OSAB"]).to_string())
    print(f"Total velocidade: {len(vd)}")
    print(f"Total MESH: {len(md)}")
    print(f"Total nome/variante: {len(nv)}")
    print(f"Total sem OSAB: {len(sem_osab)}")

    cols_out = [
        "ID",
        "OS",
        "Cliente",
        "CPF/CNPJ",
        "Vendedor",
        "Supervisor",
        "Canal",
        "Data Instalacao",
        "Validacao OSAB",
        "Plano",
        "Valor",
        "Plano OSAB",
        "Oferta",
        "velocidade_crm",
        "velocidade_osab",
        "mesh_crm",
        "mesh_osab",
        "plano_correto",
        "motivo",
    ]

    resumo = pd.DataFrame(
        {
            "Metrica": [
                "Instaladas jul/2026",
                "Com Plano OSAB",
                "Sem Plano OSAB",
                "OK (batem com OSAB)",
                "Precisam correcao/revisao",
                "— Velocidade divergente",
                "— MESH divergente (1GB)",
                "— Nome/variante diferente",
                "— Sem Plano OSAB",
            ],
            "Qtd": [
                len(jul),
                int(jul["velocidade_osab"].notna().sum()),
                int(jul["velocidade_osab"].isna().sum()),
                int((jul["motivo"] == "OK").sum()),
                len(corrigir),
                len(vd),
                len(md),
                len(nv),
                len(sem_osab),
            ],
        }
    )

    matriz = pd.crosstab(
        jul["velocidade_crm"].fillna("(sem)"),
        jul["velocidade_osab"].fillna("(sem OSAB)"),
        margins=True,
    )

    with pd.ExcelWriter(OUT, engine="openpyxl") as writer:
        resumo.to_excel(writer, sheet_name="Resumo", index=False)
        corrigir[cols_out].sort_values(["motivo", "Plano", "Plano OSAB", "ID"]).to_excel(
            writer, sheet_name="Corrigir", index=False
        )
        vd[cols_out].sort_values(["Plano", "Plano OSAB", "ID"]).to_excel(
            writer, sheet_name="Velocidade divergente", index=False
        )
        if len(md):
            md[cols_out].sort_values("ID").to_excel(writer, sheet_name="MESH divergente", index=False)
        if len(nv):
            nv[cols_out].sort_values("ID").to_excel(writer, sheet_name="Nome variante", index=False)
        sem_osab[cols_out].sort_values("ID").to_excel(writer, sheet_name="Sem Plano OSAB", index=False)
        matriz.to_excel(writer, sheet_name="Matriz velocidade")
        jul[jul["motivo"] == "OK"][cols_out].sort_values("ID").to_excel(
            writer, sheet_name="OK", index=False
        )

    print(f"\nArquivo gerado: {OUT}")
    if len(vd):
        print("\nAmostra velocidade divergente:")
        print(
            vd[
                ["ID", "OS", "Cliente", "Plano", "Plano OSAB", "Oferta", "plano_correto", "Valor"]
            ]
            .head(30)
            .to_string()
        )
    if len(md):
        print("\nAmostra MESH divergente:")
        print(
            md[["ID", "OS", "Cliente", "Plano", "Oferta", "plano_correto"]]
            .head(20)
            .to_string()
        )


if __name__ == "__main__":
    main()
