import os
import re
import shutil
import time
import zipfile
from pathlib import Path
from typing import List, Dict, Any, Optional
from fastapi import HTTPException, UploadFile

from app.config import settings
from app.core.fs_utils import atomic_write_text

PROTECTED_FILES = {"pal_panel_config.json"}

class FileManager:
    """
    Gestor de archivos completo y seguro para Palworld Server Manager.
    Previene vulnerabilidades de Path Traversal verificando que todas las operaciones
    se restrinjan estrictamente a settings.palworld_data_dir o settings.backups_dir.
    Soporta navegación, creación, edición, renombrado, duplicado, subida,
    descarga, compresión y descompresión de archivos ZIP.
    """
    def __init__(self):
        self.base_dir: Path = settings.palworld_data_dir

    def _is_subpath(self, path: Path, parent: Path) -> bool:
        try:
            path.resolve().relative_to(parent.resolve())
            return True
        except (ValueError, AttributeError):
            try:
                p_str = os.path.abspath(str(path.resolve()))
                parent_str = os.path.abspath(str(parent.resolve()))
                return p_str == parent_str or p_str.startswith(parent_str + os.sep)
            except Exception:
                return False

    def _rel_to_root(self, path: Path) -> str:
        """Calcula la ruta relativa respecto a la raíz correspondiente."""
        for root in (self.base_dir, settings.backups_dir):
            try:
                rel = path.resolve().relative_to(root.resolve())
                return str(rel).replace("\\", "/")
            except (ValueError, AttributeError):
                continue
        return path.name

    def _is_special_root(self, path: Path) -> bool:
        p = path.resolve()
        return p in (self.base_dir.resolve(), settings.backups_dir.resolve())

    def _assert_not_protected(self, path: str) -> None:
        if Path(path).name in PROTECTED_FILES:
            raise HTTPException(status_code=403, detail="Archivo de configuración protegido: use el panel de Ajustes.")

    def _resolve_safe_path(self, relative_path: str = "") -> Path:
        clean_rel = (relative_path or "").replace("\\", "/").strip("/")
        
        # Normalizar si el frontend envía alias como "data", "/data", "palworld", "/palworld"
        if clean_rel in ("data", "palworld", "/data", "/palworld"):
            clean_rel = ""
        elif clean_rel.startswith("data/"):
            clean_rel = clean_rel[len("data/"):].lstrip("/")
        elif clean_rel.startswith("palworld/"):
            clean_rel = clean_rel[len("palworld/"):].lstrip("/")

        # Acceso transparente a respaldos
        if clean_rel == "backups" or clean_rel.startswith("backups/"):
            sub_rel = clean_rel[len("backups"):].lstrip("/")
            target = (settings.backups_dir / sub_rel).resolve()
            if not self._is_subpath(target, settings.backups_dir):
                raise HTTPException(status_code=403, detail="Acceso denegado fuera de la carpeta de respaldos.")
            return target

        # Asegurar que el directorio base de datos existe
        try:
            self.base_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

        target = (self.base_dir / clean_rel).resolve()
        if not self._is_subpath(target, self.base_dir):
            raise HTTPException(status_code=403, detail="Acceso denegado: intento de salida de directorio.")
        return target

    def list_directory(self, relative_path: str = "") -> Dict[str, Any]:
        """Lista el contenido de un directorio con metadatos completos y tolerancia a permisos."""
        try:
            safe_path = self._resolve_safe_path(relative_path)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Ruta inválida: {e}")

        # Si el directorio no existe pero es la raíz, crearlo
        if not safe_path.exists() and (not relative_path or relative_path in ("data", "palworld", "/data", "/palworld")):
            try:
                safe_path.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass

        if not safe_path.exists():
            return {"current_path": relative_path, "items": []}
        if not safe_path.is_dir():
            raise HTTPException(status_code=400, detail="La ruta especificada no es un directorio.")

        items: List[Dict[str, Any]] = []

        # Si estamos en la raíz del servidor, exponer la carpeta virtual de respaldos
        try:
            if safe_path.resolve() == self.base_dir.resolve():
                items.append({
                    "name": "backups",
                    "type": "directory",
                    "size_formatted": "-",
                    "size_bytes": 0,
                    "modified": "-",
                    "extension": "",
                    "is_special": True,
                    "path": "backups"
                })
        except Exception:
            pass

        try:
            entries = list(safe_path.iterdir())
        except Exception as iter_err:
            print(f"[FileManager] Advertencia al iterar directorio {safe_path}: {iter_err}")
            entries = []

        for entry in entries:
            # Ocultar archivos protegidos del panel
            if entry.name in PROTECTED_FILES:
                continue

            try:
                stat = entry.stat()
                is_dir = entry.is_dir()
                mod_time = time.strftime("%d/%m/%Y %H:%M", time.localtime(stat.st_mtime))
                
                size_str = "-"
                size_bytes = 0
                if not is_dir:
                    size_bytes = stat.st_size
                    if size_bytes < 1024:
                        size_str = f"{size_bytes} B"
                    elif size_bytes < 1024 * 1024:
                        size_str = f"{size_bytes / 1024:.1f} KB"
                    elif size_bytes < 1024 * 1024 * 1024:
                        size_str = f"{size_bytes / (1024 * 1024):.1f} MB"
                    else:
                        size_str = f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"

                ext = entry.suffix.lstrip(".").lower() if not is_dir else ""
                rel = self._rel_to_root(entry)

                items.append({
                    "name": entry.name,
                    "type": "directory" if is_dir else "file",
                    "is_dir": is_dir,
                    "size": size_bytes,
                    "size_bytes": size_bytes,
                    "size_formatted": size_str,
                    "modified": int(stat.st_mtime),
                    "modified_timestamp": int(stat.st_mtime),
                    "modified_str": mod_time,
                    "extension": ext,
                    "is_special": False,
                    "path": rel
                })
            except Exception:
                continue

        # Ordenar: directorios primero, luego archivos alfabéticamente
        items.sort(key=lambda x: (0 if x["is_dir"] else 1, x["name"].lower()))

        return {
            "current_path": (relative_path or "").replace("\\", "/"),
            "items": items
        }

    def read_file(self, relative_path: str) -> Dict[str, Any]:
        """Lee el contenido de un archivo de texto seguro."""
        self._assert_not_protected(relative_path)
        safe_path = self._resolve_safe_path(relative_path)
        if not safe_path.exists() or not safe_path.is_file():
            raise HTTPException(status_code=404, detail="Archivo no encontrado.")

        # Límite de 5 MB para edición web
        if safe_path.stat().st_size > 5 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="El archivo excede el tamaño máximo permitido para edición web (5 MB).")

        try:
            content = safe_path.read_text(encoding="utf-8", errors="replace")
            return {
                "success": True,
                "path": relative_path,
                "name": safe_path.name,
                "content": content,
                "size": safe_path.stat().st_size
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error leyendo el archivo: {e}")

    def write_file(self, relative_path: str, content: str) -> Dict[str, Any]:
        """Escribe contenido en un archivo de texto de forma atómica."""
        self._assert_not_protected(relative_path)
        safe_path = self._resolve_safe_path(relative_path)
        if safe_path.is_dir():
            raise HTTPException(status_code=400, detail="La ruta es un directorio, no un archivo.")

        try:
            atomic_write_text(safe_path, content)
            return {"success": True, "message": "Archivo guardado exitosamente.", "path": relative_path}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error escribiendo el archivo: {e}")

    def create_folder(self, relative_path: str) -> Dict[str, Any]:
        safe_path = self._resolve_safe_path(relative_path)
        if safe_path.exists():
            raise HTTPException(status_code=400, detail="La carpeta ya existe.")
        try:
            safe_path.mkdir(parents=True, exist_ok=True)
            return {"success": True, "message": "Carpeta creada exitosamente."}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error creando la carpeta: {e}")

    def create_file(self, relative_path: str) -> Dict[str, Any]:
        self._assert_not_protected(relative_path)
        safe_path = self._resolve_safe_path(relative_path)
        if safe_path.exists():
            raise HTTPException(status_code=400, detail="El archivo ya existe.")
        try:
            safe_path.parent.mkdir(parents=True, exist_ok=True)
            safe_path.touch()
            return {"success": True, "message": "Archivo creado exitosamente."}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error creando el archivo: {e}")

    def delete_item(self, relative_path: str) -> Dict[str, Any]:
        self._assert_not_protected(relative_path)
        safe_path = self._resolve_safe_path(relative_path)
        if self._is_special_root(safe_path):
            raise HTTPException(status_code=400, detail="No se permite eliminar directorios raíz del servidor.")
        if not safe_path.exists():
            raise HTTPException(status_code=404, detail="El elemento a eliminar no existe.")

        try:
            if safe_path.is_dir():
                shutil.rmtree(safe_path)
            else:
                safe_path.unlink()
            return {"success": True, "message": "Elemento eliminado correctamente."}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error eliminando el elemento: {e}")

    def rename_item(self, relative_path: str, new_name: str) -> Dict[str, Any]:
        self._assert_not_protected(relative_path)
        clean_new = new_name.replace("/", "").replace("\\", "").strip()
        if not clean_new:
            raise HTTPException(status_code=400, detail="Nombre inválido.")
        if clean_new in PROTECTED_FILES:
            raise HTTPException(status_code=403, detail="Nombre de archivo reservado.")

        safe_path = self._resolve_safe_path(relative_path)
        if self._is_special_root(safe_path):
            raise HTTPException(status_code=400, detail="No se permite renombrar directorios raíz.")

        dest = safe_path.parent / clean_new
        if dest.exists():
            raise HTTPException(status_code=400, detail="Ya existe un elemento con ese nombre.")

        try:
            safe_path.rename(dest)
            return {"success": True, "message": "Elemento renombrado exitosamente."}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error renombrando: {e}")

    def duplicate_item(self, relative_path: str) -> Dict[str, Any]:
        self._assert_not_protected(relative_path)
        safe_path = self._resolve_safe_path(relative_path)
        if self._is_special_root(safe_path):
            raise HTTPException(status_code=400, detail="No se permite duplicar directorios raíz.")
        if not safe_path.exists():
            raise HTTPException(status_code=404, detail="Elemento no encontrado.")

        stem = safe_path.stem
        suffix = safe_path.suffix
        new_name = f"{stem}_copia{suffix}"
        dest = safe_path.parent / new_name

        count = 1
        while dest.exists():
            count += 1
            dest = safe_path.parent / f"{stem}_copia_{count}{suffix}"

        try:
            if safe_path.is_dir():
                shutil.copytree(safe_path, dest)
            else:
                shutil.copy2(safe_path, dest)
            return {"success": True, "message": f"Duplicado creado: {dest.name}"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error duplicando: {e}")

    async def save_upload(self, relative_dir: str, file: UploadFile) -> Dict[str, Any]:
        dest_dir = self._resolve_safe_path(relative_dir)
        if not dest_dir.is_dir():
            raise HTTPException(status_code=400, detail="La ruta de destino no es un directorio.")

        filename = Path(file.filename or "uploaded_file").name
        if filename in PROTECTED_FILES:
            raise HTTPException(status_code=403, detail="No se puede sobrescribir archivos protegidos del panel.")

        dest = dest_dir / filename
        try:
            with open(dest, "wb") as buffer:
                while chunk := await file.read(1024 * 1024):
                    buffer.write(chunk)
            return {"success": True, "message": f"Archivo '{filename}' subido exitosamente."}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error al subir el archivo: {e}")

    def resolve_download(self, relative_path: str) -> Path:
        self._assert_not_protected(relative_path)
        safe_path = self._resolve_safe_path(relative_path)
        if not safe_path.exists() or not safe_path.is_file():
            raise HTTPException(status_code=404, detail="Archivo para descarga no encontrado.")
        return safe_path

    def compress_item(self, relative_path: str) -> Dict[str, Any]:
        """Comprime un archivo o directorio a formato .zip."""
        safe_path = self._resolve_safe_path(relative_path)
        if not safe_path.exists():
            raise HTTPException(status_code=404, detail="Elemento a comprimir no encontrado.")

        zip_name = f"{safe_path.name}.zip"
        dest_zip = safe_path.parent / zip_name

        try:
            with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_DEFLATED) as zipf:
                if safe_path.is_file():
                    zipf.write(safe_path, arcname=safe_path.name)
                else:
                    for root, _, files in os.walk(safe_path):
                        for f in files:
                            full_path = Path(root) / f
                            rel_arc = full_path.relative_to(safe_path.parent)
                            zipf.write(full_path, arcname=str(rel_arc))
            return {"success": True, "message": f"Comprimido creado: {zip_name}"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error al comprimir: {e}")

    def extract_zip(self, relative_path: str, target_relative: str = "") -> Dict[str, Any]:
        """Extrae un archivo .zip en el directorio especificado protegiendo contra Zip Slip."""
        zip_path = self._resolve_safe_path(relative_path)
        if not zip_path.is_file() or not zipfile.is_zipfile(zip_path):
            raise HTTPException(status_code=400, detail="El archivo no es un archivo .zip válido.")

        target_dir = self._resolve_safe_path(target_relative or str(Path(relative_path).parent))
        target_dir.mkdir(parents=True, exist_ok=True)

        try:
            with zipfile.ZipFile(zip_path, "r") as zipf:
                for member in zipf.infolist():
                    extracted_path = (target_dir / member.filename).resolve()
                    if not self._is_subpath(extracted_path, target_dir):
                        raise HTTPException(status_code=400, detail="Zip Slip malicioso detectado en el archivo.")
                zipf.extractall(target_dir)
            return {"success": True, "message": f"Archivo '{zip_path.name}' descomprimido exitosamente."}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error al descomprimir: {e}")

    def bulk_delete(self, paths: List[str]) -> Dict[str, Any]:
        """Elimina de forma segura múltiples archivos o directorios."""
        deleted = []
        errors = []
        for p in paths:
            try:
                target = self._resolve_safe_path(p)
                if not target.exists() or self._is_special_root(target):
                    continue
                self._assert_not_protected(p)
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
                deleted.append(p)
            except Exception as e:
                errors.append({"path": p, "error": str(e)})

        return {"status": "ok", "deleted": deleted, "errors": errors, "count": len(deleted), "deleted_count": len(deleted)}

    def bulk_compress(self, paths: List[str], target_dir: str = "", archive_name: str = "") -> Dict[str, Any]:
        """Comprime múltiples archivos o carpetas seleccionados en un único archivo .zip."""
        dest_dir = self._resolve_safe_path(target_dir)
        if not dest_dir.exists() or not dest_dir.is_dir():
            dest_dir = self.base_dir

        raw_name = (archive_name or "").strip()
        if not raw_name or "/" in raw_name or "\\" in raw_name:
            raw_name = f"archive_{int(time.time())}.zip"
        if not raw_name.lower().endswith(".zip"):
            raw_name += ".zip"

        dest_zip = dest_dir / raw_name
        if dest_zip.exists():
            dest_zip = dest_dir / f"{dest_zip.stem}_{int(time.time())}.zip"

        try:
            with zipfile.ZipFile(dest_zip, 'w', zipfile.ZIP_DEFLATED) as zf:
                for p in paths:
                    target = self._resolve_safe_path(p)
                    if not target.exists() or self._is_special_root(target):
                        continue
                    if target.is_file():
                        zf.write(target, arcname=target.name)
                    else:
                        for root, _, files in os.walk(target):
                            for file in files:
                                file_path = Path(root) / file
                                arcname = Path(target.name) / file_path.relative_to(target)
                                zf.write(file_path, arcname=str(arcname).replace("\\", "/"))

            rel_zip = self._rel_to_root(dest_zip)
            return {"status": "compressed", "archive_name": dest_zip.name, "path": rel_zip}
        except Exception as e:
            if dest_zip.exists():
                dest_zip.unlink(missing_ok=True)
            raise HTTPException(status_code=500, detail=f"Error al comprimir: {str(e)}")

file_manager = FileManager()

