from pathlib import Path

BASE_DIR = Path(__file__).parent.absolute()

SECRET_KEY = "FOOBAR"

MIDDLEWARE = []
INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
]

RATELIMIT_DEFAULT_CACHE = "default"

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "cache-ratelimits",
    },
    "db": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "cache-ratelimits",
    },
}

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    },
}
