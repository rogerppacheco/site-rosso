import requests
import json

url = "http://localhost:8000/api/auth/login/"
payload = {"username": "admin", "password": "admin123"}

print("=" * 80)
print("TESTE DE LOGIN")
print("=" * 80)
print(f"\nURL: {url}")
print(f"Payload: {json.dumps(payload)}")

response = requests.post(url, json=payload)

print(f"\nStatus Code: {response.status_code}")
print(f"Headers: {dict(response.headers)}")
print(f"\nResponse Body:")
print(response.text)

if response.status_code == 200:
    data = response.json()
    print("\n✅ LOGIN SUCESSO!")
    print(f"Token: {data.get('token', data.get('access', ''))[:50]}...")
else:
    print(f"\n❌ LOGIN FALHOU (HTTP {response.status_code})")
    try:
        error = response.json()
        print(f"Erro: {json.dumps(error, indent=2)}")
    except:
        print(f"Resposta: {response.text}")
