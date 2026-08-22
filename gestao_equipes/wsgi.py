"""
WSGI config for gestao_equipes project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

from gestao_equipes.wsgi_loop_guard import WsgiLoopGuard

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')

application = WsgiLoopGuard(get_wsgi_application())
