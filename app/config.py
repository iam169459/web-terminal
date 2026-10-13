"""Central configuration for the web UI.

Everything is overridable with environment variables so the same code can run on a
laptop, a Raspberry Pi or a rack server without edits.
"""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"

# Mutable runtime state (update log, …) lives outside the code tree.
DATA_DIR = Path(
    os.environ.get("WEBUI_DATA_DIR", str(Path.home() / ".local" / "share" / "webui"))
)
DATA_DIR.mkdir(parents=True, exist_ok=True)

# No authentication: bind to localhost only by default so the UI (and its root
# shell) is never exposed to the network unless explicitly asked for.
HOST = os.environ.get("WEBUI_HOST", "127.0.0.1")
PORT = int(os.environ.get("WEBUI_PORT", "8080"))

USERNAME = os.environ.get("WEBUI_USER", "admin")

# How often the dashboard websocket pushes a fresh metric snapshot (seconds).
METRICS_INTERVAL = float(os.environ.get("WEBUI_METRICS_INTERVAL", "2.0"))

# The file manager is jailed to this directory. "/" means no jail (admin box).
FILE_ROOT = Path(os.environ.get("WEBUI_FILE_ROOT", "/")).expanduser()

# Largest file the in-browser editor will open, in bytes.
MAX_EDIT_SIZE = int(os.environ.get("WEBUI_MAX_EDIT_SIZE", str(2 * 1024 * 1024)))

# Shell spawned for each web terminal session.
SHELL = os.environ.get("WEBUI_SHELL") or "/bin/bash"
