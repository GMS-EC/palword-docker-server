import httpx
import logging
from typing import Optional, Dict, Any, List
from app.config import settings
from app.core.rcon_client import PalRconClient

logger = logging.getLogger("palworld.api")

class PalApiClient:
    """
    Cliente unificado para la administración de Palworld Server.
    Soporta la API REST oficial de Palworld (puerto 8212) con autenticación HTTP Basic,
    y utiliza automáticamente el protocolo Source RCON (puerto 25575) como respaldo
    o para comandos que requieran ejecución directa por consola.
    """
    def __init__(self):
        self._rcon = PalRconClient(
            host=settings.rcon_host,
            port=settings.rcon_port,
            password=settings.admin_server_password
        )

    def _get_admin_password(self) -> str:
        from app.core.pal_settings_manager import pal_settings_manager
        ini = pal_settings_manager.read_settings()
        return str(ini.get("AdminPassword") or settings.admin_server_password or "adminpassword")

    def _get_base_url(self) -> str:
        from app.core.pal_settings_manager import pal_settings_manager
        ini = pal_settings_manager.read_settings()
        port = ini.get("RESTAPIPort") or settings.rest_api_port
        return f"http://{settings.rest_api_host}:{port}/v1/api"

    def _get_auth(self) -> tuple[str, str]:
        return ("admin", self._get_admin_password())

    def _sync_rcon(self) -> None:
        from app.core.pal_settings_manager import pal_settings_manager
        ini = pal_settings_manager.read_settings()
        self._rcon.password = str(ini.get("AdminPassword") or settings.admin_server_password or "adminpassword")
        self._rcon.port = int(ini.get("RCONPort") or settings.rcon_port)

    @property
    def rcon(self) -> PalRconClient:
        self._sync_rcon()
        return self._rcon

    async def get_server_info(self) -> Optional[Dict[str, Any]]:
        """Obtiene la información del servidor (versión, nombre, descripción)."""
        if not settings.rest_api_enabled:
            return None
        url = f"{self._get_base_url()}/info"
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                res = await client.get(url, auth=self._get_auth())
                if res.status_code == 200:
                    return res.json()
        except Exception:
            pass
        return None

    async def get_metrics(self) -> Optional[Dict[str, Any]]:
        """
        Obtiene métricas en vivo del juego desde la REST API:
        serverfps, serverframetime, currentplayernum, maxplayernum, uptime.
        """
        if not settings.rest_api_enabled:
            return None
        url = f"{self._get_base_url()}/metrics"
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                res = await client.get(url, auth=self._get_auth())
                if res.status_code == 200:
                    return res.json()
        except Exception:
            pass
        return None

    async def get_online_players(self) -> List[Dict[str, Any]]:
        """
        Obtiene la lista de jugadores conectados.
        Prioriza la REST API (/v1/api/players) que provee ping, nivel, ubicación e IP.
        Si la REST API falla o está desactivada, recurre a RCON ShowPlayers.
        """
        if settings.rest_api_enabled:
            url = f"{self._get_base_url()}/players"
            try:
                async with httpx.AsyncClient(timeout=4.0) as client:
                    res = await client.get(url, auth=self._get_auth())
                    if res.status_code == 200:
                        data = res.json()
                        raw_list = data.get("players", [])
                        players = []
                        for p in raw_list:
                            players.append({
                                "name": p.get("name") or "Pal Tamer",
                                "player_id": p.get("playerId") or "",
                                "steam_id": p.get("userId") or p.get("playerId") or "Desconocido",
                                "ip": p.get("ip") or "-",
                                "ping": round(p.get("ping", 0), 1),
                                "level": p.get("level", 1),
                                "location_x": p.get("location_x"),
                                "location_y": p.get("location_y"),
                                "status": "online"
                            })
                        return players
            except Exception as e:
                logger.debug(f"REST API /players falló: {e}, intentando RCON fallback...")

        # Fallback vía RCON ShowPlayers
        return await self.rcon.list_players()

    async def announce(self, message: str) -> bool:
        """Emite un anuncio a todos los jugadores en el servidor."""
        if settings.rest_api_enabled:
            url = f"{self._get_base_url()}/announce"
            try:
                async with httpx.AsyncClient(timeout=4.0) as client:
                    res = await client.post(url, auth=self._get_auth(), json={"message": message})
                    if res.status_code == 200:
                        return True
            except Exception as e:
                logger.debug(f"REST API /announce falló: {e}, intentando RCON...")

        # Fallback RCON
        res = await self.rcon.broadcast(message)
        return not res.startswith("Error")

    async def save_world(self) -> bool:
        """Fuerza el guardado inmediato del estado del mundo."""
        if settings.rest_api_enabled:
            url = f"{self._get_base_url()}/save"
            try:
                async with httpx.AsyncClient(timeout=6.0) as client:
                    res = await client.post(url, auth=self._get_auth())
                    if res.status_code in (200, 204):
                        return True
            except Exception as e:
                logger.debug(f"REST API /save falló: {e}, intentando RCON...")

        # Fallback RCON
        res = await self.rcon.save_world()
        return "Complete" in res or "Saved" in res or not res.startswith("Error")

    async def shutdown(self, wait_seconds: int = 10, message: str = "El servidor se apagará...") -> bool:
        """Apaga el servidor de forma segura con cuenta regresiva."""
        if settings.rest_api_enabled:
            url = f"{self._get_base_url()}/shutdown"
            try:
                async with httpx.AsyncClient(timeout=4.0) as client:
                    res = await client.post(
                        url,
                        auth=self._get_auth(),
                        json={"waittime": wait_seconds, "message": message}
                    )
                    if res.status_code in (200, 204):
                        return True
            except Exception:
                pass

        # Fallback RCON
        res = await self.rcon.shutdown(seconds=wait_seconds, message=message)
        return not res.startswith("Error")

    async def kick_player(self, user_id: str, message: str = "Has sido expulsado del servidor.") -> bool:
        """Expulsa a un jugador por su userId o Steam ID."""
        if settings.rest_api_enabled:
            url = f"{self._get_base_url()}/kick"
            try:
                async with httpx.AsyncClient(timeout=4.0) as client:
                    res = await client.post(
                        url,
                        auth=self._get_auth(),
                        json={"userid": user_id, "message": message}
                    )
                    if res.status_code in (200, 204):
                        return True
            except Exception:
                pass

        res = await self.rcon.kick_player(user_id)
        return not res.startswith("Error")

    async def ban_player(self, user_id: str, message: str = "Has sido baneado del servidor.") -> bool:
        """Banea a un jugador permanentemente."""
        if settings.rest_api_enabled:
            url = f"{self._get_base_url()}/ban"
            try:
                async with httpx.AsyncClient(timeout=4.0) as client:
                    res = await client.post(
                        url,
                        auth=self._get_auth(),
                        json={"userid": user_id, "message": message}
                    )
                    if res.status_code in (200, 204):
                        return True
            except Exception:
                pass

        res = await self.rcon.ban_player(user_id)
        return not res.startswith("Error")

    async def unban_player(self, user_id: str) -> bool:
        """Desbanea a un jugador."""
        if settings.rest_api_enabled:
            url = f"{self._get_base_url()}/unban"
            try:
                async with httpx.AsyncClient(timeout=4.0) as client:
                    res = await client.post(
                        url,
                        auth=self._get_auth(),
                        json={"userid": user_id}
                    )
                    if res.status_code in (200, 204):
                        return True
            except Exception:
                pass
        return False

    async def execute_raw_command(self, command: str) -> str:
        """Ejecuta un comando raw mediante RCON o comandos de compatibilidad."""
        cmd_lower = command.strip().lower()
        if cmd_lower in ("save", "saveworld"):
            ok = await self.save_world()
            return "Guardado del mundo completado exitosamente." if ok else "Error al guardar el mundo."
        if cmd_lower.startswith("announce ") or cmd_lower.startswith("broadcast "):
            parts = command.split(" ", 1)
            msg = parts[1] if len(parts) > 1 else ""
            ok = await self.announce(msg)
            return f"Anuncio enviado: {msg}" if ok else "Error al emitir anuncio."
        if cmd_lower.startswith("shutdown"):
            ok = await self.shutdown()
            return "Orden de apagado emitida al servidor." if ok else "Error al emitir orden de apagado."
        
        # Ejecución directa en RCON
        return await self.rcon.execute(command)

pal_api_client = PalApiClient()
