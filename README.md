# Palworld Server Docker & Web Manager

[![Docker](https://img.shields.io/badge/Docker-Enabled-blue.svg)](https://www.docker.com/)
[![Palworld](https://img.shields.io/badge/Palworld-Dedicated_Server-orange.svg)](https://store.steampowered.com/app/1623730/Palworld/)
[![FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688.svg)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

Servidor dedicado de **Palworld** en contenedor **Docker** con panel de administración web interactivo en tiempo real (**Palworld Server Manager**), integración con la **REST API oficial**, protocolo **Source RCON**, respaldos automatizados, explorador de archivos seguro, webhook de Discord y configuración gráfica de todas las directivas de `PalWorldSettings.ini`.

---

## 🌟 Características Principales

- **🎮 Servidor Dedicado Oficial de Palworld (SteamCMD AppID 2394010)**:
  - Instalación bajo demanda o automática.
  - Ejecución nativa en Linux de 64 bits con optimización multihilo (`-useperfthreads -UseMultithreadForDS`).
  - Detección automática del estado del servidor (Starting, Running, Offline).

- **💻 Panel Web Interactivo (Palworld Server Manager)**:
  - Interfaz moderna oscura con estética *Dockraft* (sin frameworks pesados, estilizada con CSS nativo y Vanilla JS).
  - Terminal de consola en tiempo real vía **WebSockets** con streaming de logs y ejecución de comandos RCON / CLI.
  - Botones de acción rápida: **Iniciar**, **Detener** (con guardado previo de mundo), **Reiniciar**, **Guardar Mundo** (`SaveWorld`) y **Actualizar Servidor**.
  - Emisión de anuncios en el juego (`Announce` / `Broadcast`) a todos los jugadores conectados.

- **📊 Monitor de Recursos & Rendimiento en Vivo**:
  - Lectura en tiempo real de consumo de CPU host, RAM de Palworld (con soporte para Cgroups v1 y v2), espacio en disco y tiempo de actividad (*Uptime*).
  - Detección del **Tickrate / Server FPS** del motor de juego mediante la REST API oficial.
  - Gráficas históricas interactivas impulsadas por **Chart.js**.

- **👥 Gestión de Domadores / Jugadores Conectados**:
  - Consulta en tiempo real de jugadores en línea vía **REST API** (`/v1/api/players`) y **RCON** (`ShowPlayers`).
  - Visualización de Nombre, Player UID, Steam ID, Ping, Nivel e IP.
  - Acciones administrativas directas: **Expulsar** (*Kick*) y **Banear** (*Ban*) con ventana modal de motivo.
  - Historial persistente de conexiones con opción de revocar baneos (*Unban*).

- **💾 Sistema Integral de Respaldos**:
  - Copias de seguridad comprimidas en `.tar.gz` de la carpeta `Pal/Saved` (mundos, inventarios de jugadores, bases y gremios).
  - Creación de respaldos instantáneos con un solo clic y etiqueta personalizada.
  - Restauración automática en 1-clic con resguardo de seguridad pre-restauración.
  - Descarga directa de archivos `.tar.gz` a tu equipo.
  - Rotación y poda automática de respaldos antiguos (`BACKUP_MAX_COUNT`).

- **⏰ Automatización & Tareas Programadas**:
  - Respaldos automáticos periódicos cada X horas.
  - Guardado periódico del mundo (`SaveWorld`) para evitar pérdida de progreso ante apagados repentinos.
  - Reinicio automático programado con avisos previos en el chat del juego (a los 10 minutos y 1 minuto).
  - Control de horario de encendido y apagado (*Power Schedule*).

- **🔔 Notificaciones Ricas en Discord (Webhooks)**:
  - Tarjetas embebidas (*Discord Embeds*) con soporte bilingüe (Español / Inglés).
  - Alertas de Servidor Iniciando, Servidor Online, Servidor Detenido, Respaldo Creado y Entrada/Salida de Jugadores.
  - Selector granular de eventos y botón de prueba integrado.

- **📁 Explorador de Archivos Web Completo**:
  - Navegación segura dentro del contenedor con protección contra *Path Traversal* y *Zip Slip*.
  - Editor de texto integrado con atajo <kbd>Ctrl+S</kbd> para editar archivos `.ini` y archivos de configuración.
  - Subida, descarga, creación, renombrado, duplicado y compresión/descompresión de archivos ZIP.

- **⚙️ Gestor Visual de Configuraciones (`PalWorldSettings.ini`)**:
  - Edición organizada por categorías de todos los parámetros de `OptionSettings`:
    - Identidad, contraseñas, crossplay y visibilidad.
    - Multiplicadores de tasas (XP, captura de Pals, aparición de Pals, ciclo día/noche).
    - Combate, daño de Pals/jugadores, PvP, fuego amigo e invasiones a bases.
    - Incubación de huevos, hambre, resistencia y velocidad de trabajo.
    - Límites de bases, trabajadores y jugadores por gremio.

---

## 🚀 Inicio Rápido con Docker Compose

### 1. Clonar o descargar el repositorio
```bash
git clone https://github.com/GMS-EC/palword-docker-server.git
cd palword-docker-server
```

### 2. Configurar variables de entorno (Opcional)
Puedes personalizar las credenciales en el archivo `docker-compose.yml` o crear un archivo `.env`:
```bash
cp .env.example .env
```

### 3. Levantar el contenedor
```bash
docker compose up -d --build
```

### 4. Acceder al Panel de Control Web
Abre tu navegador e ingresa a:
👉 **`http://localhost:8080`**

- **Usuario por defecto:** `admin`
- **Contraseña por defecto:** `adminpassword` *(cámbiala en `.env` o `docker-compose.yml`)*

---

## 🔌 Puertos de Red

| Puerto | Protocolo | Servicio | Descripción |
|---|---|---|---|
| **`8080`** | TCP | HTTP | Panel de Control Web (**Palworld Server Manager**) |
| **`8211`** | UDP | Palworld | Puerto principal del juego (conexión de clientes) |
| **`27015`** | UDP | Steam Query | Explorador de servidores de Steam / buscador |
| **`25575`** | TCP | RCON | Consola remota para administración y comandos |
| **`8212`** | TCP | REST API | API oficial de Palworld (métricas, jugadores, save, shutdown) |

> [!NOTE]
> Para permitir que tus amigos o miembros de tu comunidad se unan a través de Internet, asegúrate de abrir y redirigir (*Port Forwarding*) el puerto **`8211/udp`** en tu router o firewall.

---

## 📂 Volúmenes Persistentes

El contenedor expone tres volúmenes principales montados localmente:
- **`./steamcmd/palworld`**: Carpeta donde se descargan los binarios del juego y se almacenan los mundos guardados (`Pal/Saved/SaveGames`) y configuraciones (`Pal/Saved/Config/LinuxServer/PalWorldSettings.ini`).
- **`./palworld-backups`**: Carpeta donde se guardan los archivos comprimidos `.tar.gz` de las copias de seguridad automáticas y manuales.
- **`./data`**: Carpeta para almacenar el historial de actividad y configuraciones del Panel Web.

---

## 🛠️ Tecnologías Empleadas

- **Base Container**: `cm2network/steamcmd:root` (Ubuntu/Debian con SteamCMD oficial).
- **Backend**: Python 3 con **FastAPI** + **Uvicorn** asíncrono.
- **Frontend**: Jinja2 Templates, Vanilla JavaScript, CSS3 variables oscuras (*Dockraft design*) y **Chart.js**.
- **Protocolos de Juego**: Palworld REST API (v1 HTTP Basic Auth) y Valve Source RCON.
