<table>
  <tr>
    <td width="140" align="center" valign="middle">
      <img src="web/static/img/logo.png" alt="Palworld Server Manager Logo" width="120" style="border-radius: 14px;" />
    </td>
    <td valign="middle">
      <h2>🎮 Palworld Dedicated Server & Web Manager in Docker</h2>
      <p><strong>Panel web ultra-ligero y automatizado para administrar una única instancia dedicada de servidor de Palworld (SteamCMD AppID 2394010).</strong></p>
      <p>
        <a href="https://hub.docker.com/r/marcusm99/palword-docker-server"><img src="https://img.shields.io/badge/docker%20hub-marcusm99%2Fpalword--docker--server-0db7ed?style=flat-square&logo=docker" alt="Docker Hub" /></a>
        <a href="LICENSE"><img src="https://img.shields.io/badge/license-GPL%20v3-007ec6?style=flat-square" alt="License" /></a>
        <a href="https://fastapi.tiangolo.com"><img src="https://img.shields.io/badge/framework-fastapi-009688?style=flat-square&logo=fastapi" alt="FastAPI" /></a>
        <a href="https://gmsec.cc"><img src="https://img.shields.io/badge/author-gmsec.cc-8a2be2?style=flat-square" alt="gmsec.cc" /></a>
        <br />
        <img src="https://img.shields.io/badge/platform-linux%20amd64-black?style=flat-square&logo=linux" alt="Platform" />
      </p>
    </td>
  </tr>
</table>

<p>
  🌐 <strong>Select Language / Selecciona Idioma:</strong> <a href="#-versión-en-español"><strong>ES Español</strong></a> | <a href="#-english-version"><strong>GB English</strong></a>
</p>

---

## 🇪🇸 Versión en Español

### 💡 ¿Por qué Palworld Server Manager? (Arquitectura de Instancia Única)

Los paneles genéricos de gestión de juegos como **Pterodactyl** o **AMP** fueron diseñados para alojar decenas de servidores concurrentes en granjas de nodos. Por esa razón, requieren complejas bases de datos relacionales (MySQL/PostgreSQL), colas de mensajería (Redis/Celery), demonios en segundo plano y múltiples microservicios que consumen entre **500 MB y más de 1.2 GB de memoria RAM en reposo**, incluso antes de descargar o arrancar el servidor del juego.

En un juego exigente como **Palworld**, desarrollado en Unreal Engine 5 donde el servidor dedicado requiere de forma recomendada entre **8 GB y 16 GB de RAM** para sostener mundos con construcciones masivas y decenas de jugadores, desperdiciar gigabytes en middleware es inaceptable.

**Palworld Server Manager fue diseñado bajo una filosofía intencionalmente distinta: 1 Contenedor = 1 Servidor Dedicado.**

Al enfocarse exclusivamente en mantener y optimizar **una única instancia de servidor por contenedor**:
* **Cero bases de datos externas**: Todas las opciones, usuarios, tareas y webhooks se gestionan limpiamente en archivos JSON locales de alta velocidad.
* **Sin intermediarios pesados**: El panel corre en un único proceso asíncrono en Python con FastAPI y Uvicorn.
* **Aprovechamiento máximo del hardware**: El panel web consume únicamente entre **~50 y 75 MB de RAM en reposo** y **~0 % de CPU**, dejando prácticamente el **99 % de la memoria física disponible directamente para el motor de Palworld, tus Pals y tus jugadores.**
* **Ejecución 100% nativa en Linux**: El binario oficial (`PalServer.sh` / `PalServer-Linux-Test`) corre directamente en Linux de 64 bits mediante SteamCMD oficial, sin capas de emulación como Wine o Proton.

---

### ✨ Características Principales

* 🕹️ **Instalación y Actualización en 1 Clic con SteamCMD**:
  * Descarga automática de los binarios oficiales de Palworld (SteamCMD AppID `2394010`).
  * Validación de integridad de archivos (`validate`) para corregir descargas corruptas.
  * Optimización multihilo activada por defecto (`-useperfthreads`, `-NoAsyncLoadingThread`, `-UseMultithreadForDS`).
  * Selector de Servidor Comunitario Público (`-publiclobby`).
* 📟 **Terminal y Consola Interactiva en Vivo**:
  * Flujo de registros en tiempo real mediante **WebSockets**.
  * Envío directo de comandos de consola y protocolo **Source RCON**.
  * Emisión de mensajes globales en el chat del juego (**Broadcast**) desde la barra superior.
  * Botones de acción rápida: Iniciar, Guardar Mundo (`SaveWorld`), Reiniciar y Detener con apagado seguro.
* ⚙️ **Configuración Total de `PalWorldSettings.ini` sin Reiniciar Contenedor**:
  * **Modo Visual**: Edición por categorías de multiplicadores de experiencia (`ExpRate`), ratio de captura (`PalCaptureRate`), daño de Pals/jugadores, velocidad de hambre/energía, penalización por muerte y velocidad de ciclo día/noche.
  * **Modo Raw**: Editor de texto en bruto con validación de sintaxis y buscador integrado.
  * Los cambios se sincronizan directamente con el archivo nativo en `Pal/Saved/Config/LinuxServer/PalWorldSettings.ini`.
* 👥 **Gestión de Domadores / Jugadores en Tiempo Real**:
  * Lista interactiva de jugadores conectados mediante la **REST API oficial** (`/v1/api/players`) y **RCON** (`ShowPlayers`).
  * Consulta de Nombre, Player UID, Steam ID, Ping, Nivel e IP.
  * Acciones de moderación: **Expulsar** (*Kick*) y **Banear** (*Ban*) con ventana modal de motivo.
  * Historial persistente de jugadores con opción de revocar baneos (*Unban*).
* 💾 **Sistema Integral de Respaldos**:
  * Copias de seguridad comprimidas en `.tar.gz` de las partidas guardadas (`Pal/Saved`).
  * Restauración automática en 1 clic con resguardo preventivo de seguridad.
  * Descarga directa del archivo de respaldo a tu navegador.
  * Poda y rotación automática para mantener el almacenamiento bajo control.
* ⏰ **Automatización y Tareas Programadas**:
  * Tareas automáticas mediante **expresiones Cron** o **intervalos regulares**.
  * Automatiza reinicios de madrugada, guardados periódicos (`SaveWorld`), copias de seguridad o comandos de consola personalizados.
* 🔔 **Notificaciones Webhooks Multicanal**:
  * Alertas instantáneas en **Discord** (con tarjetas temáticas), **Telegram** y **Correo Electrónico (SMTP)**.
  * Notificaciones de servidor iniciando, en línea, detenido, respaldos creados y entrada/salida de jugadores.
  * Botones de prueba integrados por canal para validar la conectividad en segundos.
* 📁 **Explorador de Archivos Web Seguro**:
  * Navegación completa en el directorio del servidor con protección contra *Path Traversal*.
  * Editor de texto integrado con guardado rápido (<kbd>Ctrl+S</kbd>).
  * Subida, descarga, creación, renombrado y compresión/descompresión de archivos ZIP.
* 🔒 **Seguridad y Control de Acceso**:
  * Autenticación mediante credenciales de administrador y cookies seguras con firma HMAC.
  * **Protección contra fuerza bruta**: Bloqueo temporal automático tras 5 intentos fallidos de inicio de sesión.
* 🌐 **Bilingüe (Español / Inglés)**: Conmutación de idioma en caliente sin recargar la página.

---

### ⚡ Rendimiento del Servidor y FPS (Server Tickrate)

El servidor dedicado de Palworld ejecuta su ciclo de físicas, inteligencia artificial de Pals y combate en torno a **60 FPS / Ticks por segundo**. El panel web consulta y grafica esta información en tiempo real directamente desde el endpoint oficial de telemetría de Palworld (`GET /v1/api/metrics`), donde el motor Unreal Engine 5 reporta el valor exacto de `serverfps` y `serverframetime`. Monitorear los FPS en vivo permite diagnosticar problemas de rendimiento antes de que los jugadores experimenten retrasos.

| Server FPS | Estado | Experiencia en el Juego |
| :---: | :---: | :--- |
| **50.0 – 60.0** | 🟢 Óptimo | Simulación perfecta, combates fluidos y captura inmediata de Pals. |
| **35.0 – 49.9** | 🟡 Carga Ligera | Fluidez adecuada, prácticamente imperceptible. |
| **20.0 – 34.9** | 🟠 Lag Moderado | Retraso leve en interacción con cofres, construcción y habilidades de Pals. |
| **< 20.0** | 🔴 Sobrecarga | Desincronización notable de golpes, teletransportación de Pals y lag severo. |

---

### 🚀 Despliegue con Docker Compose (Recomendado)

#### Opción 1: Copiar y Pegar (Más rápido, sin clonar repositorio)
Crea una carpeta en tu servidor y un archivo `docker-compose.yml` con el siguiente contenido:

```yaml
services:
  palworld-server:
    image: marcusm99/palword-docker-server:latest
    container_name: palworld-server
    restart: unless-stopped
    stop_grace_period: 30s
    mem_limit: 8g # Recomendado: 8g a 16g según jugadores concurrentes
    ports:
      - "8080:8080"        # Panel Web Palworld Server Manager (HTTP)
      - "8211:8211/udp"    # Puerto de Juego Principal Palworld (UDP)
      - "27015:27015/udp"  # Puerto de Consulta Steam Query (UDP)
      - "25575:25575/tcp"  # Puerto RCON Consola Remota (TCP)
      - "8212:8212/tcp"    # Puerto REST API Oficial de Palworld (TCP)
    environment:
      - TZ=America/Guayaquil
      - PANEL_USER=admin
      - PANEL_PASSWORD=MiContraseñaSegura123
    volumes:
      - ./steamcmd/palworld:/home/steam/steamcmd/palworld
      - ./palworld-backups:/home/steam/palworld-backups
      - ./data:/app/data
```

Luego inicia el contenedor:
```bash
docker compose up -d
```

#### Opción 2: Clonando el repositorio oficial
1. Clona el repositorio:
   ```bash
   git clone https://github.com/GMS-EC/palword-docker-server.git
   cd palword-docker-server
   ```

2. Configura tus credenciales y zona horaria en el archivo `docker-compose.yml`.

3. Inicia el servidor:
   ```bash
   docker compose up -d
   ```

El panel estará disponible de inmediato en **`http://localhost:8080`** (o en la IP pública de tu servidor).

---

### 🐳 Despliegue con Docker Run Directo

```bash
docker run -d \
  --name palworld-server \
  --restart unless-stopped \
  --stop-timeout 30 \
  --memory 8g \
  -p 8080:8080 \
  -p 8211:8211/udp \
  -p 27015:27015/udp \
  -p 25575:25575/tcp \
  -p 8212:8212/tcp \
  -v ./steamcmd/palworld:/home/steam/steamcmd/palworld \
  -v ./palworld-backups:/home/steam/palworld-backups \
  -v ./data:/app/data \
  -e TZ=America/Guayaquil \
  -e PANEL_USER=admin \
  -e PANEL_PASSWORD=MiContraseñaSegura123 \
  marcusm99/palword-docker-server:latest
```

---

### ⚙️ Variables de Entorno

| Variable | Valor por Defecto | Descripción |
| :--- | :---: | :--- |
| `PANEL_PORT` | `8080` | Puerto HTTP donde se sirve el panel web administrativo. |
| `PANEL_USER` | `admin` | Nombre de usuario para el inicio de sesión web. |
| `PANEL_PASSWORD` | `adminpassword` | Contraseña administrativa del panel web. |
| `TZ` | `America/Guayaquil` | Zona horaria del contenedor para fechas de auditoría y tareas Cron. |
| `PUID` | `1000` | User ID de Linux con el que se ejecutan SteamCMD y Palworld. |
| `PGID` | `1000` | Group ID de Linux con el que se gestionan los archivos en disco. |
| `PALWORLD_DATA_DIR` | `/home/steam/steamcmd/palworld` | Ruta interna de instalación del servidor y partidas guardadas. |
| `BACKUP_DIR` | `/home/steam/palworld-backups` | Carpeta interna donde se almacenan las copias de seguridad `.tar.gz`. |

---

### 📂 Volúmenes Persistentes

* **`./steamcmd/palworld`** (`/home/steam/steamcmd/palworld`): Contiene los binarios descargados por SteamCMD, el archivo de configuración `PalWorldSettings.ini` y el directorio de partidas guardadas `Pal/Saved/SaveGames`.
* **`./palworld-backups`** (`/home/steam/palworld-backups`): Carpeta donde se almacenan los archivos `.tar.gz` de las copias de seguridad manuales y automáticas.
* **`./data`** (`/app/data`): Carpeta de datos del panel web (usuarios, sesiones activas, tareas programadas, historial de domadores y webhooks).

---

### 🧪 Verificación y Compilación

Para comprobar la integridad del código del backend:
```bash
python -m compileall app
```

---

## 🇬🇧 English Version

### 💡 Why Palworld Server Manager? (Single-Instance Dedicated Architecture)

Traditional game hosting control panels such as **Pterodactyl** or **AMP** were architected to host dozens of multi-game servers across node clusters. Because of that design, they mandate heavy relational databases (MySQL/PostgreSQL), background worker queues (Redis/Celery), and multiple distributed daemons that consume between **500 MB and over 1.2 GB of idle RAM** before any game server is even installed or launched.

In a resource-intensive game like **Palworld**, powered by Unreal Engine 5 where a dedicated server requires between **8 GB and 16 GB of RAM** to sustain massive bases and concurrent players, wasting gigabytes on management middleware is unacceptable.

**Palworld Server Manager was deliberately built under a different philosophy: 1 Container = 1 Dedicated Server.**

By focusing strictly on hosting, maintaining, and optimizing **a single server instance per container**:
* **Zero external database dependencies**: All settings, tasks, and audit logs are managed cleanly via fast, local JSON files.
* **No bloated middleware**: Runs as a single asynchronous Python process powered by FastAPI and Uvicorn.
* **Maximum hardware efficiency**: Consumes only **~50 to 75 MB of RAM at idle** and **~0% CPU**, leaving more than **99% of your physical host memory directly available for Palworld, your Pals, and your community.**
* **100% Native Linux Execution**: Uses official SteamCMD to run native 64-bit Linux binaries (`PalServer.sh` / `PalServer-Linux-Test`) without emulated layers like Wine or Proton.

---

### ✨ Key Features

* 🕹️ **1-Click SteamCMD Installer & Integrity Checker**:
  * Automatic download of official Palworld server files (SteamCMD AppID `2394010`).
  * File validation (`validate`) to automatically repair missing or corrupted assets.
  * Multi-threaded engine optimization enabled out-of-the-box (`-useperfthreads`, `-NoAsyncLoadingThread`, `-UseMultithreadForDS`).
  * Community Public Lobby toggle (`-publiclobby`).
* 📟 **Live Web Console & Real-Time Terminal**:
  * Real-time log streaming powered by **WebSockets**.
  * Direct console command execution and **Source RCON** communication.
  * In-game server-wide announcements (**Broadcast**) from the top bar.
  * Quick-action buttons: Start, Instant Save (`SaveWorld`), Restart, and Graceful Shutdown.
* ⚙️ **Full `PalWorldSettings.ini` Suite without Container Restarts**:
  * **Visual Mode**: Intuitive sliders and selectors for experience rate (`ExpRate`), Pal capture rate (`PalCaptureRate`), combat damage multipliers, hunger/stamina rates, death penalties, and day/night speed.
  * **Raw Mode**: Raw configuration text editor with syntax validation and live search.
  * Changes are safely saved directly to `Pal/Saved/Config/LinuxServer/PalWorldSettings.ini`.
* 👥 **Real-Time Tamer / Player Management**:
  * Live player roster retrieved via **official REST API** (`/v1/api/players`) and **RCON** (`ShowPlayers`).
  * Details per player: Player Name, Player UID, Steam ID, Ping, Level, and IP Address.
  * Moderation actions: **Kick** and **Ban** (with custom reason modal).
  * Persistent connection history with 1-click **Unban** functionality.
* 💾 **Selective Backup System**:
  * Compressed `.tar.gz` archives of game worlds and player profiles (`Pal/Saved`).
  * 1-Click automatic restoration with safety pre-restore snapshots.
  * Direct archive download from the web interface.
  * Automated retention pruning to keep storage under control.
* ⏰ **Automation & Scheduled Tasks**:
  * Automated tasks using standard **Cron expressions** or **custom intervals**.
  * Automate daily early-morning restarts, periodic `SaveWorld` execution, recurring backups, or custom RCON commands.
* 🔔 **Multi-Channel Webhook Notifications**:
  * Real-time notification embeds on **Discord**, **Telegram Bot**, and **SMTP Email**.
  * Alerts for server starting, server online, server stopped, backup completed, and player join/leave events.
  * Built-in per-channel test buttons to verify delivery in seconds.
* 📁 **Secure Built-in Web File Manager**:
  * File tree restricted to container data volumes with path-traversal safeguards.
  * Integrated text editor with fast save shortcut (<kbd>Ctrl+S</kbd>).
  * Upload, download, create, rename, duplicate, zip, and unzip capabilities.
* 🔒 **Security & Access Control**:
  * Session-based login with bcrypt hashing and HMAC cryptographic signing.
  * **Brute-force protection**: Automatic IP lockout after 5 consecutive failed attempts.
* 🌐 **Bilingual (English / Spanish)**: Instant language switching without reloading the page.

---

### ⚡ Performance & Server FPS (Tickrate)

The Palworld dedicated server runs its physics, Pal artificial intelligence, and combat calculations at a target of **60 FPS / Ticks per second**. The web panel queries and graphs this metric in real time directly from the official Palworld REST API endpoint (`GET /v1/api/metrics`), where Unreal Engine 5 reports the exact `serverfps` and `serverframetime` values. Monitoring server FPS in real time allows server admins to detect performance bottlenecks before players feel lag.

| Server FPS | Status | Gameplay Experience |
| :---: | :---: | :--- |
| **50.0 – 60.0** | 🟢 Optimal | Flawless simulation, fluid combat, and instantaneous Pal capture. |
| **35.0 – 49.9** | 🟡 Light Load | Smooth gameplay, virtually unnoticeable lag. |
| **20.0 – 34.9** | 🟠 Moderate Lag | Slight delay when opening chests, building, and using Pal active skills. |
| **< 20.0** | 🔴 Overloaded | Hit desynchronization, Pal rubberbanding, and severe gameplay lag. |

---

### 🚀 Quick Start with Docker Compose (Recommended)

#### Option 1: Copy & Paste (Fastest, no git clone needed)
Create a new directory and save the following as `docker-compose.yml`:

```yaml
services:
  palworld-server:
    image: marcusm99/palword-docker-server:latest
    container_name: palworld-server
    restart: unless-stopped
    stop_grace_period: 30s
    mem_limit: 8g # Recommended: 8g to 16g depending on player count
    ports:
      - "8080:8080"        # Palworld Server Manager Web Panel (HTTP)
      - "8211:8211/udp"    # Palworld Main Game Port (UDP)
      - "27015:27015/udp"  # Steam Query Port (UDP)
      - "25575:25575/tcp"  # Remote Console RCON Port (TCP)
      - "8212:8212/tcp"    # Official Palworld REST API Port (TCP)
    environment:
      - TZ=America/Guayaquil
      - PANEL_USER=admin
      - PANEL_PASSWORD=MySecurePassword123
    volumes:
      - ./steamcmd/palworld:/home/steam/steamcmd/palworld
      - ./palworld-backups:/home/steam/palworld-backups
      - ./data:/app/data
```

Then launch the container:
```bash
docker compose up -d
```

#### Option 2: Clone the Official Repository
1. Clone the repository:
   ```bash
   git clone https://github.com/GMS-EC/palword-docker-server.git
   cd palword-docker-server
   ```

2. Configure your credentials and timezone in `docker-compose.yml`.

3. Launch the stack:
   ```bash
   docker compose up -d
   ```

Access the panel immediately at **`http://localhost:8080`** (or your server's public IP).

---

### 🐳 Run Directly with Docker

```bash
docker run -d \
  --name palworld-server \
  --restart unless-stopped \
  --stop-timeout 30 \
  --memory 8g \
  -p 8080:8080 \
  -p 8211:8211/udp \
  -p 27015:27015/udp \
  -p 25575:25575/tcp \
  -p 8212:8212/tcp \
  -v ./steamcmd/palworld:/home/steam/steamcmd/palworld \
  -v ./palworld-backups:/home/steam/palworld-backups \
  -v ./data:/app/data \
  -e TZ=America/Guayaquil \
  -e PANEL_USER=admin \
  -e PANEL_PASSWORD=MySecurePassword123 \
  marcusm99/palword-docker-server:latest
```

---

### ⚙️ Environment Variables

| Variable | Default Value | Description |
| :--- | :---: | :--- |
| `PANEL_PORT` | `8080` | Web panel port. |
| `PANEL_USER` | `admin` | Administrator username for web login. |
| `PANEL_PASSWORD` | `adminpassword` | Administrator password for web login. |
| `TZ` | `America/Guayaquil` | Server timezone for audit timestamps and Cron scheduler. |
| `PUID` | `1000` | Linux user ID for SteamCMD and Palworld execution. |
| `PGID` | `1000` | Linux group ID for file permissions. |
| `PALWORLD_DATA_DIR` | `/home/steam/steamcmd/palworld` | Internal container path for game binaries and saved worlds. |
| `BACKUP_DIR` | `/home/steam/palworld-backups` | Internal container path for compressed `.tar.gz` backup archives. |

---

### 📂 Persistent Storage Volumes

* **`./steamcmd/palworld`** (`/home/steam/steamcmd/palworld`): Stores downloaded SteamCMD binaries, `PalWorldSettings.ini` configuration, and saved worlds in `Pal/Saved/SaveGames`.
* **`./palworld-backups`** (`/home/steam/palworld-backups`): Isolated directory where `.tar.gz` backups are saved.
* **`./data`** (`/app/data`): Internal web panel state (users, sessions, scheduled tasks, tamer connection logs, and webhooks).

---

### 🧪 Automated Testing & Code Compilation

Verify backend integrity locally:
```bash
python -m compileall app
```

---

## 📄 License

Distributed under the **GNU General Public License v3.0 (GPLv3)**. See [`LICENSE`](LICENSE) for details.

Developed with care by [**GMS-EC**](https://gmsec.cc).
