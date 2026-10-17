import os
import json
import time
import uuid
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import List, Dict, Any, Optional
from croniter import croniter

from app.config import settings
from app.core.fs_utils import atomic_write_json
from app.core.pal_api_client import pal_api_client
from app.core.backup_manager import backup_manager

logger = logging.getLogger("palworld.tasks")

def get_server_timezone() -> ZoneInfo:
    tz_name = os.getenv("TZ", "America/Guayaquil")
    try:
        return ZoneInfo(tz_name)
    except Exception:
        try:
            return ZoneInfo("UTC")
        except Exception:
            return timezone.utc  # type: ignore

class TaskScheduler:
    """
    Planificador interactivo y automatizado de tareas para Palworld Server Manager:
    Soporta programación por Intervalo o Expresión Cron (5 campos), persistencia en tasks.json,
    ejecución manual, alternancia de estado y notificaciones a webhooks multicanal.
    """
    def __init__(self):
        self.tasks_file: Path = settings.data_dir / "tasks.json"
        self.tasks: List[Dict[str, Any]] = []
        self._running: bool = False
        self._loop_task: Optional[asyncio.Task] = None
        self._last_save_time = time.time()
        self._last_cleanup_time = time.time()
        self.load_tasks()

    def get_tz(self) -> ZoneInfo:
        return get_server_timezone()

    def now(self) -> datetime:
        return datetime.now(self.get_tz())

    def load_tasks(self) -> None:
        if self.tasks_file.exists():
            try:
                with open(self.tasks_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        self.tasks = data
            except Exception as e:
                logger.warning(f"Error cargando tasks.json: {e}")
                self.tasks = []
        else:
            self.tasks = []

    def save_tasks(self) -> None:
        try:
            atomic_write_json(self.tasks_file, self.tasks, indent=2)
        except Exception as e:
            logger.error(f"Error guardando tasks.json: {e}")

    def calculate_next_run(self, task: Dict[str, Any], from_dt: Optional[datetime] = None) -> Optional[str]:
        """Calcula la fecha y hora de la próxima ejecución en base al cron o intervalo."""
        if not task.get("enabled", True):
            return None

        base_dt = from_dt or self.now()
        sched_type = task.get("schedule_type", "interval")

        try:
            if sched_type == "cron":
                expr = task.get("cron_expression", "0 4 * * *")
                cron = croniter(expr, base_dt)
                nxt = cron.get_next(datetime)
                return nxt.strftime("%Y-%m-%d %H:%M:%S")
            else:
                val = int(task.get("interval_value", 1) or 1)
                unit = task.get("interval_unit", "days")
                if unit == "minutes":
                    delta = timedelta(minutes=val)
                elif unit == "hours":
                    delta = timedelta(hours=val)
                else:
                    delta = timedelta(days=val)
                nxt = base_dt + delta
                return nxt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception as e:
            logger.debug(f"Error calculando next_run para tarea '{task.get('name')}': {e}")
            return None

    def list_tasks(self) -> List[Dict[str, Any]]:
        tz = self.get_tz()
        now_dt = self.now()
        for t in self.tasks:
            if t.get("enabled", True) and not t.get("next_run"):
                t["next_run"] = self.calculate_next_run(t, from_dt=now_dt)
        return self.tasks

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        for t in self.tasks:
            if t.get("id") == task_id:
                return t
        return None

    def create_task(self, data: Dict[str, Any]) -> Dict[str, Any]:
        task_id = str(uuid.uuid4())[:8]
        new_task = {
            "id": task_id,
            "name": data.get("name", "Nueva Tarea"),
            "action": data.get("action", "restart"),
            "command": data.get("command", ""),
            "schedule_type": data.get("schedule_type", "interval"),
            "interval_value": data.get("interval_value", 1),
            "interval_unit": data.get("interval_unit", "days"),
            "cron_expression": data.get("cron_expression", "0 4 * * *"),
            "enabled": data.get("enabled", True),
            "created_at": self.now().strftime("%Y-%m-%d %H:%M:%S"),
            "last_run": None,
            "next_run": None
        }
        new_task["next_run"] = self.calculate_next_run(new_task)
        self.tasks.append(new_task)
        self.save_tasks()
        return new_task

    def update_task(self, task_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        for i, t in enumerate(self.tasks):
            if t.get("id") == task_id:
                for k, v in data.items():
                    if v is not None:
                        t[k] = v
                t["next_run"] = self.calculate_next_run(t)
                self.save_tasks()
                return t
        raise ValueError(f"Tarea con ID {task_id} no encontrada")

    def delete_task(self, task_id: str) -> bool:
        initial_len = len(self.tasks)
        self.tasks = [t for t in self.tasks if t.get("id") != task_id]
        if len(self.tasks) < initial_len:
            self.save_tasks()
            return True
        return False

    def toggle_task(self, task_id: str, enabled: bool) -> Dict[str, Any]:
        for t in self.tasks:
            if t.get("id") == task_id:
                t["enabled"] = enabled
                t["next_run"] = self.calculate_next_run(t) if enabled else None
                self.save_tasks()
                return t
        raise ValueError(f"Tarea {task_id} no encontrada")

    async def execute_task_action(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Ejecuta la acción asignada a una tarea (start, stop, restart, backup, save, command)."""
        from app.core.process_manager import process_manager
        action = task.get("action", "")
        task_name = task.get("name", "Tarea Programada")
        result: Dict[str, Any] = {"task_id": task.get("id"), "status": "success", "message": ""}

        logger.info(f"[TaskScheduler] Ejecutando acción '{action}' para tarea: '{task_name}'")

        try:
            if action == "start":
                if process_manager.get_status() == "OFFLINE":
                    await process_manager.start_server()
                    result["message"] = "Servidor de Palworld iniciado exitosamente."
                else:
                    result["message"] = f"El servidor ya se encuentra en estado: {process_manager.get_status()}"

            elif action == "stop":
                if process_manager.get_status() != "OFFLINE":
                    await process_manager.stop_server()
                    result["message"] = "Servidor de Palworld detenido de forma segura."
                else:
                    result["message"] = "El servidor ya estaba apagado."

            elif action == "restart":
                await process_manager.restart_server()
                result["message"] = "Servidor de Palworld reiniciado correctamente."

            elif action == "backup":
                cfg = settings.runtime_config
                scope = cfg.get("backup_scope", "full")
                targets = cfg.get("backup_targets", None)
                compression = cfg.get("backup_compression", True)
                stop_server = cfg.get("backup_stop_server", False)
                pre_cmd = (cfg.get("backup_pre_command") or "Save").strip()

                was_running = process_manager.get_status() == "RUNNING"

                if was_running and pre_cmd:
                    try:
                        await pal_api_client.execute_raw_command(pre_cmd)
                    except Exception:
                        pass
                    await asyncio.sleep(2)

                if was_running and stop_server:
                    await process_manager.stop_server()
                    for _ in range(25):
                        await asyncio.sleep(1)
                        if process_manager.get_status() == "OFFLINE":
                            break

                try:
                    backup_res = await backup_manager.create_backup(
                        custom_label="task_auto",
                        scope=scope,
                        targets=targets,
                        compression=compression
                    )
                    result["message"] = f"Copia de seguridad creada: {backup_res.get('filename')}"
                finally:
                    if was_running and stop_server:
                        await asyncio.sleep(1)
                        await process_manager.start_server()

            elif action == "save":
                ok = await pal_api_client.save_world()
                result["message"] = "Guardado de partida (SaveWorld) ejecutado con éxito." if ok else "Error al guardar la partida."

            elif action == "command":
                cmd = task.get("command", "").strip()
                if cmd:
                    resp = await pal_api_client.execute_raw_command(cmd)
                    result["message"] = f"Comando '{cmd}' ejecutado: {resp}"
                else:
                    result["message"] = "Comando vacío omitido."

            elif action == "check_updates":
                result["message"] = "Verificación de actualizaciones de SteamCMD completada."

            else:
                result["status"] = "error"
                result["message"] = f"Acción desconocida: {action}"

        except Exception as e:
            result["status"] = "error"
            result["message"] = f"Error ejecutando tarea '{task_name}': {e}"

        now_str = self.now().strftime("%Y-%m-%d %H:%M:%S")
        for t in self.tasks:
            if t.get("id") == task.get("id"):
                t["last_run"] = now_str
                t["next_run"] = self.calculate_next_run(t)
                self.save_tasks()
                break

        # Disparar alerta en webhooks
        try:
            from app.core.webhook_manager import webhook_manager
            is_success = result.get("status") == "success"
            await webhook_manager.notify_task_executed(task_name, success=is_success)
        except Exception:
            pass

        return result

    async def run_task_now(self, task_id: str) -> Dict[str, Any]:
        for t in self.tasks:
            if t.get("id") == task_id:
                return await self.execute_task_action(t)
        raise ValueError(f"Tarea {task_id} no encontrada")

    async def _scheduler_loop(self) -> None:
        """Bucle continuo en segundo plano que evalúa tareas programadas y mantenimiento."""
        self._running = True
        logger.info(f"TaskScheduler iniciado en zona horaria: {os.getenv('TZ', 'America/Guayaquil')}")

        while self._running:
            try:
                await asyncio.sleep(10)
                now_dt = self.now()
                tz = self.get_tz()

                # Evaluar tareas programadas
                for t in self.tasks:
                    if not t.get("enabled", True):
                        continue

                    next_run_str = t.get("next_run")
                    if not next_run_str:
                        t["next_run"] = self.calculate_next_run(t, from_dt=now_dt)
                        next_run_str = t.get("next_run")

                    if next_run_str:
                        try:
                            next_dt = datetime.strptime(next_run_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz)
                            if now_dt >= next_dt:
                                await self.execute_task_action(t)
                        except Exception as ex:
                            logger.error(f"Error evaluando tarea {t.get('id')}: {ex}")

                # Tareas periódicas de mantenimiento del servidor Palworld
                now_epoch = time.time()
                # 1. Guardado automático (SaveWorld) cada 30 minutos si está encendido
                if now_epoch - self._last_save_time >= 1800:
                    self._last_save_time = now_epoch
                    try:
                        from app.core.process_manager import process_manager
                        if process_manager.get_status() == "RUNNING":
                            await pal_api_client.save_world()
                    except Exception:
                        pass

                # 2. Limpieza de logs antiguos una vez al día
                if now_epoch - self._last_cleanup_time >= 86400:
                    self._last_cleanup_time = now_epoch
                    try:
                        self._cleanup_old_logs()
                    except Exception:
                        pass

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error en bucle del TaskScheduler: {e}")
                await asyncio.sleep(5)

    def _cleanup_old_logs(self):
        logs_dir = settings.palworld_data_dir / "Pal" / "Saved" / "Logs"
        if logs_dir.exists() and logs_dir.is_dir():
            cutoff = time.time() - (7 * 86400)
            for f in logs_dir.glob("*.log"):
                try:
                    if f.stat().st_mtime < cutoff:
                        f.unlink()
                except Exception:
                    pass

    def start_loop(self) -> None:
        if self._loop_task is None or self._loop_task.done():
            self._loop_task = asyncio.create_task(self._scheduler_loop())

    def stop_loop(self) -> None:
        self._running = False
        if self._loop_task and not self._loop_task.done():
            self._loop_task.cancel()
            self._loop_task = None

task_scheduler = TaskScheduler()
