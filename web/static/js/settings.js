// Palworld Server Settings Script (Visual & Raw PalWorldSettings.ini)
const Settings = {
  properties: {},
  runtimeConfig: {},
  serverStatus: {},
  dirty: false,
  mode: 'visual',
  currentCategory: 'server',
  searchQuery: '',
  eventsSetup: false,

  _t(key, fallback) {
    if (typeof I18n !== 'undefined' && I18n.t) return I18n.t(key, fallback);
    return fallback !== undefined ? fallback : key;
  },

  async loadSettings() {
    this.setupEvents();
    if (window.__INITIAL_STATS__) {
      this.serverStatus = window.__INITIAL_STATS__;
    }
    if (window.__INITIAL_CONFIG__) {
      this.runtimeConfig = window.__INITIAL_CONFIG__;
    }

    this.updateHeaderProfile();
    this.setPropertiesCategory(this.currentCategory || 'server');

    await Promise.all([
      this.fetchServerStatus(),
      this.fetchSettings(),
      this.loadRawProperties()
    ]);
  },

  setupEvents() {
    if (this.eventsSetup) return;
    this.eventsSetup = true;

    window.addEventListener('dockraft:language_changed', () => {
      if (typeof App === 'undefined' || App.activeTab === 'settings') {
        this.updateHeaderProfile();
      }
    });
  },

  updateHeaderProfile() {
    const isInstalled = this.serverStatus.is_installed !== false;
    const status = this.serverStatus.status || 'OFFLINE';
    const statusEl = document.getElementById('settings-badge-status');
    const restartBtn = document.getElementById('btn-settings-restart-now');
    const emptyState = document.getElementById('settings-empty-state');
    const container = document.getElementById('settings-container');

    if (emptyState && container) {
      if (!isInstalled) {
        emptyState.style.display = 'block';
        container.style.display = 'none';
      } else {
        emptyState.style.display = 'none';
        container.style.display = 'block';
      }
    }

    const isRunning = status === 'RUNNING';
    const isStarting = status === 'STARTING';
    const isStopping = status === 'STOPPING';
    const color = isRunning ? '#3fb950' : (isStarting ? '#d29922' : (isStopping ? '#f85149' : '#8b949e'));
    const text = isRunning ? 'En Ejecución' : (isStarting ? 'Iniciando...' : (isStopping ? 'Deteniendo...' : 'Apagado'));

    if (statusEl) {
      statusEl.innerHTML = `<span class="badge" style="display:inline-flex; align-items:center; background-color: rgba(255,255,255,0.06); border: 1px solid ${color}; color: ${color}; font-size: 0.8rem; padding: 4px 10px;"><span style="display:inline-block; width:7px; height:7px; border-radius:50%; background-color:${color}; margin-right:6px;"></span>${text}</span>`;
    }

    if (restartBtn) {
      restartBtn.style.display = isRunning ? 'inline-flex' : 'none';
    }

    // Si el servidor no está en ejecución, ocultar el aviso de reinicio
    if (!isRunning) {
      const banner = document.getElementById('settings-status-banner');
      if (banner) banner.style.display = 'none';
    }
  },

  async fetchServerStatus() {
    try {
      const res = await fetch('/api/server/status');
      if (res.ok) {
        this.serverStatus = await res.json();
        this.updateHeaderProfile();
      }
    } catch (e) {
      console.warn("Could not load server status:", e);
    }
  },

  async fetchSettings() {
    try {
      const res = await fetch('/api/settings');
      if (res.ok) {
        const data = await res.json();
        this.properties = data.ini_settings || {};
        this.runtimeConfig = data.runtime_config || {};
        this.populateVisualForm(this.properties);
        this.setDirty(false);
      }
    } catch (e) {
      console.warn("Could not load settings:", e);
    }
  },

  populateVisualForm(ini) {
    if (!ini) return;
    Object.keys(ini).forEach(key => {
      const el = document.getElementById(`prop-${key}`);
      if (!el) return;

      const val = ini[key];
      if (el.type === 'checkbox') {
        el.checked = (val === true || val === 'True' || val === 'true' || val === 1);
      } else {
        el.value = (val !== undefined && val !== null) ? val : '';
      }
    });

    // Sincronizar controles interactivos de Crossplay y Autostart
    this.syncCrossplayToUI(ini.CrossplayPlatforms || '(Steam,Xbox,PS5,Mac)');
    const autostartVal = (this.runtimeConfig && this.runtimeConfig.autostart_server !== undefined)
      ? this.runtimeConfig.autostart_server
      : (ini.autostart_server === true || ini.autostart_server === 'true');
    this.syncAutostartToUI(autostartVal);
  },

  syncCrossplayToUI(rawVal) {
    const str = String(rawVal || '').replace(/[()"]/g, '').toLowerCase();
    const isEnabled = str.includes('xbox') || str.includes('ps5') || str.includes('mac') || str === 'true' || str === 'activado';

    const toggle = document.getElementById('toggle-crossplay-enabled');
    if (toggle) toggle.checked = isEnabled;

    const label = document.getElementById('crossplay-status-label');
    if (label) {
      label.textContent = isEnabled ? this._t('t_settings_crossplay_on', 'Activado') : this._t('t_settings_crossplay_off', 'Desactivado');
      label.style.color = isEnabled ? '#58a6ff' : 'var(--text-dim)';
    }

    const hiddenInput = document.getElementById('prop-CrossplayPlatforms');
    if (hiddenInput) hiddenInput.value = isEnabled ? '(Steam,Xbox,PS5)' : '(Steam)';
  },

  onCrossplayToggle(enabled) {
    const label = document.getElementById('crossplay-status-label');
    if (label) {
      label.textContent = enabled ? this._t('t_settings_crossplay_on', 'Activado') : this._t('t_settings_crossplay_off', 'Desactivado');
      label.style.color = enabled ? '#58a6ff' : 'var(--text-dim)';
    }

    const hiddenInput = document.getElementById('prop-CrossplayPlatforms');
    if (hiddenInput) hiddenInput.value = enabled ? '(Steam,Xbox,PS5)' : '(Steam)';

    this.markDirty();
  },

  syncAutostartToUI(rawVal) {
    const isEnabled = (rawVal === true || rawVal === 'true' || rawVal === 1);
    const toggle = document.getElementById('toggle-autostart-server');
    if (toggle) toggle.checked = isEnabled;

    const label = document.getElementById('autostart-status-label');
    if (label) {
      label.textContent = isEnabled ? 'Activado' : 'Desactivado';
      label.style.color = isEnabled ? '#3fb950' : 'var(--text-dim)';
    }

    const hiddenInput = document.getElementById('prop-autostart_server');
    if (hiddenInput) hiddenInput.value = isEnabled ? 'true' : 'false';
  },

  onAutostartToggle(enabled) {
    const label = document.getElementById('autostart-status-label');
    if (label) {
      label.textContent = enabled ? 'Activado' : 'Desactivado';
      label.style.color = enabled ? '#3fb950' : 'var(--text-dim)';
    }

    const hiddenInput = document.getElementById('prop-autostart_server');
    if (hiddenInput) hiddenInput.value = enabled ? 'true' : 'false';

    this.markDirty();
  },

  markDirty() {
    this.setDirty(true);
  },

  setDirty(isDirty) {
    this.dirty = isDirty;
    const badge = document.getElementById('settings-unsaved-badge');
    if (badge) {
      badge.style.display = isDirty ? 'inline-block' : 'none';
    }
  },

  setPropertiesMode(mode) {
    this.mode = mode;
    const visualView = document.getElementById('settings-visual-view');
    const rawView = document.getElementById('settings-raw-view');
    const catBar = document.getElementById('settings-categories-bar');
    const btnVisual = document.getElementById('btn-mode-props-visual');
    const btnRaw = document.getElementById('btn-mode-props-raw');

    if (mode === 'raw') {
      if (visualView) visualView.style.display = 'none';
      if (rawView) rawView.style.display = 'block';
      if (catBar) catBar.style.display = 'none';

      if (btnVisual) {
        btnVisual.className = 'btn btn-sm btn-outline';
      }
      if (btnRaw) {
        btnRaw.className = 'btn btn-sm btn-primary';
      }
      this.loadRawProperties();
    } else {
      if (visualView) visualView.style.display = 'flex';
      if (rawView) rawView.style.display = 'none';
      if (catBar) catBar.style.display = 'flex';

      if (btnVisual) {
        btnVisual.className = 'btn btn-sm btn-primary';
      }
      if (btnRaw) {
        btnRaw.className = 'btn btn-sm btn-outline';
      }
      this.setPropertiesCategory(this.currentCategory || 'server');
    }
  },

  setPropertiesCategory(cat) {
    this.currentCategory = cat;
    document.querySelectorAll('.prop-cat-btn').forEach(btn => {
      btn.classList.toggle('active', btn.getAttribute('data-cat') === cat);
    });

    const cards = document.querySelectorAll('.setting-category-card');
    cards.forEach(card => {
      const cardCat = card.getAttribute('data-category');
      if (cat === 'all' || cardCat === cat) {
        card.style.display = 'block';
      } else {
        card.style.display = 'none';
      }
    });
  },

  filterProperties(query) {
    this.searchQuery = (query || '').trim().toLowerCase();
    const items = document.querySelectorAll('.setting-prop-item');
    const cards = document.querySelectorAll('.setting-category-card');

    if (!this.searchQuery) {
      items.forEach(el => el.style.display = '');
      this.setPropertiesCategory(this.currentCategory);
      return;
    }

    // When searching, temporarily show all category cards and filter items inside
    cards.forEach(card => card.style.display = 'block');

    cards.forEach(card => {
      let visibleInCard = 0;
      const cardItems = card.querySelectorAll('.setting-prop-item');
      cardItems.forEach(item => {
        const key = (item.getAttribute('data-key') || '').toLowerCase();
        const text = item.textContent.toLowerCase();
        if (key.includes(this.searchQuery) || text.includes(this.searchQuery)) {
          item.style.display = '';
          visibleInCard++;
        } else {
          item.style.display = 'none';
        }
      });
      card.style.display = visibleInCard > 0 ? 'block' : 'none';
    });
  },

  collectVisualForm() {
    const payload = {};
    const inputs = document.querySelectorAll('.prop-input');
    inputs.forEach(input => {
      const key = input.getAttribute('data-key');
      if (!key) return;

      if (input.type === 'checkbox') {
        payload[key] = input.checked;
      } else if (input.type === 'number') {
        const numVal = parseFloat(input.value);
        payload[key] = isNaN(numVal) ? 0 : numVal;
      } else {
        payload[key] = input.value.trim();
      }
    });
    return payload;
  },

  async saveProperties() {
    const btn = document.getElementById('btn-save-settings');
    const textEl = document.getElementById('settings-save-btn-text');

    if (btn) btn.disabled = true;
    if (textEl) textEl.textContent = 'Guardando...';

    const iniUpdates = this.collectVisualForm();

    try {
      const res = await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ini_settings: iniUpdates })
      });
      const data = await res.json();
      if (res.ok && data.success) {
        this.setDirty(false);

        // Actualizar banner superior en vivo para confirmación inmediata
        const topName = document.getElementById('top-server-name');
        if (topName && iniUpdates.ServerName) {
          topName.textContent = iniUpdates.ServerName;
        }
        const topMotd = document.getElementById('top-server-motd');
        if (topMotd && iniUpdates.ServerDescription !== undefined) {
          topMotd.textContent = iniUpdates.ServerDescription || 'Palworld Dedicated Server';
        }
        const topCrossplay = document.getElementById('top-server-crossplay');
        if (topCrossplay && iniUpdates.CrossplayPlatforms) {
          const cpStr = String(iniUpdates.CrossplayPlatforms).toLowerCase();
          const isOn = cpStr.includes('xbox') || cpStr.includes('ps5') || cpStr.includes('mac');
          topCrossplay.textContent = isOn ? 'Habilitado' : 'Desactivado';
          topCrossplay.style.color = isOn ? '#3fb950' : '#8b949e';
        }
        const topVersion = document.getElementById('top-server-version');
        if (topVersion && iniUpdates.PublicPort) {
          topVersion.textContent = `${iniUpdates.PublicPort} UDP`;
        }

        await this.loadRawProperties();

        // Si el servidor está activo, mostrar el cuadro de aviso para que el usuario sepa que debe reiniciar
        const banner = document.getElementById('settings-status-banner');
        if (this.serverStatus && this.serverStatus.status === 'RUNNING') {
          if (banner) {
            banner.style.display = 'block';
            banner.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
          }
          App.showToast('Configuración guardada en PalWorldSettings.ini. Reinicia el servidor para aplicar los cambios.', 'warning');
        } else {
          if (banner) banner.style.display = 'none';
          App.showToast('Configuración guardada en PalWorldSettings.ini. Se aplicará al iniciar el servidor.', 'success');
        }
      } else {
        App.showToast(data.message || 'Error al guardar la configuración.', 'danger');
      }
    } catch (e) {
      console.error('Error saving settings:', e);
      App.showToast('Error de red al conectar con el servidor.', 'danger');
    } finally {
      if (btn) btn.disabled = false;
      if (textEl) textEl.textContent = 'Guardar Configuración';
    }
  },

  async loadRawProperties() {
    const editor = document.getElementById('raw-props-editor');
    if (!editor) return;

    try {
      const res = await fetch('/api/settings/raw');
      if (res.ok) {
        const text = await res.text();
        editor.value = text;
      }
    } catch (e) {
      console.warn("Could not load raw PalWorldSettings.ini:", e);
    }
  },

  async saveRawProperties() {
    const editor = document.getElementById('raw-props-editor');
    const btn = document.getElementById('btn-save-raw-props');
    if (!editor) return;

    if (btn) {
      btn.disabled = true;
      btn.textContent = 'Guardando INI...';
    }

    try {
      const res = await fetch('/api/settings/raw', {
        method: 'POST',
        headers: { 'Content-Type': 'text/plain; charset=utf-8' },
        body: editor.value
      });
      const data = await res.json();
      if (res.ok && data.success) {
        this.setDirty(false);
        await this.fetchSettings();

        const banner = document.getElementById('settings-status-banner');
        if (this.serverStatus && this.serverStatus.status === 'RUNNING') {
          if (banner) {
            banner.style.display = 'block';
            banner.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
          }
          App.showToast('Archivo PalWorldSettings.ini guardado en disco. Reinicia el servidor para aplicar.', 'warning');
        } else {
          if (banner) banner.style.display = 'none';
          App.showToast('Archivo PalWorldSettings.ini actualizado con éxito. Se aplicará al iniciar el servidor.', 'success');
        }
      } else {
        App.showToast(data.message || 'Error al guardar archivo INI.', 'danger');
      }
    } catch (e) {
      App.showToast('Error al comunicar con el servidor.', 'danger');
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = 'Guardar Archivo INI';
      }
    }
  },

  async restartServer() {
    try {
      App.showToast('Reiniciando servidor de Palworld...', 'info');
      const res = await fetch('/api/server/restart', { method: 'POST' });
      const data = await res.json();
      if (res.ok && data.status !== 'error') {
        App.showToast('Servidor reiniciado con éxito. Los nuevos ajustes se están cargando.', 'success');
        const banner = document.getElementById('settings-status-banner');
        if (banner) banner.style.display = 'none';
        await this.fetchServerStatus();
      } else {
        App.showToast(data.message || 'Error al solicitar el reinicio.', 'danger');
      }
    } catch (e) {
      App.showToast('Error de conexión al reiniciar el servidor.', 'danger');
    }
  },

  async resetToDefaults() {
    const ok = await App.confirm({
      title: 'Restablecer Configuración a Valores por Defecto',
      message: '¿Estás seguro de que deseas restablecer todos los parámetros de PalWorldSettings.ini a sus valores originales recomendados?\n\nLas contraseñas y puertos personalizados se mantendrán.',
      confirmText: 'Restablecer Valores',
      danger: true
    });
    if (!ok) return;

    try {
      const res = await fetch('/api/settings/reset', { method: 'POST' });
      if (res.ok) {
        App.showToast('Configuración restablecida a valores por defecto.', 'success');
        await this.fetchSettings();
        await this.loadRawProperties();
      }
    } catch (e) {
      App.showToast('Error al restablecer valores.', 'danger');
    }
  }
};
