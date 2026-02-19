"""Django settings for testing nautobot_route_tracking plugin.

Imports all Nautobot defaults and adds the plugin to INSTALLED_APPS.
Used as DJANGO_SETTINGS_MODULE for pytest.
"""

import os

from nautobot.core.settings import *  # noqa: F403

# Testing overrides
SECRET_KEY = os.environ.get("NAUTOBOT_SECRET_KEY", "testing-secret-key")
ALLOWED_HOSTS = ["*"]
DEBUG = True

# Database
DATABASES = {
    "default": {
        "NAME": os.environ.get("NAUTOBOT_DB_NAME", "nautobot"),
        "USER": os.environ.get("NAUTOBOT_DB_USER", "nautobot"),
        "PASSWORD": os.environ.get("NAUTOBOT_DB_PASSWORD", "nautobot"),
        "HOST": os.environ.get("NAUTOBOT_DB_HOST", "localhost"),
        "PORT": os.environ.get("NAUTOBOT_DB_PORT", "5432"),
        "CONN_MAX_AGE": 300,
        "ENGINE": "django.db.backends.postgresql",
    }
}

# Redis/Cache
_REDIS_HOST = os.environ.get("NAUTOBOT_REDIS_HOST", "localhost")
_REDIS_PORT = os.environ.get("NAUTOBOT_REDIS_PORT", "6379")

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": f"redis://{_REDIS_HOST}:{_REDIS_PORT}/0",
        "TIMEOUT": 300,
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
        },
    }
}

CELERY_BROKER_URL = f"redis://{_REDIS_HOST}:{_REDIS_PORT}/1"
CELERY_RESULT_BACKEND = CELERY_BROKER_URL

# Register the plugin
PLUGINS = ["nautobot_route_tracking"]
PLUGINS_CONFIG = {
    "nautobot_route_tracking": {
        "retention_days": 90,
    }
}

# Required for pytest-django: PLUGINS is only processed by nautobot-server,
# not by django.setup(). This ensures the app is in INSTALLED_APPS for pytest.
INSTALLED_APPS.append("nautobot_route_tracking")  # noqa: F405

# Register plugin URLs under plugins:/plugins-api: namespaces for pytest.
# nautobot-server does this automatically via PLUGINS, but pytest-django does not.
ROOT_URLCONF = "tests.test_urls"
