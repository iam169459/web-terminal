"""File manager backend.

Every user-supplied path goes through :func:`resolve`, which normalises it and (when a
jail is configured) refuses anything that escapes the root.
"""
from __future__ import annotations

import base64
import mimetypes
import os
import pwd
import grp
import stat as stat_mod
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import config

TEXT_EXTENSIONS = {
    ".py", ".js", ".mjs", ".ts", ".json", ".html", ".htm", ".css", ".scss", ".md",
    ".txt", ".log", ".conf", ".cfg", ".ini", ".yml", ".yaml", ".toml", ".xml",
    ".sh", ".bash", ".zsh", ".service", ".socket", ".timer", ".desktop", ".env",
    ".c", ".h", ".cpp", ".go", ".rs", ".rb", ".php", ".sql", ".csv", ".diff", ".patch",
    ".gitignore", ".dockerfile", ".vimrc", ".bashrc", ".profile", ".zshrc",
}


class PathError(ValueError):
    """Raised for paths that are invalid or outside the allowed root."""


def resolve(path: Optional[str]) -> Path:
    raw = (path or "/").strip() or "/"
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = config.FILE_ROOT / raw
    normalised = Path(os.path.normpath(str(candidate)))

    root = Path(os.path.realpath(config.FILE_ROOT))
    if root == Path("/"):
        return normalised

    resolved = Path(os.path.realpath(str(normalised)))
    try:
        if os.path.commonpath([str(root), str(resolved)]) != str(root):
            raise PathError("Path escapes the allowed directory")
        if os.path.commonpath([str(root), str(normalised)]) != str(root):
            raise PathError("Path escapes the allowed directory")
    except ValueError as exc:  # different drives / mixing relative+absolute
        raise PathError("Invalid path") from exc
    return normalised


def _owner_group(path: Path) -> Dict[str, str]:
    try:
        st = path.stat()
        user = pwd.getpwuid(st.st_uid).pw_name
    except (KeyError, PermissionError, OSError):
        user = str(getattr(path.stat(), "st_uid", "?")) if path.exists() else "?"
    try:
        st = path.stat()
        group = grp.getgrgid(st.st_gid).gr_name
    except (KeyError, PermissionError, OSError):
        group = "?"
    return {"user": user, "group": group}


def _entry(path: Path) -> Dict[str, Any]:
    try:
        st = path.lstat()
    except OSError as exc:
        return {"name": path.name, "path": str(path), "error": str(exc)}

    is_link = stat_mod.S_ISLNK(st.st_mode)
    is_dir = path.is_dir()
    kind = "dir" if is_dir else ("link" if is_link else "file")
    names = _owner_group(path)
    return {
        "name": path.name,
        "path": str(path),
        "parent": str(path.parent),
        "type": kind,
        "is_dir": is_dir,
        "is_link": is_link,
        "size": st.st_size,
        "size_h": _human(st.st_size),
        "mode": stat_mod.filemode(st.st_mode),
        "mode_octal": oct(stat_mod.S_IMODE(st.st_mode))[2:].zfill(4),
        "uid": st.st_uid,
        "gid": st.st_gid,
        "owner": names["user"],
        "group": names["group"],
        "mtime": st.st_mtime,
        "mtime_h": time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime)),
        "target": os.readlink(path) if is_link else None,
    }


def _human(n: int) -> str:
    step = 1024.0
    value = float(n)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(value) < step:
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= step
    return f"{value:.1f} PiB"


def list_directory(path: Optional[str]) -> Dict[str, Any]:
    target = resolve(path)
    if not target.exists():
        raise FileNotFoundError(f"Not found: {target}")
    if not target.is_dir():
        raise PathError(f"Not a directory: {target}")

    entries: List[Dict[str, Any]] = []
    try:
        children = list(target.iterdir())
    except PermissionError:
        raise PermissionError(f"Permission denied: {target}")

    for child in children:
        entries.append(_entry(child))

    entries = [e for e in entries if "error" not in e] + [e for e in entries if "error" in e]
    entries.sort(key=lambda e: (e.get("type") != "dir", e.get("name", "").lower()))

    hidden = sum(1 for e in entries if e["name"].startswith("."))
    return {"path": str(target), "parent": str(target.parent), "entries": entries, "count": len(entries), "hidden": hidden}


def read_file(path: str) -> Dict[str, Any]:
    target = resolve(path)
    if target.is_dir():
        raise PathError("Cannot open a directory in the editor")
    try:
        size = target.stat().st_size
    except OSError as exc:
        raise FileNotFoundError(str(exc))
    if size > config.MAX_EDIT_SIZE:
        raise PathError(f"File too large to edit ({_human(size)} > {_human(config.MAX_EDIT_SIZE)})")

    raw = target.read_bytes()
    binary = _looks_binary(raw)
    if binary:
        return {
            "path": str(target),
            "binary": True,
            "size": size,
            "size_h": _human(size),
            "content": None,
            "encoding": None,
            "note": "Binary file - download it instead of editing.",
        }

    encoding = _detect_encoding(raw)
    text = raw.decode(encoding, errors="replace")
    info = _entry(target)
    return {
        "path": str(target),
        "name": target.name,
        "binary": False,
        "size": size,
        "size_h": _human(size),
        "content": text,
        "encoding": encoding,
        "mode_octal": info["mode_octal"],
        "mode": info["mode"],
        "owner": info["owner"],
        "group": info["group"],
        "mtime": info["mtime"],
    }


def _looks_binary(raw: bytes) -> bool:
    if b"\x00" in raw[:8192]:
        return True
    try:
        raw[:8192].decode("utf-8")
        return False
    except UnicodeDecodeError:
        return True


def _detect_encoding(raw: bytes) -> str:
    for bom, enc in (
        (b"\xef\xbb\xbf", "utf-8-sig"),
        (b"\xff\xfe\x00\x00", "utf-32-le"),
        (b"\x00\x00\xfe\xff", "utf-32-be"),
        (b"\xff\xfe", "utf-16-le"),
        (b"\xfe\xff", "utf-16-be"),
    ):
        if raw.startswith(bom):
            return enc
    try:
        raw.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        return "latin-1"


def write_file(path: str, content: str) -> Dict[str, Any]:
    target = resolve(path)
    if target.is_dir():
        raise PathError("Cannot write to a directory")
    if target.exists() and not target.is_file():
        raise PathError("Target is not a regular file")

    parent = target.parent
    if not parent.exists():
        raise FileNotFoundError(f"Directory does not exist: {parent}")

    # Preserve the original mode/owner when overwriting an existing file.
    existed = target.exists()
    old_stat = target.stat() if existed else None
    tmp = target.with_name(target.name + ".webui-tmp")
    tmp.write_text(content, encoding="utf-8", errors="strict")
    if old_stat is not None:
        os.chmod(tmp, stat_mod.S_IMODE(old_stat.st_mode))
        try:
            os.chown(tmp, old_stat.st_uid, old_stat.st_gid)
        except (PermissionError, OSError):
            pass
    os.replace(tmp, target)
    return {"ok": True, "path": str(target), "bytes": len(content.encode("utf-8"))}


def mkdir(path: str) -> Dict[str, Any]:
    target = resolve(path)
    if target.exists():
        raise FileExistsError(f"Already exists: {target}")
    target.mkdir(parents=True)
    return {"ok": True, "path": str(target)}


def delete(path: str, recursive: bool = False) -> Dict[str, Any]:
    target = resolve(path)
    if str(target) in ("/", str(config.FILE_ROOT)) and str(config.FILE_ROOT) != "/":
        raise PathError("Refusing to delete the root directory")
    if str(target) == "/":
        raise PathError("Refusing to delete /")
    if not target.exists() and not target.is_symlink():
        raise FileNotFoundError(f"Not found: {target}")

    if target.is_symlink() or target.is_file():
        target.unlink()
    elif recursive:
        import shutil
        shutil.rmtree(target)
    else:
        try:
            target.rmdir()
        except OSError as exc:
            raise PathError("Directory is not empty - enable recursive delete") from exc
    return {"ok": True, "path": str(target)}


def rename(path: str, new_name: str) -> Dict[str, Any]:
    target = resolve(path)
    new_name = os.path.basename(new_name.strip())
    if not new_name or new_name in (".", "..") or "/" in new_name:
        raise PathError("Invalid new name")
    destination = target.parent / new_name
    if destination.exists():
        raise FileExistsError(f"Already exists: {destination}")
    target.rename(destination)
    return {"ok": True, "path": str(destination)}


def chmod(path: str, mode: str) -> Dict[str, Any]:
    target = resolve(path)
    mode = mode.strip()
    if mode.startswith("0o"):
        mode = mode[2:]
    if not mode.isdigit() or not 3 <= len(mode) <= 4:
        raise PathError("Mode must be octal, e.g. 755 or 0644")
    os.chmod(target, int(mode, 8))
    return {"ok": True, "path": str(target), "mode_octal": oct(stat_mod.S_IMODE(target.stat().st_mode))[2:].zfill(4)}


def chown(path: str, owner: Optional[str] = None, group: Optional[str] = None) -> Dict[str, Any]:
    target = resolve(path)
    uid = -1
    gid = -1
    if owner:
        try:
            uid = pwd.getpwnam(owner).pw_uid
        except KeyError:
            try:
                uid = int(owner)
            except ValueError:
                raise PathError(f"Unknown user: {owner}")
    if group:
        try:
            gid = grp.getgrnam(group).gr_gid
        except KeyError:
            try:
                gid = int(group)
            except ValueError:
                raise PathError(f"Unknown group: {group}")
    os.chown(target, uid, gid)
    return {"ok": True, "path": str(target)}


def save_upload(directory: str, filename: str, data: bytes) -> Dict[str, Any]:
    target_dir = resolve(directory)
    if not target_dir.is_dir():
        raise PathError(f"Not a directory: {target_dir}")
    safe_name = os.path.basename(filename.strip())
    if not safe_name:
        raise PathError("Invalid filename")
    destination = target_dir / safe_name
    destination.write_bytes(data)
    return {"ok": True, "path": str(destination), "bytes": len(data), "name": safe_name}


def download_info(path: str) -> Dict[str, Any]:
    target = resolve(path)
    if not target.exists():
        raise FileNotFoundError(f"Not found: {target}")
    if target.is_dir():
        raise PathError("Download directories as an archive from the shell instead")
    mime = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
    return {"path": str(target), "name": target.name, "mime": mime, "size": target.stat().st_size}


def base64_preview(path: str, limit: int = 4096) -> Dict[str, Any]:
    """Small hex/base64 dump used by the editor for binary files."""
    target = resolve(path)
    with target.open("rb") as fh:
        chunk = fh.read(limit)
    return {
        "path": str(target),
        "base64": base64.b64encode(chunk).decode(),
        "truncated": len(chunk) < target.stat().st_size,
    }


def bookmarks() -> List[Dict[str, str]]:
    """Quick-access shortcuts for the sidebar."""
    candidates = [
        ("Root", "/"),
        ("Home", str(Path.home())),
        ("Etc", "/etc"),
        ("Var log", "/var/log"),
        ("Var www", "/var/www"),
        ("Opt", "/opt"),
        ("Tmp", "/tmp"),
        ("Boot", "/boot"),
        ("App", str(config.BASE_DIR)),
    ]
    out = []
    for label, path in candidates:
        p = Path(path)
        if p.exists() and p.is_dir():
            out.append({"label": label, "path": str(p)})
    return out
