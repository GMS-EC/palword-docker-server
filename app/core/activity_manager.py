import time
from collections import deque
from datetime import datetime
from typing import List, Dict, Any

class ActivityManager:
    """Registra y mantiene en memoria las actividades recientes del panel de Palworld."""
    def __init__(self, max_entries: int = 200):
        self._entries: deque = deque(maxlen=max_entries)

    def log(self, category: str, message: str) -> None:
        entry = {
            "timestamp": time.time(),
            "datetime": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
            "category": category,
            "message": message
        }
        self._entries.appendleft(entry)

    def get_recent(self, limit: int = 50) -> List[Dict[str, Any]]:
        return list(self._entries)[:limit]

activity_manager = ActivityManager()
