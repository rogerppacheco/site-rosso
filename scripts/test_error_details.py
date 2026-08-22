import requests
import json

url = "http://127.0.0.1:8000/api/auth/login/"
payload = {"username": "admin", "password": "admin123"}

print("Testando login...")
response = requests.post(url, json=payload)

print(f"Status: {response.status_code}")
print(f"Response completa:")
print(json.dumps(response.json(), indent=2))
