#!/usr/bin/env python
import requests
import json

url = "http://127.0.0.1:8000/api/auth/login/"
payload = {"username": "admin", "password": "admin123"}
headers = {"Content-Type": "application/json"}

print(f"URL: {url}")
print(f"Payload: {payload}")
print(f"Headers: {headers}")

try:
    response = requests.post(url, json=payload, headers=headers, timeout=5)
    
    print(f"\n=== RESPONSE ===")
    print(f"Status Code: {response.status_code}")
    print(f"Content Length: {len(response.content)}")
    print(f"Headers: {dict(response.headers)}")
    print(f"\nBody ({len(response.text)} chars, {len(response.content)} bytes):")
    print(repr(response.text))
    
    # Try to decode as JSON
    try:
        data = response.json()
        print(f"\nJSON: {json.dumps(data, indent=2)}")
    except:
        print(f"(Not JSON)")
        
except Exception as e:
    print(f"ERROR: {e}")
