#!/usr/bin/env python
import requests
import time

time.sleep(2)

url = "http://127.0.0.1:8002/api/auth/login/"
payload = {"username": "admin", "password": "admin123"}

print(f"Testing: {url}")
print(f"Payload: {payload}\n")

response = requests.post(url, json=payload, timeout=5)

print(f"Status: {response.status_code}")
print(f"Body: {response.text}")
