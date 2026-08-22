#!/usr/bin/env python
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
import django
django.setup()

from rest_framework.test import APIClient
import json

client = APIClient()
response = client.post('/api/auth/login/', {'username': 'admin', 'password': 'admin123'}, format='json')

print(f"Status: {response.status_code}")
print(f"Content-Type: {response.get('content-type', 'N/A')}")
print(f"Body ({len(response.content)} bytes):")
print(response.data)
print(f"\nData type: {type(response.data)}")
