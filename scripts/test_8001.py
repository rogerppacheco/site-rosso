#!/usr/bin/env python
import requests
import json
import time

time.sleep(2)  # Wait for server to start

url = "http://127.0.0.1:8001/api/auth/login/"
payload = {"username": "admin", "password": "admin123"}
headers = {"Content-Type": "application/json"}

print(f"URL: {url}")
print(f"Payload: {payload}")

try:
    response = requests.post(url, json=payload, headers=headers, timeout=5)
    
    print(f"\n=== RESPONSE ===")
    print(f"Status Code: {response.status_code}")
    print(f"Content Length: {len(response.content)}")
    print(f"\nBody (hex): {response.content[:100].hex()}")
    print(f"Body (text): {repr(response.text[:100])}")
    
    # Try to decode as JSON
    try:
        data = response.json()
        print(f"\nJSON: {json.dumps(data, indent=2, ensure_ascii=False)}")
    except Exception as je:
        print(f"(Not JSON: {je})")
        
except Exception as e:
    print(f"ERROR: {e}")
