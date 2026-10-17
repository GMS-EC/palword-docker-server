import re
import asyncio
import struct
import logging
from typing import Optional, List, Dict, Any

logger = logging.getLogger("palworld.rcon")

# RCON Packet Types (Source RCON Protocol)
SERVERDATA_AUTH = 3
SERVERDATA_AUTH_RESPONSE = 2
SERVERDATA_EXECCOMMAND = 2
SERVERDATA_RESPONSE_VALUE = 0

class PalRconClient:
    """
    Cliente RCON asíncrono nativo para Palworld Dedicated Server.
    Implementa el protocolo Source RCON a través de asyncio sin dependencias externas.
    """
    def __init__(self, host: str = "127.0.0.1", port: int = 25575, password: str = "adminpassword"):
        self.host = host
        self.port = port
        self.password = password
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self._lock = asyncio.Lock()
        self._authenticated = False
        self._req_id = 1

    def is_connected(self) -> bool:
        return self.writer is not None and not self.writer.is_closing() and self._authenticated

    async def connect(self, timeout: float = 3.0) -> bool:
        """Establece conexión TCP y se autentica con el servidor Palworld."""
        async with self._lock:
            if self.is_connected():
                return True
            try:
                self.reader, self.writer = await asyncio.wait_for(
                    asyncio.open_connection(self.host, self.port),
                    timeout=timeout
                )
                auth_ok = await self._authenticate(timeout=timeout)
                if not auth_ok:
                    await self._close_internal()
                    return False
                self._authenticated = True
                logger.info(f"Conexión RCON exitosa a {self.host}:{self.port}")
                return True
            except Exception as e:
                logger.debug(f"No se pudo conectar a RCON ({self.host}:{self.port}): {e}")
                await self._close_internal()
                return False

    async def _close_internal(self):
        self._authenticated = False
        if self.writer:
            try:
                self.writer.close()
                await self.writer.wait_closed()
            except Exception:
                pass
        self.reader = None
        self.writer = None

    async def disconnect(self):
        """Cierra la conexión RCON de manera segura."""
        async with self._lock:
            await self._close_internal()

    def _build_packet(self, req_id: int, packet_type: int, body: str) -> bytes:
        body_encoded = body.encode("utf-8", errors="replace") + b"\x00\x00"
        packet_size = 4 + 4 + len(body_encoded)
        return struct.pack("<iii", packet_size, req_id, packet_type) + body_encoded

    async def _read_packet(self, timeout: float = 4.0) -> Optional[tuple[int, int, str]]:
        if not self.reader:
            return None
        try:
            raw_size = await asyncio.wait_for(self.reader.readexactly(4), timeout=timeout)
            size = struct.unpack("<i", raw_size)[0]
            if size < 10 or size > 65535:
                return None
            data = await asyncio.wait_for(self.reader.readexactly(size), timeout=timeout)
            req_id, packet_type = struct.unpack("<ii", data[:8])
            # Descartar los 2 bytes nulos del final
            body_bytes = data[8:-2]
            body = body_bytes.decode("utf-8", errors="replace")
            return (req_id, packet_type, body)
        except Exception:
            return None

    async def _authenticate(self, timeout: float = 3.0) -> bool:
        self._req_id += 1
        auth_req_id = self._req_id
        packet = self._build_packet(auth_req_id, SERVERDATA_AUTH, self.password)
        self.writer.write(packet)
        await self.writer.drain()

        # Palworld suele responder primero con un RESPONSE_VALUE y luego con AUTH_RESPONSE
        resp = await self._read_packet(timeout=timeout)
        if not resp:
            return False

        if resp[0] == auth_req_id and resp[1] == SERVERDATA_AUTH_RESPONSE:
            return True

        if resp[1] == SERVERDATA_RESPONSE_VALUE:
            resp2 = await self._read_packet(timeout=timeout)
            if resp2 and resp2[0] == auth_req_id and resp2[1] == SERVERDATA_AUTH_RESPONSE:
                return True

        return False

    async def execute(self, command: str, timeout: float = 6.0) -> str:
        """Ejecuta un comando RCON de Palworld con auto-reconexión."""
        async with self._lock:
            if not self.is_connected():
                ok = await self._connect_unlocked(timeout=3.0)
                if not ok:
                    return "Error: No se pudo conectar a la consola RCON del servidor Palworld."

            self._req_id += 1
            cmd_req_id = self._req_id
            packet = self._build_packet(cmd_req_id, SERVERDATA_EXECCOMMAND, command)

            try:
                self.writer.write(packet)
                await self.writer.drain()

                # Leemos la respuesta
                resp = await self._read_packet(timeout=timeout)
                if resp is None:
                    await self._close_internal()
                    return "Error: Tiempo de espera agotado al recibir respuesta RCON."
                return resp[2].strip()
            except Exception as e:
                logger.debug(f"Error ejecutando comando RCON '{command}': {e}")
                await self._close_internal()
                return f"Error de comunicación RCON: {e}"

    async def _connect_unlocked(self, timeout: float = 3.0) -> bool:
        try:
            self.reader, self.writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                timeout=timeout
            )
            auth_ok = await self._authenticate(timeout=timeout)
            if not auth_ok:
                await self._close_internal()
                return False
            self._authenticated = True
            return True
        except Exception:
            await self._close_internal()
            return False

    async def list_players(self) -> List[Dict[str, Any]]:
        """
        Ejecuta el comando ShowPlayers vía RCON.
        Formato devuelto por Palworld:
        name,playeruid,steamid
        PlayerName,12345678,steam_00000000000000000
        """
        output = await self.execute("ShowPlayers")
        if not output or output.startswith("Error"):
            return []

        players = []
        lines = output.splitlines()
        for line in lines:
            line = line.strip()
            if not line or line.lower().startswith("name,playeruid"):
                continue
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 3:
                name = parts[0]
                player_uid = parts[1]
                steam_id = parts[2]
                players.append({
                    "name": name,
                    "player_uid": player_uid,
                    "steam_id": steam_id,
                    "status": "online"
                })
            elif len(parts) == 2:
                players.append({
                    "name": parts[0],
                    "player_uid": parts[1],
                    "steam_id": "Desconocido",
                    "status": "online"
                })
        return players

    async def broadcast(self, message: str) -> str:
        # Palworld RCON broadcast reemplaza espacios con guiones bajos si es necesario
        clean_msg = message.replace(" ", "_")
        return await self.execute(f"Broadcast {clean_msg}")

    async def save_world(self) -> str:
        return await self.execute("Save")

    async def shutdown(self, seconds: int = 10, message: str = "Server shutting down") -> str:
        clean_msg = message.replace(" ", "_")
        return await self.execute(f"Shutdown {seconds} {clean_msg}")

    async def kick_player(self, steam_id: str) -> str:
        return await self.execute(f"KickPlayer {steam_id}")

    async def ban_player(self, steam_id: str) -> str:
        return await self.execute(f"BanPlayer {steam_id}")
