REST_FRAMEWORK = {
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
}
from pathlib import Path
import os
import sys
from decouple import config
import dj_database_url
from datetime import timedelta

BASE_DIR = Path(__file__).resolve().parent.parent


def _running_django_tests() -> bool:
    """
    Detecta `manage.py test` / pytest.

    O .env local costuma apontar DATABASE_URL para o Postgres da Railway (schema
    exclusivo). Sem este desvio, o runner tenta criar um banco de teste lá e
    falha — além de arriscar dados de produção. Testes unitários usam SQLite.
    """
    if os.environ.get('DJANGO_TEST', '').lower() in ('1', 'true', 'yes'):
        return True
    if 'pytest' in sys.modules:
        return True
    # manage.py test [label...]  →  argv[0]=manage.py, argv[1]=test
    return len(sys.argv) >= 2 and sys.argv[1] == 'test'


TESTING = _running_django_tests()

SECRET_KEY = config('SECRET_KEY')
DEBUG = config('DEBUG', default=False, cast=bool)

ALLOWED_HOSTS = [
    '127.0.0.1',
    'localhost',
    'testserver',
    'healthcheck.railway.app',
    # Permite qualquer subdomínio do Railway
    '.up.railway.app',
    # Teste local: ngrok (ex.: d021-177-137-82-21.ngrok-free.app)
    '.ngrok-free.app',
    '.ngrok.io',
]

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'whitenoise.runserver_nostatic',
    'django.contrib.staticfiles',
    'corsheaders',
    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',
    'usuarios',
    'core',
    'presenca',
    'relatorios',
    'osab',
    'crm_app',
    'silk',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'silk.middleware.SilkyMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'core_config.middleware_static_cache.StaticCacheMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'core_config.middleware.DisableCsrfForJWT',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'core_config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [
            # Pasta frontend raiz
            os.path.join(BASE_DIR, 'frontend'),
            
            # ADICIONE ESTA LINHA ABAIXO:
            os.path.join(BASE_DIR, 'frontend', 'public'),
            
            os.path.join(BASE_DIR, 'templates'),
        ],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'core_config.context_processors.site_branding',
                'core_config.context_processors.planos_landing',
            ],
        },
    },
]

WSGI_APPLICATION = 'core_config.wsgi.application'

# ==============================================================================
# CONFIGURAÇÃO DE BANCO DE DADOS (PostgreSQL no Railway vs SQLite local)
# ==============================================================================

# 1. Padrão: SQLite (Para uso local no seu computador)
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

# 2. Produção: PostgreSQL (Railway) — schema exclusivo nova_velox (NUNCA public)
from core_config.database import (
    django_database_options,
    get_postgres_schema,
    is_pgbouncer_enabled,
)

database_url = config('DATABASE_URL', default=None)  # Railway PostgreSQL (PgBouncer quando ativo)
database_unpooled_url = config('DATABASE_UNPOOLED_URL', default=None)
test_database_url = config('TEST_DATABASE_URL', default=None)

_pgbouncer_active = bool(database_url and is_pgbouncer_enabled())
POSTGRES_SCHEMA = get_postgres_schema() if database_url else None

if database_url:
    # Com PgBouncer: conn_max_age=0 evita segurar conexões no app (multiplexação no pooler).
    _default_conn_max_age = 0 if _pgbouncer_active else config('DB_CONN_MAX_AGE', default=0, cast=int)
    if _pgbouncer_active and config('DB_CONN_MAX_AGE', default=0, cast=int) > 0:
        print(
            "[DB] PgBouncer ativo: DB_CONN_MAX_AGE ignorado (use 0 com transaction pooling)"
        )

    DATABASES['default'] = dj_database_url.parse(
        database_url,
        conn_max_age=_default_conn_max_age,
        ssl_require=False,
    )
    DATABASES['default']['ENGINE'] = 'django.db.backends.postgresql'
    DATABASES['default']['OPTIONS'] = django_database_options(
        pooled=_pgbouncer_active,
        schema=POSTGRES_SCHEMA,
    )
    # Detecta conexão morta (PgBouncer/idle/SSL) antes de reutilizar — crítico para workers PAP.
    DATABASES['default']['CONN_HEALTH_CHECKS'] = True

    # Modo transaction do PgBouncer não suporta server-side cursors nem locks de sessão.
    if _pgbouncer_active:
        DISABLE_SERVER_SIDE_CURSORS = True

    # Conexão direta ao Postgres para advisory locks (somente com PgBouncer no runtime).
    if _pgbouncer_active and database_unpooled_url:
        DATABASES['unpooled'] = dj_database_url.parse(
            database_unpooled_url,
            conn_max_age=0,
            ssl_require=False,
        )
        DATABASES['unpooled']['ENGINE'] = 'django.db.backends.postgresql'
        DATABASES['unpooled']['OPTIONS'] = django_database_options(
            pooled=False,
            schema=POSTGRES_SCHEMA,
        )
        DATABASES['unpooled']['CONN_HEALTH_CHECKS'] = True

    _h = DATABASES['default'].get('HOST') or 'localhost'
    _n = DATABASES['default'].get('NAME')
    _pool_label = "PgBouncer" if _pgbouncer_active else "direct"
    print(
        f"OK - PostgreSQL ({_pool_label}): host={_h!r} db={_n!r} "
        f"schema={POSTGRES_SCHEMA!r} (search_path exclusivo)"
    )

else:
    print("[WARNING] Nenhuma variável de ambiente de banco encontrada. Usando SQLite.")

# Testes locais: PostgreSQL local quando TEST_DATABASE_URL estiver configurada;
# caso contrário, SQLite em memória. Nunca aceita host remoto nesta variável.
if TESTING:
    if test_database_url:
        test_database = dj_database_url.parse(
            test_database_url,
            conn_max_age=0,
            ssl_require=False,
        )
        test_host = (test_database.get('HOST') or '').strip().lower()
        if test_host not in {'localhost', '127.0.0.1', '::1'}:
            raise ValueError(
                'TEST_DATABASE_URL deve apontar para PostgreSQL local '
                '(localhost, 127.0.0.1 ou ::1).'
            )
        test_database['ENGINE'] = 'django.db.backends.postgresql'
        # O banco inteiro é temporário e isolado; public evita depender da
        # criação prévia do schema nova_velox antes das migrations.
        test_database['OPTIONS'] = {'options': '-c search_path=public'}
        DATABASES = {'default': test_database}
        POSTGRES_SCHEMA = 'public'
        print(
            '[TEST] Banco de testes: PostgreSQL local '
            f"(host={test_host!r}, base={test_database.get('NAME')!r})."
        )
    else:
        DATABASES = {
            'default': {
                'ENGINE': 'django.db.backends.sqlite3',
                'NAME': ':memory:',
            }
        }
        POSTGRES_SCHEMA = None
        print("[TEST] Banco de testes: SQLite em memória (fallback local).")
    DISABLE_SERVER_SIDE_CURSORS = False

# ==============================================================================

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',},
]

LANGUAGE_CODE = 'pt-br'
TIME_ZONE = 'America/Sao_Paulo'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
STATICFILES_DIRS = [
    os.path.join(BASE_DIR, 'static'),
    os.path.join(BASE_DIR, 'frontend', 'public'),
]
# Garante que o Whitenoise sirva arquivos estáticos corretamente em produção

# Serve arquivos estáticos corretamente em todos ambientes
if not DEBUG:
    STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'
else:
    STATICFILES_STORAGE = 'django.contrib.staticfiles.storage.StaticFilesStorage'
    # Em desenvolvimento, o WhiteNoise reindexa os arquivos a cada requisição,
    # evitando precisar rodar collectstatic e reiniciar o servidor a cada edição.
    WHITENOISE_AUTOREFRESH = True
    WHITENOISE_USE_FINDERS = True

# Instrução: Após cada deploy, execute no Railway:
# python manage.py collectstatic --noinput

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.AllowAny',
    ),
    # ✅ PAGINAÇÃO PARA PERFORMANCE
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,  # 20 registros por página
    'MAX_PAGE_SIZE': 1000,  # Permite até 1000 registros por página na API
    # ✅ FILTRAGEM
    'DEFAULT_FILTER_BACKENDS': [
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ],
}

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=30),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=1),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'ALGORITHM': 'HS256',
    'SIGNING_KEY': SECRET_KEY,
    'AUTH_HEADER_TYPES': ('Bearer',),
    'USER_ID_FIELD': 'id',
    'USER_ID_CLAIM': 'user_id',
}

AUTH_USER_MODEL = 'usuarios.Usuario'
LOGIN_URL = '/'

CORS_ALLOW_CREDENTIALS = True

CORS_ALLOWED_ORIGINS = [
    'http://localhost:8000',
    'http://127.0.0.1:8000',
]

CSRF_TRUSTED_ORIGINS = [
    'http://localhost:8000',
    'http://127.0.0.1:8000',
]

SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'
X_FRAME_OPTIONS = 'SAMEORIGIN'

# --- CONFIGURAÇÕES DE E-MAIL (UOL Host — bo@recordpap.com.br) ---
# SMTP: smtps.uhserver.com:465 SSL. Credenciais vêm do .env (não versionar senha).
EMAIL_BACKEND = config('EMAIL_BACKEND', default='django.core.mail.backends.smtp.EmailBackend')
EMAIL_HOST = config('EMAIL_HOST', default='smtps.uhserver.com')
EMAIL_PORT = config('EMAIL_PORT', default=465, cast=int)
EMAIL_USE_TLS = config('EMAIL_USE_TLS', default=False, cast=bool)
EMAIL_USE_SSL = config('EMAIL_USE_SSL', default=True, cast=bool)
EMAIL_HOST_USER = config('EMAIL_HOST_USER', default='bo@recordpap.com.br')
EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD', default='')
DEFAULT_FROM_EMAIL = config('DEFAULT_FROM_EMAIL', default='Record PAP <bo@recordpap.com.br>')

# --- CLOUDFLARE R2 (armazenamento de arquivos) ---
CLOUDFLARE_R2_ACCOUNT_ID = config('CLOUDFLARE_R2_ACCOUNT_ID', default='')
CLOUDFLARE_R2_ACCESS_KEY_ID = config('CLOUDFLARE_R2_ACCESS_KEY_ID', default='')
CLOUDFLARE_R2_SECRET_ACCESS_KEY = config('CLOUDFLARE_R2_SECRET_ACCESS_KEY', default='')
CLOUDFLARE_R2_BUCKET_NAME = config('CLOUDFLARE_R2_BUCKET_NAME', default='nova-velox-midia')
CLOUDFLARE_R2_PUBLIC_URL = config('CLOUDFLARE_R2_PUBLIC_URL', default='')
# Prefixo raiz no bucket; cada funcionalidade usa subpasta própria (Record_Apoia, CDOI, etc.)
R2_FOLDER_ROOT = config('R2_FOLDER_ROOT', default='NovaVelox_CDOI')

# --- WHATSAPP: Z-API (legado) ou Evolution API ---
WHATSAPP_PROVIDER = config('WHATSAPP_PROVIDER', default='zapi').strip().lower()
ZAPI_INSTANCE_ID = config('ZAPI_INSTANCE_ID', default='')
ZAPI_TOKEN = config('ZAPI_TOKEN', default='')
ZAPI_CLIENT_TOKEN = config('ZAPI_CLIENT_TOKEN', default='')
EVOLUTION_API_URL = config(
    'EVOLUTION_API_URL',
    default='https://evolution-api-production-8bbb.up.railway.app',
)
EVOLUTION_API_KEY = config('EVOLUTION_API_KEY', default='')
EVOLUTION_INSTANCE_NAME = config('EVOLUTION_INSTANCE_NAME', default='nova_velox_zap')
# Outbound híbrido (Opção B): texto/mídia URL via n8n → Evolution
N8N_OUTBOUND_WEBHOOK_URL = config('N8N_OUTBOUND_WEBHOOK_URL', default='')
N8N_WEBHOOK_URL = config('N8N_WEBHOOK_URL', default='')
OUTBOUND_WEBHOOK_URL = config('OUTBOUND_WEBHOOK_URL', default='')
N8N_OUTBOUND_DIRECT_FALLBACK = config(
    'N8N_OUTBOUND_DIRECT_FALLBACK',
    default=True,
    cast=lambda v: str(v).lower() in ('true', '1', 'yes'),
)
# Teams: Django → n8n → Incoming Webhook do canal Teams
N8N_TEAMS_WEBHOOK_URL = config('N8N_TEAMS_WEBHOOK_URL', default='')
SITE_URL = config('SITE_URL', default='https://nova-velox.up.railway.app')
# Contatos públicos (landing) — altere no .env sem mexer no HTML
SITE_BRAND_NAME = config('SITE_BRAND_NAME', default='Futura Telecom')
SITE_PHONE_DISPLAY = config('SITE_PHONE_DISPLAY', default='(31) 9XXXX-XXXX')
SITE_WHATSAPP_DIGITS = config('SITE_WHATSAPP_DIGITS', default='319XXXXXXXX')
SITE_CONTACT_EMAIL = config('SITE_CONTACT_EMAIL', default='contato@futuratelecom.com.br')
# Cidade padrão da landing (preços GDP). Vazio = preço nacional "a partir de".
SITE_LANDING_CIDADE = config('SITE_LANDING_CIDADE', default='')
SITE_LANDING_UF = config('SITE_LANDING_UF', default='')
# Descarta webhooks Z-API irrelevantes (grupo, fromMe, etc.) antes do handler pesado
WHATSAPP_WEBHOOK_FASTPATH = config('WHATSAPP_WEBHOOK_FASTPATH', default=True, cast=bool)

# --- DFV Power BI (comando WhatsApp DFV — ao vivo; independente da base local FACHADA) ---
DFV_POWERBI_ENABLED = config(
    'DFV_POWERBI_ENABLED',
    default=True,
    cast=lambda v: str(v).lower() not in ('false', '0', 'no'),
)
DFV_POWERBI_RESOURCE_KEY = config(
    'DFV_POWERBI_RESOURCE_KEY',
    default='8a9db8f9-7cf1-4db5-90d2-5259ad149eba',
)
DFV_POWERBI_TENANT = config(
    'DFV_POWERBI_TENANT',
    default='85b28421-d45a-4b07-889d-24b528c7f250',
)
DFV_POWERBI_CLUSTER = config(
    'DFV_POWERBI_CLUSTER',
    default='https://wabi-brazil-south-b-primary-api.analysis.windows.net',
)
DFV_POWERBI_MODEL_ID = config('DFV_POWERBI_MODEL_ID', default=6061538, cast=int)
# DFV SP / Sul (mesmo cluster; resource keys dos links públicos Nio)
DFV_POWERBI_SP_RESOURCE_KEY = config(
    'DFV_POWERBI_SP_RESOURCE_KEY',
    default='81e95c1a-e770-44e3-9646-19df8443756c',
)
DFV_POWERBI_SP_MODEL_ID = config('DFV_POWERBI_SP_MODEL_ID', default=7340452, cast=int)
DFV_POWERBI_SUL_RESOURCE_KEY = config(
    'DFV_POWERBI_SUL_RESOURCE_KEY',
    default='cc212c25-1b6a-4301-877b-703e2c7aa788',
)
DFV_POWERBI_SUL_MODEL_ID = config('DFV_POWERBI_SUL_MODEL_ID', default=6062850, cast=int)
DFV_POWERBI_CO_RESOURCE_KEY = config(
    'DFV_POWERBI_CO_RESOURCE_KEY',
    default='a321b404-8186-4645-8070-507a8fea6abb',
)
DFV_POWERBI_CO_MODEL_ID = config('DFV_POWERBI_CO_MODEL_ID', default=6063900, cast=int)
DFV_POWERBI_NN_RESOURCE_KEY = config(
    'DFV_POWERBI_NN_RESOURCE_KEY',
    default='7b6cd391-63ef-4af2-9b09-1b0b1caa29a9',
)
DFV_POWERBI_NN_MODEL_ID = config('DFV_POWERBI_NN_MODEL_ID', default=6064171, cast=int)
DFV_POWERBI_TIMEOUT_SECONDS = config('DFV_POWERBI_TIMEOUT_SECONDS', default=18, cast=float)
DFV_POWERBI_CACHE_TTL_SECONDS = config('DFV_POWERBI_CACHE_TTL_SECONDS', default=600, cast=int)
DFV_POWERBI_WINDOW_COUNT = config('DFV_POWERBI_WINDOW_COUNT', default=5000, cast=int)
DFV_POWERBI_MAX_PAGES = config('DFV_POWERBI_MAX_PAGES', default=20, cast=int)
# Telefones adicionais ignorados pelo webhook (vírgula). 12981750292 já está bloqueado no código.
WHATSAPP_TELEFONES_BLOQUEADOS = [
    t.strip() for t in config('WHATSAPP_TELEFONES_BLOQUEADOS', default='').split(',') if t.strip()
]
# --- CONFIGURAÇÕES ZENVIA VOICE (AUDITORIA DE LIGAÇÕES) ---
ZENVIA_VOICE_API_URL = config('ZENVIA_VOICE_API_URL', default='https://voice-api.zenvia.com')
ZENVIA_VOICE_ACCESS_TOKEN = config('ZENVIA_VOICE_ACCESS_TOKEN', default='')
ZENVIA_VOICE_CALLS_ENDPOINT = config('ZENVIA_VOICE_CALLS_ENDPOINT', default='/chamada')
ZENVIA_VOICE_RECORDING_ENDPOINT_TEMPLATE = config(
    'ZENVIA_VOICE_RECORDING_ENDPOINT_TEMPLATE',
    default='/chamada/{call_id}/gravacao'
)
ZENVIA_VOICE_DEFAULT_SOURCE_NUMBER = config('ZENVIA_VOICE_DEFAULT_SOURCE_NUMBER', default='')
ZENVIA_VOICE_TIMEOUT_SECONDS = config('ZENVIA_VOICE_TIMEOUT_SECONDS', default=20, cast=int)
ZENVIA_VOICE_WEBHOOK_SECRET = config('ZENVIA_VOICE_WEBHOOK_SECRET', default='')
AUDITORIA_R2_FOLDER = config(
    'AUDITORIA_R2_FOLDER',
    default=config('AUDITORIA_ONEDRIVE_FOLDER', default='Auditoria_Ligacoes'),
)

# --- Sonax (auditoria: click2call + gravação pega_gravacao / webhook) ---
# Provedor SIP da auditoria. Padrão: sonax. Use AUDITORIA_VOICE_PROVIDER=zenvia só se for fallback explícito.
AUDITORIA_VOICE_PROVIDER = config('AUDITORIA_VOICE_PROVIDER', default='sonax').strip().lower()
SONAX_CLICK2CALL_URL = config(
    'SONAX_CLICK2CALL_URL',
    default='https://click2call.sonax.net.br/sonax-click2call.php',
)
SONAX_CLICK2CALL_TOKEN = config('SONAX_CLICK2CALL_TOKEN', default='')
SONAX_ID_CLIENTE = config('SONAX_ID_CLIENTE', default='')
# Token usado em dbdial_webapi.php (pega_gravacao, etc.); se vazio, usa SONAX_CLICK2CALL_TOKEN.
SONAX_INTEGRATION_TOKEN = config('SONAX_INTEGRATION_TOKEN', default='')
SONAX_DBDIAL_BASE_URL = config(
    'SONAX_DBDIAL_BASE_URL',
    default='https://api.sonax.net.br/a2billing_v2/admin/Public/dbdial_webapi.php',
)
SONAX_RAMAIS = config('SONAX_RAMAIS', default='101,102,103')
SONAX_TIMEOUT_SECONDS = config('SONAX_TIMEOUT_SECONDS', default=30, cast=int)
SONAX_WEBHOOK_SECRET = config('SONAX_WEBHOOK_SECRET', default='')

# --- Fallback Sonax (quando webhook de desligamento não chegar) ---
# Intervalo (minutos) para varrer chamadas pendentes e consultar status/baixar gravação.
SONAX_AUDITORIA_FALLBACK_INTERVAL_MINUTES = config('SONAX_AUDITORIA_FALLBACK_INTERVAL_MINUTES', default=2, cast=int)
# Quantidade máxima de ligações por execução (ordem antiga → nova).
SONAX_AUDITORIA_FALLBACK_LIMIT = config('SONAX_AUDITORIA_FALLBACK_LIMIT', default=15, cast=int)
# "Janela de graça" após iniciar a chamada antes de começar o polling (segundos).
SONAX_AUDITORIA_FALLBACK_GRACE_SECONDS = config('SONAX_AUDITORIA_FALLBACK_GRACE_SECONDS', default=90, cast=int)

# --- CONFIGURAÇÕES DE CAPTCHA (reCAPTCHA SOLVER) ---
# Use CapSolver, 2Captcha ou API customizada para resolver reCAPTCHA v2 na página Nio (PDF fatura)
CAPTCHA_API_KEY = config('CAPTCHA_API_KEY', default='CAP-4A266E1BA9DC47B87D28FBDE12A129014DB5B7EABC69D961115B3E184D497F85')
CAPTCHA_PROVIDER = config('CAPTCHA_PROVIDER', default='capsolver')  # Opções: 'capsolver', '2captcha' ou 'custom'
# Para provedor 'custom': URL da sua API que recebe POST JSON { siteKey, pageUrl } e retorna { token } ou { gRecaptchaResponse }
RECAPTCHA_SOLVER_API_URL = config('RECAPTCHA_SOLVER_API_URL', default='')

# Caminho para armazenar/reusar cookies da Nio (storage state do Playwright)
NIO_STORAGE_STATE = os.path.join(BASE_DIR, '.playwright_state.json')

# Sessão Google Forms (Inclusão/Viabilidade). Gere com:
#   .venv\Scripts\python.exe scripts\salvar_sessao_google_form.py
# Em produção, aponte para volume persistente (ex.: /data/google_form_state.json).
# Sessão Google Forms (Inclusão/Viabilidade). Gere com:
#   .venv\Scripts\python.exe scripts\salvar_sessao_google_form.py
# Login da sessão = GOOGLE_FORM_LOGIN_EMAIL (ex. roggerio@gmail.com).
# Campo e-mail do form = GOOGLE_FORM_EMAIL (ex. comunicacao@recordpap.com.br).
# Em produção, aponte para volume persistente (ex.: /data/google_form_state.json)
# ou use GOOGLE_FORM_STORAGE_STATE_B64.
GOOGLE_FORM_STORAGE_STATE = config(
    'GOOGLE_FORM_STORAGE_STATE',
    default=os.path.join(BASE_DIR, '.playwright_google_form_state.json'),
)
# Alternativa para produção sem volume: JSON do storage state em base64
# (gerar localmente com scripts/salvar_sessao_google_form.py e colar no Railway).
GOOGLE_FORM_STORAGE_STATE_B64 = config('GOOGLE_FORM_STORAGE_STATE_B64', default='')
GOOGLE_FORM_LOGIN_EMAIL = config('GOOGLE_FORM_LOGIN_EMAIL', default='roggerio@gmail.com')
GOOGLE_FORM_EMAIL = config('GOOGLE_FORM_EMAIL', default='comunicacao@recordpap.com.br')

# --- CONFIGURAÇÕES DE ARQUIVOS ESTÁTICOS E MÍDIA ---
# Para upload de PDFs das faturas M-10
MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

# --- LIMITES DE UPLOAD ---
# Ajuste para permitir arquivos grandes (ex: 200MB)
DATA_UPLOAD_MAX_MEMORY_SIZE = 200 * 1024 * 1024  # 200MB
FILE_UPLOAD_MAX_MEMORY_SIZE = 200 * 1024 * 1024  # 200MB

# ==============================================================================
# AUTOMAÇÃO PAP (VENDER NO WHATSAPP)
# ==============================================================================
# PAP_HEADLESS: Se True (padrão), o navegador roda em segundo plano (produção).
# Se False, o navegador abre na tela para você ver cada etapa (só use em teste local).
# Variável de ambiente: PAP_HEADLESS=false para ver o navegador.
PAP_HEADLESS = config('PAP_HEADLESS', default=True, cast=lambda v: str(v).lower() not in ('false', '0', 'no'))

# Br Pronto (ged360): headless=False para acompanhar a navegação no desktop
BRPRONTO_HEADLESS = config(
    'BRPRONTO_HEADLESS',
    default=True,
    cast=lambda v: str(v).lower() not in ('false', '0', 'no'),
)

# Diretório das sessões PAP (storage state Playwright). Em produção use volume Railway:
# PAP_SESSIONS_DIR=/data/pap_sessions (ver railway.pap.toml e pap_sessions/README.md).
PAP_SESSIONS_DIR = config(
    'PAP_SESSIONS_DIR',
    default=os.path.join(BASE_DIR, 'pap_sessions'),
)


# Gestão de Terceiros NIO (gestaodeterceiros.nashai.ai) → importação em Gestão de Usuários.
# Login automático usa matrícula/senha PAP de um usuário com perfil Diretoria.
NIO_TERCEIROS_BASE_URL = config(
    'NIO_TERCEIROS_BASE_URL',
    default='https://gestaodeterceiros.nashai.ai',
)
NIO_TERCEIROS_EMPRESA_ID = config('NIO_TERCEIROS_EMPRESA_ID', default='370721')
NIO_TERCEIROS_MATRICULA_DIRETOR = config('NIO_TERCEIROS_MATRICULA_DIRETOR', default='TT833162')
NIO_TERCEIROS_STORAGE_STATE = config(
    'NIO_TERCEIROS_STORAGE_STATE',
    default=os.path.join(PAP_SESSIONS_DIR, 'nio_gestaodeterceiros_session.json'),
)
NIO_TERCEIROS_CACHE = config(
    'NIO_TERCEIROS_CACHE',
    default=os.path.join(PAP_SESSIONS_DIR, 'nio_terceiros_cache.json'),
)
NIO_TERCEIROS_HEADLESS = config(
    'NIO_TERCEIROS_HEADLESS',
    default=True,
    cast=lambda v: str(v).lower() not in ('false', '0', 'no'),
)

# FORCE_FATURA_PDF_PLAYWRIGHT: Se True, o PDF da fatura é SEMPRE buscado abrindo o navegador (Playwright),
# em vez de tentar primeiro a API. Use só para debug: ver os cliques (Consultar → Pagar conta → Gerar boleto → Baixar PDF).
# Variável de ambiente: FORCE_FATURA_PDF_PLAYWRIGHT=true
FORCE_FATURA_PDF_PLAYWRIGHT = config('FORCE_FATURA_PDF_PLAYWRIGHT', default=False, cast=lambda v: str(v).lower() in ('true', '1', 'yes'))

# PAP_CAPTURE_SCREENSHOTS: Se True, salva screenshot em cada etapa da venda PAP (em produção).
# Os arquivos ficam em downloads/pap_venda_*.png e podem ser vistos em /api/crm/debug/screenshots/
# Variável de ambiente: PAP_CAPTURE_SCREENSHOTS=true
PAP_CAPTURE_SCREENSHOTS = config('PAP_CAPTURE_SCREENSHOTS', default=False, cast=lambda v: str(v).lower() in ('true', '1', 'yes'))

# PAP_SCREENSHOTS_R2: Se True, além de salvar em downloads/, envia cada screenshot para o R2.
# Também habilita captura em FALHAS da Etapa 1 mesmo com PAP_CAPTURE_SCREENSHOTS=false.
# Variável de ambiente: PAP_SCREENSHOTS_R2=true (aceita legado PAP_SCREENSHOTS_ONEDRIVE)
PAP_SCREENSHOTS_R2 = config(
    'PAP_SCREENSHOTS_R2',
    default=config('PAP_SCREENSHOTS_ONEDRIVE', default=False),
    cast=lambda v: str(v).lower() in ('true', '1', 'yes'),
)
# Pasta no R2 (dentro de R2_FOLDER_ROOT). Ex: PAP_Screenshots
PAP_R2_FOLDER = config('PAP_R2_FOLDER', default=config('PAP_ONEDRIVE_FOLDER', default='PAP_Screenshots'))

# Homologação: vendedor pode digitar FORCAR_SIM na etapa de aguardar SIM do cliente (sem resposta real do cliente).
# Variável: PAP_WHATSAPP_PERMITIR_FORCAR_SIM_CLIENTE=true (não use em produção com clientes reais).
PAP_WHATSAPP_PERMITIR_FORCAR_SIM_CLIENTE = config(
    'PAP_WHATSAPP_PERMITIR_FORCAR_SIM_CLIENTE',
    default=False,
    cast=lambda v: str(v).lower() in ('true', '1', 'yes'),
)

# Desenvolvimento local: com DEBUG=True, após enviar o resumo ao cliente marca o SIM automaticamente
# (não precisa do webhook nem de FORCAR_SIM). Nunca use em produção (DEBUG=False ignora mesmo com true).
PAP_WHATSAPP_AUTO_SIM_CLIENTE_LOCAL = config(
    'PAP_WHATSAPP_AUTO_SIM_CLIENTE_LOCAL',
    default=False,
    cast=lambda v: str(v).lower() in ('true', '1', 'yes'),
)

# Após "Abrir OS", tempo máximo (ms) aguardando a UI de agendamento (portal pode demorar nas validações).
PAP_ETAPA7_AGENDAMENTO_TIMEOUT_MS = config('PAP_ETAPA7_AGENDAMENTO_TIMEOUT_MS', default=120000, cast=int)

# Reduz esperas fixas no Playwright (login, consulta crédito, STATUS online). PAP_STATUS_FAST_MODE=false restaura waits longos.
PAP_CREDITO_FAST_MODE = config('PAP_CREDITO_FAST_MODE', default=True, cast=lambda v: str(v).lower() not in ('false', '0', 'no'))
# Máximo de consultas de crédito por TT/dia (distribui carga; evita bloqueio na Nio)
PAP_CREDITO_MAX_CONSULTAS_POR_TT_DIA = config('PAP_CREDITO_MAX_CONSULTAS_POR_TT_DIA', default=6, cast=int)
PAP_STATUS_FAST_MODE = config('PAP_STATUS_FAST_MODE', default=True, cast=lambda v: str(v).lower() not in ('false', '0', 'no'))

# Assertiva Localize: dados reais do cliente no fluxo CRÉDITO.
# A finalidade LGPD enviada pelo serviço é 2 (ciclo de crédito).
ASSERTIVA_CLIENT_ID = config('ASSERTIVA_CLIENT_ID', default='')
ASSERTIVA_CLIENT_SECRET = config('ASSERTIVA_CLIENT_SECRET', default='')
ASSERTIVA_CREDITO_ENABLED = config(
    'ASSERTIVA_CREDITO_ENABLED',
    default=bool(ASSERTIVA_CLIENT_ID and ASSERTIVA_CLIENT_SECRET),
    cast=lambda v: str(v).lower() in ('true', '1', 'yes'),
)
ASSERTIVA_API_BASE_URL = config(
    'ASSERTIVA_API_BASE_URL',
    default='https://api.assertivasolucoes.com.br',
)
ASSERTIVA_TOKEN_URL = config(
    'ASSERTIVA_TOKEN_URL',
    default='https://api.assertivasolucoes.com.br/oauth2/v3/token',
)
ASSERTIVA_TIMEOUT_SECONDS = config(
    'ASSERTIVA_TIMEOUT_SECONDS',
    default=20,
    cast=int,
)

# Sync noturno da esteira (AGENDADO/PENDENCIADA) via PAP
SYNC_ESTEIRA_HORA_INICIO = config('SYNC_ESTEIRA_HORA_INICIO', default=22, cast=int)
SYNC_ESTEIRA_HORA_FIM = config('SYNC_ESTEIRA_HORA_FIM', default=7, cast=int)
SYNC_ESTEIRA_MAX_POR_HORA = config('SYNC_ESTEIRA_MAX_POR_HORA', default=40, cast=int)
SYNC_ESTEIRA_INTERVALO_CURTO_MIN_SEG = config('SYNC_ESTEIRA_INTERVALO_CURTO_MIN_SEG', default=120, cast=int)
SYNC_ESTEIRA_INTERVALO_CURTO_MAX_SEG = config('SYNC_ESTEIRA_INTERVALO_CURTO_MAX_SEG', default=300, cast=int)
SYNC_ESTEIRA_INTERVALO_LONGO_MIN_SEG = config('SYNC_ESTEIRA_INTERVALO_LONGO_MIN_SEG', default=300, cast=int)
SYNC_ESTEIRA_INTERVALO_LONGO_MAX_SEG = config('SYNC_ESTEIRA_INTERVALO_LONGO_MAX_SEG', default=600, cast=int)
# Quantas consultas STATUS reutilizam o mesmo browser antes de reciclar (evita N logins V.tal).
SYNC_ESTEIRA_MAX_CONSULTAS_POR_SESSAO = config('SYNC_ESTEIRA_MAX_CONSULTAS_POR_SESSAO', default=20, cast=int)

# Consulta STATUS PAP da aba (login do usuário na Esteira) — ~5–6 O.S./min
CONSULTA_ESTEIRA_INTERVALO_MIN_SEG = config('CONSULTA_ESTEIRA_INTERVALO_MIN_SEG', default=8, cast=int)
CONSULTA_ESTEIRA_INTERVALO_MAX_SEG = config('CONSULTA_ESTEIRA_INTERVALO_MAX_SEG', default=15, cast=int)
CONSULTA_ESTEIRA_TELEFONE_ALERTA_STATUS = config(
    'CONSULTA_ESTEIRA_TELEFONE_ALERTA_STATUS', default='21979630377'
)

# Lembretes WhatsApp para supervisores concluírem presença (10h, 11h) e falta automática às 12h
PRESENCA_LEMBRETES_ATIVOS = config(
    'PRESENCA_LEMBRETES_ATIVOS', default=True, cast=lambda v: str(v).lower() in ('true', '1', 'yes')
)
PRESENCA_FALTA_AUTOMATICA_12H_ATIVA = config(
    'PRESENCA_FALTA_AUTOMATICA_12H_ATIVA', default=True, cast=lambda v: str(v).lower() in ('true', '1', 'yes')
)
PRESENCA_URL_SITE = config('PRESENCA_URL_SITE', default='https://nova-velox.up.railway.app/presenca/')
PRESENCA_IMAGEM_ALERTA_SUPERVISOR = config(
    'PRESENCA_IMAGEM_ALERTA_SUPERVISOR', default='presenca/assets/alerta_supervisor.png'
)
PRESENCA_MOTIVO_FALTA_AUTOMATICA = config(
    'PRESENCA_MOTIVO_FALTA_AUTOMATICA', default='Falta automática (supervisor)'
)

# Pasta no R2 para solicitações de inclusão/viabilidade (subpasta por solicitação)
INCLUSAO_R2_FOLDER = config(
    'INCLUSAO_R2_FOLDER',
    default=config('INCLUSAO_ONEDRIVE_FOLDER', default='Inclusao_Viabilidade'),
)

# --- Análise de crédito via WhatsApp: e-mails para o PAP/Nio ---
# O Nio valida o e-mail (envia teste). Use um dos dois:
# CREDITO_EMAILS: lista de e-mails reais separados por vírgula; o sistema escolhe um aleatório a cada análise.
#   Ex: comunicacao@novavelox.com.br,suporte@novavelox.com.br,vendas@novavelox.com.br
# CREDITO_EMAIL_MAILINATOR: se true, gera endereços @mailinator.com (aceitam envio; Nio pode bloquear o domínio).
CREDITO_EMAILS = config('CREDITO_EMAILS', default='')
CREDITO_EMAIL_MAILINATOR = config('CREDITO_EMAIL_MAILINATOR', default=True, cast=lambda v: str(v).lower() in ('true', '1', 'yes'))

# Google Street View Static API - foto automática na automação Inclusão/Viabilidade
GOOGLE_STREETVIEW_API_KEY = config('GOOGLE_STREETVIEW_API_KEY', default='')

# Funil de vendas (WhatsApp VENDER): grava tentativas e eventos no banco. Produção: FUNIL_VENDAS_REGISTRAR=true
FUNIL_VENDAS_REGISTRAR = config(
    'FUNIL_VENDAS_REGISTRAR',
    default=False,
    cast=lambda v: str(v).lower() in ('true', '1', 'yes'),
)

# --- Performance: cache folha de comissionamento (DatabaseCache, compartilhado entre workers) ---
FOLHA_COMISSAO_CACHE_ENABLED = config(
    'FOLHA_COMISSAO_CACHE_ENABLED',
    default=True,
    cast=lambda v: str(v).lower() in ('true', '1', 'yes'),
)
FOLHA_COMISSAO_CACHE_TTL = config('FOLHA_COMISSAO_CACHE_TTL', default=1800, cast=int)

# Webhook Z-API: processar em thread/fila e responder HTTP 200 imediatamente
WHATSAPP_WEBHOOK_ASYNC = config(
    'WHATSAPP_WEBHOOK_ASYNC',
    default=True,
    cast=lambda v: str(v).lower() in ('true', '1', 'yes'),
)
# "Enviar resumo": espera DeliveryCallback (entrega real) após messageId da API
WHATSAPP_DELIVERY_WAIT_SECONDS = config('WHATSAPP_DELIVERY_WAIT_SECONDS', default=25, cast=float)
WHATSAPP_DELIVERY_CACHE_TTL = config('WHATSAPP_DELIVERY_CACHE_TTL', default=180, cast=int)
# Webhook dedicado: web enfileira; serviço webhook consome (fila PostgreSQL, sem Redis)
WHATSAPP_USE_DEDICATED_WORKER = config(
    'WHATSAPP_USE_DEDICATED_WORKER',
    default=False,
    cast=lambda v: str(v).lower() in ('true', '1', 'yes'),
)
WHATSAPP_WORKER_MODE = config(
    'WHATSAPP_WORKER_MODE',
    default=False,
    cast=lambda v: str(v).lower() in ('true', '1', 'yes'),
)
WHATSAPP_WORKER_POLL_SECONDS = config('WHATSAPP_WORKER_POLL_SECONDS', default=1, cast=float)

# Gunicorn (scripts/start_web.sh): workers/threads configuráveis no Railway
GUNICORN_WORKERS = config('GUNICORN_WORKERS', default=2, cast=int)
GUNICORN_THREADS = config('GUNICORN_THREADS', default=2, cast=int)

STATIC_CACHE_MAX_AGE = config('STATIC_CACHE_MAX_AGE', default=86400, cast=int)
if DEBUG:
    # Evita cache agressivo de JS/CSS quebrado durante desenvolvimento local
    STATIC_CACHE_MAX_AGE = 0

# Rate limit folha de comissionamento (por usuário)
FOLHA_COMISSAO_RATE_LIMIT = config('FOLHA_COMISSAO_RATE_LIMIT', default=6, cast=int)
FOLHA_COMISSAO_RATE_PERIOD = config('FOLHA_COMISSAO_RATE_PERIOD', default=60, cast=int)
FOLHA_COMISSAO_TIMEOUT_SECONDS = config('FOLHA_COMISSAO_TIMEOUT_SECONDS', default=180, cast=int)

# PAP dedicado: web enfileira jobs; serviço pap consome (fila PostgreSQL, sem Redis)
PAP_USE_DEDICATED_WORKER = config(
    'PAP_USE_DEDICATED_WORKER',
    default=False,
    cast=lambda v: str(v).lower() in ('true', '1', 'yes'),
)
PAP_WORKER_MODE = config(
    'PAP_WORKER_MODE',
    default=False,
    cast=lambda v: str(v).lower() in ('true', '1', 'yes'),
)
PAP_WORKER_POLL_SECONDS = config('PAP_WORKER_POLL_SECONDS', default=2, cast=float)
# Watchdog da fila: processando sem heartbeat / pendente órfão (minutos).
PAP_JOB_STALE_PROCESSANDO_MINUTES = config('PAP_JOB_STALE_PROCESSANDO_MINUTES', default=12, cast=int)
PAP_JOB_STALE_PENDENTE_MINUTES = config('PAP_JOB_STALE_PENDENTE_MINUTES', default=10, cast=int)
# 0 = usa timeout por tipo (status=240s, credito=360s).
PAP_JOB_TIMEOUT_SECONDS = config('PAP_JOB_TIMEOUT_SECONDS', default=0, cast=int)

# Sentry (tier gratuito — definir SENTRY_DSN no Railway)
SENTRY_DSN = config('SENTRY_DSN', default='')
SENTRY_TRACES_SAMPLE_RATE = config('SENTRY_TRACES_SAMPLE_RATE', default=0.1, cast=float)

if SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[DjangoIntegration()],
        traces_sample_rate=SENTRY_TRACES_SAMPLE_RATE,
        send_default_pii=False,
        environment=config('RAILWAY_ENVIRONMENT', default='local'),
    )

# Cache: Redis (mesmo Redis das filas Celery - zero custo extra).
# KEY_PREFIX isola chaves do projeto 'site-rosso' no Redis compartilhado.
# DB 1 separado das filas Celery (que usam DB 0).
_REDIS_CACHE_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/1')
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.redis.RedisCache',
        'LOCATION': _REDIS_CACHE_URL,
        'KEY_PREFIX': 'site-rosso',
        'TIMEOUT': FOLHA_COMISSAO_CACHE_TTL,
    },
}

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'level': 'INFO',
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': True,
        },
        'django.request': {
            'handlers': ['console'],
            'level': 'ERROR',
            'propagate': False,
        },
    },
}

# CELERY CONFIGURATION
import os
CELERY_BROKER_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
CELERY_RESULT_BACKEND = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE


# CELERY BEAT SCHEDULE (Substituindo o antigo APScheduler)
from celery.schedules import crontab

CELERY_BEAT_SCHEDULE = {
    'buscar_faturas_diario': {
        'task': 'crm_app.tasks_celery.run_legacy_scheduler_job',
        'schedule': crontab(minute='*/20', hour='22-23,0-6'),
        'args': ('buscar_faturas_automatico',)
    },
    'finalizar_match_nio_noturno': {
        'task': 'crm_app.tasks_celery.run_legacy_scheduler_job',
        'schedule': crontab(minute='0', hour='7'),
        'args': ('finalizar_match_nio_noturno',)
    },
    'processar_envio_performance': {
        'task': 'crm_app.tasks_celery.run_legacy_scheduler_job',
        'schedule': crontab(minute='*/1'),
        'args': ('processar_envio_performance_agendado',)
    },
    'processar_relatorio_esteira_gc': {
        'task': 'crm_app.tasks_celery.run_legacy_scheduler_job',
        'schedule': crontab(minute='*/1'),
        'args': ('processar_relatorio_esteira_gc_agendado',)
    },
    'processar_relatorio_pendencia_cliente': {
        'task': 'crm_app.tasks_celery.run_legacy_scheduler_job',
        'schedule': crontab(minute='*/1'),
        'args': ('processar_relatorio_pendencia_cliente_agendado',)
    },
    'processar_fila_boas_vindas': {
        'task': 'crm_app.tasks_celery.run_legacy_scheduler_job',
        'schedule': crontab(minute='*/5'),
        'args': ('processar_fila_boas_vindas',)
    },
    'enviar_templates_cobranca_nio': {
        'task': 'crm_app.tasks_celery.run_legacy_scheduler_job',
        'schedule': crontab(minute='0', hour='9'),
        'args': ('enviar_templates_cobranca_nio',)
    },
    'processar_relatorio_tratamento': {
        'task': 'crm_app.tasks_celery.run_legacy_scheduler_job',
        'schedule': crontab(minute='*/1'),
        'args': ('processar_relatorio_tratamento_agendado',)
    },
    'encerrar_sessoes_tratamento_ociosas': {
        'task': 'crm_app.tasks_celery.run_legacy_scheduler_job',
        'schedule': crontab(minute='*/3'),
        'args': ('encerrar_sessoes_tratamento_ociosas',)
    },
    'processar_fallback_sonax_auditoria': {
        'task': 'crm_app.tasks_celery.run_legacy_scheduler_job',
        'schedule': crontab(minute='*/2'),
        'args': ('_processar_fallback_sonax_auditoria',)
    },
    'sync_status_esteira_pap_noturno': {
        'task': 'crm_app.tasks_celery.run_legacy_scheduler_job',
        'schedule': crontab(minute='0', hour='22'),
        'args': ('sync_status_esteira_pap_automatico',)
    },
    'preaquecer_cache_folha_6h': {
        'task': 'crm_app.tasks_celery.run_legacy_scheduler_job',
        'schedule': crontab(minute='0', hour='6'),
        'args': ('preaquecer_cache_folha_comissionamento',)
    },
    'preaquecer_cache_folha_12h': {
        'task': 'crm_app.tasks_celery.run_legacy_scheduler_job',
        'schedule': crontab(minute='0', hour='12'),
        'args': ('preaquecer_cache_folha_comissionamento',)
    },
    'lembrete_presenca_supervisor_10h': {
        'task': 'crm_app.tasks_celery.run_legacy_scheduler_job',
        'schedule': crontab(minute='0', hour='10', day_of_week='1-5'),
        'args': ('lembrete_presenca_supervisor_10h',)
    },
    'lembrete_presenca_supervisor_11h': {
        'task': 'crm_app.tasks_celery.run_legacy_scheduler_job',
        'schedule': crontab(minute='0', hour='11', day_of_week='1-5'),
        'args': ('lembrete_presenca_supervisor_11h',)
    },
    'aplicar_faltas_presenca_12h': {
        'task': 'crm_app.tasks_celery.run_legacy_scheduler_job',
        'schedule': crontab(minute='0', hour='12', day_of_week='1-5'),
        'args': ('aplicar_faltas_presenca_12h',)
    },
    'lista_agendamento_vendedor_manha': {
        'task': 'crm_app.tasks_celery.run_legacy_scheduler_job',
        'schedule': crontab(minute='30', hour='7'),
        'args': ('lista_agendamento_vendedor_manha',)
    },
    'lista_agendamento_vendedor_tarde': {
        'task': 'crm_app.tasks_celery.run_legacy_scheduler_job',
        'schedule': crontab(minute='30', hour='12'),
        'args': ('lista_agendamento_vendedor_tarde',)
    },
    'varrer_jobs_pendentes_pap': {
        'task': 'crm_app.tasks_celery.varrer_jobs_pendentes_pap',
        'schedule': 15.0,  # A cada 15 segundos
    },
}

CELERY_BROKER_TRANSPORT_OPTIONS = {'global_keyprefix': 'site-rosso'}

