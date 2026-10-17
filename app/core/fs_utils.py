import os
import json
import tempfile
from pathlib import Path
from typing import Any

def atomic_write_text(target_path: Path, content: str, encoding: str = "utf-8") -> None:
    """Escribe texto en un archivo temporal en el mismo directorio y reemplaza atómicamente."""
    target_path = Path(target_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temp_fd, temp_name = tempfile.mkstemp(dir=target_path.parent, prefix=".tmp_")
    try:
        with open(temp_fd, "w", encoding=encoding) as f:
            f.write(content)
        os.replace(temp_name, target_path)
    except Exception:
        if os.path.exists(temp_name):
            try:
                os.remove(temp_name)
            except OSError:
                pass
        raise

def atomic_write_json(target_path: Path, data: Any, indent: int = 2) -> None:
    """Serializa un objeto Python a JSON y lo guarda de forma atómica."""
    content = json.dumps(data, indent=indent, ensure_ascii=False)
    atomic_write_text(target_path, content)
