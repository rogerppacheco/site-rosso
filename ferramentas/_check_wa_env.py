import json
import subprocess

keys = [
    "WHATSATENDE_WEBHOOK_TOKEN",
    "WHATSATENDE_TOKEN",
    "WHATSATENDE_WHATSAPP_ID",
    "WHATSATENDE_API_URL",
]
for svc in ["site-record", "site-record-webhook"]:
    print(f"=== {svc} ===")
    p = subprocess.run(
        ["railway", "variables", "-s", svc, "--json"],
        capture_output=True,
        text=True,
    )
    raw = p.stdout or ""
    s = raw.find("{")
    data = json.loads(raw[s:]) if s >= 0 else {}
    for k in keys:
        v = data.get(k)
        if v:
            print(f"  {k}: OK (len={len(str(v))})")
        else:
            print(f"  {k}: AUSENTE")
