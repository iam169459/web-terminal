"""Interactive PTY sessions exposed over WebSocket.

Each browser tab gets its own pseudo-terminal running the configured login shell.
Stdout is pumped from the master fd by a reader thread; stdin and resize events come
in over the websocket.
"""
from __future__ import annotations

import asyncio
import fcntl
import os
import pty
import signal
import struct
import subprocess
import termios
import threading
from typing import Optional

from fastapi import WebSocket

from . import config

READ_SIZE = 8192


class PtySession:
    """One shell process attached to a pseudo-terminal."""

    def __init__(self, cols: int = 120, rows: int = 32, cwd: Optional[str] = None):
        self.cols = cols
        self.rows = rows
        self.closed = threading.Event()
        self.exit_status: Optional[int] = None

        env = os.environ.copy()
        env.update(
            {
                "TERM": env.get("TERM") or "xterm-256color",
                "COLORTERM": "truecolor",
                "WEBUI": "1",
                "COLUMNS": str(cols),
                "LINES": str(rows),
            }
        )
        env.pop("PYTHONSTARTUP", None)

        master, slave = pty.openpty()
        self.master_fd = master

        # Start the child with the slave as its controlling terminal so job control,
        # colours and full-screen programs (vim, htop) behave normally.
        def _setup_controlling_tty() -> None:  # pragma: no cover - runs in the child
            try:
                fcntl.ioctl(0, termios.TIOCSCTTY, 0)
            except OSError:
                pass

        self.proc = subprocess.Popen(
            [config.SHELL, "-i"],
            stdin=slave,
            stdout=slave,
            stderr=slave,
            env=env,
            cwd=cwd or str(config.FILE_ROOT) if config.FILE_ROOT.is_dir() else None,
            start_new_session=True,
            preexec_fn=_setup_controlling_tty,
            close_fds=True,
        )
        os.close(slave)
        self.set_winsize(cols, rows)

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._outbox: Optional[asyncio.Queue] = None
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        threading.Thread(target=self._watch_exit, daemon=True).start()

    # -- terminal plumbing -------------------------------------------------
    def set_winsize(self, cols: int, rows: int) -> None:
        self.cols, self.rows = int(cols), int(rows)
        winsize = struct.pack("HHHH", self.rows, self.cols, 0, 0)
        try:
            fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, winsize)
        except OSError:
            pass

    def _read_loop(self) -> None:
        """Move bytes from the pty master into the asyncio queue."""
        while not self.closed.is_set():
            try:
                data = os.read(self.master_fd, READ_SIZE)
            except OSError:
                break
            if not data:
                break
            self._dispatch(data)
        self.closed.set()
        self._dispatch(None)  # EOF marker

    def _dispatch(self, data: Optional[bytes]) -> None:
        if self._loop is None or self._outbox is None:
            return
        try:
            self._loop.call_soon_threadsafe(self._outbox.put_nowait, data)
        except RuntimeError:
            pass

    def _watch_exit(self) -> None:
        try:
            self.exit_status = self.proc.wait()
        except OSError:
            self.exit_status = -1
        self.closed.set()

    def attach(self, loop: asyncio.AbstractEventLoop) -> asyncio.Queue:
        self._loop = loop
        self._outbox = asyncio.Queue()
        return self._outbox

    def write(self, data: bytes) -> None:
        if not data or self.closed.is_set():
            return
        try:
            os.write(self.master_fd, data)
        except OSError:
            self.close()

    def close(self) -> None:
        if self.closed.is_set() and self.proc.poll() is not None:
            return
        self.closed.set()
        for sig in (signal.SIGHUP, signal.SIGTERM):
            if self.proc.poll() is not None:
                break
            try:
                self.proc.send_signal(sig)
                if self.proc.wait(timeout=1.0) is not None:
                    break
            except (OSError, subprocess.TimeoutExpired):
                continue
        try:
            self.proc.kill()
        except OSError:
            pass
        try:
            os.close(self.master_fd)
        except OSError:
            pass


async def handle_websocket(websocket: WebSocket) -> None:
    """Echo-style protocol: raw text in/out plus JSON ``resize`` control messages."""
    import json

    await websocket.accept()
    cols = int(websocket.query_params.get("cols") or 120)
    rows = int(websocket.query_params.get("rows") or 32)
    cwd = websocket.query_params.get("cwd")

    try:
        session = PtySession(cols=cols, rows=rows, cwd=cwd)
    except (OSError, ValueError) as exc:
        await websocket.send_text(f"\r\n\x1b[31mFailed to start shell: {exc}\x1b[0m\r\n")
        await websocket.close()
        return

    queue = session.attach(asyncio.get_running_loop())
    session.write(b"")

    async def pump_stdout() -> None:
        while True:
            data = await queue.get()
            if data is None:
                break
            await websocket.send_text(data.decode("utf-8", errors="replace"))

    stdout_task = asyncio.create_task(pump_stdout())
    try:
        while not session.closed.is_set():
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break
            if message.get("bytes") is not None:
                session.write(message["bytes"])
                continue
            text = message.get("text") or ""
            if text.startswith("{") and text.endswith("}"):
                try:
                    control = json.loads(text)
                except ValueError:
                    control = {}
                if control.get("type") == "resize":
                    session.set_winsize(control.get("cols", cols), control.get("rows", rows))
                    continue
                if control.get("type") == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
                    continue
            session.write(text.encode("utf-8", errors="replace"))
    except Exception:  # client vanished mid-write, etc.
        pass
    finally:
        stdout_task.cancel()
        session.close()
        try:
            await websocket.close()
        except RuntimeError:
            pass
