import csv
import os
import re
import time
import requests

# Caminhos
ARQUIVO_ENTRADA = r"C:\Downloads\cnpj_condominios_mg.csv"
ARQUIVO_SAIDA = r"C:\Downloads\cnpj_condominios_mg_cepaberto.csv"

# Token do CEP Aberto - IDEAL: usar variável de ambiente
CEPABERTO_TOKEN = os.getenv("CEPABERTO_TOKEN") or "1064e2cf82ae1616ee84255580b2a6d9"  # troque ou use env var

BASE_URL = "https://www.cepaberto.com/api/v3/cep"

def normalizar_cep(val):
    s = re.sub(r"\D", "", str(val or ""))
    return s[:8] if len(s) >= 8 else (s.zfill(8) if len(s) == 7 else None)

def buscar_cidade_cepaberto(cep, cache, delay=0.2):
    cep_limpo = normalizar_cep(cep)
    if not cep_limpo:
        return None
    if cep_limpo in cache:
        return cache[cep_limpo]

    headers = {"Authorization": f"Token token={CEPABERTO_TOKEN}"}
    try:
        resp = requests.get(BASE_URL, params={"cep": cep_limpo}, headers=headers, timeout=5)
        if resp.status_code == 200:
            data = resp.json() or {}
            cidade = (data.get("cidade") or "").strip()
            # Alguns formatos da API trazem "cidade" dentro de "cidade":{"nome":...}
            if not cidade and isinstance(data.get("cidade"), dict):
                cidade = (data["cidade"].get("nome") or "").strip()
            cache[cep_limpo] = cidade or None
        else:
            cache[cep_limpo] = None
    except Exception:
        cache[cep_limpo] = None

    time.sleep(delay)  # evitar bater forte na API
    return cache[cep_limpo]

def main():
    if CEPABERTO_TOKEN == "SEU_TOKEN_AQUI":
        print("Defina o token do CEP Aberto (variável CEPABERTO_TOKEN ou direto no código).")
        return

    with open(ARQUIVO_ENTRADA, "r", encoding="utf-8-sig", newline="") as f_in, \
         open(ARQUIVO_SAIDA, "w", encoding="utf-8-sig", newline="") as f_out:

        reader = csv.DictReader(f_in, delimiter=";")
        fieldnames = reader.fieldnames
        if "Município" not in fieldnames:
            raise RuntimeError("Coluna 'Município' não encontrada no CSV de entrada.")
        writer = csv.DictWriter(f_out, fieldnames=fieldnames, delimiter=";")
        writer.writeheader()

        cache = {}
        total = 0
        atualizados = 0

        for row in reader:
            total += 1
            municipio_atual = (row.get("Município") or "").strip()
            if not municipio_atual:
                cep = row.get("CEP") or ""
                cidade = buscar_cidade_cepaberto(cep, cache)
                if cidade:
                    row["Município"] = cidade
                    atualizados += 1
            writer.writerow({k: row.get(k, "") for k in fieldnames})

            if total % 1000 == 0:
                print(f"{total} linhas processadas... ({atualizados} municípios preenchidos via CEP Aberto)")

    print(f"Concluído. Linhas: {total} | Municípios preenchidos: {atualizados}")
    print(f"Arquivo gerado: {ARQUIVO_SAIDA}")

if __name__ == "__main__":
    main()