#!/usr/bin/env python
import requests

url = "http://127.0.0.1:8000/api/auth/login/"
payload = {"username": "admin", "password": "admin123"}

# Teste 1: com header Host correto
print("=== Teste 1: Host padrão ===")
response = requests.post(url, json=payload)
print(f"Status: {response.status_code}")
print(f"Body: {response.text[:200]}")

# Teste 2: com headers explícitos
print("\n=== Teste 2: Headers explícitos ===")
headers = {'Host': '127.0.0.1:8000'}
response = requests.post(url, json=payload, headers=headers)
print(f"Status: {response.status_code}")
print(f"Body: {response.text[:200]}")

# Teste 3: com Host localhost
print("\n=== Teste 3: Localhost ===")
url_localhost = "http://localhost:8000/api/auth/login/"
response = requests.post(url_localhost, json=payload)
print(f"Status: {response.status_code}")
print(f"Body: {response.text[:200]}")
