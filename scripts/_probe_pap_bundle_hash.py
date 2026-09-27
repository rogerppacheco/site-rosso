"""Busca no bundle.js do PAP a lógica do hash anti-replay."""
import re
import requests

URL = "https://pap.niointernet.com.br/administrativo/bundle.js"
print("Baixando", URL)
r = requests.get(URL, timeout=120)
print("status", r.status_code, "len", len(r.text))
text = r.text

needles = [
    "5Hsrpt5",
    "antiReplay",
    "anti-replay",
    "anti_replay",
    "jwt malformed",
    "btoa",
    "charCodeAt",
    "Authorization",
    "replay",
]
for n in needles:
    idx = text.find(n)
    print(f"find({n!r}) = {idx}")
    if idx >= 0:
        print(text[max(0, idx - 120) : idx + 200].replace("\n", " ")[:320])
        print("---")

# strings longas candidatas a chave
for m in re.finditer(r"['\"]([-A-Za-z0-9_+/=]{32,64})['\"]", text):
    s = m.group(1)
    if "Hsr" in s or s.startswith("-5") or len(s) in (40, 43, 44):
        print("CANDIDATE", s)
