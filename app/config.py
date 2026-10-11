"""Central configuration for the web UI.

Everything is overridable with environment variables so the same code can run on a
laptop, a Raspberry Pi or a rack server without edits.
"""
from __future__ import annotations

import os
import secrets
import stat
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"

# Mutable runtime state (auth secret, generated password) lives outside the code tree.
DATA_DIR = Path(
    os.environ.get("WEBUI_DATA_DIR", str(Path.home() / ".local" / "share" / "webui"))
)
DATA_DIR.mkdir(parents=True, exist_ok=True)

HOST = os.environ.get("WEBUI_HOST", "0.0.0.0")
PORT = int(os.environ.get("WEBUI_PORT", "8080"))

USERNAME = os.environ.get("WEBUI_USER", "admin")

# How often the dashboard websocket pushes a fresh metric snapshot (seconds).
METRICS_INTERVAL = float(os.environ.get("WEBUI_METRICS_INTERVAL", "2.0"))

# Signed session tokens are valid for this long by default.
TOKEN_TTL = int(os.environ.get("WEBUI_TOKEN_TTL", str(60 * 60 * 12)))  # 12h

# The file manager is jailed to this directory. "/" means no jail (admin box).
FILE_ROOT = Path(os.environ.get("WEBUI_FILE_ROOT", "/")).expanduser()

# Largest file the in-browser editor will open, in bytes.
MAX_EDIT_SIZE = int(os.environ.get("WEBUI_MAX_EDIT_SIZE", str(2 * 1024 * 1024)))

# Shell spawned for each web terminal session.
SHELL = os.environ.get("WEBUI_SHELL") or "/bin/bash"


def _read_or_create_secret(filename: str, nbytes: int = 32) -> str:
    """Persist a generated secret so sessions survive a restart."""
    path = DATA_DIR / filename
    try:
        value = path.read_text().strip()
        if value:
            return value
    except OSError:
        pass
    value = secrets.token_hex(nbytes)
    path.write_text(value)
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600
    except OSError:
        pass
    return value


SECRET_KEY = _read_or_create_secret("secret.key")


def _resolve_password() -> str:
    """Password order: env var -> stored password -> freshly generated one."""
    env_pw = os.environ.get("WEBUI_PASSWORD")
    if env_pw:
        return env_pw
    path = DATA_DIR / "password"
    try:
        value = path.read_text().strip()
        if value:
            return value
    except OSError:
        pass
    value = secrets.token_urlsafe(12)
    path.write_text(value)
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    return value


PASSWORD = _resolve_password()
