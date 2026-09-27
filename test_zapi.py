import os
from dotenv import load_dotenv
import requests

load_dotenv()

instance_id = os.environ.get('ZAPI_INSTANCE_ID')
token = os.environ.get('ZAPI_TOKEN')
client_token = os.environ.get('ZAPI_CLIENT_TOKEN')

print(f"INSTANCE: {instance_id}")
if not instance_id:
    print("Sem var!")
else:
    base_url = f"https://api.z-api.io/instances/{instance_id}/token/{token}"
    headers = {"client-token": client_token}
    try:
        res = requests.get(f"{base_url}/status", headers=headers)
        print("Status:", res.status_code, res.text)
        
        res_g = requests.get(f"{base_url}/groups", headers=headers)
        print("Grupos status:", res_g.status_code)
        if res_g.status_code == 200:
            try:
                data = res_g.json()
                print("Grupos keys:", data.keys() if isinstance(data, dict) else len(data))
            except:
                print("Non JSON.")
    except Exception as e:
        print("Erro:", e)
