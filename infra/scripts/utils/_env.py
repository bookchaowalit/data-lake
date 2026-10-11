"""
Shared environment loader for Solo Empire Python scripts.
Loads infra/.env and provides computed paths.

Usage in scripts:
    from _env import PROJECT_ROOT, DB_PATH, get_google_creds, get_env
"""

import os
from pathlib import Path

# Project root is 4 levels up from this file: _env.py -> utils -> scripts -> infra -> solo-empire
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

# Canonical relative path from repository root
DEFAULT_DB_REL = Path("infra") / "database" / "solo-empire.db"
BACKUP_DIR = PROJECT_ROOT / "data" / "backups"
BRIEFINGS_DIR = PROJECT_ROOT / "data" / "generated" / "briefings"
DRAFTS_DIR = BRIEFINGS_DIR / "drafts"
RAW_DATA_DIR = PROJECT_ROOT / "data" / "raw"
KNOWLEDGE_BASE = PROJECT_ROOT / "knowledge"


# ── .env loader ─────────────────────────────────────────────
def load_env():
    """Load infra/.env into os.environ (idempotent)."""
    env_path = PROJECT_ROOT / "infra" / ".env"
    if not env_path.exists():
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            # Don't overwrite existing env vars (allow override from shell)
            if key not in os.environ:
                os.environ[key] = value


def resolve_db_path(env_value: str | None = None) -> Path:
    """
    Resolve the SQLite path the test doubles use.

    The control-plane database was retired on 2026-10-11 (archived outside the
    repository); production code never opens it. Tests point their SQLite
    doubles at a temporary file through SOLO_EMPIRE_DB_PATH.

    Uses SOLO_EMPIRE_DB_PATH when set:
    - absolute path → used as-is (after expanduser)
    - relative path → resolved from PROJECT_ROOT (not CWD)

    Default when unset: <PROJECT_ROOT>/infra/database/solo-empire.db
    """
    if env_value is None:
        env_value = os.environ.get("SOLO_EMPIRE_DB_PATH")
    if env_value is None or str(env_value).strip() == "":
        return (PROJECT_ROOT / DEFAULT_DB_REL).resolve()

    path = Path(str(env_value).strip()).expanduser()
    if path.is_absolute():
        return path.resolve()
    return (PROJECT_ROOT / path).resolve()


# Load on import
load_env()

# ── Computed paths ──────────────────────────────────────────
DB_PATH = resolve_db_path()


# ── Secret accessors ────────────────────────────────────────
def _looks_like_secret(key):
    """Identify credential-shaped env names without treating normal config as secrets."""
    name = key.upper()
    markers = (
        "_TOKEN", "_SECRET", "_PASSWORD", "_PASS", "_API_KEY", "_ACCESS_KEY",
        "_PRIVATE_KEY", "_WEBHOOK_URL", "_DATABASE_URL", "_CLIENT_ID", "_CHAT_ID",
    )
    return any(name.endswith(marker) for marker in markers)


def get_env(key, default=None, required=False):
    """Get config; credential-shaped names resolve through the secret provider."""
    if _looks_like_secret(key):
        return get_secret(key, default=default, required=required)
    value = os.environ.get(key, default)
    if required and not value:
        raise ValueError(f"Required env var {key} is not set. Check infra/.env or infra/.env.example")
    return value


def get_secret(key, default=None, required=False):
    """Resolve a secret from the configured runtime provider or env fallback."""
    from secret_resolver import SecretUnavailable, get_secret as resolve_secret

    try:
        value = resolve_secret(key, default=default, required=required)
    except SecretUnavailable:
        if required:
            raise ValueError(
                f"Required env var {key} is not set. Check infra/.env or secret provider configuration"
            ) from None
        return default
    return value


def get_google_creds():
    """Return Google OAuth credentials from Infisical/Vault/env."""
    return (
        get_secret("GOOGLE_CLIENT_ID", required=True),
        get_secret("GOOGLE_CLIENT_SECRET", required=True),
        get_secret("GOOGLE_REFRESH_TOKEN", required=True),
    )


def get_google_alt_creds():
    """Return alternate Google OAuth creds (used by get_google_refresh_token.py utility)."""
    return (
        get_secret("GOOGLE_CLIENT_ID_ALT", required=True),
        get_secret("GOOGLE_CLIENT_SECRET_ALT", required=True),
    )


def get_cloudflare_token():
    """Return Cloudflare API token from environment (or legacy settings.json)."""
    token = get_secret("CLOUDFLARE_API_TOKEN")
    if token:
        return token
    # Fallback: try legacy Qwen settings
    import json
    settings_path = os.path.expanduser("~/.qwen/settings.json")
    if os.path.exists(settings_path):
        with open(settings_path) as f:
            settings = json.load(f)
            return settings.get("env", {}).get("CLOUDFLARE_API_TOKEN")
    return None


def get_strava_token():
    """Return Strava access token from environment."""
    return get_secret("STRAVA_ACCESS_TOKEN")


def get_binance_th_creds():
    """Return (api_key, api_secret) for Binance TH from environment."""
    return (
        get_secret("BINANCE_TH_API_KEY"),
        get_secret("BINANCE_TH_API_SECRET"),
    )
