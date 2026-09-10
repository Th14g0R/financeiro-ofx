import os
import sys
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")


SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]

DEBUG = os.getenv("DJANGO_DEBUG", "False").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv(
        "DJANGO_ALLOWED_HOSTS",
        "127.0.0.1,localhost",
    ).split(",")
    if host.strip()
]


INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    "core.apps.CoreConfig",
    "finance.apps.FinanceConfig",
    "imports.apps.ImportsConfig",
    "integrations.apps.IntegrationsConfig",
]


MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "core.middleware.AuditTrailMiddleware",
    "core.middleware.SensitiveSurfaceMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.middleware.SecurityHeadersMiddleware",
]


ROOT_URLCONF = "config.urls"


TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.access_context",
            ],
        },
    },
]


WSGI_APPLICATION = "config.wsgi.application"


DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}


AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "UserAttributeSimilarityValidator"
        ),
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "MinimumLengthValidator"
        ),
        "OPTIONS": {
            "min_length": 8,
        },
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "CommonPasswordValidator"
        ),
    },
    {
        "NAME": (
            "django.contrib.auth.password_validation."
            "NumericPasswordValidator"
        ),
    },
]


LANGUAGE_CODE = "pt-br"

TIME_ZONE = "America/Fortaleza"

USE_I18N = True

USE_TZ = True


# ------------------------------------------------------------------
# Pluggy / Meu Pluggy
# ------------------------------------------------------------------
# Em Development Application, o fluxo pessoal mais previsível é autorizar
# pelo "Ir para Demo" do Pluggy Dashboard e registrar o Item ID no
# Financeiro. O widget embutido fica opt-in para não induzir o usuário a
# contornar restrições do ambiente Demo por configuração de frontend.
PLUGGY_EMBEDDED_CONNECT_ENABLED = os.getenv(
    "PLUGGY_EMBEDDED_CONNECT_ENABLED",
    "False",
).strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}


STATIC_URL = "static/"

STATICFILES_DIRS = [
    BASE_DIR / "static",
]

STATIC_ROOT = BASE_DIR / "staticfiles"

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": (
            "whitenoise.storage.CompressedManifestStaticFilesStorage"
        ),
    },
}


# A suíte Django não executa collectstatic automaticamente.
# Portanto, durante `manage.py test`, use um storage sem manifesto.
# Em execução normal/produção, WhiteNoise continua usando arquivos
# versionados por hash após collectstatic.
if "test" in sys.argv:
    STORAGES["staticfiles"] = {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
        ),
    }

MEDIA_URL = "media/"

MEDIA_ROOT = BASE_DIR / "media"


DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


LOGIN_URL = "login"

LOGIN_REDIRECT_URL = "home"

LOGOUT_REDIRECT_URL = "login"


# ------------------------------------------------------------------
# Recuperação de senha por e-mail
# ------------------------------------------------------------------
EMAIL_BACKEND = os.getenv(
    "EMAIL_BACKEND",
    "django.core.mail.backends.smtp.EmailBackend",
)
EMAIL_HOST = os.getenv(
    "EMAIL_HOST",
    "",
).strip()
EMAIL_PORT = int(
    os.getenv(
        "EMAIL_PORT",
        "587",
    )
)
EMAIL_HOST_USER = os.getenv(
    "EMAIL_HOST_USER",
    "",
).strip()
EMAIL_HOST_PASSWORD = os.getenv(
    "EMAIL_HOST_PASSWORD",
    "",
)
EMAIL_USE_TLS = os.getenv(
    "EMAIL_USE_TLS",
    "True",
).strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
EMAIL_USE_SSL = os.getenv(
    "EMAIL_USE_SSL",
    "False",
).strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
EMAIL_TIMEOUT = int(
    os.getenv(
        "EMAIL_TIMEOUT_SECONDS",
        "15",
    )
)
DEFAULT_FROM_EMAIL = os.getenv(
    "DEFAULT_FROM_EMAIL",
    EMAIL_HOST_USER or "financeiro-ofx@localhost",
).strip()
PASSWORD_RECOVERY_EMAIL_ENABLED = os.getenv(
    "PASSWORD_RECOVERY_EMAIL_ENABLED",
    "False",
).strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
PASSWORD_RESET_TIMEOUT = int(
    os.getenv(
        "PASSWORD_RESET_TIMEOUT_SECONDS",
        "3600",
    )
)


# ------------------------------------------------------------------
# Segurança
# ------------------------------------------------------------------

SECURE_MODE = os.getenv(
    "DJANGO_SECURE_MODE",
    "False",
).strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = int(
    os.getenv(
        "DJANGO_SESSION_AGE_SECONDS",
        "1800",
    )
)
SESSION_SAVE_EVERY_REQUEST = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = True

CSRF_COOKIE_SAMESITE = "Lax"

SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

SESSION_COOKIE_SECURE = SECURE_MODE
CSRF_COOKIE_SECURE = SECURE_MODE
SECURE_SSL_REDIRECT = SECURE_MODE

# HSTS começa conservadoramente. Aumente após validar o HTTPS em produção.
SECURE_HSTS_SECONDS = (
    int(
        os.getenv(
            "DJANGO_HSTS_SECONDS",
            "3600",
        )
    )
    if SECURE_MODE
    else 0
)
SECURE_HSTS_INCLUDE_SUBDOMAINS = (
    os.getenv(
        "DJANGO_HSTS_INCLUDE_SUBDOMAINS",
        "False",
    ).strip().lower()
    in {
        "1",
        "true",
        "yes",
        "on",
    }
)
SECURE_HSTS_PRELOAD = False

CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "DJANGO_CSRF_TRUSTED_ORIGINS",
        "",
    ).split(",")
    if origin.strip()
]

TRUST_PROXY_SSL_HEADER = os.getenv(
    "DJANGO_TRUST_PROXY_SSL_HEADER",
    "False",
).strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

if TRUST_PROXY_SSL_HEADER:
    SECURE_PROXY_SSL_HEADER = (
        "HTTP_X_FORWARDED_PROTO",
        "https",
    )

# Limites de upload/POST como defesa adicional contra abuso de recursos.
FILE_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
DATA_UPLOAD_MAX_NUMBER_FIELDS = 1000
DATA_UPLOAD_MAX_NUMBER_FILES = 25
FILE_UPLOAD_PERMISSIONS = 0o600

# Rate limit de login. Dois buckets independentes: usuário e IP.
LOGIN_THROTTLE_USERNAME_MAX = int(
    os.getenv(
        "LOGIN_THROTTLE_USERNAME_MAX",
        "5",
    )
)
LOGIN_THROTTLE_IP_MAX = int(
    os.getenv(
        "LOGIN_THROTTLE_IP_MAX",
        "20",
    )
)
LOGIN_THROTTLE_WINDOW_SECONDS = int(
    os.getenv(
        "LOGIN_THROTTLE_WINDOW_SECONDS",
        "900",
    )
)
LOGIN_THROTTLE_LOCK_SECONDS = int(
    os.getenv(
        "LOGIN_THROTTLE_LOCK_SECONDS",
        "900",
    )
)
