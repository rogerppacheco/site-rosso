import requests
import json
import sys
import time

time.sleep(2)  # Aguardar servidor iniciar

url = "http://localhost:8000/api/auth/login/"
payload = {"username": "admin", "password": "admin123"}

print("Testando login...")
response = requests.post(url, json=payload)

print(f"Status: {response.status_code}")
if response.status_code == 200:
    data = response.json()
    print("✅ LOGIN SUCESSO!")
    print(f"Token: {data.get('token', data.get('access', ''))[:80]}...")
    sys.exit(0)
else:
    print(f"❌ LOGIN FALHOU")
    print(f"Response: {response.text}")
    sys.exit(1)
