import os
import sys
import time
import shutil
import asyncio
import socket
import psutil
from collections import deque
from pathlib import Path
from typing import Set, List, Deque, Dict, Any, Optional
from fastapi import WebSocket

from app.config import settings
from app.core.pal_api_client import pal_api_client

class ProcessManager:
    """
    Controlador del ciclo de vida del servidor dedicado de Palworld.
    Maneja la instalación bajo demanda vía SteamCMD, el inicio,
    la detención segura con guardado de mundo, el monitoreo de logs en tiempo real
    vía WebSockets y la ejecución de comandos.
    """
    def __init__(self):
        self.process: Optional[asyncio.subprocess.Process] = None
        self.status: str = "OFFLINE"  # OFFLINE, STARTING, RUNNING, STOPPING, INSTALLING
        self.connected_websockets: Set[WebSocket] = set()
        self.log_buffer: Deque[str] = deque(maxlen=1000)
        self._reader_task: Optional[asyncio.Task] = None
        self._log_file_task: Optional[asyncio.Task] = None
        self.started_at: Optional[float] = None
        self._intentional_stop: bool = False
        self._server_up_detected: bool = False
        self._is_simulation: bool = False

    def is_installed(self) -> bool:
        """Verifica si los binarios del servidor de Palworld están instalados."""
        server_sh = settings.palworld_data_dir / "PalServer.sh"
        shipping_bin = settings.palworld_data_dir / "Pal" / "Binaries" / "Linux" / "PalServer-Linux-Shipping"
        return server_sh.exists() or shipping_bin.exists()

    def get_status(self) -> str:
        if self.status in ("INSTALLING", "STOPPING"):
            return self.status

        if self.status == "STARTING":
            if self.process and self.process.returncode is not None:
                self.status = "OFFLINE"
                return "OFFLINE"
            return "STARTING"

        is_running = self._is_pal_process_running()

        if not is_running:
            self.status = "OFFLINE"
            return "OFFLINE"

        if self.status == "OFFLINE":
            self.status = "RUNNING"
            return "RUNNING"

        return self.status

    def _is_pal_process_running(self) -> bool:
        if self.process and self.process.returncode is None:
            return True
        try:
            for p in psutil.process_iter(['name', 'cmdline']):
                name = (p.info.get('name') or '').lower()
                if name in ('python', 'python.exe', 'python3', 'bash', 'sh', 'powershell.exe', 'pwsh.exe', 'cmd.exe'):
                    continue
                cmdline_list = p.info.get('cmdline') or []
                cmdline = ' '.join(cmdline_list).lower()
                is_server = (
                    'palserver' in name or
                    'palserver-linux-shipping' in name or
                    'palserver-linux-test' in name or
                    'palserver.sh' in cmdline or
                    'palserver-linux-shipping' in cmdline
                )
                if is_server:
                    return True
        except Exception:
            pass
        return False

    def get_server_pid(self) -> Optional[int]:
        if self.process and self.process.returncode is None:
            return self.process.pid
        try:
            for p in psutil.process_iter(['pid', 'name', 'cmdline']):
                name = (p.info.get('name') or '').lower()
                if name in ('python', 'python.exe', 'python3', 'bash', 'sh', 'powershell.exe', 'pwsh.exe', 'cmd.exe'):
                    continue
                cmdline_list = p.info.get('cmdline') or []
                cmdline = ' '.join(cmdline_list).lower()
                is_server = (
                    'palserver' in name or
                    'palserver-linux-shipping' in name or
                    'palserver.sh' in cmdline or
                    'palserver-linux-shipping' in cmdline
                )
                if is_server:
                    return p.info['pid']
        except Exception:
            pass
        return None

    async def broadcast_log(self, message: str) -> None:
        """Añade un log al buffer y lo difunde a todos los clientes web conectados."""
        clean_line = message.rstrip("\r\n")
        if not clean_line:
            return
        self.log_buffer.append(clean_line)
        dead_ws = set()
        for ws in self.connected_websockets:
            try:
                await ws.send_text(clean_line)
            except Exception:
                dead_ws.add(ws)
        self.connected_websockets.difference_update(dead_ws)

    async def is_server_ready(self) -> bool:
        """Comprueba si el servidor Palworld ya terminó de cargar el mundo."""
        # 1. Comprobar REST API (/v1/api/info)
        info = await pal_api_client.get_server_info()
        if info:
            return True

        # 2. Comprobar conexión RCON
        if settings.rcon_enabled:
            ok = await pal_api_client.rcon.connect(timeout=1.5)
            if ok:
                return True

        # 3. Comprobar puerto UDP del juego
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0.5)
            s.connect(("127.0.0.1", settings.server_port))
            s.close()
        except Exception:
            pass

        return False

    async def _watch_server_readiness(self):
        """Monitorea el arranque del servidor hasta que esté completamente listo para jugar."""
        await self.broadcast_log("[Palworld Server] Servidor en proceso de inicialización. Cargando mundo y recursos...")
        start_time = time.time()
        # Tiempo máximo de espera 15 minutos
        timeout = 900

        while time.time() - start_time < timeout:
            if not self._is_pal_process_running():
                if not self._intentional_stop:
                    await self.broadcast_log("[Palworld Server] [AVISO] El proceso del servidor se cerró durante el arranque.")
                self.status = "OFFLINE"
                return

            if await self.is_server_ready():
                self.status = "RUNNING"
                self._server_up_detected = True
                await self.broadcast_log("========================================================================")
                await self.broadcast_log("  PALWORLD DEDICATED SERVER 100% ONLINE Y DISPONIBLE PARA CONEXIONES  ")
                await self.broadcast_log(f"  Puerto de Juego: {settings.server_port} (UDP) | RCON: {settings.rcon_port} | REST API: {settings.rest_api_port}")
                await self.broadcast_log("========================================================================")
                
                # Disparar webhook de inicio completado
                try:
                    from app.core.webhook_manager import webhook_manager
                    await webhook_manager.notify_started()
                except Exception as e:
                    print(f"[Webhook] Error al enviar notificación de inicio: {e}")
                return

            await asyncio.sleep(4)

        if self.status == "STARTING":
            # Si el proceso sigue vivo tras el timeout, asumir RUNNING
            self.status = "RUNNING"
            await self.broadcast_log("[Palworld Server] Tiempo de arranque completado. Servidor en línea.")

    async def _read_stream(self, stream):
        """Lee el stdout del proceso y lo difunde en tiempo real."""
        try:
            while stream and not stream.at_eof():
                line = await stream.readline()
                if not line:
                    break
                decoded = line.decode("utf-8", errors="replace")
                await self.broadcast_log(decoded)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            await self.broadcast_log(f"[Sistema] Error leyendo stdout del servidor: {e}")

    async def _tail_log_file(self):
        """Monitorea el archivo de log nativo de Palworld."""
        log_path = settings.log_file
        # Esperar hasta que se cree el archivo de log
        for _ in range(60):
            if log_path.exists():
                break
            await asyncio.sleep(2)

        if not log_path.exists():
            return

        try:
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                f.seek(0, os.SEEK_END)
                while self.status in ("STARTING", "RUNNING"):
                    line = f.readline()
                    if line:
                        await self.broadcast_log(f"[PalLog] {line}")
                    else:
                        await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    async def start_server(self) -> Dict[str, Any]:
        """Inicia el servidor Palworld Dedicated Server."""
        current = self.get_status()
        if current in ("RUNNING", "STARTING"):
            return {"success": False, "message": f"El servidor ya se encuentra en estado {current}."}

        if not self.is_installed():
            return {"success": False, "message": "El servidor de Palworld no está instalado. Ve a la pestaña 'Setup' para instalarlo."}

        self.status = "STARTING"
        self._intentional_stop = False
        self._server_up_detected = False
        self.started_at = time.time()

        # En sistemas Linux de producción se utiliza scripts/start.sh o PalServer.sh directamente
        start_script = Path("/home/steam/scripts/start.sh")
        server_sh = settings.palworld_data_dir / "PalServer.sh"

        cmd: List[str] = []
        cwd = str(settings.palworld_data_dir)

        if start_script.exists():
            cmd = ["/bin/bash", str(start_script)]
        elif server_sh.exists():
            # Construcción de argumentos dinámicos desde PalWorldSettings.ini y runtime_config
            from app.core.pal_settings_manager import pal_settings_manager
            ini = pal_settings_manager.read_settings()
            runtime = settings.runtime_config

            game_port = ini.get("PublicPort") or settings.server_port or 8211
            max_p = ini.get("ServerPlayerMaxNum") or settings.max_players or 32

            args = [
                str(server_sh),
                f"-port={game_port}",
                f"-players={max_p}",
                f"-queryport={settings.query_port}"
            ]
            if runtime.get("community", False) or str(ini.get("bShowPlayerList", "")).lower() == "true":
                args.append("-publiclobby")
            if runtime.get("multithreading", True):
                args.extend(["-useperfthreads", "-NoAsyncLoadingThread", "-UseMultithreadForDS"])
            pub_ip = str(ini.get("PublicIP", "")).strip()
            if pub_ip:
                args.append(f"-publicip={pub_ip}")
            cmd = args
        else:
            # Modo local / Simulación si no estamos en el contenedor
            self._is_simulation = True
            await self.broadcast_log("[Palworld Server] Modo local detectado: PalServer.sh no encontrado en el PATH.")
            self.status = "RUNNING"
            return {"success": True, "message": "Modo simulación iniciado (entorno de desarrollo local)."}

        try:
            await self.broadcast_log(f"[Palworld Server] Lanzando ejecutable del servidor con comando: {' '.join(cmd)}")
            self.process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=cwd
            )

            self._reader_task = asyncio.create_task(self._read_stream(self.process.stdout))
            self._log_file_task = asyncio.create_task(self._tail_log_file())
            asyncio.create_task(self._watch_server_readiness())

            return {"success": True, "message": "Servidor de Palworld iniciando...", "pid": self.process.pid}
        except Exception as e:
            self.status = "OFFLINE"
            await self.broadcast_log(f"[Palworld Server] [ERROR] No se pudo lanzar el servidor: {e}")
            return {"success": False, "message": str(e)}

    async def stop_server(self, grace_seconds: int = 15) -> Dict[str, Any]:
        """Detiene de forma segura el servidor ejecutando un guardado previo del mundo."""
        current = self.get_status()
        if current == "OFFLINE":
            return {"success": True, "message": "El servidor ya se encuentra detenido."}

        self.status = "STOPPING"
        self._intentional_stop = True

        await self.broadcast_log(f"[Palworld Server] [SEGURIDAD] Guardando estado del mundo (SaveWorld) antes de apagar...")
        try:
            save_ok = await pal_api_client.save_world()
            if save_ok:
                await self.broadcast_log("[Palworld Server] Guardado del mundo completado con éxito.")
        except Exception as e:
            await self.broadcast_log(f"[Palworld Server] Aviso durante guardado: {e}")

        # Enviar orden de shutdown vía API / RCON
        try:
            await pal_api_client.shutdown(wait_seconds=5, message="El servidor se apagará ahora")
        except Exception:
            pass

        # Si tenemos el proceso controlado
        pid = self.get_server_pid()
        if self.process and self.process.returncode is None:
            try:
                self.process.terminate()
                try:
                    await asyncio.wait_for(self.process.wait(), timeout=grace_seconds)
                except asyncio.TimeoutError:
                    await self.broadcast_log("[Palworld Server] El proceso no respondió al apagado seguro; forzando cierre...")
                    self.process.kill()
                    await self.process.wait()
            except Exception as e:
                await self.broadcast_log(f"[Palworld Server] Excepción deteniendo proceso: {e}")
        elif pid:
            try:
                p = psutil.Process(pid)
                p.terminate()
                gone, alive = psutil.wait_procs([p], timeout=grace_seconds)
                for a in alive:
                    a.kill()
            except Exception:
                pass

        if self._reader_task:
            self._reader_task.cancel()
        if self._log_file_task:
            self._log_file_task.cancel()

        self.status = "OFFLINE"
        self.started_at = None
        await self.broadcast_log("[Palworld Server] Servidor de Palworld detenido exitosamente.")

        # Notificar por webhook
        try:
            from app.core.webhook_manager import webhook_manager
            await webhook_manager.notify_stopped()
        except Exception:
            pass

        return {"success": True, "message": "Servidor detenido correctamente."}

    async def restart_server(self, grace_seconds: int = 15) -> Dict[str, Any]:
        """Reinicia el servidor."""
        await self.broadcast_log("[Palworld Server] Solicitud de reinicio recibida...")
        await self.stop_server(grace_seconds=grace_seconds)
        await asyncio.sleep(2)
        return await self.start_server()

    async def install_server(self, validate: bool = True) -> Dict[str, Any]:
        """Instala o actualiza el servidor Palworld usando SteamCMD."""
        if self.get_status() in ("RUNNING", "STARTING", "INSTALLING"):
            return {"success": False, "message": f"No se puede instalar mientras el servidor está en estado {self.status}."}

        self.status = "INSTALLING"
        await self.broadcast_log("========================================================================")
        await self.broadcast_log(" INICIANDO DESCARGA / ACTUALIZACIÓN DE PALWORLD SERVER CON STEAMCMD ")
        await self.broadcast_log(" Palworld Dedicated Server (SteamCMD)                               ")
        await self.broadcast_log("========================================================================")

        steamcmd_exe = "/home/steam/steamcmd/steamcmd.sh"
        if not os.path.exists(steamcmd_exe):
            # Fallback en Windows / desarrollo local
            steamcmd_exe = shutil.which("steamcmd") or "steamcmd"

        cmd = [
            steamcmd_exe,
            "+@sSteamCmdForcePlatformType", "linux",
            "+@sSteamCmdForcePlatformBitness", "64",
            "+force_install_dir", str(settings.palworld_data_dir),
            "+login", "anonymous",
            "+app_update", "2394010"
        ]
        if validate:
            cmd.append("validate")
        cmd.append("+quit")

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT
            )

            while proc.stdout and not proc.stdout.at_eof():
                line = await proc.stdout.readline()
                if not line:
                    break
                await self.broadcast_log(f"[SteamCMD] {line.decode('utf-8', errors='replace').rstrip()}")

            rc = await proc.wait()
            if rc == 0:
                await self.broadcast_log("========================================================================")
                await self.broadcast_log(" INSTALACIÓN DE PALWORLD DEDICATED SERVER FINALIZADA CORRECTAMENTE ")
                await self.broadcast_log("========================================================================")
                self.status = "OFFLINE"
                return {"success": True, "message": "Instalación de Palworld completada con éxito."}
            else:
                self.status = "OFFLINE"
                await self.broadcast_log(f"[SteamCMD] Error: El proceso terminó con código {rc}")
                return {"success": False, "message": f"SteamCMD falló con código {rc}"}
        except FileNotFoundError:
            self.status = "OFFLINE"
            await self.broadcast_log("[SteamCMD] Binario 'steamcmd' no encontrado en el sistema. Asegúrate de ejecutar dentro del contenedor Docker.")
            return {"success": False, "message": "SteamCMD no encontrado en el sistema."}
        except Exception as e:
            self.status = "OFFLINE"
            await self.broadcast_log(f"[SteamCMD] Error durante la instalación: {e}")
            return {"success": False, "message": str(e)}

process_manager = ProcessManager()
