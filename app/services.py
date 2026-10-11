"""systemd service control.

Commands go through ``systemctl``/``journalctl``. When the UI runs as a normal user we
transparently prefix ``sudo -n`` if (and only if) passwordless sudo is available.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from typing import Any, Dict, List, Optional

SYSTEMCTL = shutil.which("systemctl")
JOURNALCTL = shutil.which("journalctl")
SUDO = shutil.which("sudo")

_UNIT_RE = re.compile(r"^[A-Za-z0-9@_.\-]+$")
_SUDO_OK: Optional[bool] = None

ACTIONS = {
    "start": "start",
    "stop": "stop",
    "restart": "restart",
    "reload": "reload",
    "enable": "enable",
    "disable": "disable",
    "mask": "mask",
    "unmask": "unmask",
}


def available() -> bool:
    return bool(SYSTEMCTL)


def _use_sudo() -> bool:
    global _SUDO_OK
    if os.geteuid() == 0:
        return False
    if os.environ.get("WEBUI_SYSTEMCTL_SUDO", "").lower() in ("0", "false", "no"):
        return False
    if not SUDO:
        return False
    if _SUDO_OK is None:
        try:
            _SUDO_OK = subprocess.run(
                [SUDO, "-n", "true"], capture_output=True, timeout=5
            ).returncode == 0
        except (OSError, subprocess.SubprocessError):
            _SUDO_OK = False
    return _SUDO_OK


def _run(args: List[str], timeout: int = 30) -> subprocess.CompletedProcess:
    cmd = ([SUDO, "-n"] if _use_sudo() else []) + args
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _validate_unit(unit: str) -> str:
    unit = (unit or "").strip()
    if not unit or not _UNIT_RE.match(unit):
        raise ValueError(f"Invalid unit name: {unit!r}")
    return unit


def list_services() -> Dict[str, Any]:
    if not available():
        return {"available": False, "services": [], "sudo": False, "error": "systemctl not found"}

    units: Dict[str, Dict[str, Any]] = {}
    try:
        proc = _run(
            [
                SYSTEMCTL, "list-units", "--type=service", "--all",
                "--no-pager", "--no-legend", "--plain",
            ],
            timeout=20,
        )
    except subprocess.TimeoutExpired:
        return {"available": True, "services": [], "sudo": _use_sudo(), "error": "systemctl timed out"}

    for line in proc.stdout.splitlines():
        parts = line.split(None, 4)
        if len(parts) < 4:
            continue
        unit, load, active, sub = parts[0], parts[1], parts[2], parts[3]
        description = parts[4] if len(parts) > 4 else ""
        if not unit.endswith(".service"):
            continue
        units[unit] = {
            "unit": unit,
            "load": load,
            "active": active,
            "sub": sub,
            "description": description.strip(),
            "enabled": None,
        }

    # Merge in the on-boot state, which list-units does not show.
    try:
        files = _run(
            [SYSTEMCTL, "list-unit-files", "--type=service", "--no-pager", "--no-legend"],
            timeout=20,
        )
        for line in files.stdout.splitlines():
            parts = line.split(None, 1)
            if len(parts) != 2:
                continue
            unit, state = parts[0].strip(), parts[1].strip().split()[0]
            if unit in units:
                units[unit]["enabled"] = state
            else:
                units[unit] = {
                    "unit": unit, "load": "-", "active": "inactive", "sub": "dead",
                    "description": "", "enabled": state,
                }
    except (subprocess.TimeoutExpired, OSError):
        pass

    services = sorted(units.values(), key=lambda s: s["unit"].lower())
    return {
        "available": True,
        "sudo": _use_sudo(),
        "total": len(services),
        "running": sum(1 for s in services if s["active"] == "active"),
        "failed": sum(1 for s in services if s["active"] == "failed"),
        "services": services,
    }


def service_status(unit: str) -> Dict[str, Any]:
    unit = _validate_unit(unit)
    if not available():
        raise RuntimeError("systemctl not found")
    proc = _run([SYSTEMCTL, "status", unit, "--no-pager", "-l", "-n", "30"], timeout=20)
    return {
        "unit": unit,
        "output": proc.stdout or proc.stderr,
        "returncode": proc.returncode,
    }


def service_logs(unit: str, lines: int = 200) -> Dict[str, Any]:
    unit = _validate_unit(unit)
    lines = max(1, min(int(lines), 2000))
    if not JOURNALCTL:
        raise RuntimeError("journalctl not found")
    proc = _run(
        [JOURNALCTL, "-u", unit, "-n", str(lines), "--no-pager", "-o", "short-iso"],
        timeout=25,
    )
    output = proc.stdout or proc.stderr
    if proc.returncode != 0 and not output.strip():
        output = "(no log output - journal may require elevated privileges)"
    return {"unit": unit, "lines": lines, "output": output, "returncode": proc.returncode}


def service_action(unit: str, action: str) -> Dict[str, Any]:
    unit = _validate_unit(unit)
    if action not in ACTIONS:
        raise ValueError(f"Unknown action: {action}")
    if not available():
        raise RuntimeError("systemctl not found")

    try:
        proc = _run([SYSTEMCTL, ACTIONS[action], unit], timeout=60)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"systemctl {action} timed out") from exc

    ok = proc.returncode == 0
    detail = (proc.stderr or proc.stdout or "").strip()
    try:
        state = _run([SYSTEMCTL, "is-active", unit], timeout=10).stdout.strip()
    except (subprocess.TimeoutExpired, OSError):
        state = "unknown"
    return {
        "ok": ok,
        "unit": unit,
        "action": action,
        "state": state,
        "message": detail,
        "returncode": proc.returncode,
    }
