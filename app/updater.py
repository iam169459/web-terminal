"""Self-update: fetch the latest code, reinstall dependencies, restart the server.

The actual work runs in a **detached helper process** rather than inside the request
handler, because the server has to be killed and restarted - doing that from a thread
that is serving the response would drop the connection and leave the tree in a
half-updated state.

Flow: ``POST /api/update/run`` spawns the helper and returns immediately. The helper
waits for this process to exit, resets the tree to ``origin/<branch>``, installs
``requirements.txt`` and starts the server again. Progress is written to a log file the
status endpoint tails, so the browser can watch it across the restart.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import config

GIT = shutil.which("git")
PYTHON = str(Path(sys.executable).absolute())  # absolute(), NOT resolve(): keep the venv symlink
MODULE = "app.main"
LOG_FILE = config.DATA_DIR / "update.log"
GIT_DIR = config.BASE_DIR / ".git"

_LOCK = threading.Lock()
STATE: Dict[str, Any] = {
    "running": False,
    "phase": "idle",
    "started_at": None,
    "started_pid": None,
}


def _git(*args: str, timeout: int = 30) -> subprocess.CompletedProcess:
    if not GIT:
        raise RuntimeError("git is not installed")
    return subprocess.run(
        [GIT, "-C", str(config.BASE_DIR), *args],
        capture_output=True, text=True, timeout=timeout,
    )


def _ok(proc: subprocess.CompletedProcess) -> Optional[str]:
    """Return stripped stdout when the command succeeded, otherwise None."""
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def available() -> bool:
    """True when this install is a git checkout that can be updated."""
    return bool(GIT) and GIT_DIR.exists()


def current_info() -> Dict[str, Any]:
    info: Dict[str, Any] = {
        "available": available(),
        "git_installed": bool(GIT),
        "path": str(config.BASE_DIR),
        "python": PYTHON,
    }
    if not info["available"]:
        return info

    info["sha"] = _ok(_git("rev-parse", "--short", "HEAD")) or "unknown"
    info["full_sha"] = _ok(_git("rev-parse", "HEAD")) or "unknown"
    info["branch"] = _ok(_git("rev-parse", "--abbrev-ref", "HEAD")) or "main"
    info["message"] = _ok(_git("log", "-1", "--pretty=%s")) or ""
    info["date"] = _ok(_git("log", "-1", "--pretty=%cI")) or ""
    info["author"] = _ok(_git("log", "-1", "--pretty=%an")) or ""
    info["remote_url"] = _ok(_git("config", "--get", "remote.origin.url"))
    info["dirty"] = bool(_ok(_git("status", "--porcelain")))
    return info


def check_for_updates(fetch: bool = True) -> Dict[str, Any]:
    """Compare HEAD against its upstream. ``fetch`` refreshes the remote refs."""
    info = current_info()
    if not info["available"]:
        info.update({"update_available": None, "behind": 0, "ahead": 0,
                     "error": "Not a git checkout - nothing to update against."})
        return info

    upstream = _ok(_git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"))
    if fetch:
        try:
            _git("fetch", "--quiet", "--prune", "origin", timeout=120)
        except (subprocess.TimeoutExpired, RuntimeError) as exc:
            info["fetch_error"] = str(exc)

    if not upstream:
        # No tracking branch configured - fall back to origin/<current branch>.
        upstream = f"origin/{info['branch']}"
        if not _ok(_git("rev-parse", "--verify", "--quiet", upstream)):
            info.update({"update_available": False, "behind": 0, "ahead": 0,
                         "error": "No upstream branch configured."})
            return info

    info["upstream"] = upstream
    behind = _ok(_git("rev-list", "--count", f"HEAD..{upstream}"))
    ahead = _ok(_git("rev-list", "--count", f"{upstream}..HEAD"))
    info["behind"] = int(behind or 0)
    info["ahead"] = int(ahead or 0)
    info["update_available"] = info["behind"] > 0

    if info["behind"] > 0:
        info["latest_sha"] = _ok(_git("rev-parse", "--short", upstream))
        info["latest_message"] = _ok(_git("log", "-1", "--pretty=%s", upstream))
        info["latest_date"] = _ok(_git("log", "-1", "--pretty=%cI", upstream))
        info["incoming"] = _incoming_commits(upstream, 10)
    return info


def _incoming_commits(upstream: str, limit: int) -> List[Dict[str, str]]:
    proc = _git("log", "--no-decorate", f"-{limit}", "--pretty=%h%x1f%s%x1f%an%x1f%cI", f"HEAD..{upstream}")
    out: List[Dict[str, str]] = []
    for line in (proc.stdout or "").splitlines():
        parts = line.split("\x1f")
        if len(parts) == 4:
            out.append({"sha": parts[0], "message": parts[1], "author": parts[2], "date": parts[3]})
    return out


def _restart_mode() -> str:
    """Under systemd we simply exit and let it restart us; otherwise relaunch ourselves."""
    if os.environ.get("INVOCATION_ID") and shutil.which("systemctl"):
        return "systemd"
    return "manual"


def _tail_log(lines: int = 120) -> str:
    try:
        content = LOG_FILE.read_text(errors="replace")
    except OSError:
        return ""
    return "\n".join(content.splitlines()[-lines:])


def status() -> Dict[str, Any]:
    with _LOCK:
        running = STATE["running"]
        phase = STATE["phase"]
        started_at = STATE["started_at"]

    # Once the helper takes over, the log file is the source of truth.
    log = _tail_log()
    if running and ("done" in log or "ERROR" in log):
        phase = "complete" if "done" in log else "failed"

    return {
        "available": available(),
        "running": running,
        "phase": phase,
        "started_at": started_at,
        "restart_mode": _restart_mode(),
        "log": log,
        "info": check_for_updates(fetch=False),
    }


def _script_body() -> str:
    """Shell helper executed by the detached process."""
    return r'''#!/usr/bin/env bash
# Detached self-updater spawned by Server Console. Do not edit.
set -uo pipefail

DIR="$1"; PID="$2"; PY="$3"; LOG="$4"; MODULE="$5"; MODE="$6"

say() { echo "[$(date '+%H:%M:%S')] $*" >>"$LOG"; }

say "update started (helper pid $$, replacing server pid $PID, mode $MODE)"

say "waiting for the running server to stop..."
for _ in $(seq 1 40); do
  kill -0 "$PID" 2>/dev/null || break
  sleep 0.5
done
kill -9 "$PID" 2>/dev/null
say "old server stopped"

cd "$DIR" || { say "ERROR: cannot cd into $DIR"; exit 1; }

OLD=$(git rev-parse --short HEAD 2>/dev/null || echo unknown)
say "current commit: $OLD"
say "fetching from origin..."
if ! git fetch --quiet --prune origin >>"$LOG" 2>&1; then
  say "WARNING: git fetch failed - continuing with existing refs"
fi

BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo main)
TARGET="origin/$BRANCH"
if git rev-parse --verify --quiet "$TARGET" >/dev/null; then
  say "resetting to $TARGET (local modifications are discarded)"
  git reset --hard "$TARGET" >>"$LOG" 2>&1 || say "WARNING: git reset failed"
else
  say "WARNING: $TARGET not found - skipping checkout"
fi

NEW=$(git rev-parse --short HEAD 2>/dev/null || echo unknown)
say "now at commit: $NEW (was $OLD)"

if [ -f requirements.txt ]; then
  say "installing dependencies..."
  if ! "$PY" -m pip install --quiet --upgrade -r requirements.txt >>"$LOG" 2>&1; then
    say "WARNING: dependency install reported errors"
  fi
fi

if [ "$MODE" = "systemd" ]; then
  say "restarting: exiting so systemd can restart the service"
  say "done"
  exit 0
fi

say "starting the updated server..."
cd "$DIR" || { say "ERROR: cannot cd into $DIR"; exit 1; }
SRVLOG="$(dirname "$4")/server.log"
nohup "$PY" -m "$MODULE" >>"$SRVLOG" 2>&1 &
say "done - new server pid $! (logging to $SRVLOG)"
'''


def run_update() -> Dict[str, Any]:
    """Kick off a detached update. Raises RuntimeError if one is already running."""
    if not available():
        raise RuntimeError("This install is not a git checkout, so it cannot self-update")

    with _LOCK:
        if STATE["running"]:
            raise RuntimeError("An update is already in progress")
        STATE.update({"running": True, "phase": "starting", "started_at": time.time()})

    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as fh:
        fh.write(f"\n{'=' * 60}\n")

    script_path = Path(tempfile.mkstemp(prefix="webui-update-", suffix=".sh")[1])
    script_path.write_text(_script_body())
    script_path.chmod(0o700)

    try:
        proc = subprocess.Popen(
            [
                "/bin/bash", str(script_path),
                str(config.BASE_DIR),
                str(os.getpid()),
                PYTHON,
                str(LOG_FILE),
                MODULE,
                _restart_mode(),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,   # detach from our process group/session
            cwd=str(config.BASE_DIR),
        )
    except OSError as exc:
        with _LOCK:
            STATE.update({"running": False, "phase": "failed"})
        script_path.unlink(missing_ok=True)
        raise RuntimeError(f"Could not start the updater: {exc}") from exc

    with _LOCK:
        STATE["started_pid"] = proc.pid
        STATE["phase"] = "running"

    # The helper outlives us, so the temp script is safe to remove shortly after.
    threading.Timer(5.0, lambda: script_path.unlink(missing_ok=True)).start()
    return {
        "started": True,
        "helper_pid": proc.pid,
        "restart_mode": _restart_mode(),
        "log": str(LOG_FILE),
    }


def clear_log() -> None:
    try:
        LOG_FILE.unlink(missing_ok=True)
    except OSError:
        pass
