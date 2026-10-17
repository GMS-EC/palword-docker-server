import os
import json
import time
import asyncio
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional

from app.config import settings
from app.core.pal_api_client import pal_api_client
from app.core.fs_utils import atomic_write_json

logger = logging.getLogger("palworld.players")

HISTORY_SAVE_DEBOUNCE_SECONDS = 20
HISTORY_MAX_ENTRIES = 2000
HISTORY_MAX_AGE_DAYS = 365

class PlayerManager:
    """
    Gestor de jugadores para Palworld.
    Obtiene los jugadores en línea mediante la REST API y RCON,
    mantiene historial persistente de conexiones, niveles y tiempos de juego,
    y emite alertas de entrada y salida de jugadores.
    """
    def __init__(self):
        self._history_file = settings.palworld_data_dir / "pal_players.json"
        self._player_history: Dict[str, Dict[str, Any]] = {}
        self._current_online: Dict[str, str] = {}
        self._monitor_running: bool = False
        self._monitor_task: Optional[asyncio.Task] = None
        self._history_dirty: bool = False
        self._last_history_save: float = 0.0
        self._load_history()

    def start_monitor(self):
        if not self._monitor_running:
            self._monitor_running = True
            self._monitor_task = asyncio.create_task(self._monitor_loop())

    def stop_monitor(self):
        self._monitor_running = False
        if self._monitor_task:
            self._monitor_task.cancel()
        if self._history_dirty:
            self._save_history()

    async def _monitor_loop(self):
        # Import diferido para evitar ciclos
        from app.core.process_manager import process_manager
        while self._monitor_running:
            try:
                if process_manager.get_status() == "RUNNING":
                    current_players = await self.get_online_players()
                    new_online = {p.get("steam_id") or p.get("name"): p.get("name") for p in current_players}

                    # Detectar nuevos jugadores
                    for pid, name in new_online.items():
                        if pid not in self._current_online:
                            logger.info(f"Jugador conectado: {name}")
                            try:
                                from app.core.webhook_manager import webhook_manager
                                await webhook_manager.notify_player_join(name)
                            except Exception as e:
                                logger.debug(f"Error webhook player join: {e}")

                    # Detectar jugadores desconectados
                    for pid, name in self._current_online.items():
                        if pid not in new_online:
                            logger.info(f"Jugador desconectado: {name}")
                            try:
                                from app.core.webhook_manager import webhook_manager
                                await webhook_manager.notify_player_leave(name)
                            except Exception as e:
                                logger.debug(f"Error webhook player leave: {e}")

                    self._current_online = new_online
                else:
                    self._current_online.clear()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Error en monitor de jugadores: {e}")

            await asyncio.sleep(10)

    def _load_history(self) -> None:
        if self._history_file.exists():
            try:
                with open(self._history_file, "r", encoding="utf-8") as f:
                    self._player_history = json.load(f)
            except Exception:
                self._player_history = {}

    def _save_history(self) -> None:
        try:
            self._prune_history()
            atomic_write_json(self._history_file, self._player_history, indent=2)
            self._history_dirty = False
            self._last_history_save = time.time()
        except Exception as e:
            logger.debug(f"Error guardando historial de jugadores: {e}")

    def _prune_history(self) -> None:
        cutoff = time.time() - (HISTORY_MAX_AGE_DAYS * 86400)
        pruned = {
            pid: rec for pid, rec in self._player_history.items()
            if rec.get("banned") or rec.get("last_ts", 0) >= cutoff
        }
        if len(pruned) > HISTORY_MAX_ENTRIES:
            ordered = sorted(
                pruned.values(),
                key=lambda r: r.get("last_ts", 0),
                reverse=True
            )[:HISTORY_MAX_ENTRIES]
            keep_ids = {r.get("steam_id") for r in ordered}
            pruned = {sid: rec for sid, rec in pruned.items() if sid in keep_ids}
        self._player_history = pruned

    def _schedule_save(self) -> None:
        self._history_dirty = True
        now = time.time()
        if now - self._last_history_save >= HISTORY_SAVE_DEBOUNCE_SECONDS:
            self._save_history()

    async def get_online_players(self) -> List[Dict[str, Any]]:
        """Devuelve la lista de jugadores conectados actualmente."""
        from app.core.process_manager import process_manager
        if process_manager.get_status() != "RUNNING":
            return []

        try:
            raw_players = await pal_api_client.get_online_players()
            now_str = datetime.now().strftime("%d/%m/%Y %H:%M")
            now_ts = time.time()
            history_updated = False
            enriched_players = []

            for p in raw_players:
                name = (p.get("name") or "Pal Tamer").strip()
                steam_id = (p.get("steam_id") or p.get("player_uid") or p.get("player_id") or "Desconocido").strip()
                if not name and not steam_id:
                    continue

                if steam_id and steam_id != "Desconocido":
                    if steam_id not in self._player_history:
                        self._player_history[steam_id] = {
                            "name": name,
                            "steam_id": steam_id,
                            "first_seen": now_str,
                            "last_seen": now_str,
                            "last_ts": now_ts,
                            "banned": False,
                            "level": p.get("level", 1)
                        }
                        history_updated = True
                    else:
                        self._player_history[steam_id]["name"] = name
                        self._player_history[steam_id]["last_seen"] = now_str
                        self._player_history[steam_id]["last_ts"] = now_ts
                        if "level" in p:
                            self._player_history[steam_id]["level"] = p["level"]
                        history_updated = True

                enriched_players.append({
                    "name": name,
                    "player_id": p.get("player_id") or p.get("player_uid") or "-",
                    "steam_id": steam_id,
                    "ip": p.get("ip", "-"),
                    "ping": p.get("ping", 0),
                    "level": p.get("level", 1),
                    "status": "online",
                    "last_seen": now_str
                })

            if history_updated:
                self._schedule_save()
            return enriched_players
        except Exception as e:
            logger.debug(f"Error obteniendo jugadores conectados: {e}")
            return []

    def get_player_history(self) -> List[Dict[str, Any]]:
        return list(self._player_history.values())

    async def kick_player(self, player_id: str, reason: str = "Expulsado por el administrador") -> bool:
        return await pal_api_client.kick_player(player_id, message=reason)

    async def ban_player(self, player_id: str, reason: str = "Baneado por el administrador") -> bool:
        ok = await pal_api_client.ban_player(player_id, message=reason)
        if ok and player_id in self._player_history:
            self._player_history[player_id]["banned"] = True
            self._schedule_save()
        return ok

    async def unban_player(self, player_id: str) -> bool:
        ok = await pal_api_client.unban_player(player_id)
        if player_id in self._player_history:
            self._player_history[player_id]["banned"] = False
    async def list_players(self) -> Dict[str, Any]:
        """Devuelve un diccionario estructurado con jugadores en línea, offline y baneados."""
        online = await self.get_online_players()
        online_ids = {p.get("steam_id") or p.get("name") for p in online}
        history = self.get_player_history()

        players_res = []
        for p in online:
            players_res.append({
                "name": p.get("name", "Pal Tamer"),
                "player_id": p.get("player_id", "-"),
                "steam_id": p.get("steam_id", "-"),
                "is_online": True,
                "level": p.get("level", 1),
                "ping": p.get("ping", 0),
                "ip": p.get("ip", "-"),
                "last_connection": p.get("last_seen", "-")
            })

        for h in history:
            sid = h.get("steam_id") or h.get("name")
            if sid not in online_ids and not h.get("banned", False):
                players_res.append({
                    "name": h.get("name", "Pal Tamer"),
                    "player_id": sid,
                    "steam_id": sid,
                    "is_online": False,
                    "level": h.get("level", 1),
                    "ping": 0,
                    "ip": "-",
                    "last_connection": h.get("last_seen", "-")
                })

        banned_res = []
        for h in history:
            if h.get("banned", False):
                banned_res.append({
                    "name": h.get("name", "Pal Tamer"),
                    "player_id": h.get("steam_id", "-"),
                    "steam_id": h.get("steam_id", "-"),
                    "reason": h.get("ban_reason", "Baneado por el administrador"),
                    "date": h.get("last_seen", "-")
                })

        return {"players": players_res, "banned": banned_res, "total": len(players_res)}

player_manager = PlayerManager()

