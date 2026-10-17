// Dockraft Players Management Controller
const Players = {
  playersList: [],
  bannedList: [],
  filterText: '',
  pollTimer: null,
  pendingAction: null, // { type: 'kick'|'ban', player: string }
  loaded: false,

  tr(key, fallback) {
    return (typeof I18n !== 'undefined' && I18n.t) ? I18n.t(key, fallback) : fallback;
  },

  trf(key, args, fallback) {
    if (typeof I18n !== 'undefined' && I18n.fmt) return I18n.fmt(key, args || [], fallback);
    let text = (fallback !== undefined ? fallback : key);
    (args || []).forEach((value, i) => {
      text = String(text).split(`{${i}}`).join(value);
    });
    return text;
  },

  init() {
    if (this._initialized) return;
    this._initialized = true;
    // Localize the online KPI badge before the first fetch (uses current cached count)
    const badge = document.getElementById('players-online-badge');
    if (badge) {
      const onlineCount = this.playersList.filter(p => p.is_online).length;
      badge.textContent = this.trf('t_player_online_badge', [onlineCount], `${onlineCount} en línea`);
    }

    // Re-render the current tables (no toast, no network) when the language changes
    window.addEventListener('dockraft:language_changed', () => {
      const isActive = (typeof App === 'undefined' || App.activeTab === 'players');
      if (isActive && this.loaded && document.getElementById('players-table-body')) {
        this.render();
      }
    });
  },

  async loadPlayers() {
    await this.fetchPlayers();
    this.startPolling();
  },

  startPolling() {
    this.stopPolling();
    this.pollTimer = setInterval(() => {
      if (typeof App !== 'undefined' && App.activeTab === 'players') {
        this.fetchPlayers(true);
      }
    }, 8000);
  },

  stopPolling() {
    if (this.pollTimer) {
      clearInterval(this.pollTimer);
      this.pollTimer = null;
    }
  },

  async fetchPlayers(isBackground = false) {
    try {
      const res = await fetch('/api/players/list');
      if (!res.ok) return;
      const data = await res.json();
      this.playersList = data.players || [];
      this.bannedList = data.banned || [];
      this.loaded = true;

      this.render();
    } catch (e) {
      if (!isBackground) {
        console.error("Players fetch error:", e);
      }
    }
  },

  filterPlayers() {
    const input = document.getElementById('players-search-input');
    this.filterText = (input ? input.value : '').trim().toLowerCase();
    this.renderLeftTable();
  },

  render() {
    // Update KPI badges
    const onlineCount = this.playersList.filter(p => p.is_online).length;
    const onlineBadge = document.getElementById('players-online-badge');
    if (onlineBadge) {
      onlineBadge.textContent = this.trf('t_player_online_badge', [onlineCount], `${onlineCount} en línea`);
      onlineBadge.style.background = onlineCount > 0 ? 'rgba(46, 160, 67, 0.15)' : 'rgba(56, 189, 248, 0.15)';
      onlineBadge.style.color = onlineCount > 0 ? '#3fb950' : '#38bdf8';
    }

    const bannedBadge = document.getElementById('players-banned-count-badge');
    if (bannedBadge) {
      bannedBadge.textContent = this.bannedList.length;
    }

    // Update Kick All button state
    const kickAllBtn = document.getElementById('btn-kick-all');
    if (kickAllBtn) {
      if (onlineCount === 0) {
        kickAllBtn.style.opacity = '0.5';
        kickAllBtn.title = this.tr('t_player_kickall_none_title', 'No hay jugadores conectados actualmente');
      } else {
        kickAllBtn.style.opacity = '1';
        kickAllBtn.title = this.trf('t_player_kickall_count_title', [onlineCount], `Expulsar a los ${onlineCount} jugador(es) en línea`);
      }
    }

    this.renderLeftTable();
    this.renderRightTable();
  },

  renderLeftTable() {
    const tbody = document.getElementById('players-table-body');
    const emptyState = document.getElementById('players-empty-state');
    if (!tbody) return;

    tbody.innerHTML = '';

    let filtered = this.playersList;
    if (this.filterText) {
      filtered = filtered.filter(p => p.name.toLowerCase().includes(this.filterText));
    }

    if (filtered.length === 0) {
      if (emptyState) emptyState.style.display = 'block';
      return;
    }
    if (emptyState) emptyState.style.display = 'none';

    filtered.forEach(p => {
      const tr = document.createElement('tr');
      tr.style.borderBottom = '1px solid #21262d';

      // Player Cell
      const opBadge = p.is_op ? `<span class="badge" style="background: rgba(234, 179, 8, 0.15); border: 1px solid #eab308; color: #fbbf24; font-size: 0.65rem; padding: 1px 4px;">OP</span>` : '';
      const safeName = this.escapeHtml(p.name);

      // Status Cell
      const onlineLabel = this.tr('t_player_online', 'En línea');
      const offlineLabel = this.tr('t_player_offline', 'Desconectado');
      let statusHtml = '';
      if (p.is_online) {
        statusHtml = `
          <div style="display: inline-flex; align-items: center; gap: 5px; color: #3fb950; font-weight: 600; font-size: 0.76rem;">
            <span class="status-dot" style="background-color: #34d399; width: 6px; height: 6px; box-shadow: 0 0 5px #34d399; flex-shrink: 0;"></span>
            <span>${onlineLabel}</span>
          </div>
        `;
      } else {
        let connText = p.last_connection;
        const isNever = !connText || connText === 'never' || connText === '--' || connText.toLowerCase() === 'nunca' || connText.toLowerCase() === 'never';
        if (isNever) {
          connText = this.tr('t_player_never', 'Nunca');
        }
        statusHtml = `
          <div style="display: flex; flex-direction: column; gap: 1px; min-width: 0;">
            <div style="display: inline-flex; align-items: center; gap: 5px; color: #8b949e; font-weight: 500; font-size: 0.74rem;">
              <span class="status-dot" style="background-color: #6e7681; width: 6px; height: 6px; flex-shrink: 0;"></span>
              <span>${offlineLabel}</span>
            </div>
            <span style="font-size: 0.66rem; color: var(--text-dim); max-width: 100px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${this.escapeHtml(connText)}">${this.escapeHtml(connText)}</span>
          </div>
        `;
      }

      // Action Buttons Cell
      const kickDisabled = !p.is_online ? 'opacity: 0.45; cursor: not-allowed;' : '';
      const kickAttr = !p.is_online ? 'disabled' : 'data-action="kick"';

      const banBtnTitle = this.tr('t_player_btn_ban_title', 'Banear jugador');
      const banBtnLabel = this.tr('t_player_btn_ban', 'Ban');
      const kickBtnTitle = this.tr('t_player_btn_kick_title', 'Expulsar jugador');
      const kickBtnLabel = this.tr('t_player_btn_kick', 'Kick');
      const deopTitle = this.tr('t_player_btn_deop_title', 'Revocar permisos de operador');
      const opTitle = this.tr('t_player_btn_op_title', 'Hacer Operador del servidor');

      const opBtn = p.is_op
        ? `<button class="btn btn-outline" style="padding: 2px 6px; font-size: 0.72rem; min-height: 24px; line-height: 1; border-color: #eab308; color: #fbbf24; border-radius: 4px;" data-action="deop" title="${deopTitle}">De-OP</button>`
        : `<button class="btn btn-warning" style="padding: 2px 6px; font-size: 0.72rem; min-height: 24px; line-height: 1; background-color: #eab308; border-color: #ca8a04; color: #000; font-weight: 600; border-radius: 4px;" data-action="op" title="${opTitle}">OP</button>`;

      const levelBadge = p.level ? `<span class="badge" style="background: rgba(56, 189, 248, 0.15); border: 1px solid rgba(56, 189, 248, 0.3); color: #38bdf8; font-size: 0.65rem; padding: 1px 4px;">Nv. ${p.level}</span>` : '';

      tr.innerHTML = `
        <td style="padding: 6px 8px; overflow: hidden;">
          <div style="display: flex; align-items: center; gap: 7px; min-width: 0;">
            <div style="width: 24px; height: 24px; border-radius: 5px; background: rgba(56, 189, 248, 0.1); display: flex; align-items: center; justify-content: center; overflow: hidden; flex-shrink: 0; border: 1px solid rgba(56, 189, 248, 0.3);">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#38bdf8" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
            </div>
            <div style="display: flex; flex-direction: column; min-width: 0; overflow: hidden;">
              <div style="display: flex; align-items: center; gap: 4px; overflow: hidden;">
                <span style="font-family: var(--font-mono); font-weight: 600; color: #c9d1d9; font-size: 0.82rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${safeName}</span>
                ${levelBadge}
                ${opBadge}
              </div>
              ${p.steam_id && p.steam_id !== '-' ? `<span style="font-size: 0.68rem; color: var(--text-dim); font-family: var(--font-mono); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 130px;" title="${this.escapeHtml(p.steam_id)}">${this.escapeHtml(p.steam_id)}</span>` : ''}
            </div>
          </div>
        </td>
        <td style="padding: 6px 6px; overflow: hidden;">
          ${statusHtml}
        </td>
        <td style="padding: 6px 8px; text-align: right; overflow: hidden;">
          <div style="display: inline-flex; gap: 3px; align-items: center; justify-content: flex-end;">
            <button class="btn btn-danger" style="padding: 2px 7px; font-size: 0.72rem; min-height: 24px; line-height: 1; border-radius: 4px;" data-action="ban" title="${banBtnTitle}">${banBtnLabel}</button>
            <button class="btn btn-outline" style="padding: 2px 7px; font-size: 0.72rem; min-height: 24px; line-height: 1; border-color: #da3633; color: #f85149; border-radius: 4px; ${kickDisabled}" ${kickAttr} title="${kickBtnTitle}">${kickBtnLabel}</button>
            ${opBtn}
          </div>
        </td>
      `;
      tr.querySelectorAll('[data-action]').forEach(btn => {
        const act = btn.getAttribute('data-action');
        const playerName = p.name;
        btn.addEventListener('click', (e) => {
          e.preventDefault();
          e.stopPropagation();
          if (act === 'ban') this.promptBan(playerName);
          else if (act === 'kick') this.promptKick(playerName);
          else if (act === 'op') this.setOp(playerName, true);
          else if (act === 'deop') this.setOp(playerName, false);
        });
      });
      tbody.appendChild(tr);
    });
  },

  renderRightTable() {
    const tbody = document.getElementById('banned-table-body');
    const emptyState = document.getElementById('banned-empty-state');
    if (!tbody) return;

    tbody.innerHTML = '';

    if (this.bannedList.length === 0) {
      if (emptyState) emptyState.style.display = 'block';
      return;
    }
    if (emptyState) emptyState.style.display = 'none';

    this.bannedList.forEach(b => {
      const tr = document.createElement('tr');
      tr.style.borderBottom = '1px solid #21262d';
      const safeName = this.escapeHtml(b.name);
      const defaultReason = this.tr('t_player_reason_default', 'Baneado por operador');
      const pardonTitle = this.tr('t_player_btn_pardon_title', 'Desbanear jugador');
      const pardonLabel = this.tr('t_player_btn_pardon', 'Perdonar');

      tr.innerHTML = `
        <td style="padding: 6px 8px; overflow: hidden;">
          <div style="display: flex; align-items: center; gap: 7px; min-width: 0;">
            <div style="width: 24px; height: 24px; border-radius: 5px; background: rgba(218, 54, 51, 0.15); display: flex; align-items: center; justify-content: center; overflow: hidden; flex-shrink: 0; border: 1px solid #da3633;">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#f85149" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="4.93" y1="4.93" x2="19.07" y2="19.07"/></svg>
            </div>
            <span style="font-family: var(--font-mono); font-weight: 600; color: #f85149; font-size: 0.82rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${safeName}</span>
          </div>
        </td>
        <td style="padding: 6px 6px; font-size: 0.74rem; color: var(--text-dim); overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${this.escapeHtml(b.reason || defaultReason)}">
          ${this.escapeHtml(b.reason || defaultReason)}
        </td>
        <td style="padding: 6px 8px; text-align: right; overflow: hidden;">
          <button class="btn btn-outline" style="padding: 2px 8px; font-size: 0.72rem; min-height: 24px; line-height: 1; border-color: #2ea043; color: #3fb950; border-radius: 4px; display: inline-flex; align-items: center; gap: 3px;" data-action="pardon" title="${pardonTitle}">
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6L9 17l-5-5"/></svg>
            ${pardonLabel}
          </button>
        </td>
      `;
      tr.querySelector('[data-action="pardon"]')?.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        this.pardon(b.name);
      });
      tbody.appendChild(tr);
    });
  },

  renderActionChips(type) {
    const container = document.getElementById('modal-player-action-chips');
    if (!container) return;
    container.innerHTML = '';

    let chips = [];
    if (type === 'ban') {
      chips = [
        this.tr('t_player_chip_ban_hacks', 'Uso de Hacks / Trampas'),
        this.tr('t_player_chip_ban_grief', 'Griefing / Destrucción'),
        this.tr('t_player_chip_ban_toxic', 'Comportamiento Tóxico'),
        this.tr('t_player_chip_ban_spam', 'Spam o Publicidad'),
        this.tr('t_player_chip_ban_rules', 'Incumplimiento de Reglas')
      ];
    } else if (type === 'kick') {
      chips = [
        this.tr('t_player_chip_kick_afk', 'Inactividad prolongada (AFK)'),
        this.tr('t_player_chip_kick_warn', 'Advertencia del Administrador'),
        this.tr('t_player_chip_kick_lag', 'Lag / Ping excesivo'),
        this.tr('t_player_chip_kick_chat', 'Spam en el chat'),
        this.tr('t_player_chip_kick_maint', 'Mantenimiento temporal')
      ];
    } else if (type === 'kick_all') {
      chips = [
        this.tr('t_player_chip_all_maint', 'Mantenimiento programado del servidor'),
        this.tr('t_player_chip_all_restart', 'Reinicio del servidor'),
        this.tr('t_player_chip_all_backup', 'Copia de seguridad en progreso'),
        this.tr('t_player_chip_all_update', 'Actualización del sistema')
      ];
    }

    chips.forEach(text => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'btn btn-outline';
      btn.style.cssText = 'padding: 3px 8px; font-size: 0.74rem; border-color: #30363d; color: #8b949e; background: rgba(22, 27, 34, 0.6); cursor: pointer;';
      btn.textContent = text;
      btn.onclick = () => this.selectReasonChip(text);
      container.appendChild(btn);
    });
  },

  selectReasonChip(text) {
    const input = document.getElementById('modal-player-action-reason');
    if (input) {
      input.value = text;
      input.focus();
    }
  },

  promptKick(playerName) {
    this.pendingAction = { type: 'kick', player: playerName };
    const modal = document.getElementById('modal-player-action');
    const title = document.getElementById('modal-player-action-title');
    const avatarBox = document.getElementById('modal-player-avatar-box');
    const nameEl = document.getElementById('modal-player-target-name');
    const subEl = document.getElementById('modal-player-target-subtitle');
    const callout = document.getElementById('modal-player-action-callout');
    const calloutIcon = document.getElementById('modal-player-callout-icon');
    const desc = document.getElementById('modal-player-action-desc');
    const reasonInput = document.getElementById('modal-player-action-reason');
    const reasonLabel = document.getElementById('modal-player-action-reason-label');
    const confirmBtn = document.getElementById('btn-modal-confirm-action');

    const safeName = this.escapeHtml(playerName);

    if (title) {
      title.style.color = '#f59e0b';
      title.innerHTML = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"/><polyline points="10 17 15 12 10 7"/><line x1="15" y1="12" x2="3" y2="12"/></svg> ${this.trf('t_player_kick_title', [safeName], `Expulsar a ${safeName}`)}`;
    }

    if (avatarBox) {
      avatarBox.innerHTML = `
        <div style="width: 32px; height: 32px; border-radius: 6px; background: rgba(245, 158, 11, 0.15); display: flex; align-items: center; justify-content: center; border: 1px solid #f59e0b;">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#f59e0b" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"/><polyline points="10 17 15 12 10 7"/><line x1="15" y1="12" x2="3" y2="12"/></svg>
        </div>
      `;
    }

    if (nameEl) nameEl.textContent = playerName;
    if (subEl) subEl.textContent = this.tr('t_player_kick_subtitle', 'Jugador conectado a la partida');

    if (callout) {
      callout.style.background = 'rgba(245, 158, 11, 0.1)';
      callout.style.borderColor = 'rgba(245, 158, 11, 0.3)';
    }
    if (calloutIcon) {
      calloutIcon.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#f59e0b" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>`;
    }
    if (desc) {
      desc.textContent = this.tr('t_player_kick_desc', 'El jugador será desconectado inmediatamente pero podrá volver a conectarse. Palworld mostrará este motivo directamente en su pantalla de desconexión.');
    }

    if (reasonLabel) reasonLabel.textContent = this.tr('t_player_kick_reason_label', 'Motivo de Expulsión (Visible en Palworld):');
    if (reasonInput) {
      reasonInput.value = '';
      reasonInput.placeholder = this.tr('t_player_kick_reason_placeholder', 'ej: Inactividad prolongada o advertencia del admin');
    }

    if (confirmBtn) {
      confirmBtn.textContent = this.tr('t_player_kick_confirm_btn', 'Expulsar (Kick)');
      confirmBtn.className = 'btn btn-warning';
      confirmBtn.style.background = '#d97706';
      confirmBtn.style.borderColor = '#b45309';
      confirmBtn.style.color = '#fff';
    }

    this.renderActionChips('kick');
    if (modal) modal.classList.add('open');
    if (reasonInput) setTimeout(() => reasonInput.focus(), 60);
  },

  promptBan(playerName) {
    this.pendingAction = { type: 'ban', player: playerName };
    const modal = document.getElementById('modal-player-action');
    const title = document.getElementById('modal-player-action-title');
    const avatarBox = document.getElementById('modal-player-avatar-box');
    const nameEl = document.getElementById('modal-player-target-name');
    const subEl = document.getElementById('modal-player-target-subtitle');
    const callout = document.getElementById('modal-player-action-callout');
    const calloutIcon = document.getElementById('modal-player-callout-icon');
    const desc = document.getElementById('modal-player-action-desc');
    const reasonInput = document.getElementById('modal-player-action-reason');
    const reasonLabel = document.getElementById('modal-player-action-reason-label');
    const confirmBtn = document.getElementById('btn-modal-confirm-action');

    const safeName = this.escapeHtml(playerName);

    if (title) {
      title.style.color = '#f85149';
      title.innerHTML = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="4.93" y1="4.93" x2="19.07" y2="19.07"/></svg> ${this.trf('t_player_ban_title', [safeName], `Banear a ${safeName}`)}`;
    }

    if (avatarBox) {
      avatarBox.innerHTML = `
        <div style="width: 32px; height: 32px; border-radius: 6px; background: rgba(218, 54, 51, 0.15); display: flex; align-items: center; justify-content: center; border: 1px solid #da3633;">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#f85149" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="4.93" y1="4.93" x2="19.07" y2="19.07"/></svg>
        </div>
      `;
    }

    if (nameEl) nameEl.textContent = playerName;
    if (subEl) subEl.textContent = this.tr('t_player_ban_subtitle', 'Bloqueo permanente en banned-players.json');

    if (callout) {
      callout.style.background = 'rgba(218, 54, 51, 0.1)';
      callout.style.borderColor = 'rgba(218, 54, 51, 0.3)';
    }
    if (calloutIcon) {
      calloutIcon.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#f85149" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="4.93" y1="4.93" x2="19.07" y2="19.07"/></svg>`;
    }
    if (desc) {
      desc.textContent = this.tr('t_player_ban_desc', 'El jugador será desconectado inmediatamente y bloqueado permanentemente. Palworld mostrará este motivo cada vez que intente conectarse al servidor.');
    }

    if (reasonLabel) reasonLabel.textContent = this.tr('t_player_ban_reason_label', 'Motivo del Baneo (Visible en Palworld):');
    if (reasonInput) {
      reasonInput.value = '';
      reasonInput.placeholder = this.tr('t_player_ban_reason_placeholder', 'ej: Infracción de normas o trampas');
    }

    if (confirmBtn) {
      confirmBtn.textContent = this.tr('t_player_ban_confirm_btn', 'Banear Jugador');
      confirmBtn.className = 'btn btn-danger';
      confirmBtn.style.background = '#da3633';
      confirmBtn.style.borderColor = '#b62324';
      confirmBtn.style.color = '#fff';
    }

    this.renderActionChips('ban');
    if (modal) modal.classList.add('open');
    if (reasonInput) setTimeout(() => reasonInput.focus(), 60);
  },

  promptKickAll() {
    const onlinePlayers = this.playersList.filter(p => p.is_online);
    const onlineCount = onlinePlayers.length;

    this.pendingAction = { type: 'kick_all' };
    const modal = document.getElementById('modal-player-action');
    const title = document.getElementById('modal-player-action-title');
    const avatarBox = document.getElementById('modal-player-avatar-box');
    const nameEl = document.getElementById('modal-player-target-name');
    const subEl = document.getElementById('modal-player-target-subtitle');
    const callout = document.getElementById('modal-player-action-callout');
    const calloutIcon = document.getElementById('modal-player-callout-icon');
    const desc = document.getElementById('modal-player-action-desc');
    const reasonInput = document.getElementById('modal-player-action-reason');
    const reasonLabel = document.getElementById('modal-player-action-reason-label');
    const confirmBtn = document.getElementById('btn-modal-confirm-action');

    if (title) {
      title.style.color = '#f85149';
      title.innerHTML = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/><line x1="18" y1="8" x2="23" y2="13"/><line x1="23" y1="8" x2="18" y2="13"/></svg> ${this.tr('t_player_kickall_modal_title', 'Expulsar a Todos los Jugadores')}`;
    }

    if (avatarBox) {
      avatarBox.innerHTML = `
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#f85149" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>
      `;
    }

    if (nameEl) nameEl.textContent = this.tr('t_player_kickall_target', 'Todos los jugadores en línea (@a)');
    if (subEl) subEl.textContent = this.trf('t_player_kickall_subtitle', [onlineCount], `${onlineCount} jugador(es) conectado(s) actualmente`);

    if (callout) {
      callout.style.background = 'rgba(234, 88, 12, 0.12)';
      callout.style.borderColor = 'rgba(234, 88, 12, 0.35)';
    }
    if (calloutIcon) {
      calloutIcon.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#f97316" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>`;
    }
    if (desc) {
      desc.textContent = this.tr('t_player_kickall_desc', 'Se desconectará de inmediato a todos los jugadores que están dentro de la partida. Todos verán este motivo en su pantalla de Palworld.');
    }

    if (reasonLabel) reasonLabel.textContent = this.tr('t_player_kickall_reason_label', 'Motivo de Expulsión Masiva (Visible para todos):');
    if (reasonInput) {
      reasonInput.value = this.tr('t_player_kickall_default_reason', 'Mantenimiento del servidor');
      reasonInput.placeholder = this.tr('t_player_kickall_reason_placeholder', 'ej: Mantenimiento del servidor o reinicio');
    }

    if (confirmBtn) {
      confirmBtn.textContent = this.tr('t_player_kickall_confirm_btn', 'Expulsar a Todos');
      confirmBtn.className = 'btn btn-danger';
      confirmBtn.style.background = '#da3633';
      confirmBtn.style.borderColor = '#b62324';
      confirmBtn.style.color = '#fff';
    }

    this.renderActionChips('kick_all');
    if (modal) modal.classList.add('open');
    if (reasonInput) setTimeout(() => {
      reasonInput.focus();
      reasonInput.select();
    }, 60);
  },

  closeActionModal() {
    const modal = document.getElementById('modal-player-action');
    if (modal) modal.classList.remove('open');
    this.pendingAction = null;
  },

  async executePendingAction() {
    if (!this.pendingAction) return;
    const { type, player } = this.pendingAction;
    const reasonInput = document.getElementById('modal-player-action-reason');
    const reason = reasonInput ? reasonInput.value.trim() : '';

    this.closeActionModal();

    if (type === 'kick') {
      await this.kick(player, reason);
    } else if (type === 'ban') {
      await this.ban(player, reason);
    } else if (type === 'kick_all') {
      await this.kickAll(reason);
    }
  },

  async kickAll(reason = '') {
    try {
      const res = await fetch('/api/players/kick-all', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason })
      });
      const data = await res.json();
      if (res.ok) {
        if (typeof App !== 'undefined' && App.showToast) App.showToast(data.message, 'success');
        await this.fetchPlayers();
      } else {
        if (typeof App !== 'undefined' && App.showToast) App.showToast(data.message || this.tr('t_player_err_kickall', 'Error al expulsar a todos'), 'danger');
      }
    } catch (e) {
      if (typeof App !== 'undefined' && App.showToast) App.showToast(e.message, 'danger');
    }
  },

  async kick(player, reason = '') {
    try {
      const res = await fetch('/api/players/kick', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ player, reason })
      });
      const data = await res.json();
      if (res.ok) {
        if (typeof App !== 'undefined' && App.showToast) App.showToast(data.message, 'success');
        await this.fetchPlayers();
      } else {
        if (typeof App !== 'undefined' && App.showToast) App.showToast(data.message || this.tr('t_player_err_kick', 'Error al expulsar'), 'danger');
      }
    } catch (e) {
      if (typeof App !== 'undefined' && App.showToast) App.showToast(e.message, 'danger');
    }
  },

  async ban(player, reason = '') {
    try {
      const res = await fetch('/api/players/ban', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ player, reason })
      });
      const data = await res.json();
      if (res.ok) {
        if (typeof App !== 'undefined' && App.showToast) App.showToast(data.message, 'success');
        await this.fetchPlayers();
      } else {
        if (typeof App !== 'undefined' && App.showToast) App.showToast(data.message || this.tr('t_player_err_ban', 'Error al banear'), 'danger');
      }
    } catch (e) {
      if (typeof App !== 'undefined' && App.showToast) App.showToast(e.message, 'danger');
    }
  },

  async pardon(player) {
    const ok = await App.confirm({
      title: this.tr('t_player_pardon_confirm_title', 'Desbanear Jugador'),
      message: this.trf('t_player_pardon_confirm_msg', [player], `¿Deseas desbanear y permitir el acceso de nuevo a ${player}?`),
      confirmText: this.tr('t_player_pardon_confirm_btn', 'Desbanear'),
      type: 'info'
    });
    if (!ok) return;
    try {
      const res = await fetch('/api/players/pardon', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ player })
      });
      const data = await res.json();
      if (res.ok) {
        if (typeof App !== 'undefined' && App.showToast) App.showToast(data.message, 'success');
        await this.fetchPlayers();
      } else {
        if (typeof App !== 'undefined' && App.showToast) App.showToast(data.message || this.tr('t_player_err_pardon', 'Error al desbanear'), 'danger');
      }
    } catch (e) {
      if (typeof App !== 'undefined' && App.showToast) App.showToast(e.message, 'danger');
    }
  },

  async setOp(player, isOp) {
    const endpoint = isOp ? '/api/players/op' : '/api/players/deop';
    const ok = await App.confirm({
      title: this.tr(
        isOp ? 't_player_op_confirm_title' : 't_player_deop_confirm_title',
        isOp ? 'Dar Operador (OP)' : 'Quitar Operador (DEOP)'
      ),
      message: this.trf(
        isOp ? 't_player_op_confirm_msg' : 't_player_deop_confirm_msg',
        [player],
        isOp ? `¿Confirmas dar permisos de Operador (OP) a ${player}?` : `¿Confirmas quitar permisos de Operador (DEOP) a ${player}?`
      ),
      confirmText: this.tr(
        isOp ? 't_player_op_confirm_btn' : 't_player_deop_confirm_btn',
        isOp ? 'Hacer OP' : 'Quitar OP'
      ),
      warning: !isOp
    });
    if (!ok) return;

    try {
      const res = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ player })
      });
      const data = await res.json();
      if (res.ok) {
        if (typeof App !== 'undefined' && App.showToast) App.showToast(data.message, 'success');
        await this.fetchPlayers();
      } else {
        if (typeof App !== 'undefined' && App.showToast) App.showToast(data.message || this.tr('t_player_err_op', 'Error al cambiar permisos de operador'), 'danger');
      }
    } catch (e) {
      if (typeof App !== 'undefined' && App.showToast) App.showToast(e.message, 'danger');
    }
  },

  openAddModal() {
    const modal = document.getElementById('modal-add-player');
    const input = document.getElementById('add-player-name');
    if (input) input.value = '';
    if (modal) modal.classList.add('open');
    if (input) setTimeout(() => input.focus(), 50);
  },

  closeAddModal() {
    const modal = document.getElementById('modal-add-player');
    if (modal) modal.classList.remove('open');
  },

  async submitAddPlayer() {
    const input = document.getElementById('add-player-name');
    const player = input ? input.value.trim() : '';
    if (!player) return;

    try {
      const res = await fetch('/api/players/add', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ player })
      });
      const data = await res.json();
      if (res.ok) {
        this.closeAddModal();
        if (typeof App !== 'undefined' && App.showToast) App.showToast(data.message, 'success');
        await this.fetchPlayers();
      } else {
        if (typeof App !== 'undefined' && App.showToast) App.showToast(data.message, 'danger');
      }
    } catch (e) {
      if (typeof App !== 'undefined' && App.showToast) App.showToast(e.message, 'danger');
    }
  },

  escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }
};

// Initialize on DOM Ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => Players.init());
} else {
  Players.init();
}
