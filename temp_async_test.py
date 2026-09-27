import os
import django
import asyncio

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gestao_equipes.settings')
django.setup()

from crm_app.models import SyncStatusEsteiraExecucao
from crm_app.esteira_consulta_status_pap_service import _run_django_sync

async def test_async():
    try:
        SyncStatusEsteiraExecucao.objects.count()
        print("Success without _run_django_sync!")
    except Exception as e:
        print(f"Error without: {e.__class__.__name__}: {e}")
        
    try:
        def my_query():
            return SyncStatusEsteiraExecucao.objects.count()
            
        old = os.environ.get('DJANGO_ALLOW_ASYNC_UNSAFE')
        os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = 'true'
        res = my_query()
        if old is None:
            del os.environ['DJANGO_ALLOW_ASYNC_UNSAFE']
        else:
            os.environ['DJANGO_ALLOW_ASYNC_UNSAFE'] = old
        print(f"Success with DJANGO_ALLOW_ASYNC_UNSAFE: {res}")
    except Exception as e:
        print(f"Error with DJANGO_ALLOW_ASYNC_UNSAFE: {e}")

asyncio.run(test_async())
