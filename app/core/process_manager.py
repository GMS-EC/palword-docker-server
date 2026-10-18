import os
import sys
import time
import shutil
import asyncio
import socket
import signal
import psutil
import json
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

    def _get_all_pal_processes(self) -> List[psutil.Process]:
        """Obtiene todos los objetos psutil.Process activos pertenecientes al servidor de Palworld y sus subprocesos."""
        found_procs: Dict[int, psutil.Process] = {}

        # 1. Proceso principal manejado y su árbol completo de hijos
        if self.process and self.process.pid:
            try:
                main_p = psutil.Process(self.process.pid)
                if main_p.is_running() and main_p.status() != psutil.STATUS_ZOMBIE:
                    found_procs[main_p.pid] = main_p
                    for child in main_p.children(recursive=True):
                        try:
                            if child.is_running() and child.status() != psutil.STATUS_ZOMBIE:
                                found_procs[child.pid] = child
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            pass
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        # 2. Escaneo global para detectar procesos huérfanos o binarios nativos (PalServer-Linux-Shipping, etc.)
        try:
            for p in psutil.process_iter(['pid', 'name', 'cmdline', 'status']):
                try:
                    if p.info.get('status') == psutil.STATUS_ZOMBIE:
                        continue
                    pid = p.info.get('pid')
                    if not pid or pid == os.getpid() or pid in found_procs:
                        continue

                    name = (p.info.get('name') or '').lower()
                    if name in ('python', 'python.exe', 'python3', 'uvicorn', 'systemd', 'init'):
                        continue

                    cmdline_list = p.info.get('cmdline') or []
                    cmdline = ' '.join(cmdline_list).lower()

                    # Proteger el propio panel web de FastAPI / Uvicorn
                    if 'uvicorn' in cmdline or 'app.main:app' in cmdline:
                        continue

                    is_pal = (
                        'palserver' in name or
                        'palserver-linux-shipping' in name or
                        'palserver-linux-test' in name or
                        'palserver.sh' in cmdline or
                        'palserver-linux-shipping' in cmdline or
                        'pal/binaries/linux' in cmdline
                    )
                    if is_pal:
                        found_procs[pid] = p
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except Exception:
            pass

        return list(found_procs.values())

    def _is_pal_process_running(self) -> bool:
        """Verifica si existe algún proceso del servidor de Palworld activo en el sistema."""
        return len(self._get_all_pal_processes()) > 0

    def get_server_pid(self) -> Optional[int]:
        """Retorna el PID del proceso de Palworld más relevante (priorizando el binario nativo PalServer-Linux-Shipping)."""
        procs = self._get_all_pal_processes()
        for p in procs:
            try:
                name = p.name().lower()
                cmdline = ' '.join(p.cmdline()).lower()
                if 'palserver-linux-shipping' in name or 'palserver-linux-shipping' in cmdline:
                    return p.pid
            except Exception:
                pass

        if procs:
            return procs[0].pid

        if self.process and self.process.returncode is None:
            return self.process.pid

        return None

    def get_status(self) -> str:
        if self.status in ("INSTALLING", "STOPPING"):
            return self.status

        is_running = self._is_pal_process_running()

        if self.status == "STARTING":
            if not is_running:
                self.status = "OFFLINE"
                return "OFFLINE"
            return "STARTING"

        if not is_running:
            self.status = "OFFLINE"
            return "OFFLINE"

        if self.status == "OFFLINE":
            self.status = "RUNNING"
            return "RUNNING"

        return self.status

    async def broadcast_log(self, message: str) -> None:
        """Añade un log al buffer y lo difunde a todos los clientes web conectados."""
        clean_line = message.rstrip("\r\n")
        if not clean_line:
            return

        # Filtrar consultas periódicas de telemetría REST API para no saturar la consola del servidor
        if "REST accessed endpoint" in clean_line:
            return

        self.log_buffer.append(clean_line)
        dead_ws = set()
        payload = json.dumps({"type": "log", "data": clean_line})
        for ws in self.connected_websockets:
            try:
                await ws.send_text(payload)
            except Exception:
                dead_ws.add(ws)
        self.connected_websockets.difference_update(dead_ws)

    async def broadcast_status(self, new_status: str) -> None:
        """Difunde una actualización de estado del servidor a todos los WebSockets conectados."""
        self.status = new_status
        payload = json.dumps({"type": "status", "status": new_status})
        dead_ws = set()
        for ws in self.connected_websockets:
            try:
                await ws.send_text(payload)
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
                await self.broadcast_status("OFFLINE")
                return

            if await self.is_server_ready():
                self.status = "RUNNING"
                self._server_up_detected = True
                await self.broadcast_status("RUNNING")
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
            await self.broadcast_status("RUNNING")
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

        if self._is_pal_process_running():
            return {"success": False, "message": "Ya existe una instancia de Palworld en ejecución en el sistema."}

        if not self.is_installed():
            return {"success": False, "message": "El servidor de Palworld no está instalado. Ve a la pestaña 'Setup' para instalarlo."}

        self.status = "STARTING"
        self._intentional_stop = False
        self._server_up_detected = False
        self.started_at = time.time()
        await self.broadcast_status("STARTING")

        # En sistemas Linux de producción se utiliza scripts/start.sh o PalServer.sh directamente
        start_script = Path("/home/steam/scripts/start.sh")
        server_sh = settings.palworld_data_dir / "PalServer.sh"

        cmd: List[str] = []
        cwd = str(settings.palworld_data_dir)

        if start_script.exists():
            cmd = ["/bin/bash", str(start_script)]
        elif server_sh.exists():
            # Asegurar que PalServer.sh use exec al llamar a PalServer-Linux-Shipping para control limpio de señales
            try:
                sh_text = server_sh.read_text(encoding="utf-8", errors="ignore")
                if "exec " not in sh_text and "PalServer-Linux-Shipping" in sh_text:
                    patched = sh_text.replace('"$SCRIPT_DIR/Pal/Binaries/Linux/PalServer-Linux-Shipping"', 'exec "$SCRIPT_DIR/Pal/Binaries/Linux/PalServer-Linux-Shipping"')
                    server_sh.write_text(patched, encoding="utf-8")
            except Exception:
                pass

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
            await self.broadcast_status("RUNNING")
            return {"success": True, "message": "Modo simulación iniciado (entorno de desarrollo local)."}

        proc_kwargs = {}
        if os.name != "nt":
            proc_kwargs["preexec_fn"] = os.setsid

        try:
            await self.broadcast_log(f"[Palworld Server] Lanzando ejecutable del servidor con comando: {' '.join(cmd)}")
            self.process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=cwd,
                **proc_kwargs
            )

            self._reader_task = asyncio.create_task(self._read_stream(self.process.stdout))
            self._log_file_task = asyncio.create_task(self._tail_log_file())
            asyncio.create_task(self._watch_server_readiness())

            return {"success": True, "message": "Servidor de Palworld iniciando...", "pid": self.process.pid}
        except Exception as e:
            self.status = "OFFLINE"
            await self.broadcast_status("OFFLINE")
            await self.broadcast_log(f"[Palworld Server] [ERROR] No se pudo lanzar el servidor: {e}")
            return {"success": False, "message": str(e)}

    async def stop_server(self, grace_seconds: int = 15) -> Dict[str, Any]:
        """Detiene de forma segura y completa el servidor Palworld y todo su árbol de procesos."""
        current = self.get_status()
        if current == "OFFLINE" and not self._is_pal_process_running():
            return {"success": True, "message": "El servidor ya se encuentra detenido."}

        self.status = "STOPPING"
        self._intentional_stop = True
        await self.broadcast_status("STOPPING")

        if grace_seconds > 0:
            await self.broadcast_log("[Palworld Server] [SEGURIDAD] Guardando estado del mundo (SaveWorld) antes de apagar...")
            try:
                save_ok = await pal_api_client.save_world()
                if save_ok:
                    await self.broadcast_log("[Palworld Server] Guardado del mundo completado con éxito.")
            except Exception as e:
                await self.broadcast_log(f"[Palworld Server] Aviso durante guardado: {e}")

            # Enviar orden de shutdown vía API / RCON
            try:
                await pal_api_client.shutdown(wait_seconds=min(grace_seconds, 5), message="El servidor se apagará ahora")
            except Exception:
                pass

            # Esperar brevemente (hasta 4s) a que el servidor atienda el shutdown ordenado de la REST API
            for _ in range(4):
                if not self._is_pal_process_running():
                    break
                await asyncio.sleep(1)

        # Obtener todos los procesos del árbol de Palworld
        procs = self._get_all_pal_processes()

        if procs:
            if grace_seconds > 0:
                pids_str = ", ".join(str(p.pid) for p in procs)
                await self.broadcast_log(f"[Palworld Server] Solicitando cierre ordenado de {len(procs)} proceso(s) (PIDs: {pids_str})...")

                # Intentar SIGTERM al grupo de procesos en POSIX
                if self.process and self.process.pid and os.name != "nt":
                    try:
                        os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
                    except Exception:
                        pass

                for p in procs:
                    try:
                        p.terminate()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass

                gone, alive = psutil.wait_procs(procs, timeout=max(1, grace_seconds - 4))
            else:
                alive = procs

            # Si quedaron procesos vivos tras el timeout o si es Kill inmediato (grace_seconds == 0)
            if alive:
                alive_pids = ", ".join(str(p.pid) for p in alive)
                await self.broadcast_log(f"[Palworld Server] Forzando cierre inmediato (SIGKILL) de {len(alive)} proceso(s) remanente(s) (PIDs: {alive_pids})...")
                if self.process and self.process.pid and os.name != "nt":
                    try:
                        os.killpg(os.getpgid(self.process.pid), signal.SIGKILL)
                    except Exception:
                        pass
                for p in alive:
                    try:
                        p.kill()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                psutil.wait_procs(alive, timeout=3)

        # Limpiar el objeto de proceso asyncio
        if self.process:
            try:
                if self.process.returncode is None:
                    self.process.kill()
                await asyncio.wait_for(self.process.wait(), timeout=1.5)
            except Exception:
                pass
            self.process = None

        if self._reader_task:
            self._reader_task.cancel()
            self._reader_task = None
        if self._log_file_task:
            self._log_file_task.cancel()
            self._log_file_task = None

        # Verificación exhaustiva final de procesos
        remaining = self._get_all_pal_processes()
        if remaining:
            # Reintento final de terminación forzada
            for p in remaining:
                try:
                    p.kill()
                except Exception:
                    pass
            await asyncio.sleep(0.5)
            remaining = self._get_all_pal_processes()

        if remaining:
            self.status = "RUNNING"
            await self.broadcast_status("RUNNING")
            err_pids = ", ".join(str(p.pid) for p in remaining)
            err_msg = f"[Palworld Server] [ERROR] No se pudieron terminar los procesos con PID: {err_pids}."
            await self.broadcast_log(err_msg)
            return {"success": False, "message": err_msg}

        self.status = "OFFLINE"
        self.started_at = None
        await self.broadcast_log("[Palworld Server] Servidor de Palworld detenido exitosamente.")
        await self.broadcast_status("OFFLINE")

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
        """Instala o actualiza el servidor Palworld usando SteamCMD con reintento automático."""
        if self.get_status() in ("RUNNING", "STARTING", "INSTALLING"):
            return {"success": False, "message": f"No se puede instalar mientras el servidor está en estado {self.status}."}

        self.status = "INSTALLING"
        await self.broadcast_status("INSTALLING")
        await self.broadcast_log("========================================================================")
        await self.broadcast_log(" INICIANDO DESCARGA / ACTUALIZACIÓN DE PALWORLD SERVER CON STEAMCMD ")
        await self.broadcast_log(" Palworld Dedicated Server (SteamCMD)                               ")
        await self.broadcast_log("========================================================================")

        steamcmd_exe = "/home/steam/steamcmd/steamcmd.sh"
        if not os.path.exists(steamcmd_exe):
            steamcmd_exe = shutil.which("steamcmd") or "steamcmd"

        # Comando estándar oficial de SteamCMD para Palworld Linux
        cmd = [
            steamcmd_exe,
            "+force_install_dir", str(settings.palworld_data_dir),
            "+login", "anonymous",
            "+app_update", "2394010"
        ]
        if validate:
            cmd.append("validate")
        cmd.append("+quit")

        max_attempts = 2
        for attempt in range(1, max_attempts + 1):
            if attempt > 1:
                await self.broadcast_log(f"[SteamCMD] Reintentando descarga e instalación (Intento {attempt}/{max_attempts})...")
                await asyncio.sleep(3)

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
                    await self.broadcast_status("OFFLINE")
                    return {"success": True, "message": "Instalación de Palworld completada con éxito."}
                else:
                    if attempt < max_attempts:
                        await self.broadcast_log(f"[SteamCMD] Intento {attempt} finalizó con código {rc}. Reintentando automáticamente tras actualización de SteamCMD...")
                        continue

                    self.status = "OFFLINE"
                    await self.broadcast_status("OFFLINE")
                    await self.broadcast_log(f"[SteamCMD] Error: El proceso terminó con código {rc}")
                    return {"success": False, "message": f"SteamCMD falló con código {rc}"}
            except FileNotFoundError:
                self.status = "OFFLINE"
                await self.broadcast_status("OFFLINE")
                await self.broadcast_log("[SteamCMD] Binario 'steamcmd' no encontrado en el sistema. Asegúrate de ejecutar dentro del contenedor Docker.")
                return {"success": False, "message": "SteamCMD no encontrado en el sistema."}
            except Exception as e:
                if attempt < max_attempts:
                    await self.broadcast_log(f"[SteamCMD] Excepción en intento {attempt}: {e}. Reintentando...")
                    continue
                self.status = "OFFLINE"
                await self.broadcast_status("OFFLINE")
                await self.broadcast_log(f"[SteamCMD] Error durante la instalación: {e}")
                return {"success": False, "message": str(e)}

        self.status = "OFFLINE"
        await self.broadcast_status("OFFLINE")
        return {"success": False, "message": "Error desconocido en la instalación."}

process_manager = ProcessManager()
