import os
import json
import secrets
from pathlib import Path
from typing import Dict, Any
from app.core.fs_utils import atomic_write_json

BASE_DIR = Path(__file__).resolve().parent.parent

class Settings:
    def __init__(self):
        # Paths
        self.base_dir: Path = BASE_DIR
        
        # En Docker: /home/steam/steamcmd/palworld y /home/steam/palworld-backups
        # En local/desarrollo: usar fallback dentro de data y backups
        default_data = Path(os.getenv("PALWORLD_DATA_DIR", "/home/steam/steamcmd/palworld"))
        if not default_data.exists() and not os.path.exists("/home/steam"):
            default_data = self.base_dir / "data"
        default_data.mkdir(parents=True, exist_ok=True)
        self.palworld_data_dir: Path = default_data

        default_backups = Path(os.getenv("BACKUP_DIR", "/home/steam/palworld-backups"))
        if not default_backups.exists() and not os.path.exists("/home/steam"):
            default_backups = self.base_dir / "backups"
        default_backups.mkdir(parents=True, exist_ok=True)
        self.backups_dir: Path = default_backups

        # Data directory for web panel configs and databases
        self.data_dir: Path = self.base_dir / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Log file
        self.log_file: Path = self.palworld_data_dir / "Pal" / "Saved" / "Logs" / "Pal.log"

        # Web Panel Auth
        self.panel_port: int = int(os.getenv("PANEL_PORT", "8080"))
        self.admin_user: str = os.getenv("PANEL_USER", "admin")
        self.admin_password: str = os.getenv("PANEL_PASSWORD", "adminpassword")

        # Config file
        self._config_file = self.palworld_data_dir / "pal_panel_config.json"
        self.runtime_config: Dict[str, Any] = self._load_runtime_config()

        # Secret Key persistente (prioridad: env -> json en disco -> nuevo)
        env_secret = os.getenv("SECRET_KEY", "").strip()
        if env_secret:
            self.secret_key = env_secret
        else:
            saved_secret = str(self.runtime_config.get("secret_key", "")).strip()
            if saved_secret:
                self.secret_key = saved_secret
            else:
                self.secret_key = secrets.token_hex(32)
                self.runtime_config["secret_key"] = self.secret_key
                self.save_runtime_config({})

        # Palworld Server settings (Carga dinámica desde runtime_config con fallback a env vars)
        self.server_name: str = self.runtime_config.get("server_name", os.getenv("SERVER_NAME", "Palworld Dedicated Server"))
        self.server_description: str = self.runtime_config.get("server_description", os.getenv("SERVER_DESCRIPTION", "Palworld Server hosted with Docker"))
        self.server_password: str = self.runtime_config.get("server_password", os.getenv("SERVER_PASSWORD", ""))
        self.admin_server_password: str = self.runtime_config.get("admin_server_password", os.getenv("ADMIN_PASSWORD", "adminpassword"))
        
        try:
            self.max_players: int = int(self.runtime_config.get("max_players", os.getenv("PLAYERS", os.getenv("MAX_PLAYERS", "32"))))
        except Exception:
            self.max_players = 32

        self.server_port: int = int(os.getenv("PORT", os.getenv("SERVER_PORT", "8211")))
        self.query_port: int = int(os.getenv("QUERY_PORT", "27015"))
        self.rcon_port: int = int(os.getenv("RCON_PORT", "25575"))
        self.rcon_host: str = os.getenv("RCON_HOST", "127.0.0.1")
        self.rcon_enabled: bool = os.getenv("RCON_ENABLED", "true").lower() in ("true", "1", "yes")

        self.rest_api_port: int = int(os.getenv("REST_API_PORT", "8212"))
        self.rest_api_host: str = os.getenv("REST_API_HOST", "127.0.0.1")
        self.rest_api_enabled: bool = os.getenv("REST_API_ENABLED", "true").lower() in ("true", "1", "yes")

        self.community: bool = os.getenv("COMMUNITY", "false").lower() in ("true", "1", "yes")
        self.public_ip: str = os.getenv("PUBLIC_IP", "")
        self.public_port: int = int(os.getenv("PUBLIC_PORT", str(self.server_port)))

    def _load_runtime_config(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {}
        if self._config_file.exists():
            try:
                with open(self._config_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = {}

        defaults = {
            "server_name": "Palworld Dedicated Server",
            "server_description": "Palworld Server hosted with Docker",
            "server_password": "",
            "admin_server_password": "adminpassword",
            "max_players": 32,
            "multithreading": True,
            "community": False,
            "update_on_start": True,
            "autostart_server": True,
            "discord_webhook_url": "",
            "discord_language": "es",
            "schedule_enabled": False,
            "schedule_start": "18:00",
            "schedule_stop": "00:00",
            "schedule_warn_mins": 10,
            "auto_backup_enabled": True,
            "auto_backup_interval_hours": 6,
            "backup_max_count": 10,
            "auto_restart_hours": 0,
            "auto_save_interval_mins": 30
        }
        for k, v in defaults.items():
            if k not in data:
                env_val = os.getenv(k.upper())
                if env_val is not None:
                    if isinstance(v, bool):
                        data[k] = env_val.lower() in ("true", "1", "yes")
                    elif isinstance(v, int):
                        try:
                            data[k] = int(env_val)
                        except Exception:
                            data[k] = v
                    else:
                        data[k] = env_val
                else:
                    data[k] = v
        return data

    def save_runtime_config(self, new_config: Dict[str, Any]) -> None:
        self.runtime_config.update(new_config)
        if "server_name" in new_config:
            self.server_name = new_config["server_name"]
        if "server_description" in new_config:
            self.server_description = new_config["server_description"]
        if "server_password" in new_config:
            self.server_password = new_config["server_password"]
        if "admin_server_password" in new_config:
            self.admin_server_password = new_config["admin_server_password"]
        if "max_players" in new_config:
            try:
                self.max_players = int(new_config["max_players"])
            except Exception:
                pass
        try:
            atomic_write_json(self._config_file, self.runtime_config, indent=2)
        except Exception as e:
            print(f"[Config] Error guardando pal_panel_config.json: {e}")

settings = Settings()
