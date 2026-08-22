#!/usr/bin/env python
import requests
import json

url = "http://127.0.0.1:8000/api/auth/login/"
payload = {"username": "admin", "password": "admin123"}

response = requests.post(url, json=payload)

print(f"Status Code: {response.status_code}")
print(f"Content-Type: {response.headers.get('content-type', 'N/A')}")
print(f"Response Body ({len(response.text)} bytes):")
print(response.text)

if response.status_code == 200:
    print("\n✓ Login successful!")
    data = response.json()
    print(f"Token: {data.get('token', 'N/A')[:50]}...")
else:
    print(f"\n✗ Login failed with status {response.status_code}")
    try:
        print(f"JSON Error: {response.json()}")
    except:
        print(f"Raw response: {response.text}")
