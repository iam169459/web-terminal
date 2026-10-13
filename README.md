# Server Console

A self-hosted web UI for a headless Linux server — no desktop environment required.

It gives you a browser-based terminal, live system metrics (including **battery,
temperatures and fans**), a process manager, a systemd service manager and a file
manager with an in-browser editor. There is no login — it binds to `127.0.0.1` by
default, so only you on the local machine can reach it.

Built with **FastAPI + psutil** on the backend and **vanilla JS + xterm.js** on the
frontend. `xterm.js` is vendored into `static/vendor/`, so the UI works on machines
with no internet access.

---

## Features

| View | What it does |
|------|--------------|
| **Dashboard** | CPU / memory / battery / temperature gauges, live history charts for CPU, memory and network throughput, per-core load, disks, network interfaces, thermal zones, fan RPM and top processes |
| **Terminal** | A real PTY shell in the browser (xterm.js). Full-screen programs, colours, job control and live resize all work |
| **Processes** | Sortable, filterable process table with SIGTERM / SIGKILL / SIGSTOP |
| **Services** | systemd units with start / stop / restart / enable / disable and journal logs |
| **Files** | Browse, upload, download, edit, chmod, rename and delete, with quick bookmarks |
| **Update** | Pull the latest code from GitHub, reinstall dependencies and restart the server |

### Sensors

Everything is read through `psutil` and degrades gracefully:

- **Battery** — percentage, charging state, AC status and estimated time remaining.
  Machines without a battery show an explicit "no battery" state instead of breaking.
- **Temperatures** — every thermal zone (`coretemp`, `nvme`, `acpitz`, …) with a
  hottest-sensor summary and colour-coded warning / critical thresholds.
- **Fans** — RPM for each fan sensor the kernel exposes.

---

## Quick start

```bash
./run.sh
```

That creates a virtualenv, installs dependencies and starts the server:

```
  ┌──────────────────────────────────────────────────┐
  │  Headless Server Web UI                          │
  ├──────────────────────────────────────────────────┤
  │  URL        http://127.0.0.1:8080                │
  │  File root  /                                    │
  └──────────────────────────────────────────────────┘
```

Open `http://127.0.0.1:8080` — no username or password needed. To reach it from
another machine, bind to your LAN address (`WEBUI_HOST=0.0.0.0 ./run.sh`), but
remember there is no authentication then.

### Run as a service

```bash
mkdir -p ~/.config/systemd/user
cp webui.service ~/.config/systemd/user/
systemctl --user enable --now webui.service
loginctl enable-linger $USER     # keep it running after you log out
```

---

## Self-update

The sidebar shows the installed commit and lights up when upstream has new commits.
Clicking **Update** opens a panel with the current version, the incoming commits and a
live log of the update.

**Update now** does three things:

1. `git fetch` and `git reset --hard origin/<branch>` — the tree is forced to match
   upstream, so **local modifications are discarded**. The previous commit SHA is
   logged so you can roll back with `git reset --hard <sha>`.
2. `pip install --upgrade -r requirements.txt`
3. Restart the server.

The work runs in a **detached helper process**, not inside the request handler — the
server has to kill and restart itself, and doing that mid-response would drop the
connection. The helper waits for this process to exit, updates the tree, then starts
the server again. The browser watches the log across the restart and reloads once the
new code is serving.

Restart behaviour depends on how you launched it:

- **Under systemd** (`webui.service`, which uses `Restart=always`) the process exits
  cleanly and systemd starts the updated code.
- **Otherwise** the helper relaunches it with `nohup`, logging to
  `~/.local/share/webui/server.log`.

Requirements: the install must be a git clone with an `origin` remote, and the user
running the server must be able to write to the install directory. It works whether or
not the process has root — a permission failure just shows up in the log.

To roll back:

```bash
cd ~/Desktop/web-terminal
git log --oneline            # find the commit you want
git reset --hard <sha>
systemctl --user restart webui   # or just restart the process
```

---

## Configuration

Every option is an environment variable.

| Variable | Default | Description |
|----------|---------|-------------|
| `WEBUI_HOST` | `127.0.0.1` | Bind address (`0.0.0.0` exposes it to the network — there is no login) |
| `WEBUI_PORT` | `8080` | Port |
| `WEBUI_USER` | `admin` | Display name shown in the sidebar |
| `WEBUI_FILE_ROOT` | `/` | Jail the file manager to this directory (e.g. `/srv`) |
| `WEBUI_SHELL` | `/bin/bash` | Shell spawned for each terminal session |
| `WEBUI_METRICS_INTERVAL` | `2.0` | Dashboard push interval in seconds |
| `WEBUI_MAX_EDIT_SIZE` | `2097152` | Largest file the editor will open, in bytes |
| `WEBUI_SSL_CERT` / `WEBUI_SSL_KEY` | *(unset)* | Serve over HTTPS by pointing at a cert and key |
| `WEBUI_SYSTEMCTL_SUDO` | `auto` | Set to `0` to never use sudo for systemctl |

Example with a jail and TLS:

```bash
WEBUI_FILE_ROOT=/srv \
WEBUI_SSL_CERT=/etc/ssl/certs/fullchain.pem WEBUI_SSL_KEY=/etc/ssl/private/privkey.pem \
./run.sh
```

### Service control and privileges

`systemctl` commands are run as the user the server runs as. If that user has
passwordless `sudo`, the UI transparently prefixes `sudo -n` so start/stop/restart
work; otherwise those buttons are disabled and a notice explains why. Viewing
services and logs always works.

### File manager jail

With `WEBUI_FILE_ROOT` set, every path is normalised and checked against the root
(including symlink resolution), so `..` and symlink escapes are rejected. With the
default `/` there is no jail.

---

## Security notes

- **There is no authentication.** Anyone who can reach the HTTP port gets a shell
  with the server user's privileges. The default bind address is `127.0.0.1`, so
  only processes on the same machine can connect.
- If you set `WEBUI_HOST=0.0.0.0`, put the UI behind something that authenticates
  (an SSH tunnel, a reverse proxy with basic auth/TLS, a VPN like WireGuard).
- The terminal runs as **the same user as the server**.
- Plain HTTP by default. For anything beyond localhost, use `WEBUI_SSL_CERT` /
  `WEBUI_SSL_KEY` or a reverse proxy (nginx/Caddy with TLS).

---

## Project layout

```
app/
  config.py      environment-driven settings
  metrics.py     psutil collectors: cpu, memory, disks, network, battery, temps, fans
  processes.py   process listing and signalling
  services.py    systemctl / journalctl wrapper with optional sudo
  files.py       path-jailed file manager
  terminal.py    PTY sessions over websocket
  updater.py     self-update via a detached helper process
  main.py        FastAPI app, routes
static/
  index.html     single-page shell
  css/style.css  dark theme
  js/            vanilla JS views (dashboard, terminal, processes, services, files)
  vendor/        xterm.js + addons, vendored for offline use
```

## API

Interactive docs are served at `/api/docs` (Swagger UI).

```
GET  /api/me                         -> username, file root, shell, host, port
GET  /api/metrics                    -> full snapshot
WS   /ws/metrics                     -> snapshot every WEBUI_METRICS_INTERVAL
WS   /ws/terminal?cols=…&rows=…
GET  /api/processes                   POST /api/processes/{pid}/signal
GET  /api/services                    GET  /api/services/{unit}/logs
POST /api/services/{unit}/action      {action: start|stop|restart|enable|disable|…}
GET  /api/update/status               -> version, upstream, behind count, running state, log
POST /api/update/check                -> git fetch and re-read upstream
POST /api/update/run                  -> start a detached self-update, then restart
POST /api/update/clear-log
GET  /api/files?path=…                GET  /api/files/read?path=…
GET  /api/files/download?path=…       POST /api/files/write|mkdir|delete|rename|chmod|chown
POST /api/files/upload                (multipart: path, file)
```
