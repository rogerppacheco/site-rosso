"""Relatório de billing Railway — workspace rogerppacheco."""
from __future__ import annotations

import json
from pathlib import Path

USD_BRL = 5.1413

PROJECTS = {
    "1e9d99e5-abd8-4cbc-b91a-0a52887508cf": "sistema-vendas-tpl",
    "5c602881-2ffa-48a4-be87-228bd35893f4": "plano-ideal",
    "7171eee1-2c6e-446a-b7a9-880d3786c51a": "site-record",
    "8db60e30-1dde-43f9-afaa-bfc19682fe0b": "banco-de-dados",
    "c5f30c08-b32b-462e-9679-129064a82247": "viabilidade-forms-nio",
    "df858945-8b79-46f2-aad8-980bc4bfc925": "syncwa-platform",
    "fe553432-2a22-46cc-b347-ee669ff4aba3": "sysr-vendas-api",
}

RATE_CPU = 0.000463
RATE_MEM = 0.000231
RATE_NET = 0.10


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    root = Path(__file__).resolve().parent
    cpu = {
        r["projectId"]: r["estimatedValue"]
        for r in _load(root / "_usage_cpu.json")["data"]["estimatedUsage"]
    }
    mem = {
        r["projectId"]: r["estimatedValue"]
        for r in _load(root / "_usage_mem.json")["data"]["estimatedUsage"]
    }
    net = {
        r["projectId"]: r["estimatedValue"]
        for r in _load(root / "_usage_net.json")["data"]["estimatedUsage"]
    }
    ws = _load(root / "_billing_workspace.json")["data"]["workspace"]

    costs: dict[str, float] = {}
    for pid, name in PROJECTS.items():
        costs[name] = (
            cpu.get(pid, 0) * RATE_CPU
            + mem.get(pid, 0) * RATE_MEM
            + net.get(pid, 0) * RATE_NET
        )

    total_est = sum(costs.values())
    invoice_usd = ws["customer"]["subscriptions"][0]["nextInvoiceCurrentTotal"] / 100
    factor = invoice_usd / total_est if total_est else 1.0

    print("=== FATURA ATUAL (API Railway) ===")
    print(f"Estimativa proxima fatura: US$ {invoice_usd:.2f}  (R$ {invoice_usd * USD_BRL:.2f})")
    print(f"Proxima cobranca: {ws['customer']['subscriptions'][0]['nextInvoiceDate'][:10]}")
    print("Plano: Hobby (US$ 5/mes + uso)")
    print()
    print("=== ULTIMAS FATURAS PAGAS ===")
    for inv in ws["customer"]["invoices"][:5]:
        usd = inv["total"] / 100
        start = inv["periodStart"][:10]
        end = inv["periodEnd"][:10]
        print(f"  {start} a {end}: US$ {usd:.2f}  (R$ {usd * USD_BRL:.2f})")
    print()
    print(f"=== ESTIMATIVA POR PROJETO (proporcional a US$ {invoice_usd:.2f}) ===")
    for name in sorted(costs, key=costs.get, reverse=True):
        usd = costs[name] * factor
        print(f"  {name:25} US$ {usd:6.2f}   R$ {usd * USD_BRL:7.2f}")
    print()
    print(f"Cotacao: US$ 1 = R$ {USD_BRL} (22/06/2026)")


if __name__ == "__main__":
    main()
