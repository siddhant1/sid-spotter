"""Django settings for the Safe Route planner.

Everything environment-specific is read from env vars so the same image runs
locally and on the host.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BASE_DIR.parent


def env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).lower() in {"1", "true", "yes", "on"}


SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-insecure-key-change-me")
DEBUG = env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = [h for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",") if h]
CSRF_TRUSTED_ORIGINS = [o for o in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o]

INSTALLED_APPS = [
    "django.contrib.staticfiles",
    "rest_framework",
    "planner",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.middleware.gzip.GZipMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "config.urls"

# The production build of the React app (frontend/dist) is served by Django:
# index.html as a template, hashed assets through WhiteNoise.
FRONTEND_DIST = Path(os.environ.get("FRONTEND_DIST", REPO_DIR / "frontend" / "dist"))

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [FRONTEND_DIST],
        "APP_DIRS": False,
        "OPTIONS": {"context_processors": []},
    }
]

WSGI_APPLICATION = "config.wsgi.application"

# No models: the app is stateless apart from the forecast cache.
DATABASES = {}

CACHES = {
    "default": {
        # File cache so every gunicorn worker shares upstream API responses.
        "BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
        "LOCATION": os.environ.get("CACHE_DIR", "/tmp/saferoute-cache"),
        "TIMEOUT": 30 * 60,
        "OPTIONS": {"MAX_ENTRIES": 20000},
    }
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = False
USE_TZ = True

STATIC_URL = "/assets/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [FRONTEND_DIST / "assets"] if (FRONTEND_DIST / "assets").exists() else []
STORAGES = {
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": [],
    "UNAUTHENTICATED_USER": None,
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
}

# --- Upstream services (all free / keyless by default) ---------------------
OSRM_URL = os.environ.get("OSRM_URL", "https://router.project-osrm.org")
PHOTON_URL = os.environ.get("PHOTON_URL", "https://photon.komoot.io")
OPEN_METEO_URL = os.environ.get("OPEN_METEO_URL", "https://api.open-meteo.com/v1/forecast")
OPEN_METEO_API_KEY = os.environ.get("OPEN_METEO_API_KEY", "")
HTTP_USER_AGENT = os.environ.get("HTTP_USER_AGENT", "SafeRoutePlanner/1.0 (truck weather routing demo)")

# --- Planning model ---------------------------------------------------------
# OSRM's public server only has a car profile. Trucks are slower on fast roads,
# so each segment is capped at this speed when estimating arrival times.
TRUCK_MAX_SPEED_MPH = float(os.environ.get("TRUCK_MAX_SPEED_MPH", "65"))
MAX_DEPARTURE_DAYS_AHEAD = 7

if not DEBUG:
    # Hosts like Render terminate TLS at a proxy.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
