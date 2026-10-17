#!/bin/bash
set -e

echo "================================================="
echo "   Iniciando Palworld Server Manager - Docker    "
echo "================================================="

# Configurar PUID y PGID si se especifican
if [ -n "${PUID}" ] && [ -n "${PGID}" ]; then
    echo "[Palworld Server Manager] Configurando usuario steam con UID:${PUID} y GID:${PGID}"
    usermod -o -u "${PUID}" steam 2>/dev/null || true
    groupmod -o -g "${PGID}" steam 2>/dev/null || true
fi

# Crear directorios necesarios
mkdir -p /home/steam/steamcmd/palworld /home/steam/palworld-backups /app/data
chown -R steam:steam /home/steam /home/steam/palworld-backups /app /app/data 2>/dev/null || true

# Configurar Timezone del sistema desde la variable TZ
if [ -n "${TZ}" ] && [ -f "/usr/share/zoneinfo/${TZ}" ]; then
    echo "[Palworld Server Manager] Configurando zona horaria del contenedor: ${TZ}"
    ln -snf "/usr/share/zoneinfo/${TZ}" /etc/localtime
    echo "${TZ}" > /etc/timezone
fi

# Generar configuración de PalWorldSettings.ini desde variables de entorno si existe el script
if [ -f "/home/steam/scripts/generate-config.sh" ]; then
    bash /home/steam/scripts/generate-config.sh 2>/dev/null || true
fi

# Capturar señales SIGTERM y SIGINT para apagado ordenado del contenedor
trap 'echo "[Palworld Server Manager] Capturada señal de detención..."; exit 0' SIGTERM SIGINT

export PATH="/usr/local/bin:/usr/bin:/bin:/home/steam/steamcmd:/home/steam/bin:$PATH"

# Arrancar el panel web de Palworld Server Manager (FastAPI + Uvicorn) como usuario steam
echo "[Palworld Server Manager] Lanzando panel web en puerto ${PANEL_PORT:-8080}..."
cd /app
exec su -s /bin/bash steam -c "export PATH=\"/usr/local/bin:/usr/bin:/bin:/home/steam/steamcmd:/home/steam/bin:\$PATH\"; exec python3 -m uvicorn app.main:app --host 0.0.0.0 --port \"${PANEL_PORT:-8080}\""
