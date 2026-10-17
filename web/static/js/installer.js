// Palworld Server Installer Script
const Installer = {
  isInstalled: false,
  isInstalling: false,
  socket: null,
  eventsSetup: false,

  async loadInstaller() {
    this.setupEvents();
    await this.refreshStatus();
    this.setupTerminalSocket();
  },

  setupEvents() {
    if (this.eventsSetup) return;
    this.eventsSetup = true;

    window.addEventListener('dockraft:language_changed', () => {
      if (typeof App === 'undefined' || App.activeTab === 'installer') {
        this.refreshStatus();
      }
    });
  },

  setupTerminalSocket() {
    if (this.socket && this.socket.readyState === WebSocket.OPEN) return;
    try {
      const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const wsUrl = `${proto}//${window.location.host}/ws/logs`;
      this.socket = new WebSocket(wsUrl);

      this.socket.onmessage = (event) => {
        this.appendLog(event.data);
      };

      this.socket.onclose = () => {
        setTimeout(() => this.setupTerminalSocket(), 5000);
      };
    } catch (e) {
      console.warn("Could not bind installer websocket:", e);
    }
  },

  appendLog(line) {
    const term = document.getElementById('installer-terminal');
    if (!term) return;

    const row = document.createElement('div');
    row.textContent = line;
    if (line.includes('[SteamCMD] Error') || line.includes('FAILED')) {
      row.style.color = '#f85149';
    } else if (line.includes('Success!') || line.includes('FINALIZADA')) {
      row.style.color = '#3fb950';
    } else if (line.includes('SteamCMD') || line.includes('INICIANDO')) {
      row.style.color = '#38bdf8';
    }

    term.appendChild(row);
    term.scrollTop = term.scrollHeight;
  },

  async refreshStatus() {
    try {
      const res = await fetch('/api/server/status');
      if (res.ok) {
        const data = await res.json();
        this.applyLockState(data);
      }
    } catch (e) {
      console.warn("Could not fetch server status:", e);
    }
  },

  applyLockState(stats) {
    if (!stats) return;
    this.isInstalled = stats.is_installed === true;

    const badgeStatus = document.getElementById('installer-badge-status');
    const uninstalledCard = document.getElementById('installer-uninstalled-card');
    const installedCard = document.getElementById('installer-installed-card');

    if (badgeStatus) {
      if (this.isInstalled) {
        badgeStatus.textContent = 'Instalado & Listo';
        badgeStatus.style.backgroundColor = 'rgba(46, 160, 67, 0.15)';
        badgeStatus.style.color = '#3fb950';
        badgeStatus.style.borderColor = '#2ea043';
      } else {
        badgeStatus.textContent = 'Descarga Requerida';
        badgeStatus.style.backgroundColor = 'rgba(210, 153, 34, 0.15)';
        badgeStatus.style.color = '#d29922';
        badgeStatus.style.borderColor = '#d29922';
      }
    }

    if (uninstalledCard && installedCard) {
      if (this.isInstalled) {
        uninstalledCard.style.display = 'none';
        installedCard.style.display = 'block';
      } else {
        uninstalledCard.style.display = 'block';
        installedCard.style.display = 'none';
      }
    }
  },

  async startInstallation() {
    if (this.isInstalling) return;

    const btn = document.getElementById('btn-start-install');
    const btnText = document.getElementById('installer-install-btn-text');
    const validate = document.getElementById('installer-validate-checkbox')?.checked ?? true;

    this.isInstalling = true;
    if (btn) btn.disabled = true;
    if (btnText) btnText.textContent = 'Descargando archivos con SteamCMD...';

    App.showToast('Iniciando descarga de Palworld Server... Observa el registro inferior.', 'info');
    this.appendLog('[Sistema] Solicitud de instalación enviada a SteamCMD...');

    try {
      const res = await fetch('/api/server/install', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ validate })
      });
      const data = await res.json();
      if (res.ok && data.success) {
        App.showToast('¡Instalación de Palworld completada exitosamente!', 'success');
        await this.refreshStatus();
        if (typeof Console !== 'undefined' && Console.pollStatus) {
          Console.pollStatus();
        }
      } else {
        App.showToast(data.message || 'Error en la instalación con SteamCMD.', 'danger');
      }
    } catch (e) {
      App.showToast('Error de conexión durante la instalación.', 'danger');
    } finally {
      this.isInstalling = false;
      if (btn) btn.disabled = false;
      if (btnText) btnText.textContent = 'Descargar e Instalar Servidor de Palworld';
    }
  },

  async updateServer(validate = true) {
    if (this.isInstalling) return;

    const btn = document.getElementById('btn-update-server');
    const btnText = document.getElementById('installer-update-btn-text');

    this.isInstalling = true;
    if (btn) btn.disabled = true;
    if (btnText) btnText.textContent = 'Actualizando con SteamCMD...';

    App.showToast('Buscando actualizaciones de Palworld en Steam...', 'info');
    this.appendLog(`[Sistema] Comprobando actualización oficial (validate=${validate})...`);

    try {
      const res = await fetch('/api/server/install', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ validate })
      });
      const data = await res.json();
      if (res.ok && data.success) {
        App.showToast('Servidor de Palworld actualizado correctamente.', 'success');
        await this.refreshStatus();
      } else {
        App.showToast(data.message || 'Error al actualizar el servidor.', 'danger');
      }
    } catch (e) {
      App.showToast('Error de red al actualizar.', 'danger');
    } finally {
      this.isInstalling = false;
      if (btn) btn.disabled = false;
      if (btnText) btnText.textContent = 'Actualizar con SteamCMD (Validar)';
    }
  },

  async validateFiles() {
    await this.updateServer(true);
  },

  async forceReinstall() {
    const ok = await App.confirm({
      title: 'Forzar Reinstalación de Archivos',
      message: '¿Confirmas volver a descargar y verificar todos los binarios de Palworld?\n\nTus partidas guardadas en Pal/Saved permanecerán protegidas.',
      confirmText: 'Reinstalar Archivos',
      danger: true
    });
    if (ok) {
      await this.updateServer(true);
    }
  },

  async saveFlags() {
    const multithreading = document.getElementById('flag-multithreading')?.checked ?? true;
    const publiclobby = document.getElementById('flag-publiclobby')?.checked ?? false;

    try {
      await fetch('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          multithreading_enabled: multithreading,
          public_lobby_enabled: publiclobby
        })
      });
      App.showToast('Parámetros de arranque actualizados.', 'success');
    } catch (e) {
      console.warn("Could not save flags:", e);
    }
  }
};
