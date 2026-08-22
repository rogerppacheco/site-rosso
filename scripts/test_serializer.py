#!/usr/bin/env python
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
import django
django.setup()

from usuarios.serializers import CustomTokenObtainPairSerializer
from usuarios.models import Usuario

# Testar o serializer customizado
attrs = {'username': 'admin', 'password': 'admin123'}
serializer = CustomTokenObtainPairSerializer(data=attrs)
print('Serializer is_valid:', serializer.is_valid())
print('Errors:', serializer.errors)
if serializer.is_valid():
    print('Keys:', list(serializer.validated_data.keys()))
    print('Tem token:', 'token' in serializer.validated_data)
    print('Tem user:', 'user' in serializer.validated_data)
    if 'user' in serializer.validated_data:
        print('User data:', serializer.validated_data['user'])
else:
    print('Validation failed')
    import traceback
    traceback.print_exc()
