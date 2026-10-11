"""Process listing and signalling."""
from __future__ import annotations

import os
import signal
from typing import Any, Dict, List

import psutil

# Reuse Process objects between requests: psutil only produces a meaningful
# ``cpu_percent`` when it can compare against its own previous sample.
_PROC_CACHE: Dict[int, psutil.Process] = {}

_SORT_FIELDS = {
    "cpu": lambda p: p["cpu_percent"],
    "mem": lambda p: p["memory_percent"],
    "pid": lambda p: p["pid"],
    "name": lambda p: (p["name"] or "").lower(),
    "user": lambda p: (p["username"] or "").lower(),
    "started": lambda p: p["create_time"],
    "status": lambda p: p["status"],
}


def list_processes(
    sort: str = "cpu", direction: str = "desc", search: str = "", limit: int = 500
) -> Dict[str, Any]:
    me = os.getpid()
    rows: List[Dict[str, Any]] = []
    seen_pids = set()

    attrs = [
        "pid", "ppid", "name", "username", "cpu_percent", "memory_percent",
        "memory_info", "status", "create_time", "num_threads", "cmdline",
    ]
    for proc in psutil.process_iter(attrs):
        try:
            info = proc.info
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        pid = info["pid"]
        if pid == me:
            continue  # never list (or offer to kill) the web UI itself
        seen_pids.add(pid)
        cached = _PROC_CACHE.get(pid)
        if cached is None:
            try:
                cached = proc
                _PROC_CACHE[pid] = proc
            except psutil.Error:
                pass
        mem_info = info.get("memory_info")
        cmdline = " ".join(info.get("cmdline") or [])
        rows.append(
            {
                "pid": pid,
                "ppid": info.get("ppid"),
                "name": info.get("name") or "?",
                "user": info.get("username") or "?",
                "cpu_percent": round(info.get("cpu_percent") or 0.0, 1),
                "memory_percent": round(info.get("memory_percent") or 0.0, 1),
                "memory_rss": getattr(mem_info, "rss", 0) or 0,
                "status": info.get("status") or "?",
                "create_time": info.get("create_time") or 0,
                "num_threads": info.get("num_threads"),
                "cmdline": cmdline,
            }
        )

    # Drop dead pids from the cache so it cannot grow forever.
    for pid in list(_PROC_CACHE):
        if pid not in seen_pids:
            _PROC_CACHE.pop(pid, None)

    if search:
        needle = search.lower()
        rows = [r for r in rows if needle in r["name"].lower() or needle in r["cmdline"].lower()]

    key = _SORT_FIELDS.get(sort, _SORT_FIELDS["cpu"])
    reverse = direction != "asc"
    try:
        rows.sort(key=key, reverse=reverse)
    except TypeError:
        rows.sort(key=_SORT_FIELDS["cpu"], reverse=True)

    total = len(rows)
    return {"total": total, "processes": rows[: max(limit, 1)]}


def signal_process(pid: int, action: str = "term") -> Dict[str, Any]:
    """``term`` (graceful), ``kill`` (SIGKILL) or ``stop``/``cont`` (SIGSTOP/SIGCONT)."""
    if pid <= 1:
        raise ValueError("Refusing to signal PID 1")
    try:
        proc = psutil.Process(pid)
    except psutil.NoSuchProcess:
        raise ValueError(f"No such process: {pid}")
    except psutil.AccessDenied:
        raise PermissionError(f"Permission denied for pid {pid}")

    mapping = {
        "term": ("terminate", signal.SIGTERM),
        "kill": ("kill", signal.SIGKILL),
        "stop": (None, signal.SIGSTOP),
        "cont": (None, signal.SIGCONT),
        "hup": (None, signal.SIGHUP),
        "int": (None, signal.SIGINT),
    }
    if action not in mapping:
        raise ValueError(f"Unknown action: {action}")
    method, sig = mapping[action]
    try:
        if method == "terminate":
            proc.terminate()
        elif method == "kill":
            proc.kill()
        else:
            proc.send_signal(sig)
    except psutil.AccessDenied:
        raise PermissionError(f"Permission denied for pid {pid}")
    except psutil.NoSuchProcess:
        pass
    return {"ok": True, "pid": pid, "action": action}
