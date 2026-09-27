"""Monta modelo legado v5 cruzando PAP GM × OSAB (GM TELECOM)."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from crm_app.legado_pap_osab import (  # noqa: E402
    cruzar_pap_osab,
    ler_excel_bytes,
    montar_xlsx,
    pick_sheet,
)

PAP = BASE / "exports" / "legado_pap" / "Historico_PAP_2026-04_2026-08.xlsx"
OUT = BASE / "exports" / "legado_pap" / "Legado_GM_TELECOM_AbrAgo26.xlsx"
DOWNLOADS = Path(r"C:\Users\rogge\Downloads")

# Snapshots OSAB que contêm GM TELECOM (PDV 1069074)
OSAB_FILES = [
    DOWNLOADS / "MG (5).xlsb",  # abr/26
    DOWNLOADS / "MG (6).xlsb",  # mai/26
    DOWNLOADS / "OSAB_CLICKUP_JUN-26.xlsb",
    DOWNLOADS / "OSAB_JUL-26.xlsb",
    DOWNLOADS / "OSAB_CLICKUP_AGO-26.xlsb",
    DOWNLOADS / "OSAB (BI).xlsx",
    DOWNLOADS / "PP(20-08-26).xlsb",
]


def main():
    if not PAP.exists():
        raise SystemExit(f"PAP não encontrado: {PAP}")

    pap_bytes = PAP.read_bytes()
    pap_sheets = ler_excel_bytes(PAP.name, pap_bytes)
    pap_df = pick_sheet(pap_sheets, ("Pedidos", "PEDIDOS", "Pedido", "BASE", "Export"))

    osab_frames = []
    for path in OSAB_FILES:
        if not path.exists():
            print("SKIP", path.name)
            continue
        sheets = ler_excel_bytes(path.name, path.read_bytes())
        df = pick_sheet(sheets, ("BASE", "Export", "Exportar"))
        if "PEDIDO" not in df.columns:
            print(f"SKIP sem PEDIDO: {path.name}")
            continue
        print(f"OSAB {path.name}: {len(df)} linhas")
        osab_frames.append((path.name, df))

    if not osab_frames:
        raise SystemExit("Nenhuma OSAB encontrada.")

    # Todos os status (revisão); aba Modelo Legado = completo
    resultado = cruzar_pap_osab(
        pap_df,
        osab_frames,
        parceiro="GM TELECOM",
        pdv_sap="1069074",
        somente_instalada=False,
    )
    blob = montar_xlsx(resultado)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(blob)

    # Também gera só INSTALADAS (pronto para importar)
    out_inst = OUT.with_name("Legado_GM_TELECOM_AbrAgo26_INSTALADAS.xlsx")
    res_inst = cruzar_pap_osab(
        pap_df,
        osab_frames,
        parceiro="GM TELECOM",
        pdv_sap="1069074",
        somente_instalada=True,
    )
    out_inst.write_bytes(montar_xlsx(res_inst))

    print("==== RESUMO (todos status) ====")
    for k, v in resultado["resumo"].items():
        print(f"  {k}: {v}")
    print("Arquivo:", OUT)
    print("Instaladas:", out_inst, "n=", res_inst["resumo"]["modelo_legado"])

    modelo = resultado["modelo"]
    if len(modelo):
        print("STATUS_ESTEIRA:", modelo["STATUS_ESTEIRA"].value_counts().to_dict())
        # cobertura por mês da DATA_VENDA
        s = pd.to_datetime(modelo["DATA_VENDA"], dayfirst=True, errors="coerce")
        print("Por mês DATA_VENDA:", s.dt.to_period("M").astype(str).value_counts().sort_index().to_dict())


if __name__ == "__main__":
    main()
