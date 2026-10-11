"""System metric collection built on psutil.

Every function degrades gracefully: a container without sensors, a desktop without a
battery or a VM without ``/proc/net`` should still return a usable payload.
"""
from __future__ import annotations

import datetime as _dt
import os
import platform
import socket
import time
from typing import Any, Dict, List, Optional

import psutil

_BOOT_TIME = psutil.boot_time()
_PREV_NET: Dict[str, tuple] = {}
_PREV_PERCORE: Optional[List[float]] = None

_IGNORED_FILESYSTEMS = {
    "proc", "sysfs", "devtmpfs", "devpts", "tmpfs", "cgroup", "cgroup2", "pstore",
    "securityfs", "debugfs", "tracefs", "hugetlbfs", "configfs", "fusectl",
    "mqueue", "bpf", "autofs", "rpc_pipefs", "overlay", "squashfs", "iso9660",
    "efivarfs", "binfmt_misc", "fuse.gvfsd-fuse", "nsfs", "ramfs",
}


def _human_bytes(n: Optional[float]) -> str:
    if n is None:
        return "-"
    step = 1024.0
    for unit in ("B", "KiB", "MiB", "GiB", "TiB", "PiB"):
        if abs(n) < step:
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= step
    return f"{n:.1f} EiB"


def _human_rate(bps: Optional[float]) -> str:
    if bps is None:
        return "-"
    return _human_bytes(bps) + "/s"


def _human_uptime(seconds: float) -> str:
    seconds = int(seconds)
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    parts.append(f"{secs}s")
    return " ".join(parts)


def _os_release() -> Dict[str, str]:
    info: Dict[str, str] = {}
    try:
        with open("/etc/os-release") as fh:
            for line in fh:
                if "=" in line:
                    key, _, value = line.partition("=")
                    info[key.strip()] = value.strip().strip('"')
    except OSError:
        pass
    return info


def overview() -> Dict[str, Any]:
    """Static-ish host identity, refreshed cheaply."""
    release = _os_release()
    try:
        hostname = socket.gethostname()
    except OSError:
        hostname = platform.node()
    try:
        fqdn = socket.getfqdn()
    except OSError:
        fqdn = hostname
    return {
        "hostname": hostname,
        "fqdn": fqdn,
        "user": os.environ.get("USER") or os.getenv("USERNAME") or str(os.getuid()),
        "kernel": platform.release(),
        "arch": platform.machine(),
        "os": release.get("PRETTY_NAME") or platform.platform(),
        "python": platform.python_version(),
        "boot_time": _BOOT_TIME,
        "boot_time_iso": _dt.datetime.fromtimestamp(_BOOT_TIME).isoformat(timespec="seconds"),
    }


def cpu() -> Dict[str, Any]:
    global _PREV_PERCORE
    total = psutil.cpu_percent(interval=None)

    # psutil needs two samples to produce a real per-core reading, so prime it once.
    per_core = psutil.cpu_percent(interval=None, percpu=True)
    if _PREV_PERCORE is None or len(_PREV_PERCORE) != len(per_core):
        psutil.cpu_percent(interval=None, percpu=True)  # throwaway prime sample
    _PREV_PERCORE = list(per_core)

    try:
        freq = psutil.cpu_freq()
        frequency = {"current": round(freq.current, 0), "min": freq.min, "max": freq.max}
    except (AttributeError, OSError):
        frequency = None

    try:
        load = list(os.getloadavg())
    except (AttributeError, OSError):
        load = None

    try:
        affinity = len(psutil.Process().cpu_affinity())
    except (AttributeError, psutil.Error):
        affinity = os.cpu_count()

    return {
        "percent": total,
        "per_core": per_core,
        "cores_physical": psutil.cpu_count(logical=False),
        "cores_logical": os.cpu_count(),
        "available_cores": affinity,
        "frequency": frequency,
        "load_avg": load,
        "times": {
            key: round(value, 1)
            for key, value in psutil.cpu_times_percent(interval=None)._asdict().items()
        },
    }


def memory() -> Dict[str, Any]:
    vm = psutil.virtual_memory()
    swap = psutil.swap_memory()
    return {
        "total": vm.total,
        "available": vm.available,
        "used": vm.used,
        "percent": vm.percent,
        "total_h": _human_bytes(vm.total),
        "used_h": _human_bytes(vm.used),
        "available_h": _human_bytes(vm.available),
        "swap_total": swap.total,
        "swap_used": swap.used,
        "swap_percent": swap.percent,
        "swap_total_h": _human_bytes(swap.total),
        "swap_used_h": _human_bytes(swap.used),
    }


def disks() -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen = set()
    try:
        partitions = psutil.disk_partitions(all=False)
    except OSError:
        partitions = []
    for part in partitions:
        if part.fstype in _IGNORED_FILESYSTEMS:
            continue
        if part.mountpoint in seen:
            continue
        seen.add(part.mountpoint)
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except (OSError, PermissionError):
            continue
        out.append(
            {
                "device": part.device,
                "mountpoint": part.mountpoint,
                "fstype": part.fstype,
                "opts": part.opts,
                "total": usage.total,
                "used": usage.used,
                "free": usage.free,
                "percent": usage.percent,
                "total_h": _human_bytes(usage.total),
                "used_h": _human_bytes(usage.used),
                "free_h": _human_bytes(usage.free),
            }
        )
    return out


def network() -> Dict[str, Any]:
    """Per-interface throughput; the first call reports 0 rates by design."""
    global _PREV_NET
    now = time.time()
    try:
        current = psutil.net_io_counters(pernic=True)
    except OSError:
        current = {}
    interfaces: List[Dict[str, Any]] = []
    try:
        addrs = psutil.net_if_addrs()
    except OSError:
        addrs = {}

    for name, io in current.items():
        prev = _PREV_NET.get(name)
        if prev:
            dt = max(now - prev[2], 1e-6)
            sent_rate = max((io.bytes_sent - prev[0]) / dt, 0.0)
            recv_rate = max((io.bytes_recv - prev[1]) / dt, 0.0)
        else:
            sent_rate = recv_rate = 0.0
        addresses = [
            {"family": "IPv6" if a.family.name == "AF_INET6" else "IPv4", "address": a.address}
            for a in addrs.get(name, [])
            if a.family.name in ("AF_INET", "AF_INET6") and not a.address.startswith("fe80")
        ]
        interfaces.append(
            {
                "name": name,
                "sent_rate": sent_rate,
                "recv_rate": recv_rate,
                "sent_rate_h": _human_rate(sent_rate),
                "recv_rate_h": _human_rate(recv_rate),
                "sent_total": io.bytes_sent,
                "recv_total": io.bytes_recv,
                "sent_total_h": _human_bytes(io.bytes_sent),
                "recv_total_h": _human_bytes(io.bytes_recv),
                "addresses": addresses,
                "is_up": name in psutil.net_if_stats() and psutil.net_if_stats()[name].isup,
            }
        )
    _PREV_NET = {k: (v.bytes_sent, v.bytes_recv, now) for k, v in current.items()}

    try:
        totals = psutil.net_io_counters()
        aggregate = {
            "sent_total": totals.bytes_sent,
            "recv_total": totals.bytes_recv,
            "sent_total_h": _human_bytes(totals.bytes_sent),
            "recv_total_h": _human_bytes(totals.bytes_recv),
        }
    except OSError:
        aggregate = {}

    interfaces.sort(key=lambda i: max(i["sent_rate"], i["recv_rate"]), reverse=True)
    return {"interfaces": interfaces, "totals": aggregate}


def battery() -> Dict[str, Any]:
    """Battery status; ``present`` is False on machines without a battery."""
    try:
        bat = psutil.sensors_battery()
    except (AttributeError, OSError):
        bat = None
    if bat is None:
        return {"present": False}

    unknown = (psutil.POWER_TIME_UNLIMITED, psutil.POWER_TIME_UNKNOWN)
    seconds_left: Optional[int]
    if bat.secsleft in unknown or bat.secsleft < 0:
        seconds_left = None
    else:
        seconds_left = int(bat.secsleft)

    percent = round(bat.percent, 1)
    if bat.power_plugged:
        state = "Charging" if percent < 99.5 else "Full"
    elif seconds_left is None:
        state = "Discharging"
    else:
        state = "Discharging"

    return {
        "present": True,
        "percent": percent,
        "plugged": bool(bat.power_plugged),
        "state": state,
        "seconds_left": seconds_left,
        "time_left_h": _human_uptime(seconds_left) if seconds_left else None,
    }


def temperatures() -> Dict[str, Any]:
    """All thermal zones, plus the hottest reading for the summary card."""
    try:
        raw = psutil.sensors_temperatures()
    except (AttributeError, OSError):
        return {"available": False, "zones": [], "max": None}
    zones: List[Dict[str, Any]] = []
    hottest: Optional[Dict[str, Any]] = None
    for chip, entries in (raw or {}).items():
        for entry in entries:
            zone = {
                "chip": chip,
                "label": entry.label or chip,
                "current": round(entry.current, 1) if entry.current is not None else None,
                "high": entry.high,
                "critical": entry.critical,
            }
            zones.append(zone)
            if zone["current"] is not None and (hottest is None or zone["current"] > hottest["current"]):
                hottest = zone
    return {"available": bool(zones), "zones": zones, "max": hottest}


def fans() -> Dict[str, Any]:
    try:
        raw = psutil.sensors_fans()
    except (AttributeError, OSError):
        return {"available": False, "sensors": []}
    sensors: List[Dict[str, Any]] = []
    for chip, entries in (raw or {}).items():
        for entry in entries:
            sensors.append({"chip": chip, "label": entry.label or chip, "rpm": entry.current})
    return {"available": bool(sensors), "sensors": sensors}


def process_summary() -> Dict[str, Any]:
    counts = {"total": 0, "running": 0, "sleeping": 0, "stopped": 0, "zombie": 0}
    top: List[Dict[str, Any]] = []
    for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
        try:
            info = proc.info
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        counts["total"] += 1
        status = (info.get("status") or "").lower()
        if status in counts:
            counts[status] += 1
        top.append(
            {
                "pid": info["pid"],
                "name": info.get("name") or "?",
                "cpu": round(info.get("cpu_percent") or 0.0, 1),
                "mem": round(info.get("memory_percent") or 0.0, 1),
            }
        )
    top.sort(key=lambda p: p["cpu"], reverse=True)
    return {"counts": counts, "top": top[:8]}


def collect() -> Dict[str, Any]:
    """Full snapshot streamed to the dashboard every couple of seconds."""
    cpu_data = cpu()
    bat = battery()
    temps = temperatures()
    net = network()
    return {
        "ts": time.time(),
        "overview": overview(),
        "cpu": cpu_data,
        "memory": memory(),
        "disks": disks(),
        "network": net,
        "battery": bat,
        "temperatures": temps,
        "fans": fans(),
        "processes": process_summary(),
        "uptime_seconds": time.time() - _BOOT_TIME,
        "uptime_h": _human_uptime(time.time() - _BOOT_TIME),
        "load_h": " ".join(f"{v:.2f}" for v in cpu_data["load_avg"]) if cpu_data["load_avg"] else None,
    }
