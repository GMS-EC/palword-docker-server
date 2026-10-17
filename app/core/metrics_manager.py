import os
import time
import asyncio
import psutil
from pathlib import Path
from collections import deque
from typing import Dict, Any, List, Optional

from app.config import settings
from app.core.pal_api_client import pal_api_client

def get_cgroup_memory_limit() -> Optional[int]:
    """Lee el límite de memoria asignado al contenedor en cgroups v2 o v1."""
    cgroup2_max = Path("/sys/fs/cgroup/memory.max")
    if cgroup2_max.exists():
        try:
            val = cgroup2_max.read_text().strip()
            if val != "max" and val.isdigit():
                return int(val)
        except Exception:
            pass

    cgroup1_limit = Path("/sys/fs/cgroup/memory/memory.limit_in_bytes")
    if cgroup1_limit.exists():
        try:
            val = int(cgroup1_limit.read_text().strip())
            if val < 10**15:
                return val
        except Exception:
            pass

    mem_env = os.getenv("MEM_LIMIT", "").strip().lower()
    if mem_env:
        try:
            if mem_env.endswith("g"):
                return int(float(mem_env[:-1]) * (1024**3))
            elif mem_env.endswith("m"):
                return int(float(mem_env[:-1]) * (1024**2))
        except Exception:
            pass

    return None

def get_cgroup_memory_usage() -> Optional[int]:
    """Lee el consumo real de memoria del contenedor en cgroups."""
    cgroup2_cur = Path("/sys/fs/cgroup/memory.current")
    if cgroup2_cur.exists():
        try:
            val = cgroup2_cur.read_text().strip()
            if val.isdigit():
                return int(val)
        except Exception:
            pass

    cgroup1_usage = Path("/sys/fs/cgroup/memory/memory.usage_in_bytes")
    if cgroup1_usage.exists():
        try:
            val = int(cgroup1_usage.read_text().strip())
            return val
        except Exception:
            pass

    return None

class MetricsManager:
    """
    Monitor de rendimiento en tiempo real para el servidor de Palworld y el sistema host.
    Almacena histórico para Canvas y Chart.js e integra métricas nativas del motor (Tickrate/FPS).
    """
    def __init__(self, history_points: int = 120):
        self.history_len = history_points
        self.timestamps: deque = deque(maxlen=history_points)
        self.cpu_history: deque = deque(maxlen=history_points)
        self.ram_history: deque = deque(maxlen=history_points)
        self.pal_ram_history: deque = deque(maxlen=history_points)
        self.fps_history: deque = deque(maxlen=history_points)
        self.history_samples: deque = deque(maxlen=history_points)

        self.peak_cpu: float = 0.0
        self.peak_mem_mb: int = 0
        self.peak_players: int = 0

        self._task: Optional[asyncio.Task] = None
        self._running: bool = False
        self.start_time: float = time.time()

        # Cache de métricas de proceso
        self._last_pal_metrics: Dict[str, Any] = {}

    def start(self):
        if not self._running:
            self._running = True
            self._task = asyncio.create_task(self._collection_loop())

    def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()

    async def _collection_loop(self):
        # Medición inicial
        psutil.cpu_percent(interval=None)
        while self._running:
            try:
                await self.collect_snapshot()
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[Metrics] Error colectando snapshot: {e}")
            await asyncio.sleep(2)

    def _get_pal_proc_metrics(self) -> Dict[str, float]:
        """Calcula consumo de CPU y RAM del ejecutable de Palworld."""
        from app.core.process_manager import process_manager
        pid = process_manager.get_server_pid()
        if not pid:
            return {"cpu": 0.0, "ram_bytes": 0, "ram_gb": 0.0}

        try:
            proc = psutil.Process(pid)
            cpu = proc.cpu_percent(interval=None)
            mem_info = proc.memory_info()
            rss = mem_info.rss
            # Sumar subprocesos hijos si existen
            for child in proc.children(recursive=True):
                try:
                    rss += child.memory_info().rss
                except Exception:
                    pass

            return {
                "cpu": round(cpu, 1),
                "ram_bytes": rss,
                "ram_gb": round(rss / (1024**3), 2)
            }
        except Exception:
            return {"cpu": 0.0, "ram_bytes": 0, "ram_gb": 0.0}

    async def collect_snapshot(self) -> Dict[str, Any]:
        from app.core.process_manager import process_manager
        now = time.time()
        time_label = time.strftime("%H:%M:%S")

        cpu = psutil.cpu_percent(interval=None)

        # Memoria total/usada respetando límites de contenedor Docker
        cg_limit = get_cgroup_memory_limit()
        cg_usage = get_cgroup_memory_usage()

        if cg_limit and cg_usage:
            ram_used = cg_usage
            ram_total = cg_limit
            ram_pct = round((ram_used / ram_total) * 100, 1)
        else:
            vm = psutil.virtual_memory()
            ram_used = vm.used
            ram_total = vm.total
            ram_pct = vm.percent

        pal_proc = self._get_pal_proc_metrics()

        # Obtener FPS / Tickrate si REST API está disponible
        server_fps = 0.0
        server_uptime = 0
        if process_manager.get_status() == "RUNNING":
            api_metrics = await pal_api_client.get_metrics()
            if api_metrics:
                server_fps = float(api_metrics.get("serverfps", 0.0))
                server_uptime = api_metrics.get("uptime", 0)

        # Uptime general del servidor de Palworld
        uptime_seconds = 0
        if process_manager.started_at and process_manager.get_status() == "RUNNING":
            uptime_seconds = int(now - process_manager.started_at)
        elif server_uptime > 0:
            uptime_seconds = server_uptime

        days = uptime_seconds // 86400
        hours = (uptime_seconds % 86400) // 3600
        minutes = (uptime_seconds % 3600) // 60
        seconds = uptime_seconds % 60
        uptime_formatted = f"{days}d {hours:02d}h {minutes:02d}m {seconds:02d}s" if days > 0 else f"{hours:02d}h {minutes:02d}m {seconds:02d}s"

        # Disco
        try:
            disk = psutil.disk_usage(str(settings.palworld_data_dir))
            disk_total_gb = round(disk.total / (1024**3), 1)
            disk_used_gb = round(disk.used / (1024**3), 1)
            disk_pct = disk.percent
        except Exception:
            disk_total_gb = 50.0
            disk_used_gb = 10.0
            disk_pct = 20.0

        # Memoria asignada o total en MB
        mem_used_mb = int(ram_used / (1024**2))
        mem_assigned_mb = int(ram_total / (1024**2))
        disk_used_mb = int(disk_used_gb * 1024)
        disk_limit_mb = int(disk_total_gb * 1024)

        # Contar jugadores actuales
        online_players_count = 0
        try:
            from app.core.player_manager import player_manager
            online_players_count = len(player_manager._current_online)
        except Exception:
            pass

        # Actualizar picos
        if cpu > self.peak_cpu:
            self.peak_cpu = cpu
        if mem_used_mb > self.peak_mem_mb:
            self.peak_mem_mb = mem_used_mb
        if online_players_count > self.peak_players:
            self.peak_players = online_players_count

        snapshot = {
            "timestamp": now,
            "label": time_label,
            "cpu_percent": cpu,
            "ram_percent": ram_pct,
            "memory_mb": mem_used_mb,
            "assigned_memory_mb": mem_assigned_mb,
            "ram_used_gb": round(ram_used / (1024**3), 2),
            "ram_total_gb": round(ram_total / (1024**3), 2),
            "pal_cpu_percent": pal_proc["cpu"],
            "pal_ram_gb": pal_proc["ram_gb"],
            "server_fps": round(server_fps, 1),
            "disk_total_gb": disk_total_gb,
            "disk_used_gb": disk_used_gb,
            "disk_used_mb": disk_used_mb,
            "disk_limit_mb": disk_limit_mb,
            "disk_percent": disk_pct,
            "online_players": online_players_count,
            "uptime_seconds": uptime_seconds,
            "uptime_formatted": uptime_formatted
        }

        self.timestamps.append(time_label)
        self.cpu_history.append(cpu)
        self.ram_history.append(ram_pct)
        self.pal_ram_history.append(pal_proc["ram_gb"])
        self.fps_history.append(server_fps)

        # Muestra formateada para canvas chart de metrics.js
        sample_point = {
            "timestamp": int(now),
            "time_str": time_label,
            "cpu": round(cpu, 1),
            "cpu_percent": round(cpu, 1),
            "ram": round(ram_pct, 1),
            "ram_percent": round(ram_pct, 1),
            "memory_percent": round(ram_pct, 1),
            "memory_mb": mem_used_mb,
            "disk_percent": round(disk_pct, 1),
            "disk_used_mb": round(disk_used_mb, 1),
            "fps": round(server_fps, 1),
            "server_fps": round(server_fps, 1),
            "players": online_players_count,
            "players_online": online_players_count
        }
        self.history_samples.append(sample_point)

        self._last_pal_metrics = snapshot
        return snapshot

    def get_current_metrics(self) -> Dict[str, Any]:
        if not self._last_pal_metrics:
            return {
                "cpu_percent": 0.0,
                "ram_percent": 0.0,
                "memory_mb": 0,
                "assigned_memory_mb": 16384,
                "ram_used_gb": 0.0,
                "ram_total_gb": 16.0,
                "pal_cpu_percent": 0.0,
                "pal_ram_gb": 0.0,
                "server_fps": 0.0,
                "disk_total_gb": 100.0,
                "disk_used_gb": 10.0,
                "disk_used_mb": 10240,
                "disk_limit_mb": 102400,
                "disk_percent": 10.0,
                "online_players": 0,
                "uptime_formatted": "00h 00m 00s"
            }
        return self._last_pal_metrics

    def get_chart_data(self) -> Dict[str, Any]:
        return {
            "labels": list(self.timestamps),
            "cpu": list(self.cpu_history),
            "ram": list(self.ram_history),
            "pal_ram": list(self.pal_ram_history),
            "fps": list(self.fps_history)
        }

    def get_history_data(self) -> Dict[str, Any]:
        """Devuelve el historial en el formato exacto requerido por el canvas de Metrics."""
        from app.core.process_manager import process_manager
        curr = self.get_current_metrics()
        samples = list(self.history_samples)

        avg_cpu = round(sum(s["cpu"] for s in samples) / max(1, len(samples)), 1) if samples else 0.0
        avg_ram = round(sum(s.get("memory_mb", 0) for s in samples) / max(1, len(samples))) if samples else 0

        fps_val = curr.get("server_fps", 0.0)
        uptime_sec = curr.get("uptime_seconds", 0)
        h = (uptime_sec % 86400) // 3600
        m = (uptime_sec % 3600) // 60
        s = uptime_sec % 60
        uptime_clock = f"{h:02d}:{m:02d}:{s:02d}"

        summary = {
            "current_status": process_manager.get_status(),
            "current_cpu": curr.get("cpu_percent", 0.0),
            "peak_cpu": round(self.peak_cpu, 1),
            "avg_cpu": avg_cpu,
            "current_mem_mb": curr.get("memory_mb", 0),
            "peak_mem_mb": self.peak_mem_mb,
            "avg_mem_mb": avg_ram,
            "assigned_mem_mb": curr.get("assigned_memory_mb", 16384),
            "disk_used_mb": curr.get("disk_used_mb", 10240),
            "disk_limit_mb": curr.get("disk_limit_mb", 102400),
            "disk_percent": curr.get("disk_percent", 10.0),
            "current_players": curr.get("online_players", 0),
            "peak_players": self.peak_players,
            "uptime_seconds": uptime_sec,
            "uptime_formatted": curr.get("uptime_formatted", "00h 00m 00s"),
            "uptime_clock": uptime_clock,
            "tps": {
                "1m": fps_val,
                "5m": fps_val,
                "15m": fps_val
            }
        }
        return {
            "history": samples,
            "summary": summary
        }

    def reset_history(self):
        """Reinicia el búfer de muestras y contadores de picos."""
        self.history_samples.clear()
        self.timestamps.clear()
        self.cpu_history.clear()
        self.ram_history.clear()
        self.pal_ram_history.clear()
        self.fps_history.clear()
        self.peak_cpu = 0.0
        self.peak_mem_mb = 0
        self.peak_players = 0

metrics_manager = MetricsManager()
