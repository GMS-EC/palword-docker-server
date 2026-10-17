#!/bin/bash
export PATH="/usr/local/bin:/usr/bin:/bin:/home/steam/bin:$PATH"
set -e

PANEL_PORT="${PANEL_PORT:-8080}"

# 1. Verificar si el panel web responde en /health
if curl -sf "http://127.0.0.1:${PANEL_PORT}/health" > /dev/null 2>&1; then
    exit 0
fi

# 2. Fallback a /login
if curl -sf "http://127.0.0.1:${PANEL_PORT}/login" > /dev/null 2>&1; then
    exit 0
fi

# 3. Si el panel está reiniciando, verificar si PalServer ya corre
if pgrep -f "PalServer" > /dev/null 2>&1; then
    exit 0
fi

exit 1
