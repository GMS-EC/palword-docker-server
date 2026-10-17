# BUILD PALWORLD DEDICATED SERVER WITH WEB MANAGER
FROM cm2network/steamcmd:root

LABEL org.opencontainers.image.title="Palworld Dedicated Server with Web Management Panel" \
      org.opencontainers.image.description="Palworld Dedicated Server Docker container with automated backups, REST API, RCON, and Dockraft Web UI" \
      maintainer="GMS-EC"

# Install system dependencies & Python 3 for Palworld Server Manager
RUN dpkg --add-architecture i386 && \
    apt-get update && apt-get install -y --no-install-recommends \
    curl \
    lsof \
    libc6-i386 \
    lib32gcc-s1 \
    bzip2 \
    gettext-base \
    procps \
    jq \
    python3 \
    python3-pip \
    python3-venv \
    tzdata \
    ca-certificates \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

LABEL name="palworld-server-docker" \
      description="Palworld Dedicated Server Docker container with Web Manager, REST API and automated backups"

ENV HOME=/home/steam \
    PUID=1000 \
    PGID=1000 \
    TZ=UTC \
    PANEL_PORT=8080 \
    PANEL_USER="admin" \
    PANEL_PASSWORD="adminpassword" \
    PALWORLD_DATA_DIR=/home/steam/steamcmd/palworld \
    BACKUP_DIR=/home/steam/palworld-backups

# Create necessary directories
RUN mkdir -p /home/steam/steamcmd/palworld /home/steam/palworld-backups /app/data /home/steam/scripts && \
    chown -R steam:steam /home/steam /app

# Setup Palworld Server Manager Web Panel
WORKDIR /app
COPY requirements.txt /app/
RUN pip3 install --no-cache-dir --break-system-packages -r /app/requirements.txt || \
    pip3 install --no-cache-dir -r /app/requirements.txt

COPY app/ /app/app/
COPY web/ /app/web/
COPY CHANGELOG.md /app/
RUN chown -R steam:steam /app

COPY scripts/ /home/steam/scripts/
RUN sed -i 's/\r$//' /home/steam/scripts/*.sh && chmod +x /home/steam/scripts/*.sh

WORKDIR /home/steam

EXPOSE 8211/udp 27015/udp 25575/tcp 8212/tcp 8080/tcp

HEALTHCHECK --start-period=5m --interval=1m --timeout=15s --retries=3 \
            CMD /home/steam/scripts/healthcheck.sh

ENTRYPOINT ["/home/steam/scripts/init.sh"]
