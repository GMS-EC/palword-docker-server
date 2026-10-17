#!/bin/bash
export PATH="/usr/local/bin:/usr/bin:/bin:/home/steam/steamcmd:/home/steam/bin:$PATH"

PAL_ROOT="${PALWORLD_DATA_DIR:-/home/steam/steamcmd/palworld}"
mkdir -p "$PAL_ROOT"
cd "$PAL_ROOT" || exit 1

STEAMCMD_BIN="/home/steam/steamcmd/steamcmd.sh"
if [ ! -f "$STEAMCMD_BIN" ]; then
    STEAMCMD_BIN=$(command -v steamcmd || command -v steamcmd.sh || echo "steamcmd")
fi

echo "[Palworld Server Manager] Verificando instalación de Palworld Dedicated Server..."

# 1. Si no existe el script PalServer.sh, instalar automáticamente
if [ ! -f "${PAL_ROOT}/PalServer.sh" ]; then
    if [ "${UPDATE_ON_START:-true}" = "true" ] || [ "${AUTO_INSTALL:-true}" = "true" ]; then
        echo "[Palworld Server Manager] Servidor no detectado. Iniciando instalación de Palworld vía SteamCMD..."
        "$STEAMCMD_BIN" +force_install_dir "$PAL_ROOT" +login anonymous +app_update 2394010 validate +quit
    else
        echo "[Palworld Server Manager] [AVISO] El servidor de Palworld no está instalado aún."
        echo "[Palworld Server Manager] Accede al panel web (http://localhost:${PANEL_PORT:-8080}) para configurar e instalarlo."
        exit 1
    fi
fi

# 2. Actualizar si está habilitado en el Panel Web
DO_UPDATE="true"
if command -v python3 >/dev/null 2>&1 && [ -d "/app/app" ]; then
    DO_UPDATE=$(python3 -c "
import sys
sys.path.insert(0, '/app')
from app.config import settings
print('true' if settings.runtime_config.get('update_on_start', True) else 'false')
" 2>/dev/null || echo "true")
fi

if [ "$DO_UPDATE" = "true" ]; then
    echo "[Palworld Server Manager] Verificando actualizaciones con SteamCMD..."
    "$STEAMCMD_BIN" +force_install_dir "$PAL_ROOT" +login anonymous +app_update 2394010 validate +quit || true
fi

# 3. Compilar configuración inicial si no existe PalWorldSettings.ini
if [ -f "/home/steam/scripts/generate-config.sh" ]; then
    bash /home/steam/scripts/generate-config.sh
fi

# 4. Asegurar permisos de ejecución en PalServer.sh
chmod +x "${PAL_ROOT}/PalServer.sh" 2>/dev/null || true
if [ -f "${PAL_ROOT}/Pal/Binaries/Linux/PalServer-Linux-Shipping" ]; then
    chmod +x "${PAL_ROOT}/Pal/Binaries/Linux/PalServer-Linux-Shipping" 2>/dev/null || true
fi

# 5. Construir argumentos de inicio dinámicamente desde PalWorldSettings.ini y configuración del Panel Web
START_ARGS=("-port=8211" "-players=32" "-queryport=27015" "-useperfthreads" "-NoAsyncLoadingThread" "-UseMultithreadForDS")

if command -v python3 >/dev/null 2>&1 && [ -d "/app/app" ]; then
    DYN_ARGS=$(python3 -c "
import sys
sys.path.insert(0, '/app')
from app.core.pal_settings_manager import pal_settings_manager
from app.config import settings

ini = pal_settings_manager.read_settings()
runtime = settings.runtime_config

args = []
port = ini.get('PublicPort') or 8211
args.append(f'-port={port}')

players = ini.get('ServerPlayerMaxNum') or 32
args.append(f'-players={players}')

args.append('-queryport=27015')

if runtime.get('community', False) or str(ini.get('bShowPlayerList', '')).lower() == 'true':
    args.append('-publiclobby')

if runtime.get('multithreading', True):
    args.extend(['-useperfthreads', '-NoAsyncLoadingThread', '-UseMultithreadForDS'])

pub_ip = str(ini.get('PublicIP', '')).strip()
if pub_ip:
    args.append(f'-publicip={pub_ip}')

print(' '.join(args))
" 2>/dev/null)
    if [ -n "$DYN_ARGS" ]; then
        read -r -a START_ARGS <<< "$DYN_ARGS"
    fi
fi

echo "========================================================================"
echo "[Palworld Server Manager] Lanzando PalServer.sh con argumentos: ${START_ARGS[*]}"
echo "[Palworld Server Manager] [INFO] El servidor está inicializando el mundo, Pals y bases."
echo "[Palworld Server Manager] [INFO] El panel web permanecerá en estado STARTING hasta responder en el puerto de juego y REST API."
echo "========================================================================"

exec ./PalServer.sh "${START_ARGS[@]}"
