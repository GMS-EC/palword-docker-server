import os
import time
import tarfile
import shutil
import asyncio
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

from app.config import settings
from app.core.pal_api_client import pal_api_client

class BackupManager:
    """
    Gestiona la creación, restauración, rotación y descarga de copias de seguridad de Palworld.
    Respalda de forma íntegra el directorio Pal/Saved (mundos guardados en SaveGames,
    inventarios de jugadores, bases y configuración PalWorldSettings.ini).
    """
    def __init__(self):
        self.backup_dir: Path = settings.backups_dir
        self.saved_dir: Path = settings.palworld_data_dir / "Pal" / "Saved"

    def _resolve_backup(self, filename: str) -> Optional[Path]:
        """Resuelve un nombre de backup dentro de backup_dir rechazando path traversal."""
        if not filename or "/" in filename or "\\" in filename or ".." in filename:
            return None
        target = (self.backup_dir / Path(filename).name).resolve()
        if not self._is_subpath(target, self.backup_dir):
            return None
        return target if target.exists() and target.is_file() else None

    @staticmethod
    def _is_subpath(path: Path, parent: Path) -> bool:
        try:
            path.resolve().relative_to(parent.resolve())
            return True
        except (ValueError, AttributeError):
            return False

    @staticmethod
    def _format_size(size_bytes: int) -> str:
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
        else:
            return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"

    def list_backups(self) -> List[Dict[str, Any]]:
        """Lista todos los archivos de respaldo en orden cronológico inverso con formato enriquecido."""
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        results = []
        valid_exts = (".tar.gz", ".tar.bz2", ".tgz", ".zip")
        try:
            for item in self.backup_dir.iterdir():
                if item.is_file() and any(item.name.endswith(ext) for ext in valid_exts):
                    stat = item.stat()
                    size_bytes = stat.st_size
                    size_mb = round(size_bytes / (1024 * 1024), 2)
                    size_fmt = self._format_size(size_bytes)
                    created_str = datetime.fromtimestamp(stat.st_mtime).strftime("%d/%m/%Y %H:%M:%S")

                    name_lower = item.name.lower()
                    is_auto = "auto" in name_lower
                    scope = "full"
                    if "worlds" in name_lower or "savegames" in name_lower:
                        scope = "worlds"
                    elif "config" in name_lower or "cfg" in name_lower:
                        scope = "config"
                    elif "custom" in name_lower:
                        scope = "custom"

                    results.append({
                        "filename": item.name,
                        "size_bytes": size_bytes,
                        "size_formatted": size_fmt,
                        "size_mb": size_mb,
                        "created_at": created_str,
                        "timestamp": stat.st_mtime,
                        "is_auto": is_auto,
                        "scope": scope
                    })
        except Exception as e:
            print(f"[BackupManager] Error listando respaldos: {e}")

        # Ordenar por fecha descendente (el más reciente primero)
        results.sort(key=lambda x: x["timestamp"], reverse=True)
        return results

    def get_available_targets(self) -> List[Dict[str, Any]]:
        """Devuelve las carpetas y archivos clave del servidor de Palworld para respaldos selectivos."""
        data_dir = settings.palworld_data_dir
        candidates = [
            ("Pal/Saved", "world", "Directorio Completo de Estado y Mundos (Pal/Saved)"),
            ("Pal/Saved/SaveGames", "world", "Partidas y Datos de Jugadores (SaveGames)"),
            ("Pal/Saved/Config/LinuxServer", "config", "Configuraciones del Servidor (PalWorldSettings.ini)"),
            ("Pal/Content/Paks/~mods", "plugin", "Mods y Extensiones de Motor (~mods)"),
        ]
        targets = []
        for rel_path, t_type, desc in candidates:
            p = data_dir / Path(rel_path)
            size_bytes = 0
            exists = p.exists()
            if exists:
                if p.is_dir():
                    try:
                        size_bytes = sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
                    except Exception:
                        size_bytes = 0
                else:
                    try:
                        size_bytes = p.stat().st_size
                    except Exception:
                        size_bytes = 0
            targets.append({
                "name": rel_path,
                "is_dir": p.is_dir() if exists else True,
                "type": t_type,
                "desc": desc,
                "size_bytes": size_bytes,
                "size_fmt": self._format_size(size_bytes) if exists else "No creado aún"
            })
        return targets

    async def create_backup(
        self,
        custom_label: str = "",
        scope: str = "full",
        targets: Optional[List[str]] = None,
        is_auto: bool = False
    ) -> Dict[str, Any]:
        """Crea un archivo comprimido .tar.gz con los datos de Palworld según el alcance solicitado."""
        from app.core.process_manager import process_manager

        # Si el servidor está encendido, guardamos el mundo primero para máxima consistencia
        if process_manager.get_status() == "RUNNING":
            try:
                await pal_api_client.save_world()
                await asyncio.sleep(1)
            except Exception:
                pass

        self.backup_dir.mkdir(parents=True, exist_ok=True)
        now_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        prefix = "palworld_auto" if is_auto else "palworld_backup"
        scope_part = f"_{scope}" if scope != "full" else ""
        label_part = f"_{custom_label.strip()}" if custom_label.strip() else ""
        backup_filename = f"{prefix}_{now_str}{scope_part}{label_part}.tar.gz"
        dest_path = self.backup_dir / backup_filename

        loop = asyncio.get_running_loop()
        data_dir = settings.palworld_data_dir

        def _compress():
            with tarfile.open(dest_path, "w:gz") as tar:
                if scope == "worlds":
                    sg = data_dir / "Pal" / "Saved" / "SaveGames"
                    if sg.exists():
                        tar.add(sg, arcname="Saved/SaveGames")
                elif scope == "config":
                    cfg = data_dir / "Pal" / "Saved" / "Config"
                    if cfg.exists():
                        tar.add(cfg, arcname="Saved/Config")
                elif scope == "custom" and targets:
                    for t in targets:
                        target_p = data_dir / Path(t)
                        if target_p.exists():
                            tar.add(target_p, arcname=t)
                else:
                    # Scope Full: respaldar Pal/Saved completo
                    if self.saved_dir.exists():
                        tar.add(self.saved_dir, arcname="Saved")

        try:
            await loop.run_in_executor(None, _compress)
            size_bytes = dest_path.stat().st_size
            size_mb = round(size_bytes / (1024 * 1024), 2)
            size_fmt = self._format_size(size_bytes)

            # Notificar Discord webhook
            try:
                from app.core.webhook_manager import webhook_manager
                await webhook_manager.notify_backup(backup_filename, size_mb)
            except Exception:
                pass

            # Rotar respaldos si excede el límite
            self.prune_backups()

            return {
                "success": True,
                "filename": backup_filename,
                "size_bytes": size_bytes,
                "size_formatted": size_fmt,
                "size_mb": size_mb,
                "message": f"Respaldo creado con éxito ({size_fmt})."
            }
        except Exception as e:
            if dest_path.exists():
                try:
                    dest_path.unlink()
                except Exception:
                    pass
            return {"success": False, "message": f"Error creando respaldo: {e}"}

    async def restore_backup(self, filename: str) -> Dict[str, Any]:
        """Restaura una copia de seguridad seleccionada."""
        from app.core.process_manager import process_manager
        archive_path = self._resolve_backup(filename)
        if not archive_path:
            return {"success": False, "message": "Archivo de respaldo no encontrado o inválido."}

        was_running = process_manager.get_status() == "RUNNING"
        if was_running:
            await process_manager.stop_server()

        loop = asyncio.get_running_loop()

        def _extract():
            # Crear respaldo de seguridad pre-restauración en caso de contingencia
            if self.saved_dir.exists():
                pre_restore = self.saved_dir.parent / f"Saved_pre_restore_{int(time.time())}"
                shutil.move(str(self.saved_dir), str(pre_restore))

            dest_root = self.saved_dir.parent.resolve()
            dest_root.mkdir(parents=True, exist_ok=True)
            with tarfile.open(archive_path, "r:gz") as tar:
                # Protección contra vulnerabilidades Tar Slip / Path Traversal
                for member in tar.getmembers():
                    member_target = (dest_root / member.name).resolve()
                    if not self._is_subpath(member_target, dest_root):
                        raise ValueError(f"Ruta no permitida detectada en el archivo de respaldo: {member.name}")
                if hasattr(tarfile, 'data_filter'):
                    tar.extractall(path=dest_root, filter='data')
                else:
                    tar.extractall(path=dest_root)

        try:
            await loop.run_in_executor(None, _extract)

            if was_running:
                await process_manager.start_server()

            return {"success": True, "message": f"Respaldo '{filename}' restaurado exitosamente."}
        except Exception as e:
            return {"success": False, "message": f"Error durante la restauración: {e}"}

    def delete_backup(self, filename: str) -> Dict[str, Any]:
        """Elimina un archivo de respaldo específico."""
        archive_path = self._resolve_backup(filename)
        if not archive_path:
            return {"success": False, "message": "Archivo no encontrado."}
        try:
            archive_path.unlink()
            return {"success": True, "message": f"Respaldo '{filename}' eliminado."}
        except Exception as e:
            return {"success": False, "message": f"No se pudo eliminar el archivo: {e}"}

    def prune_backups(self) -> int:
        """Elimina los respaldos más antiguos que superen el límite configurado."""
        max_count = int(settings.runtime_config.get("backup_max_count", os.getenv("BACKUP_MAX_COUNT", 10)))
        backups = self.list_backups()
        if len(backups) <= max_count:
            return 0

        to_remove = backups[max_count:]
        deleted_count = 0
        for b in to_remove:
            target = self.backup_dir / b["filename"]
            if target.exists():
                try:
                    target.unlink()
                    deleted_count += 1
                except Exception:
                    pass
        return deleted_count

backup_manager = BackupManager()
