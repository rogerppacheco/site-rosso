#!/usr/bin/env python
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
django.setup()

from rest_framework.test import APIRequestFactory
from rest_framework_simplejwt.tokens import RefreshToken
from crm_app.views import BuscarOSFPDView
from usuarios.models import Usuario

# Criar request mockado com autenticação
factory = APIRequestFactory()

# Buscar um usuário existente
usuario = Usuario.objects.filter(is_staff=True).first()
if not usuario:
    usuario = Usuario.objects.first()

print(f"Usando usuário: {usuario.username}")

# Gerar token
refresh = RefreshToken.for_user(usuario)
token = str(refresh.access_token)

# Criar request
request = factory.get('/api/bonus-m10/buscar-os-fpd/?os=07309961', HTTP_AUTHORIZATION=f'Bearer {token}')
request.user = usuario

# Chamar view
view = BuscarOSFPDView.as_view()
response = view(request)

print("Status:", response.status_code)
print("Data:", response.data)
print("\n✅ Teste concluído!")
