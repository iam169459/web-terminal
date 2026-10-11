"""FastAPI application: REST API, websockets and the static UI."""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Optional

from fastapi import Body, Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile, WebSocket
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, files, metrics, processes, security, services, terminal

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("webui")

app = FastAPI(title="Headless Server Web UI", version="1.0.0", docs_url="/api/docs", redoc_url=None)


# --------------------------------------------------------------------------- auth
class LoginBody(BaseModel):
    username: str = ""
    password: str = ""


PUBLIC_PATHS = {"/api/login", "/api/health", "/favicon.ico"}


def require_auth(request: Request) -> None:
    token = security.extract_token(
        request.headers.get("authorization"), request.query_params.get("token")
    )
    if not security.verify_token(token):
        raise HTTPException(status_code=401, detail="Not authenticated")


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api/") and path not in PUBLIC_PATHS:
        token = security.extract_token(
            request.headers.get("authorization"), request.query_params.get("token")
        )
        if not security.verify_token(token):
            return JSONResponse({"detail": "Not authenticated"}, status_code=401)
    return await call_next(request)


@app.exception_handler(files.PathError)
async def path_error_handler(request: Request, exc: files.PathError):
    return JSONResponse({"detail": str(exc)}, status_code=400)


@app.exception_handler(PermissionError)
async def permission_error_handler(request: Request, exc: PermissionError):
    return JSONResponse({"detail": str(exc)}, status_code=403)


@app.exception_handler(FileNotFoundError)
async def not_found_handler(request: Request, exc: FileNotFoundError):
    return JSONResponse({"detail": str(exc)}, status_code=404)


@app.exception_handler(FileExistsError)
async def exists_handler(request: Request, exc: FileExistsError):
    return JSONResponse({"detail": str(exc)}, status_code=409)


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    return JSONResponse({"detail": str(exc)}, status_code=400)


# --------------------------------------------------------------------------- auth api
@app.post("/api/login")
def login(body: LoginBody):
    if not security.verify_password(body.password) or (
        body.username and body.username != config.USERNAME
    ):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    return {"token": security.issue_token(), "username": config.USERNAME, "ttl": config.TOKEN_TTL}


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/me")
def me(_=Depends(require_auth)):
    return {
        "username": config.USERNAME,
        "root": str(config.FILE_ROOT),
        "shell": config.SHELL,
        "host": config.HOST,
        "port": config.PORT,
    }


# --------------------------------------------------------------------------- metrics
@app.get("/api/metrics")
def metrics_snapshot(_=Depends(require_auth)):
    return metrics.collect()


@app.get("/api/overview")
def overview(_=Depends(require_auth)):
    return {"overview": metrics.overview(), "battery": metrics.battery()}


@app.websocket("/ws/metrics")
async def metrics_websocket(websocket: WebSocket):
    token = security.extract_token(None, websocket.query_params.get("token"))
    if not security.verify_token(token):
        await websocket.close(code=4401)
        return
    await websocket.accept()
    try:
        while True:
            await websocket.send_json(metrics.collect())
            await asyncio.sleep(config.METRICS_INTERVAL)
    except Exception:  # client disconnected
        pass


# --------------------------------------------------------------------------- terminal
@app.websocket("/ws/terminal")
async def terminal_websocket(websocket: WebSocket):
    token = security.extract_token(None, websocket.query_params.get("token"))
    if not security.verify_token(token):
        await websocket.close(code=4401)
        return
    await terminal.handle_websocket(websocket)


# --------------------------------------------------------------------------- processes
@app.get("/api/processes")
def get_processes(
    sort: str = Query("cpu"),
    direction: str = Query("desc"),
    search: str = Query(""),
    limit: int = Query(500, ge=1, le=5000),
    _=Depends(require_auth),
):
    return processes.list_processes(sort=sort, direction=direction, search=search, limit=limit)


class SignalBody(BaseModel):
    action: str = "term"


@app.post("/api/processes/{pid}/signal")
def post_signal(pid: int, body: SignalBody, _=Depends(require_auth)):
    try:
        return processes.signal_process(pid, body.action)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# --------------------------------------------------------------------------- services
@app.get("/api/services")
def get_services(_=Depends(require_auth)):
    return services.list_services()


@app.get("/api/services/{unit}/logs")
def get_service_logs(unit: str, lines: int = Query(200, ge=1, le=2000), _=Depends(require_auth)):
    try:
        return services.service_logs(unit, lines)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/services/{unit}/status")
def get_service_status(unit: str, _=Depends(require_auth)):
    try:
        return services.service_status(unit)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


class ServiceActionBody(BaseModel):
    action: str


@app.post("/api/services/{unit}/action")
def post_service_action(unit: str, body: ServiceActionBody, _=Depends(require_auth)):
    try:
        return services.service_action(unit, body.action)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# --------------------------------------------------------------------------- files
@app.get("/api/files")
def get_files(path: str = Query("/"), _=Depends(require_auth)):
    try:
        return files.list_directory(path)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.get("/api/files/bookmarks")
def get_bookmarks(_=Depends(require_auth)):
    return {"bookmarks": files.bookmarks()}


@app.get("/api/files/read")
def get_file_read(path: str = Query(...), _=Depends(require_auth)):
    try:
        return files.read_file(path)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.get("/api/files/download")
def download_file(path: str = Query(...), _=Depends(require_auth)):
    try:
        info = files.download_info(path)
    except (files.PathError, FileNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return FileResponse(
        info["path"], media_type=info["mime"], filename=info["name"]
    )


class WriteBody(BaseModel):
    path: str
    content: str


@app.post("/api/files/write")
def post_write(body: WriteBody, _=Depends(require_auth)):
    try:
        return files.write_file(body.path, body.content)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))


class MkdirBody(BaseModel):
    path: str


@app.post("/api/files/mkdir")
def post_mkdir(body: MkdirBody, _=Depends(require_auth)):
    try:
        return files.mkdir(body.path)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))


class DeleteBody(BaseModel):
    path: str
    recursive: bool = False


@app.post("/api/files/delete")
def post_delete(body: DeleteBody, _=Depends(require_auth)):
    try:
        return files.delete(body.path, body.recursive)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))


class RenameBody(BaseModel):
    path: str
    new_name: str


@app.post("/api/files/rename")
def post_rename(body: RenameBody, _=Depends(require_auth)):
    try:
        return files.rename(body.path, body.new_name)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))


class ChmodBody(BaseModel):
    path: str
    mode: str


@app.post("/api/files/chmod")
def post_chmod(body: ChmodBody, _=Depends(require_auth)):
    try:
        return files.chmod(body.path, body.mode)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))


class ChownBody(BaseModel):
    path: str
    owner: Optional[str] = None
    group: Optional[str] = None


@app.post("/api/files/chown")
def post_chown(body: ChownBody, _=Depends(require_auth)):
    try:
        return files.chown(body.path, body.owner, body.group)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))


@app.post("/api/files/upload")
async def post_upload(
    path: str = Form(...),
    file: UploadFile = File(...),
    _=Depends(require_auth),
):
    data = await file.read()
    try:
        return files.save_upload(path, file.filename or "upload.bin", data)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))


# --------------------------------------------------------------------------- static ui
if config.STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(config.STATIC_DIR)), name="static")


@app.get("/")
def index():
    page = config.STATIC_DIR / "index.html"
    if page.is_file():
        return FileResponse(page)
    return RedirectResponse("/api/docs")


def main() -> None:
    import uvicorn

    banner = f"""
  ┌──────────────────────────────────────────────────┐
  │  Headless Server Web UI                          │
  ├──────────────────────────────────────────────────┤
  │  URL        http://{config.HOST}:{config.PORT:<27}│
  │  Username   {config.USERNAME:<33}│
  │  Password   {config.PASSWORD:<33}│
  │  File root  {str(config.FILE_ROOT)[:33]:<33}│
  └──────────────────────────────────────────────────┘
"""
    print(banner)
    ssl_cert = os.environ.get("WEBUI_SSL_CERT")
    ssl_key = os.environ.get("WEBUI_SSL_KEY")
    kwargs = {}
    if ssl_cert and ssl_key:
        kwargs["ssl_certfile"] = ssl_cert
        kwargs["ssl_keyfile"] = ssl_key
        print(f"  TLS enabled ({ssl_cert})\n")
    uvicorn.run(app, host=config.HOST, port=config.PORT, log_level="info", **kwargs)


if __name__ == "__main__":
    main()
