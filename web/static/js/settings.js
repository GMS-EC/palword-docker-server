// Palworld Server Settings Script (Visual & Raw PalWorldSettings.ini)
const Settings = {
  properties: {},
  runtimeConfig: {},
  serverStatus: {},
  dirty: false,
  mode: 'visual',
  currentCategory: 'all',
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

    if (statusEl) {
      const isRunning = status === 'RUNNING';
      const isStarting = status === 'STARTING';
      const isStopping = status === 'STOPPING';
      const color = isRunning ? '#3fb950' : (isStarting ? '#d29922' : (isStopping ? '#f85149' : '#8b949e'));
      const text = isRunning ? 'En Línea' : (isStarting ? 'Iniciando...' : (isStopping ? 'Deteniendo...' : 'Apagado'));
      statusEl.innerHTML = `<span class="badge" style="display:inline-flex; align-items:center; background-color: rgba(255,255,255,0.06); border: 1px solid ${color}; color: ${color}; font-size: 0.8rem; padding: 4px 10px;"><span style="display:inline-block; width:7px; height:7px; border-radius:50%; background-color:${color}; margin-right:6px;"></span>${text}</span>`;
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

    // Sincronizar controles interactivos de Crossplay
    this.syncCrossplayToUI(ini.CrossplayPlatforms || '(Steam,Xbox,PS5,Mac)');
  },

  syncCrossplayToUI(rawVal) {
    const str = String(rawVal || '').replace(/[()"]/g, '');
    const platforms = str.split(',').map(s => s.trim().toLowerCase()).filter(Boolean);
    const hasConsole = platforms.includes('xbox') || platforms.includes('ps5') || platforms.includes('mac');
    
    const toggle = document.getElementById('toggle-crossplay-enabled');
    if (toggle) toggle.checked = hasConsole;

    const cbXbox = document.getElementById('crossplay-plat-xbox');
    if (cbXbox) cbXbox.checked = platforms.includes('xbox');

    const cbPs5 = document.getElementById('crossplay-plat-ps5');
    if (cbPs5) cbPs5.checked = platforms.includes('ps5');

    const cbMac = document.getElementById('crossplay-plat-mac');
    if (cbMac) cbMac.checked = platforms.includes('mac');

    const picker = document.getElementById('crossplay-platforms-picker');
    if (picker) picker.style.opacity = hasConsole ? '1' : '0.45';
  },

  onCrossplayToggle(enabled) {
    const cbXbox = document.getElementById('crossplay-plat-xbox');
    const cbPs5 = document.getElementById('crossplay-plat-ps5');
    const cbMac = document.getElementById('crossplay-plat-mac');
    const picker = document.getElementById('crossplay-platforms-picker');

    if (enabled) {
      if (cbXbox) cbXbox.checked = true;
      if (cbPs5) cbPs5.checked = true;
      if (cbMac) cbMac.checked = true;
      if (picker) picker.style.opacity = '1';
    } else {
      if (cbXbox) cbXbox.checked = false;
      if (cbPs5) cbPs5.checked = false;
      if (cbMac) cbMac.checked = false;
      if (picker) picker.style.opacity = '0.45';
    }
    this.syncCrossplayFromUI();
  },

  syncCrossplayFromUI() {
    const cbXbox = document.getElementById('crossplay-plat-xbox')?.checked;
    const cbPs5 = document.getElementById('crossplay-plat-ps5')?.checked;
    const cbMac = document.getElementById('crossplay-plat-mac')?.checked;
    const toggle = document.getElementById('toggle-crossplay-enabled');

    const plats = ['Steam'];
    if (cbXbox) plats.push('Xbox');
    if (cbPs5) plats.push('PS5');
    if (cbMac) plats.push('Mac');

    const hasConsole = plats.length > 1;
    if (toggle) toggle.checked = hasConsole;

    const picker = document.getElementById('crossplay-platforms-picker');
    if (picker) picker.style.opacity = hasConsole ? '1' : '0.45';

    const formatted = `(${plats.join(',')})`;
    const hiddenInput = document.getElementById('prop-CrossplayPlatforms');
    if (hiddenInput) hiddenInput.value = formatted;

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
      if (visualView) visualView.style.display = 'grid';
      if (rawView) rawView.style.display = 'none';
      if (catBar) catBar.style.display = 'flex';

      if (btnVisual) {
        btnVisual.className = 'btn btn-sm btn-primary';
      }
      if (btnRaw) {
        btnRaw.className = 'btn btn-sm btn-outline';
      }
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
        App.showToast('Configuración de Palworld guardada exitosamente.', 'success');
        await this.loadRawProperties();
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
        App.showToast('Archivo PalWorldSettings.ini actualizado con éxito.', 'success');
        await this.fetchSettings();
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
