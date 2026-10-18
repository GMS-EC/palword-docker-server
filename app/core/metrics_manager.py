import os
import time
import asyncio
import subprocess
import psutil
from pathlib import Path
from collections import deque
from typing import Dict, Any, List, Optional

from app.config import settings
from app.core.pal_api_client import pal_api_client


def get_cgroup_memory_limit() -> Optional[int]:
    """Lee el límite de memoria asignado al contenedor en cgroups v2, v1 o por variable de entorno."""
    # cgroups v2
    cgroup2_max = Path("/sys/fs/cgroup/memory.max")
    if cgroup2_max.exists():
        try:
            val = cgroup2_max.read_text().strip()
            if val != "max" and val.isdigit():
                return int(val)
        except Exception:
            pass

    # cgroups v1
    cgroup1_limit = Path("/sys/fs/cgroup/memory/memory.limit_in_bytes")
    if cgroup1_limit.exists():
        try:
            val = int(cgroup1_limit.read_text().strip())
            if val < 10**15:
                return val
        except Exception:
            pass

    # Variable de entorno de Docker/Compose (ej. MEM_LIMIT=8g o MEMORY_LIMIT=16g)
    mem_env = (os.getenv("MEM_LIMIT") or os.getenv("MEMORY_LIMIT") or "").strip().lower()
    if mem_env:
        try:
            if mem_env.endswith("g") or mem_env.endswith("gb"):
                num = mem_env.rstrip("gb").strip()
                return int(float(num) * (1024**3))
            elif mem_env.endswith("m") or mem_env.endswith("mb"):
                num = mem_env.rstrip("mb").strip()
                return int(float(num) * (1024**2))
            elif mem_env.isdigit():
                return int(float(mem_env) * (1024**3))
        except Exception:
            pass

    return None


def get_cgroup_memory_usage() -> Optional[int]:
    """
    Lee el consumo real de memoria del contenedor en cgroups,
    descontando la caché inactiva de archivos (inactive_file),
    tal como hace 'docker stats' para no reportar memoria inflada por el SO.
    """
    # cgroups v2
    cgroup2_cur = Path("/sys/fs/cgroup/memory.current")
    if cgroup2_cur.exists():
        try:
            val = cgroup2_cur.read_text().strip()
            if val.isdigit():
                cur_bytes = int(val)
                # Descontar cache inactiva (inactive_file)
                cg2_stat = Path("/sys/fs/cgroup/memory.stat")
                inactive_file = 0
                if cg2_stat.exists():
                    for line in cg2_stat.read_text().splitlines():
                        if line.startswith("inactive_file"):
                            parts = line.split()
                            if len(parts) >= 2 and parts[1].isdigit():
                                inactive_file = int(parts[1])
                                break
                return max(0, cur_bytes - inactive_file)
        except Exception:
            pass

    # cgroups v1
    cgroup1_usage = Path("/sys/fs/cgroup/memory/memory.usage_in_bytes")
    if cgroup1_usage.exists():
        try:
            val = int(cgroup1_usage.read_text().strip())
            cg1_stat = Path("/sys/fs/cgroup/memory/memory.stat")
            inactive_file = 0
            if cg1_stat.exists():
                for line in cg1_stat.read_text().splitlines():
                    if line.startswith("total_inactive_file"):
                        parts = line.split()
                        if len(parts) >= 2 and parts[1].isdigit():
                            inactive_file = int(parts[1])
                            break
            return max(0, val - inactive_file)
        except Exception:
            pass

    return None


def get_container_process_ram_bytes() -> int:
    """Suma el RSS de todos los procesos accesibles en el contenedor (fallback sin cgroups)."""
    total_rss = 0
    try:
        for p in psutil.process_iter(['pid', 'memory_info']):
            try:
                mem = p.info.get('memory_info')
                if mem and hasattr(mem, 'rss'):
                    total_rss += mem.rss
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception:
        pass
    return total_rss


def get_cgroup_cpu_usage_ns() -> Optional[int]:
    """Lee el tiempo acumulado de CPU consumido por el contenedor en nanosegundos (cgroups v2 o v1)."""
    # cgroups v2 (/sys/fs/cgroup/cpu.stat -> usage_usec)
    cg2_stat = Path("/sys/fs/cgroup/cpu.stat")
    if cg2_stat.exists():
        try:
            for line in cg2_stat.read_text().splitlines():
                if line.startswith("usage_usec"):
                    parts = line.split()
                    if len(parts) >= 2 and parts[1].isdigit():
                        return int(parts[1]) * 1000
        except Exception:
            pass

    # cgroups v1 (/sys/fs/cgroup/cpuacct/cpuacct.usage o variantes)
    for p in [
        Path("/sys/fs/cgroup/cpuacct/cpuacct.usage"),
        Path("/sys/fs/cgroup/cpu,cpuacct/cpuacct.usage"),
        Path("/sys/fs/cgroup/cpu/cpuacct.usage"),
        Path("/sys/fs/cgroup/cpuacct.usage")
    ]:
        if p.exists():
            try:
                val = p.read_text().strip()
                if val.isdigit():
                    return int(val)
            except Exception:
                pass

    return None


def get_container_cpu_cores() -> float:
    """Calcula el número de cores asignados al contenedor según cgroups o el host."""
    # cgroups v2 (/sys/fs/cgroup/cpu.max: "quota period")
    cg2_max = Path("/sys/fs/cgroup/cpu.max")
    if cg2_max.exists():
        try:
            parts = cg2_max.read_text().strip().split()
            if len(parts) >= 2 and parts[0] != "max" and parts[0].isdigit() and parts[1].isdigit():
                quota = int(parts[0])
                period = int(parts[1])
                if period > 0:
                    return max(0.1, quota / period)
        except Exception:
            pass

    # cgroups v1 (/sys/fs/cgroup/cpu/cpu.cfs_quota_us y cpu.cfs_period_us)
    cg1_quota = Path("/sys/fs/cgroup/cpu/cpu.cfs_quota_us")
    cg1_period = Path("/sys/fs/cgroup/cpu/cpu.cfs_period_us")
    if cg1_quota.exists() and cg1_period.exists():
        try:
            quota = int(cg1_quota.read_text().strip())
            period = int(cg1_period.read_text().strip())
            if quota > 0 and period > 0:
                return max(0.1, quota / period)
        except Exception:
            pass

    return float(os.cpu_count() or 1)


def get_configured_disk_limit_bytes() -> Optional[int]:
    """Lee el límite de disco configurado en variables de entorno (DISK_LIMIT / MAX_DISK_GB)."""
    val = os.getenv("DISK_LIMIT") or os.getenv("MAX_DISK_GB") or os.getenv("STORAGE_LIMIT")
    if val:
        val = str(val).strip().lower()
        try:
            if val.endswith("g") or val.endswith("gb"):
                num = val.rstrip("gb").strip()
                return int(float(num) * (1024**3))
            elif val.endswith("m") or val.endswith("mb"):
                num = val.rstrip("mb").strip()
                return int(float(num) * (1024**2))
            elif val.isdigit():
                return int(float(val) * (1024**3))
        except Exception:
            pass
    return None


def _get_container_storage_paths() -> List[Path]:
    """Retorna las rutas únicas de almacenamiento persistente del contenedor."""
    paths: List[Path] = []
    seen: set = set()
    for p in [settings.palworld_data_dir, settings.backups_dir, settings.data_dir]:
        if p and p.exists():
            resolved = p.resolve()
            if not any(resolved == s or resolved in s.parents for s in seen):
                seen.add(resolved)
                paths.append(resolved)
    return paths


def _calculate_dir_size_bytes(path: Path) -> int:
    """Calcula el tamaño en bytes de un directorio (usando 'du -sb' en Linux si existe, o scandir)."""
    try:
        res = subprocess.run(
            ["du", "-sb", str(path)],
            capture_output=True,
            text=True,
            timeout=2.0
        )
        if res.returncode == 0:
            line = res.stdout.strip().split()
            if line and line[0].isdigit():
                return int(line[0])
    except Exception:
        pass

    total = 0
    try:
        for entry in os.scandir(path):
            try:
                if entry.is_file(follow_symlinks=False):
                    total += entry.stat(follow_symlinks=False).st_size
                elif entry.is_dir(follow_symlinks=False):
                    total += _calculate_dir_size_bytes(Path(entry.path))
            except Exception:
                continue
    except Exception:
        pass
    return total


class MetricsManager:
    """
    Monitor de rendimiento en tiempo real aislado exclusivamente al contenedor Docker
    y al servidor de Palworld.
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

        # Delta de cgroups CPU para aislamiento de contenedor
        self._last_cg_cpu_ns: Optional[int] = None
        self._last_cg_cpu_time: Optional[float] = None

        # Cache de almacenamiento de disco para evitar I/O redundante en cada snapshot
        self._cached_disk_info: Dict[str, Any] = {}
        self._last_disk_calc_time: float = 0.0

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
        """Calcula consumo de CPU y RAM del ejecutable de Palworld y sus subprocesos."""
        from app.core.process_manager import process_manager
        pid = process_manager.get_server_pid()
        if not pid:
            return {"cpu": 0.0, "ram_bytes": 0, "ram_gb": 0.0}

        try:
            proc = psutil.Process(pid)
            cpu = proc.cpu_percent(interval=None)
            mem_info = proc.memory_info()
            rss = mem_info.rss
            # Sumar subprocesos hijos (ej. PalServer-Linux-Shipping bajo PalServer.sh)
            for child in proc.children(recursive=True):
                try:
                    cpu += child.cpu_percent(interval=None)
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

    async def _get_disk_metrics(self) -> Dict[str, Any]:
        """Calcula el espacio utilizado exclusivamente por el contenedor y el espacio disponible."""
        now = time.time()
        if self._cached_disk_info and (now - self._last_disk_calc_time < 60.0):
            return self._cached_disk_info

        try:
            paths = _get_container_storage_paths()
            free_bytes = 0
            try:
                du = psutil.disk_usage(str(settings.palworld_data_dir))
                free_bytes = du.free
            except Exception:
                free_bytes = 50 * (1024**3)

            def _calc_total() -> int:
                total = 0
                for p in paths:
                    total += _calculate_dir_size_bytes(p)
                return total

            container_used_bytes = await asyncio.to_thread(_calc_total)

            configured_limit = get_configured_disk_limit_bytes()
            if configured_limit:
                effective_total_bytes = min(configured_limit, container_used_bytes + free_bytes)
            else:
                effective_total_bytes = container_used_bytes + free_bytes

            if effective_total_bytes <= 0:
                effective_total_bytes = 10 * (1024**3)

            pct = round((container_used_bytes / effective_total_bytes) * 100, 1)

            disk_total_gb = round(effective_total_bytes / (1024**3), 1)
            disk_used_gb = round(container_used_bytes / (1024**3), 2)
            disk_used_mb = int(container_used_bytes / (1024**2))
            disk_limit_mb = int(effective_total_bytes / (1024**2))
            disk_free_mb = int(free_bytes / (1024**2))

            result = {
                "disk_total_gb": disk_total_gb,
                "disk_used_gb": disk_used_gb,
                "disk_used_mb": disk_used_mb,
                "disk_limit_mb": disk_limit_mb,
                "disk_free_mb": disk_free_mb,
                "disk_percent": pct
            }
            self._cached_disk_info = result
            self._last_disk_calc_time = now
            return result
        except Exception:
            if self._cached_disk_info:
                return self._cached_disk_info
            return {
                "disk_total_gb": 50.0,
                "disk_used_gb": 5.0,
                "disk_used_mb": 5120,
                "disk_limit_mb": 51200,
                "disk_free_mb": 46080,
                "disk_percent": 10.0
            }

    async def collect_snapshot(self) -> Dict[str, Any]:
        from app.core.process_manager import process_manager
        now = time.time()
        time_label = time.strftime("%H:%M:%S")

        # 1. CPU del contenedor (cgroups delta o suma de procesos del contenedor)
        cores = get_container_cpu_cores()
        cg_cpu_ns = get_cgroup_cpu_usage_ns()
        cpu: float = 0.0

        if cg_cpu_ns is not None:
            if self._last_cg_cpu_ns is not None and self._last_cg_cpu_time is not None:
                delta_ns = cg_cpu_ns - self._last_cg_cpu_ns
                delta_t = now - self._last_cg_cpu_time
                if delta_t > 0.1 and delta_ns >= 0:
                    cpu = (delta_ns / 1e9) / (delta_t * cores) * 100.0
                    cpu = round(min(100.0, max(0.0, cpu)), 1)
            self._last_cg_cpu_ns = cg_cpu_ns
            self._last_cg_cpu_time = now
        else:
            pal_proc = self._get_pal_proc_metrics()
            panel_cpu = 0.0
            try:
                panel_cpu = psutil.Process().cpu_percent(interval=None)
            except Exception:
                pass
            total_proc_cpu = pal_proc.get("cpu", 0.0) + panel_cpu
            cpu = round(min(100.0, max(0.0, total_proc_cpu / cores)), 1)

        # Si el servidor está apagado (OFFLINE), el juego no consume CPU
        # y la aplicación panel en reposo se normaliza
        if process_manager.get_status() == "OFFLINE":
            cpu = min(cpu, 0.5)

        # 2. Memoria RAM aislada al contenedor (cgroups descontando inactive_file o procesos del contenedor)
        cg_limit = get_cgroup_memory_limit()
        cg_usage = get_cgroup_memory_usage()

        if cg_limit and cg_limit > 0:
            ram_total = cg_limit
        else:
            ram_total = psutil.virtual_memory().total

        if cg_usage is not None and cg_usage > 0:
            ram_used = cg_usage
        else:
            ram_used = get_container_process_ram_bytes()

        ram_pct = round((ram_used / max(1, ram_total)) * 100, 1)

        pal_proc = self._get_pal_proc_metrics()

        # 3. Obtener FPS / Tickrate si REST API está disponible
        server_fps = 0.0
        server_uptime = 0
        if process_manager.get_status() == "RUNNING":
            api_metrics = await pal_api_client.get_metrics()
            if api_metrics:
                server_fps = float(api_metrics.get("serverfps", 0.0))
                server_uptime = api_metrics.get("uptime", 0)

        # 4. Uptime general del servidor de Palworld
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

        # 5. Métricas de almacenamiento del contenedor (/server_data y backups)
        disk_info = await self._get_disk_metrics()
        disk_total_gb = disk_info["disk_total_gb"]
        disk_used_gb = disk_info["disk_used_gb"]
        disk_used_mb = disk_info["disk_used_mb"]
        disk_limit_mb = disk_info["disk_limit_mb"]
        disk_free_mb = disk_info.get("disk_free_mb", max(0, disk_limit_mb - disk_used_mb))
        disk_pct = disk_info["disk_percent"]

        # Memoria asignada o total en MB
        mem_used_mb = int(ram_used / (1024**2))
        mem_assigned_mb = int(ram_total / (1024**2))

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
            "disk_free_mb": disk_free_mb,
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
            cg_limit = get_cgroup_memory_limit()
            if cg_limit and cg_limit > 0:
                host_mem_mb = int(cg_limit / (1024**2))
                host_mem_gb = round(cg_limit / (1024**3), 1)
            else:
                vm = psutil.virtual_memory()
                host_mem_mb = int(vm.total / (1024**2))
                host_mem_gb = round(vm.total / (1024**3), 1)

            disk_limit_b = get_configured_disk_limit_bytes()
            disk_lim_mb = int(disk_limit_b / (1024**2)) if disk_limit_b else 102400
            disk_lim_gb = round(disk_lim_mb / 1024, 1)

            return {
                "cpu_percent": 0.0,
                "ram_percent": 0.0,
                "memory_mb": 0,
                "assigned_memory_mb": host_mem_mb,
                "ram_used_gb": 0.0,
                "ram_total_gb": host_mem_gb,
                "pal_cpu_percent": 0.0,
                "pal_ram_gb": 0.0,
                "server_fps": 0.0,
                "disk_total_gb": disk_lim_gb,
                "disk_used_gb": 0.0,
                "disk_used_mb": 0,
                "disk_limit_mb": disk_lim_mb,
                "disk_free_mb": disk_lim_mb,
                "disk_percent": 0.0,
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

        avg_cpu = round(sum(s.get("cpu", 0) for s in samples) / max(1, len(samples)), 1) if samples else 0.0
        avg_ram = round(sum(s.get("memory_mb", 0) for s in samples) / max(1, len(samples))) if samples else 0

        uptime_sec = curr.get("uptime_seconds", 0)
        h = (uptime_sec % 86400) // 3600
        m = (uptime_sec % 3600) // 60
        s = uptime_sec % 60
        uptime_clock = f"{h:02d}:{m:02d}:{s:02d}"

        mem_mb = curr.get("memory_mb", 0)
        assigned_mb = curr.get("assigned_memory_mb", 8192)
        ram_pct = curr.get("ram_percent", round((mem_mb / max(1, assigned_mb)) * 100, 1))

        summary = {
            "current_status": process_manager.get_status(),
            "current_cpu": curr.get("cpu_percent", 0.0),
            "peak_cpu": round(self.peak_cpu, 1),
            "avg_cpu": avg_cpu,
            "current_mem_mb": mem_mb,
            "current_ram_mb": mem_mb,
            "current_ram_percent": ram_pct,
            "ram_percent": ram_pct,
            "peak_mem_mb": self.peak_mem_mb,
            "peak_ram_mb": self.peak_mem_mb,
            "avg_mem_mb": avg_ram,
            "avg_ram_mb": avg_ram,
            "assigned_mem_mb": assigned_mb,
            "assigned_ram_mb": assigned_mb,
            "disk_used_mb": curr.get("disk_used_mb", 0),
            "disk_limit_mb": curr.get("disk_limit_mb", 102400),
            "disk_free_mb": curr.get("disk_free_mb", 102400),
            "disk_percent": curr.get("disk_percent", 0.0),
            "current_players": curr.get("online_players", 0),
            "peak_players": self.peak_players,
            "uptime_seconds": uptime_sec,
            "uptime_formatted": curr.get("uptime_formatted", "00h 00m 00s"),
            "uptime_clock": uptime_clock
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
