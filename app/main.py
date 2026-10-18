import os
import time
import json
import asyncio
import logging
import platform
import psutil
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Dict, Any, Optional, List

from fastapi import (
    FastAPI, WebSocket, WebSocketDisconnect, Depends,
    HTTPException, Request, Response, Form, status,
    UploadFile, File, Query
)
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.gzip import GZipMiddleware
from pydantic import BaseModel

from app.config import settings, BASE_DIR
from app.core.security import (
    create_session_token, verify_session_token, verify_admin_credentials, is_authenticated,
    require_auth, check_login_rate_limit, record_failed_login, reset_failed_login,
    SESSION_COOKIE_NAME, get_client_ip
)
from app.core.process_manager import process_manager
from app.core.pal_api_client import pal_api_client
from app.core.player_manager import player_manager
from app.core.metrics_manager import metrics_manager
from app.core.pal_settings_manager import pal_settings_manager, DEFAULT_PALWORLD_SETTINGS
from app.core.backup_manager import backup_manager
from app.core.file_manager import file_manager
from app.core.task_scheduler import task_scheduler
from app.core.webhook_manager import webhook_manager
from app.core.activity_manager import activity_manager
from app.version import get_app_version


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        if request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache, must-revalidate"
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Ciclo de vida de la aplicación Palworld Server Manager."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)

    metrics_manager.start()
    task_scheduler.start_loop()
    player_manager.start_monitor()

    # Si el proceso del servidor ya está corriendo en el host
    if process_manager._is_pal_process_running():
        if await process_manager.is_server_ready():
            process_manager.status = "RUNNING"
        else:
            process_manager.status = "STARTING"
            asyncio.create_task(process_manager._watch_server_readiness())

    # Autoinicio si el servidor está configurado para ello (por defecto desactivado a menos que se configure en Ajustes o AUTOSTART_SERVER=true)
    autostart_cfg = settings.runtime_config.get(
        "autostart_server",
        os.getenv("AUTOSTART_SERVER", "false").lower() in ("true", "1", "yes")
    )
    if autostart_cfg and process_manager.is_installed():
        async def _autostart():
            await asyncio.sleep(2)
            if process_manager.get_status() == "OFFLINE":
                activity_manager.log("Servidor", "Inicio automático activado al arrancar Palworld Server Manager")
                await webhook_manager.notify_starting()
                await process_manager.start_server()
        asyncio.create_task(_autostart())

    yield

    player_manager.stop_monitor()
    task_scheduler.stop_loop()
    metrics_manager.stop()

    if process_manager._is_pal_process_running():
        try:
            print("[Palworld Server] Contenedor deteniéndose. Ejecutando guardado seguro (SaveWorld)...")
            await process_manager.stop_server(grace_seconds=15)
        except Exception as e:
            print(f"[Palworld Server] Error durante guardado seguro al apagar: {e}")
    await pal_api_client.rcon.disconnect()


app = FastAPI(
    title="Palworld Server Manager",
    description="Panel de Control Web & API REST para Servidores de Palworld en Docker",
    version=get_app_version(),
    lifespan=lifespan
)

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(GZipMiddleware, minimum_size=1000)

static_dir = BASE_DIR / "web" / "static"
static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

templates_dir = BASE_DIR / "web" / "templates"
templates_dir.mkdir(parents=True, exist_ok=True)
templates = Jinja2Templates(directory=str(templates_dir))

START_TIME_TOKEN = str(int(time.time()))
templates.env.globals["asset_v"] = START_TIME_TOKEN
templates.env.globals["app_version"] = get_app_version()


# --- Modelos Pydantic para Solicitudes ---
class LoginRequest(BaseModel):
    username: Optional[str] = "admin"
    password: str

class ServerCommandRequest(BaseModel):
    command: str

class AnnounceRequest(BaseModel):
    message: str

class PlayerActionRequest(BaseModel):
    player_id: Optional[str] = None
    player: Optional[str] = None
    reason: Optional[str] = "Acción administrativa"

class FileSaveRequest(BaseModel):
    path: str
    content: str

class FolderCreateRequest(BaseModel):
    path: str

class FileCreateRequest(BaseModel):
    path: str

class FileRenameRequest(BaseModel):
    path: str
    new_name: str

class FileDuplicateRequest(BaseModel):
    path: str

class FileCompressRequest(BaseModel):
    path: str

class FileBulkDeleteRequest(BaseModel):
    paths: List[str]

class FileBulkCompressRequest(BaseModel):
    paths: List[str]
    target_dir: Optional[str] = ""
    archive_name: Optional[str] = ""

class UnzipRequest(BaseModel):
    path: str
    target_dir: Optional[str] = ""

class BackupRestoreRequest(BaseModel):
    filename: str

class BackupCreateRequest(BaseModel):
    tag: Optional[str] = ""
    label: Optional[str] = ""
    scope: Optional[str] = "full"
    targets: Optional[List[str]] = None
    compression: Optional[bool] = True
    stop_server: Optional[bool] = False
    pre_command: Optional[str] = ""

class TaskCreateRequest(BaseModel):
    id: Optional[str] = None
    name: str
    action: str
    command: Optional[str] = ""
    schedule_type: Optional[str] = "interval"
    interval_value: Optional[int] = 1
    interval_unit: Optional[str] = "days"
    cron_expression: Optional[str] = "0 4 * * *"
    enabled: Optional[bool] = True


def _build_server_stats_dict() -> Dict[str, Any]:
    """Construye el diccionario unificado de métricas y estado del servidor para SSR y API."""
    installed = process_manager.is_installed()
    curr_status = process_manager.get_status()
    metrics = metrics_manager.get_current_metrics()
    ini = pal_settings_manager.read_settings()

    server_name = ini.get("ServerName") or settings.server_name
    server_desc = ini.get("ServerDescription") or settings.server_description
    game_port = ini.get("PublicPort") or settings.server_port
    max_players = ini.get("ServerPlayerMaxNum") or settings.max_players
    tz_str = os.getenv("TZ", "America/Guayaquil")

    is_off = (curr_status == "OFFLINE")
    pid = None if is_off else process_manager.get_server_pid()
    started_at_str = "--"
    if process_manager.started_at and not is_off:
        started_at_str = time.strftime("%d/%m/%Y %H:%M:%S", time.localtime(process_manager.started_at))

    cp_raw = str(ini.get("CrossplayPlatforms", "(Steam,Xbox,PS5)")).lower()
    crossplay_on = "xbox" in cp_raw or "ps5" in cp_raw or "true" in cp_raw or "activado" in cp_raw or "habilitado" in cp_raw

    return {
        "status": curr_status,
        "is_installed": installed,
        "pid": pid,
        "started_at": None if is_off else process_manager.started_at,
        "started_at_str": started_at_str,
        "uptime_formatted": "--" if is_off else metrics.get("uptime_formatted", "--"),
        "timezone": tz_str,
        "cpu_percent": 0.0 if is_off else metrics.get("cpu_percent", 0.0),
        "memory_mb": 0 if is_off else metrics.get("memory_mb", 0),
        "current_ram_mb": 0 if is_off else metrics.get("memory_mb", 0),
        "current_mem_mb": 0 if is_off else metrics.get("memory_mb", 0),
        "assigned_memory_mb": metrics.get("assigned_memory_mb", 8192),
        "assigned_ram_mb": metrics.get("assigned_memory_mb", 8192),
        "memory_percent": 0.0 if is_off else metrics.get("ram_percent", 0.0),
        "ram_percent": 0.0 if is_off else metrics.get("ram_percent", 0.0),
        "disk_used_mb": metrics.get("disk_used_mb", 10240),
        "disk_limit_mb": metrics.get("disk_limit_mb", 102400),
        "disk_percent": metrics.get("disk_percent", 10.0),
        "online_players": 0 if is_off else metrics.get("online_players", 0),
        "max_players": max_players,
        "server_name": server_name,
        "server_port": game_port,
        "motd": server_desc,
        "server_fps": 0.0 if is_off else metrics.get("server_fps", 0.0),
        "server_type": "palworld",
        "server_version": "SteamCMD",
        "crossplay_platforms": "Habilitado" if crossplay_on else "Desactivado",
        "crossplay_enabled": crossplay_on,
        "app_version": get_app_version()
    }


# --- Endpoint de Salud Público (Docker Healthcheck) ---
@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "server_status": process_manager.get_status(),
        "is_installed": process_manager.is_installed()
    }

@app.get("/api/version")
async def api_version():
    return {
        "app": "Palworld Server Manager",
        "version": get_app_version()
    }


# --- Rutas de Vistas Web ---
@app.get("/", response_class=HTMLResponse)
async def index_view(request: Request):
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

    stats_obj = _build_server_stats_dict()
    cfg_obj = settings.runtime_config
    stats_json = json.dumps(stats_obj)
    cfg_json = json.dumps(cfg_obj)

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "is_installed": stats_obj["is_installed"],
            "server_status": stats_obj["status"],
            "status": stats_obj["status"],
            "stats": stats_obj,
            "cfg": cfg_obj,
            "stats_json": stats_json,
            "cfg_json": cfg_json,
            "server_name": stats_obj["server_name"],
            "server_port": stats_obj["server_port"],
            "motd": stats_obj["motd"],
            "timezone": stats_obj["timezone"],
            "asset_v": START_TIME_TOKEN,
            "app_version": get_app_version()
        }
    )

@app.get("/login", response_class=HTMLResponse)
async def login_view(request: Request):
    if is_authenticated(request):
        return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"error": None, "asset_v": START_TIME_TOKEN, "app_version": get_app_version()}
    )

@app.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    response: Response,
    username: str = Form(...),
    password: str = Form(...)
):
    client_ip = get_client_ip(request)
    if check_login_rate_limit(client_ip):
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={
                "error": "Demasiados intentos fallidos. Tu IP ha sido bloqueada temporalmente durante 5 minutos.",
                "asset_v": START_TIME_TOKEN,
                "app_version": get_app_version()
            },
            status_code=status.HTTP_429_TOO_MANY_REQUESTS
        )

    if verify_admin_credentials(username, password):
        reset_failed_login(client_ip)
        token = create_session_token(username.strip())
        res = RedirectResponse(url="/" , status_code=status.HTTP_302_FOUND)
        res.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=token,
            max_age=7 * 24 * 3600,
            httponly=True,
            samesite="lax",
            secure=(request.url.scheme == "https")
        )
        activity_manager.log("Seguridad", f"Inicio de sesión exitoso desde {client_ip}")
        return res
    else:
        record_failed_login(client_ip)
        activity_manager.log("Seguridad", f"Intento fallido de login desde {client_ip}")
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={
                "error": "Credenciales incorrectas. Verifique su usuario y contraseña.",
                "asset_v": START_TIME_TOKEN,
                "app_version": get_app_version()
            },
            status_code=status.HTTP_401_UNAUTHORIZED
        )

@app.get("/logout")
async def logout(request: Request):
    res = RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    res.delete_cookie(SESSION_COOKIE_NAME)
    return res


# --- Endpoints de Autenticación API ---
@app.get("/api/auth/status")
async def api_auth_status(request: Request):
    auth_ok = is_authenticated(request)
    return {
        "authenticated": auth_ok,
        "auth_required": True,
        "session_timeout_minutes": 60
    }

@app.post("/api/auth/refresh")
async def api_auth_refresh(request: Request, response: Response):
    if not is_authenticated(request):
        raise HTTPException(status_code=401, detail="Sesión expirada.")
    token = create_session_token("admin")
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=7 * 24 * 3600,
        httponly=True,
        samesite="lax",
        secure=(request.url.scheme == "https")
    )
    return {"status": "success", "success": True}

@app.post("/api/auth/logout")
async def api_auth_logout(response: Response):
    response.delete_cookie(SESSION_COOKIE_NAME)
    return {"status": "success", "success": True}

@app.post("/api/auth/login")
async def api_auth_login(req: LoginRequest, request: Request, response: Response):
    client_ip = get_client_ip(request)
    if check_login_rate_limit(client_ip):
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={"status": "error", "message": "IP bloqueada temporalmente por intentos fallidos."}
        )

    user = (req.username or "admin").strip()
    if verify_admin_credentials(user, req.password):
        reset_failed_login(client_ip)
        token = create_session_token(user)
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=token,
            max_age=7 * 24 * 3600,
            httponly=True,
            samesite="lax",
            secure=(request.url.scheme == "https")
        )
        activity_manager.log("Seguridad", f"Inicio de sesión exitoso vía API desde {client_ip}")
        return {"status": "success", "success": True, "message": "Acceso concedido."}
    else:
        record_failed_login(client_ip)
        activity_manager.log("Seguridad", f"Intento fallido de login vía API desde {client_ip}")
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"status": "error", "message": "Credenciales incorrectas."}
        )


# --- WebSocket de Consola & Streaming de Logs ---
async def _handle_websocket_connection(websocket: WebSocket):
    token = websocket.cookies.get(SESSION_COOKIE_NAME)
    if not verify_session_token(token):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()
    process_manager.connected_websockets.add(websocket)

    # 1. Enviar estado inicial y logs acumulados en buffer
    try:
        init_payload = {
            "type": "init",
            "status": process_manager.get_status(),
            "history": list(process_manager.log_buffer)
        }
        await websocket.send_text(json.dumps(init_payload))
    except Exception:
        pass

    try:
        while True:
            raw_data = await websocket.receive_text()
            if not raw_data:
                continue

            # Soporta tanto cadenas simples como objetos JSON {"type": "command", "command": ...}
            cmd_text = raw_data.strip()
            try:
                parsed = json.loads(raw_data)
                if isinstance(parsed, dict) and "command" in parsed:
                    cmd_text = parsed["command"].strip()
            except Exception:
                pass

            if not cmd_text:
                continue

            activity_manager.log("Consola", f"Comando ejecutado: {cmd_text}")
            resp = await pal_api_client.execute_raw_command(cmd_text)
            if resp:
                log_line = f"[RCON Response] {resp}"
                await websocket.send_text(json.dumps({"type": "log", "data": log_line}))
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        process_manager.connected_websockets.discard(websocket)


@app.websocket("/ws/console")
async def websocket_console(websocket: WebSocket):
    await _handle_websocket_connection(websocket)


@app.websocket("/ws/logs")
async def websocket_logs(websocket: WebSocket):
    await _handle_websocket_connection(websocket)



# --- Endpoints de Control de Servidor ---
@app.get("/api/server/status", dependencies=[Depends(require_auth)])
async def api_server_status():
    return _build_server_stats_dict()

@app.post("/api/server/start", dependencies=[Depends(require_auth)])
async def api_server_start():
    activity_manager.log("Servidor", "Iniciando servidor de Palworld...")
    await webhook_manager.notify_starting()
    return await process_manager.start_server()

@app.post("/api/server/stop", dependencies=[Depends(require_auth)])
async def api_server_stop():
    activity_manager.log("Servidor", "Deteniendo servidor de Palworld...")
    return await process_manager.stop_server()

@app.post("/api/server/restart", dependencies=[Depends(require_auth)])
async def api_server_restart():
    activity_manager.log("Servidor", "Reiniciando servidor de Palworld...")
    return await process_manager.restart_server()

@app.post("/api/server/kill", dependencies=[Depends(require_auth)])
async def api_server_kill():
    activity_manager.log("Servidor", "Forzando apagado inmediato (Kill)...")
    return await process_manager.stop_server(grace_seconds=0)

@app.post("/api/server/install", dependencies=[Depends(require_auth)])
async def api_server_install(payload: Optional[Dict[str, Any]] = None):
    validate = True
    if payload and "validate" in payload:
        validate = bool(payload["validate"])
    activity_manager.log("Servidor", f"Instalando/Actualizando Palworld con SteamCMD (validate={validate})...")
    return await process_manager.install_server(validate=validate)

@app.get("/api/server/eula")
async def api_server_eula_get():
    return {"accepted": True}

@app.post("/api/server/eula")
async def api_server_eula_post():
    return {"accepted": True}

@app.post("/api/server/command", dependencies=[Depends(require_auth)])
async def api_server_command(req: ServerCommandRequest):
    if not req.command.strip():
        return {"success": False, "error": "Comando vacío."}
    activity_manager.log("Consola", f"Comando ejecutado: {req.command}")
    resp = await pal_api_client.execute_raw_command(req.command.strip())
    return {"success": True, "response": resp}

@app.post("/api/server/announce", dependencies=[Depends(require_auth)])
async def api_server_announce(req: AnnounceRequest):
    ok = await pal_api_client.announce(req.message)
    activity_manager.log("Consola", f"Anuncio emitido: {req.message}")
    return {"success": ok}

@app.post("/api/server/save", dependencies=[Depends(require_auth)])
async def api_server_save():
    ok = await pal_api_client.save_world()
    activity_manager.log("Servidor", "Guardado del mundo ejecutado")
    return {"success": ok}


# --- Endpoints de Métricas ---
@app.get("/api/metrics/current", dependencies=[Depends(require_auth)])
async def api_metrics_current():
    return metrics_manager.get_current_metrics()

@app.get("/api/metrics/chart", dependencies=[Depends(require_auth)])
async def api_metrics_chart():
    return metrics_manager.get_chart_data()

@app.get("/api/metrics/history", dependencies=[Depends(require_auth)])
async def api_metrics_history():
    return metrics_manager.get_history_data()

@app.post("/api/metrics/reset", dependencies=[Depends(require_auth)])
async def api_metrics_reset():
    metrics_manager.reset_history()
    activity_manager.log("Métricas", "Historial de métricas reiniciado")
    return {"success": True}


# --- Endpoints de Jugadores ---
@app.get("/api/players/online", dependencies=[Depends(require_auth)])
async def api_players_online():
    players = await player_manager.get_online_players()
    return {"count": len(players), "max": settings.max_players, "players": players}

@app.get("/api/players/history", dependencies=[Depends(require_auth)])
async def api_players_history():
    return {"players": player_manager.get_player_history()}

@app.get("/api/players/list", dependencies=[Depends(require_auth)])
async def api_players_list():
    return await player_manager.list_players()

@app.post("/api/players/kick", dependencies=[Depends(require_auth)])
async def api_players_kick(req: PlayerActionRequest):
    target = (req.player or req.player_id or "").strip()
    if not target:
        return {"success": False, "message": "Identificador de jugador requerido."}
    ok = await player_manager.kick_player(target, req.reason or "Expulsado por el administrador")
    activity_manager.log("Jugadores", f"Jugador {target} expulsado: {req.reason}")
    return {"success": ok, "message": f"Jugador {target} expulsado exitosamente." if ok else "Error al expulsar jugador."}

@app.post("/api/players/ban", dependencies=[Depends(require_auth)])
async def api_players_ban(req: PlayerActionRequest):
    target = (req.player or req.player_id or "").strip()
    if not target:
        return {"success": False, "message": "Identificador de jugador requerido."}
    ok = await player_manager.ban_player(target, req.reason or "Baneado por el administrador")
    activity_manager.log("Jugadores", f"Jugador {target} baneado: {req.reason}")
    return {"success": ok, "message": f"Jugador {target} baneado exitosamente." if ok else "Error al banear jugador."}

@app.post("/api/players/unban", dependencies=[Depends(require_auth)])
@app.post("/api/players/pardon", dependencies=[Depends(require_auth)])
async def api_players_unban(req: PlayerActionRequest):
    target = (req.player or req.player_id or "").strip()
    if not target:
        return {"success": False, "message": "Identificador de jugador requerido."}
    ok = await player_manager.unban_player(target)
    activity_manager.log("Jugadores", f"Jugador {target} desbaneado")
    return {"success": ok, "message": f"Jugador {target} desbaneado exitosamente." if ok else "Error al desbanear jugador."}

@app.post("/api/players/kick-all", dependencies=[Depends(require_auth)])
async def api_players_kick_all(payload: Optional[Dict[str, Any]] = None):
    reason = "Mantenimiento del servidor"
    if payload and "reason" in payload:
        reason = payload["reason"]
    online = await player_manager.get_online_players()
    count = 0
    for p in online:
        pid = p.get("player_id") or p.get("steam_id") or p.get("name")
        if pid:
            if await player_manager.kick_player(str(pid), reason):
                count += 1
    activity_manager.log("Jugadores", f"Expulsión masiva ejecutada: {count} jugadores expulsados ({reason})")
    return {"success": True, "message": f"Se expulsó a {count} jugador(es) del servidor."}


# --- Endpoints de Configuración & Ajustes (PalWorldSettings.ini) ---
@app.get("/api/settings", dependencies=[Depends(require_auth)])
async def api_get_settings():
    ini_settings = pal_settings_manager.read_settings()
    runtime = settings.runtime_config
    return {
        "ini_settings": ini_settings,
        "runtime_config": runtime,
        "server_name": ini_settings.get("ServerName") or settings.server_name,
        "server_description": ini_settings.get("ServerDescription") or settings.server_description,
        "server_password": ini_settings.get("ServerPassword", ""),
        "admin_password": ini_settings.get("AdminPassword", "adminpassword"),
        "max_players": ini_settings.get("ServerPlayerMaxNum", 32),
        "server_port": ini_settings.get("PublicPort", 8211),
        "rcon_port": ini_settings.get("RCONPort", 25575),
        "rest_api_port": ini_settings.get("RESTAPIPort", 8212)
    }

@app.post("/api/settings", dependencies=[Depends(require_auth)])
async def api_save_settings(payload: Dict[str, Any]):
    ini_updates = payload.get("ini_settings", {})
    runtime_updates = payload.get("runtime_config", {})

    for key in ("server_name", "server_description", "server_password", "admin_server_password", "max_players"):
        if key in payload:
            runtime_updates[key] = payload[key]

    if "autostart_server" in payload:
        runtime_updates["autostart_server"] = bool(payload["autostart_server"])
    if "autostart_server" in ini_updates:
        val = ini_updates.pop("autostart_server")
        runtime_updates["autostart_server"] = (val is True or str(val).lower() in ("true", "1", "yes"))

    if "ServerName" in ini_updates:
        runtime_updates["server_name"] = ini_updates["ServerName"]
    if "ServerDescription" in ini_updates:
        runtime_updates["server_description"] = ini_updates["ServerDescription"]
    if "ServerPassword" in ini_updates:
        runtime_updates["server_password"] = ini_updates["ServerPassword"]
    if "AdminPassword" in ini_updates:
        runtime_updates["admin_server_password"] = ini_updates["AdminPassword"]
    if "ServerPlayerMaxNum" in ini_updates:
        runtime_updates["max_players"] = ini_updates["ServerPlayerMaxNum"]

    settings.save_runtime_config(runtime_updates)

    if ini_updates:
        pal_settings_manager.update_settings(ini_updates)

    activity_manager.log("Ajustes", "Configuraciones de Palworld actualizadas exitosamente")
    return {"success": True, "message": "Configuración guardada exitosamente."}

@app.get("/api/settings/raw", dependencies=[Depends(require_auth)])
@app.get("/api/server/properties/raw", dependencies=[Depends(require_auth)])
async def api_settings_raw_get():
    pal_settings_manager._ensure_paths()
    content = ""
    if pal_settings_manager.settings_file.exists():
        try:
            content = pal_settings_manager.settings_file.read_text(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if not content:
        pairs = [f"{k}={pal_settings_manager.format_value(k, v)}" for k, v in pal_settings_manager.read_settings().items()]
        content = "[/Script/Pal.PalGameWorldSettings]\nOptionSettings=(" + ",".join(pairs) + ")\n"
    return Response(content=content, media_type="text/plain; charset=utf-8")

@app.post("/api/settings/raw", dependencies=[Depends(require_auth)])
@app.post("/api/server/properties/raw", dependencies=[Depends(require_auth)])
async def api_settings_raw_post(request: Request):
    body = await request.body()
    text = body.decode("utf-8", errors="replace")
    if not text.strip():
        return {"success": False, "message": "Contenido del archivo INI vacío."}
    from app.core.fs_utils import atomic_write_text
    try:
        pal_settings_manager.config_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_text(pal_settings_manager.settings_file, text)
        activity_manager.log("Ajustes", "PalWorldSettings.ini actualizado mediante editor directo RAW")
        return {"success": True, "message": "Archivo PalWorldSettings.ini guardado exitosamente."}
    except Exception as e:
        return {"success": False, "message": f"Error escribiendo archivo: {e}"}

@app.post("/api/settings/reset", dependencies=[Depends(require_auth)])
async def api_settings_reset():
    current = pal_settings_manager.read_settings()
    keep_keys = ("ServerPassword", "AdminPassword", "PublicPort", "RCONPort", "RESTAPIPort", "ServerName")
    defaults = dict(DEFAULT_PALWORLD_SETTINGS)
    for k in keep_keys:
        if k in current:
            defaults[k] = current[k]
    pal_settings_manager.write_all_settings(defaults)
    activity_manager.log("Ajustes", "Configuración de Palworld restablecida a valores por defecto")
    return {"success": True, "message": "Valores por defecto restablecidos."}

@app.get("/api/server/properties", dependencies=[Depends(require_auth)])
async def api_server_properties_get():
    return {"properties": pal_settings_manager.read_settings()}

@app.get("/api/config", dependencies=[Depends(require_auth)])
async def api_config_get():
    return settings.runtime_config

@app.post("/api/config", dependencies=[Depends(require_auth)])
async def api_config_post(payload: Dict[str, Any]):
    settings.save_runtime_config(payload)
    activity_manager.log("Ajustes", "Configuración de variables de entorno actualizada")
    return {"success": True, "config": settings.runtime_config}


# --- Endpoints de Respaldos (Backups) ---
@app.get("/api/backups", dependencies=[Depends(require_auth)])
async def api_backups_get():
    return {"backups": backup_manager.list_backups()}

@app.get("/api/backups/list", dependencies=[Depends(require_auth)])
async def api_backups_list():
    return backup_manager.list_backups()

@app.get("/api/backups/targets", dependencies=[Depends(require_auth)])
async def api_backups_targets():
    return backup_manager.get_available_targets()

@app.get("/api/backups/config", dependencies=[Depends(require_auth)])
async def api_backups_config_get():
    cfg = settings.runtime_config
    return {
        "scope": cfg.get("backup_scope", "full"),
        "retention_count": int(cfg.get("backup_max_count", os.getenv("BACKUP_MAX_COUNT", 10))),
        "auto_backup_interval_hours": int(cfg.get("auto_backup_interval_hours", os.getenv("BACKUP_INTERVAL_HOURS", 6))),
        "targets": cfg.get("backup_targets", ["Pal/Saved"])
    }

@app.post("/api/backups/config", dependencies=[Depends(require_auth)])
async def api_backups_config_post(payload: Dict[str, Any]):
    updates = {}
    if "scope" in payload:
        updates["backup_scope"] = payload["scope"]
    if "retention_count" in payload:
        updates["backup_max_count"] = int(payload["retention_count"])
    if "auto_backup_interval_hours" in payload:
        updates["auto_backup_interval_hours"] = int(payload["auto_backup_interval_hours"])
    if "targets" in payload:
        updates["backup_targets"] = payload["targets"]
    settings.save_runtime_config(updates)
    activity_manager.log("Respaldos", "Directiva de alcance y retención de respaldos actualizada")
    return {"success": True, "message": "Configuración de respaldos actualizada."}

@app.post("/api/backups/create", dependencies=[Depends(require_auth)])
async def api_backups_create(req: BackupCreateRequest):
    custom_label = req.label or req.tag or ""
    scope = req.scope or "full"
    targets = req.targets
    res = await backup_manager.create_backup(custom_label=custom_label, scope=scope, targets=targets)
    if res.get("success"):
        activity_manager.log("Respaldos", f"Respaldo creado: {res.get('filename')}")
    return res

@app.post("/api/backups/restore", dependencies=[Depends(require_auth)])
async def api_backups_restore(req: BackupRestoreRequest):
    res = await backup_manager.restore_backup(req.filename)
    if res.get("success"):
        activity_manager.log("Respaldos", f"Respaldo restaurado: {req.filename}")
    return res

@app.delete("/api/backups/delete", dependencies=[Depends(require_auth)])
async def api_backups_delete(filename: str = Query(...)):
    res = backup_manager.delete_backup(filename)
    if res.get("success"):
        activity_manager.log("Respaldos", f"Respaldo eliminado: {filename}")
    return res

@app.get("/api/backups/download", dependencies=[Depends(require_auth)])
async def api_backups_download(filename: str = Query(...)):
    archive = backup_manager._resolve_backup(filename)
    if not archive:
        raise HTTPException(status_code=404, detail="Archivo no encontrado.")
    return FileResponse(
        str(archive),
        filename=archive.name,
        media_type="application/gzip"
    )


# --- Endpoints de Tareas Programadas ---
@app.get("/api/tasks/status", dependencies=[Depends(require_auth)])
async def api_tasks_status():
    return task_scheduler.get_status()

@app.post("/api/tasks/settings", dependencies=[Depends(require_auth)])
async def api_tasks_settings(payload: Dict[str, Any]):
    settings.save_runtime_config(payload)
    activity_manager.log("Tareas", "Configuración de automatizaciones y tareas actualizada")
    return {"success": True, "status": task_scheduler.get_status()}

@app.get("/api/tasks", dependencies=[Depends(require_auth)])
async def api_tasks_list():
    return task_scheduler.list_tasks()

@app.post("/api/tasks", dependencies=[Depends(require_auth)])
async def api_tasks_create(req: TaskCreateRequest):
    new_task = task_scheduler.create_task(req.model_dump())
    activity_manager.log("Tareas", f"Tarea programada creada: {req.name}")
    return new_task

@app.put("/api/tasks/{task_id}", dependencies=[Depends(require_auth)])
async def api_tasks_update(task_id: str, req: TaskCreateRequest):
    updated = task_scheduler.update_task(task_id, req.model_dump(exclude_unset=True))
    activity_manager.log("Tareas", f"Tarea programada actualizada: {req.name}")
    return updated

@app.delete("/api/tasks/{task_id}", dependencies=[Depends(require_auth)])
async def api_tasks_delete_by_path(task_id: str):
    ok = task_scheduler.delete_task(task_id)
    activity_manager.log("Tareas", f"Tarea eliminada ID: {task_id}")
    return {"success": ok}

@app.delete("/api/tasks", dependencies=[Depends(require_auth)])
async def api_tasks_delete_query(id: str = Query(...)):
    ok = task_scheduler.delete_task(id)
    activity_manager.log("Tareas", f"Tarea eliminada ID: {id}")
    return {"success": ok, "tasks": task_scheduler.list_tasks()}

@app.post("/api/tasks/{task_id}/toggle", dependencies=[Depends(require_auth)])
async def api_tasks_toggle(task_id: str, payload: Dict[str, Any]):
    enabled = payload.get("enabled", True)
    updated = task_scheduler.toggle_task(task_id, enabled)
    activity_manager.log("Tareas", f"Tarea {task_id} {'activada' if enabled else 'desactivada'}")
    return updated

@app.post("/api/tasks/{task_id}/run", dependencies=[Depends(require_auth)])
async def api_tasks_run_path(task_id: str):
    res = await task_scheduler.run_task_now(task_id)
    activity_manager.log("Tareas", f"Ejecución inmediata de tarea ID: {task_id}")
    return res

@app.post("/api/tasks/run", dependencies=[Depends(require_auth)])
async def api_tasks_run(payload: Dict[str, Any]):
    task_id = payload.get("id")
    if task_id:
        return await task_scheduler.run_task_now(task_id)
    action = payload.get("action", "")
    cmd = payload.get("command", "")
    res = await task_scheduler.execute_task_action({"action": action, "command": cmd, "name": "Ejecución Manual"})
    return res


# --- Endpoints de Webhooks ---
@app.get("/api/webhooks/config", dependencies=[Depends(require_auth)])
async def api_webhooks_get_config():
    return webhook_manager.load_config()

@app.post("/api/webhooks/config", dependencies=[Depends(require_auth)])
async def api_webhooks_save_config(payload: Dict[str, Any]):
    saved = webhook_manager.save_config(payload)
    activity_manager.log("Webhooks", "Configuración de canales de alerta (Discord, Telegram, Email) guardada")
    return {"status": "saved", "config": saved}

@app.post("/api/webhooks/test/{channel}", dependencies=[Depends(require_auth)])
async def api_webhooks_test_channel(channel: str):
    res = await webhook_manager.test_channel(channel.lower())
    if res.get("status") == "error":
        raise HTTPException(status_code=400, detail=res.get("message", "Error al enviar notificación de prueba"))
    return res

@app.get("/api/webhooks/settings", dependencies=[Depends(require_auth)])
async def api_webhooks_settings():
    return webhook_manager.load_config()

@app.post("/api/webhooks/settings", dependencies=[Depends(require_auth)])
async def api_webhooks_save(payload: Dict[str, Any]):
    saved = webhook_manager.save_config(payload)
    activity_manager.log("Webhooks", "Configuración de Webhooks actualizada")
    return {"success": True, "config": saved}

@app.post("/api/webhooks/test", dependencies=[Depends(require_auth)])
async def api_webhooks_test():
    ok = await webhook_manager.notify_test()
    return {"success": ok}



# --- Endpoints de Actividad & Logs ---
@app.get("/api/activity", dependencies=[Depends(require_auth)])
async def api_activity():
    return {"activity": activity_manager.get_recent(limit=50)}

@app.get("/api/activity/logs", dependencies=[Depends(require_auth)])
async def api_activity_logs(limit: int = Query(500)):
    items = activity_manager.get_recent(limit=limit)
    return {"logs": items}

@app.post("/api/activity/clear", dependencies=[Depends(require_auth)])
async def api_activity_clear():
    activity_manager._log_entries.clear()
    activity_manager.log("Sistema", "Historial de auditoría vaciado por el administrador")
    return {"success": True}


# --- Endpoints del Administrador de Archivos (Files) ---
@app.get("/api/files/list", dependencies=[Depends(require_auth)])
async def file_list(path: str = Query("")):
    return file_manager.list_directory(path)

@app.get("/api/files/content", dependencies=[Depends(require_auth)])
async def file_content(path: str = Query(...)):
    return file_manager.read_file(path)

@app.post("/api/files/save", dependencies=[Depends(require_auth)])
async def file_save(req: FileSaveRequest):
    res = file_manager.write_file(req.path, req.content)
    activity_manager.log("Archivos", f"Archivo guardado: {req.path}")
    return res

@app.post("/api/files/folder", dependencies=[Depends(require_auth)])
async def file_folder(req: FolderCreateRequest):
    res = file_manager.create_folder(req.path)
    activity_manager.log("Archivos", f"Carpeta creada: {req.path}")
    return res

@app.delete("/api/files/delete", dependencies=[Depends(require_auth)])
async def file_delete(path: str = Query(...)):
    res = file_manager.delete_item(path)
    activity_manager.log("Archivos", f"Elemento eliminado: {path}")
    return res

@app.post("/api/files/upload", dependencies=[Depends(require_auth)])
async def file_upload(path: str = Form(""), file: UploadFile = File(...)):
    res = await file_manager.save_upload(path, file)
    activity_manager.log("Archivos", f"Archivo subido: {file.filename}")
    return res

@app.post("/api/files/unzip", dependencies=[Depends(require_auth)])
async def file_unzip(req: UnzipRequest):
    res = file_manager.extract_zip(req.path, req.target_dir)
    activity_manager.log("Archivos", f"Archivo extraído: {req.path}")
    return res

@app.get("/api/files/download", dependencies=[Depends(require_auth)])
async def file_download(path: str = Query(...)):
    safe_path = file_manager.resolve_download(path)
    return FileResponse(
        str(safe_path),
        filename=safe_path.name,
        media_type="application/octet-stream"
    )

@app.post("/api/files/create", dependencies=[Depends(require_auth)])
async def file_create(req: FileCreateRequest):
    res = file_manager.create_file(req.path)
    activity_manager.log("Archivos", f"Archivo creado: {req.path}")
    return res

@app.post("/api/files/duplicate", dependencies=[Depends(require_auth)])
async def file_duplicate(req: FileDuplicateRequest):
    res = file_manager.duplicate_item(req.path)
    activity_manager.log("Archivos", f"Elemento duplicado: {req.path}")
    return res

@app.post("/api/files/compress", dependencies=[Depends(require_auth)])
async def file_compress(req: FileCompressRequest):
    res = file_manager.compress_item(req.path)
    activity_manager.log("Archivos", f"Elemento comprimido: {req.path}")
    return res

@app.post("/api/files/rename", dependencies=[Depends(require_auth)])
async def file_rename(req: FileRenameRequest):
    res = file_manager.rename_item(req.path, req.new_name)
    activity_manager.log("Archivos", f"Elemento renombrado a {req.new_name}")
    return res

@app.post("/api/files/bulk-delete", dependencies=[Depends(require_auth)])
async def file_bulk_delete(req: FileBulkDeleteRequest):
    res = file_manager.bulk_delete(req.paths)
    activity_manager.log("Archivos", f"Eliminación múltiple de {len(req.paths)} elementos")
    return res

@app.post("/api/files/bulk-compress", dependencies=[Depends(require_auth)])
async def file_bulk_compress(req: FileBulkCompressRequest):
    res = file_manager.bulk_compress(req.paths, req.target_dir, req.archive_name)
    activity_manager.log("Archivos", f"Compresión múltiple de {len(req.paths)} elementos a {res.get('archive_name')}")
    return res


# --- Endpoint de Diagnóstico de Sistema ---
@app.get("/api/diagnostics/system", dependencies=[Depends(require_auth)])
async def api_diagnostics_system():
    vm = psutil.virtual_memory()
    curr_metrics = metrics_manager.get_current_metrics()
    pid = process_manager.get_server_pid()

    return {
        "status": process_manager.get_status(),
        "is_installed": process_manager.is_installed(),
        "server_pid": pid,
        "os": platform.system(),
        "os_release": platform.release(),
        "python_version": platform.python_version(),
        "cpu_count": psutil.cpu_count(logical=True),
        "cpu_percent": curr_metrics.get("cpu_percent", 0.0),
        "ram_total_gb": curr_metrics.get("ram_total_gb", round(vm.total / (1024**3), 2)),
        "ram_used_gb": curr_metrics.get("ram_used_gb", round(vm.used / (1024**3), 2)),
        "ram_percent": curr_metrics.get("ram_percent", vm.percent),
        "disk_total_gb": curr_metrics.get("disk_total_gb", 100.0),
        "disk_used_gb": curr_metrics.get("disk_used_gb", 0.0),
        "disk_percent": curr_metrics.get("disk_percent", 0.0),
        "container_metrics": curr_metrics,
        "host_ram_total_gb": round(vm.total / (1024**3), 2),
        "host_ram_used_gb": round(vm.used / (1024**3), 2),
        "ports": {
            "game_udp": settings.server_port,
            "rest_api_tcp": settings.rest_api_port,
            "rcon_tcp": settings.rcon_port
        },
        "recent_logs": list(process_manager.log_buffer)[-20:]
    }


# --- Endpoints de Mods & Plugins ---
@app.get("/api/mods/list", dependencies=[Depends(require_auth)])
async def api_mods_list():
    mods_cfg = settings.runtime_config.get("mods", [])
    mods_dir = settings.palworld_data_dir / "Pal" / "Content" / "Paks" / "~mods"
    installed_paks = []
    if mods_dir.exists():
        installed_paks = [f.name for f in mods_dir.glob("*.pak")]

    catalog = [
        {"id": "PalDefender", "name": "PalDefender", "author": "Ultimeit", "desc": "Anti-cheat y protección contra exploits para servidores dedicados."},
        {"id": "PalSchema", "name": "PalSchema (UE4SS)", "author": "Community", "desc": "Framework base para carga de mods Lua y Unreal Engine 4/5."},
        {"id": "MapUnlocker", "name": "Map Unlocker", "author": "Community", "desc": "Desbloquea el mapa y niebla de guerra para todos los jugadores."},
        {"id": "IncreasedBaseLimits", "name": "Increased Base Limits", "author": "Community", "desc": "Aumenta la capacidad de construcción y radio de bases."},
        {"id": "BetterBreeding", "name": "Better Breeding HUD", "author": "Community", "desc": "Muestra estadísticas y genes de Pals en granjas de cría."}
    ]
    return {
        "active_mods": mods_cfg,
        "installed_paks": installed_paks,
        "catalog": catalog
    }

@app.post("/api/mods/add", dependencies=[Depends(require_auth)])
async def api_mods_add(payload: Dict[str, Any]):
    mod_name = payload.get("name", "").strip()
    if not mod_name:
        return {"success": False, "message": "Nombre del mod vacío."}
    mods = settings.runtime_config.get("mods", [])
    if mod_name not in mods:
        mods.append(mod_name)
        settings.save_runtime_config({"mods": mods})
        activity_manager.log("Mods", f"Mod añadido a la configuración: {mod_name}")
    return {"success": True, "mods": mods}

@app.post("/api/mods/remove", dependencies=[Depends(require_auth)])
async def api_mods_remove(payload: Dict[str, Any]):
    mod_name = payload.get("name", "").strip()
    mods = settings.runtime_config.get("mods", [])
    if mod_name in mods:
        mods.remove(mod_name)
        settings.save_runtime_config({"mods": mods})
        activity_manager.log("Mods", f"Mod removido de la configuración: {mod_name}")
    return {"success": True, "mods": mods}
