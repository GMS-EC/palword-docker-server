import os
import re
from pathlib import Path
from typing import Dict, Any, Optional

from app.config import settings
from app.core.fs_utils import atomic_write_text

DEFAULT_PALWORLD_SETTINGS: Dict[str, Any] = {
    # Identidad y Acceso
    "ServerName": "Palworld Dedicated Server",
    "ServerDescription": "Palworld Server hosted with Docker",
    "ServerPassword": "",
    "AdminPassword": "adminpassword",
    "ServerPlayerMaxNum": 32,
    "PublicPort": 8211,
    "PublicIP": "",
    "RCONEnabled": True,
    "RCONPort": 25575,
    "RESTAPIEnabled": True,
    "RESTAPIPort": 8212,
    "Region": "",
    "bUseAuth": True,
    "BanListURL": "https://b.palworldgame.com/api/banlist.txt",
    "bShowPlayerList": False,
    "ChatPostLimitPerMinute": 30,
    "CrossplayPlatforms": "(Steam,Xbox,PS5,Mac)",

    # Dificultad y Multiplicadores Generales
    "Difficulty": "None",
    "DayTimeSpeedRate": 1.0,
    "NightTimeSpeedRate": 1.0,
    "ExpRate": 1.0,
    "PalCaptureRate": 1.0,
    "PalSpawnNumRate": 1.0,
    "WorkSpeedRate": 1.0,
    "AutoSaveSpan": 30.0,

    # Daño y Combate
    "PalDamageRateAttack": 1.0,
    "PalDamageRateDefense": 1.0,
    "PlayerDamageRateAttack": 1.0,
    "PlayerDamageRateDefense": 1.0,
    "bEnablePlayerToPlayerDamage": False,
    "bEnableFriendlyFire": False,
    "bEnableInvaderEnemy": True,
    "bIsPvP": False,
    "bHardcore": False,
    "DeathPenalty": "Item",

    # Estadísticas del Jugador
    "PlayerStomachDecreaceRate": 1.0,
    "PlayerStaminaDecreaceRate": 1.0,
    "PlayerAutoHPRegeneRate": 1.0,
    "PlayerAutoHpRegeneRateInSleep": 1.0,
    "ItemWeightRate": 1.0,
    "bEnableFastTravel": True,
    "bEnableNonLoginPenalty": True,

    # Estadísticas y Eclosión de Pals
    "PalStomachDecreaceRate": 1.0,
    "PalStaminaDecreaceRate": 1.0,
    "PalAutoHPRegeneRate": 1.0,
    "PalAutoHpRegeneRateInSleep": 1.0,
    "PalEggDefaultHatchingTime": 1.0,
    "bPalLost": False,
    "bAllowGlobalPalboxExport": True,
    "bAllowGlobalPalboxImport": False,

    # Bases y Construcción
    "BaseCampMaxNum": 128,
    "BaseCampWorkerMaxNum": 15,
    "GuildPlayerMaxNum": 20,
    "BaseCampMaxNumInGuild": 4,
    "BuildObjectHpRate": 1.0,
    "BuildObjectDamageRate": 1.0,
    "BuildObjectDeteriorationDamageRate": 1.0,
    "DropItemMaxNum": 3000,
    "DropItemAliveMaxHours": 1.0,
    "bAutoResetGuildNoOnlinePlayers": False,
    "AutoResetGuildTimeNoOnlinePlayers": 72.0,

    # Recolección y Recursos
    "CollectionDropRate": 1.0,
    "CollectionObjectHpRate": 1.0,
    "CollectionObjectRespawnSpeedRate": 1.0,
    "EnemyDropItemRate": 1.0,
    "SupplyDropSpan": 180,
    "EquipmentDurabilityDamageRate": 1.0
}

class PalSettingsManager:
    """
    Gestor de configuración integral para Palworld Dedicated Server.
    Parsea y actualiza con precisión el bloque OptionSettings=(...) de PalWorldSettings.ini,
    respetando tipos de datos (strings entrecomillados, floats, booleans y arrays).
    """
    def __init__(self):
        self.config_dir: Path = settings.palworld_data_dir / "Pal" / "Saved" / "Config" / "LinuxServer"
        self.settings_file: Path = self.config_dir / "PalWorldSettings.ini"

    def _ensure_paths(self):
        self.config_dir.mkdir(parents=True, exist_ok=True)
        if not self.settings_file.exists():
            # Intentar copiar desde DefaultPalWorldSettings.ini si existe en la raíz de datos
            default_template = settings.palworld_data_dir / "DefaultPalWorldSettings.ini"
            if default_template.exists():
                try:
                    content = default_template.read_text(encoding="utf-8", errors="replace")
                    atomic_write_text(self.settings_file, content)
                    return
                except Exception:
                    pass
            # Si no existe, inicializar con defaults
            self.write_all_settings(DEFAULT_PALWORLD_SETTINGS)

    def parse_option_settings(self, text: str) -> Dict[str, Any]:
        """Parsea la cadena de OptionSettings=(...) en un diccionario Python."""
        match = re.search(r"OptionSettings=\((.*)\)", text, re.DOTALL)
        if not match:
            return {}

        content = match.group(1).strip()
        items: Dict[str, Any] = {}

        # Tokenizador simple que respeta strings entrecomillados y arrays entre paréntesis
        in_quotes = False
        in_paren = False
        current_token = []
        tokens = []

        for char in content:
            if char == '"':
                in_quotes = not in_quotes
                current_token.append(char)
            elif char == '(' and not in_quotes:
                in_paren = True
                current_token.append(char)
            elif char == ')' and not in_quotes:
                in_paren = False
                current_token.append(char)
            elif char == ',' and not in_quotes and not in_paren:
                tokens.append("".join(current_token).strip())
                current_token = []
            else:
                current_token.append(char)

        if current_token:
            tokens.append("".join(current_token).strip())

        for token in tokens:
            if "=" in token:
                k, v = token.split("=", 1)
                k = k.strip()
                v = v.strip()
                # Limpiar comillas si es string
                if v.startswith('"') and v.endswith('"') and len(v) >= 2:
                    val = v[1:-1]
                elif v.lower() == "true":
                    val = True
                elif v.lower() == "false":
                    val = False
                elif re.match(r"^-?\d+$", v):
                    val = int(v)
                elif re.match(r"^-?\d+\.\d+$", v):
                    val = float(v)
                else:
                    val = v
                items[k] = val

        return items

    def read_settings(self) -> Dict[str, Any]:
        """Lee y devuelve los parámetros actuales de PalWorldSettings.ini."""
        self._ensure_paths()
        if not self.settings_file.exists():
            return dict(DEFAULT_PALWORLD_SETTINGS)

        try:
            content = self.settings_file.read_text(encoding="utf-8", errors="replace")
            parsed = self.parse_option_settings(content)
            # Combinar defaults con los valores leídos para asegurar que todos los campos existan
            merged = dict(DEFAULT_PALWORLD_SETTINGS)
            merged.update(parsed)
            return merged
        except Exception as e:
            print(f"[PalSettingsManager] Error leyendo settings: {e}")
            return dict(DEFAULT_PALWORLD_SETTINGS)

    def format_value(self, key: str, val: Any) -> str:
        """Formatea un valor según el formato requerido por Unreal Engine en PalWorldSettings.ini."""
        if isinstance(val, bool):
            return "True" if val else "False"
        if isinstance(val, (int, float)):
            if isinstance(val, float):
                return f"{val:.6f}" if abs(val - int(val)) > 0.000001 else f"{val:.1f}"
            return str(val)
        val_str = str(val).strip()
        if val_str.lower() in ("true", "false"):
            return "True" if val_str.lower() == "true" else "False"
        # Arrays como CrossplayPlatforms=(Steam,Xbox,PS5,Mac)
        if val_str.startswith("(") and val_str.endswith(")"):
            return val_str
        # Si es número en string
        if re.match(r"^-?\d+$", val_str):
            return val_str
        if re.match(r"^-?\d+\.\d+$", val_str):
            return val_str
        # Identificadores simples como Difficulty=None o DeathPenalty=Item
        if key in ("Difficulty", "DeathPenalty") and not val_str.startswith('"'):
            return val_str
        # Cadenas de texto van entrecomilladas
        clean = val_str.replace('"', '\\"')
        return f'"{clean}"'

    def write_all_settings(self, settings_dict: Dict[str, Any]) -> bool:
        """Serializa y escribe el archivo PalWorldSettings.ini completo."""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        pairs = []
        for k, v in settings_dict.items():
            formatted_val = self.format_value(k, v)
            pairs.append(f"{k}={formatted_val}")

        option_settings_str = ",".join(pairs)
        content = (
            "[/Script/Pal.PalGameWorldSettings]\n"
            f"OptionSettings=({option_settings_str})\n"
        )
        try:
            atomic_write_text(self.settings_file, content)
            return True
        except Exception as e:
            print(f"[PalSettingsManager] Error escribiendo settings: {e}")
            return False

    def update_settings(self, updates: Dict[str, Any]) -> bool:
        """Actualiza parámetros específicos preservando el resto."""
        current = self.read_settings()
        current.update(updates)
        return self.write_all_settings(current)

pal_settings_manager = PalSettingsManager()
