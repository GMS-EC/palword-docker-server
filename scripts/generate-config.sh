#!/bin/bash
PAL_ROOT="${PALWORLD_DATA_DIR:-/home/steam/steamcmd/palworld}"
CONFIG_DIR="${PAL_ROOT}/Pal/Saved/Config/LinuxServer"
CONFIG_FILE="${CONFIG_DIR}/PalWorldSettings.ini"
DEFAULT_SETTINGS="${PAL_ROOT}/DefaultPalWorldSettings.ini"

mkdir -p "$CONFIG_DIR"

if [ ! -f "$CONFIG_FILE" ]; then
    echo "[Palworld Server Manager] Inicializando PalWorldSettings.ini..."
    if [ -f "$DEFAULT_SETTINGS" ]; then
        cp "$DEFAULT_SETTINGS" "$CONFIG_FILE"
    fi
fi

# Si python3 y app.core.pal_settings_manager están disponibles, sincronizar
if command -v python3 >/dev/null 2>&1 && [ -d "/app/app" ]; then
    python3 -c "
import sys
sys.path.insert(0, '/app')
from app.core.pal_settings_manager import pal_settings_manager
pal_settings_manager._ensure_paths()
print('[Palworld Server Manager] Sincronización de PalWorldSettings.ini completada.')
" 2>/dev/null || true
fi
