# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-10-17

### Added
- **Palworld Dedicated Server Engine**:
  - Full native 64-bit Linux server support managed directly via official SteamCMD.
  - Automated initial download, installation, and file verification.
  - Multi-threaded performance flags (`-useperfthreads`, `-NoAsyncLoadingThread`, `-UseMultithreadForDS`).
  - Support for public community listing (`-publiclobby`).

- **Interactive Web Management Panel**:
  - Modern dark-themed dashboard built with pure CSS and Vanilla JavaScript.
  - Interactive server lifecycle controls: Start, Graceful Stop (with pre-shutdown save), Force Kill, Restart, and Instant Save (`SaveWorld`).
  - In-game global broadcast announcements (`Broadcast`) directly from the top bar.
  - Real-time terminal with live WebSocket log streaming and interactive command input.

- **Intelligent Diagnostics & Health Monitoring**:
  - Automatic error and crash detector analyzing server logs and process state.
  - Live system telemetry: host CPU usage, container RAM with Cgroups v1/v2 compatibility, disk usage, uptime, and server FPS.
  - High-performance canvas chart for real-time CPU, RAM, and tickrate monitoring.

- **Player & Tamer Management**:
  - Real-time player listing powered by REST API (`/v1/api/players`) and RCON (`ShowPlayers`).
  - Details per player: Name, Player UID, Steam ID, Ping, Level, and IP Address.
  - Player moderation: Kick, Ban (with custom reason modal), and Unban.
  - Persistent connection history and audit logs.

- **PalWorldSettings.ini Configuration Suite**:
  - Visual settings editor organized into logical categories (General, Experience & Spawns, Combat Multipliers, Survival & Hunger, World Rules, Network & Security).
  - Raw INI editor with syntax highlighting, live validation, and search filter.
  - Safe persistence to `Pal/Saved/Config/LinuxServer/PalWorldSettings.ini` without requiring container recreation.

- **Selective Backup Engine**:
  - Full and custom scope backups compressed into `.tar.gz` archives.
  - Automated pre-restore safety snapshots and 1-click restore.
  - Direct backup download and automatic retention pruning (`BACKUP_MAX_COUNT`).

- **Automation & Task Scheduler**:
  - Automated periodic backups, scheduled restarts with chat warnings, recurring `SaveWorld`, and version checks.
  - Cron expression scheduler and interval timer support.

- **Multi-Channel Webhook Notifications**:
  - Rich Discord embed notifications for server state changes, backups, and player joins/leaves.
  - Telegram Bot alerts and SMTP Email notifications with clean templates.
  - Integrated notification test buttons per channel.

- **Secure Web File Manager**:
  - Directory browser restricted to container paths with path-traversal protection.
  - Inline text editor for `.ini`, `.json`, `.txt`, and `.sh` files with Ctrl+S shortcut.
  - File upload, download, rename, duplicate, zip, and unzip capabilities.

- **Security & Multi-Language**:
  - Session-based authentication with bcrypt password hashing and brute-force rate limiting.
  - Full bilingual localization (English / Spanish) with dynamic runtime switching.
