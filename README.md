# Server Console

A self-hosted web UI for a headless Linux server — no desktop environment required.

It gives you a browser-based terminal, live system metrics (including **battery,
temperatures and fans**), a process manager, a systemd service manager and a file
manager with an in-browser editor, all behind a single login.

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

That creates a virtualenv, installs dependencies and starts the server. On first run
it generates a random password and prints it in the startup banner:

```
  ┌──────────────────────────────────────────────────┐
  │  Headless Server Web UI                          │
  ├──────────────────────────────────────────────────┤
  │  URL        http://0.0.0.0:8080                  │
  │  Username   admin                                │
  │  Password   aB3dEf7hJk9mNp2q                     │
  └──────────────────────────────────────────────────┘
```

The password is stored in `~/.local/share/webui/password` (mode `0600`) so it
survives restarts. Open `http://<server-ip>:8080` and sign in.

### Run as a service

```bash
mkdir -p ~/.config/systemd/user
cp webui.service ~/.config/systemd/user/
systemctl --user enable --now webui.service
loginctl enable-linger $USER     # keep it running after you log out
```

---

## Configuration

Every option is an environment variable.

| Variable | Default | Description |
|----------|---------|-------------|
| `WEBUI_HOST` | `0.0.0.0` | Bind address |
| `WEBUI_PORT` | `8080` | Port |
| `WEBUI_USER` | `admin` | Login username |
| `WEBUI_PASSWORD` | *(generated)* | Login password |
| `WEBUI_FILE_ROOT` | `/` | Jail the file manager to this directory (e.g. `/srv`) |
| `WEBUI_SHELL` | `/bin/bash` | Shell spawned for each terminal session |
| `WEBUI_METRICS_INTERVAL` | `2.0` | Dashboard push interval in seconds |
| `WEBUI_TOKEN_TTL` | `43200` | Session token lifetime in seconds (12h) |
| `WEBUI_MAX_EDIT_SIZE` | `2097152` | Largest file the editor will open, in bytes |
| `WEBUI_SSL_CERT` / `WEBUI_SSL_KEY` | *(unset)* | Serve over HTTPS by pointing at a cert and key |
| `WEBUI_SYSTEMCTL_SUDO` | `auto` | Set to `0` to never use sudo for systemctl |

Example with a jail and TLS:

```bash
WEBUI_FILE_ROOT=/srv WEBUI_PASSWORD=hunter2 \
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

- Sessions are HMAC-signed tokens; the signing key lives in
  `~/.local/share/webui/secret.key` and is generated per install.
- Unauthenticated requests to `/api/*` and both websockets are rejected.
- The terminal runs as **the same user as the server**. Anyone who signs in gets a
  shell with that user's privileges, so use a strong password.
- The server speaks plain HTTP by default. For anything beyond a trusted LAN, put it
  behind a reverse proxy (nginx/Caddy with TLS) or set `WEBUI_SSL_CERT` /
  `WEBUI_SSL_KEY`.

---

## Project layout

```
app/
  config.py      environment-driven settings, generated secrets
  security.py    HMAC token auth, password check
  metrics.py     psutil collectors: cpu, memory, disks, network, battery, temps, fans
  processes.py   process listing and signalling
  services.py    systemctl / journalctl wrapper with optional sudo
  files.py       path-jailed file manager
  terminal.py    PTY sessions over websocket
  main.py        FastAPI app, routes, auth middleware
static/
  index.html     single-page shell
  css/style.css  dark theme
  js/            vanilla JS views (dashboard, terminal, processes, services, files)
  vendor/        xterm.js + addons, vendored for offline use
```

## API

Interactive docs are served at `/api/docs` (Swagger UI).

```
POST /api/login                       -> {token}
GET  /api/metrics                     -> full snapshot
WS   /ws/metrics?token=…              -> snapshot every WEBUI_METRICS_INTERVAL
WS   /ws/terminal?token=…&cols=…&rows=…
GET  /api/processes                   POST /api/processes/{pid}/signal
GET  /api/services                    GET  /api/services/{unit}/logs
POST /api/services/{unit}/action      {action: start|stop|restart|enable|disable|…}
GET  /api/files?path=…                GET  /api/files/read?path=…
GET  /api/files/download?path=…       POST /api/files/write|mkdir|delete|rename|chmod|chown
POST /api/files/upload                (multipart: path, file)
```
