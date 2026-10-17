import os
import json
import asyncio
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional, List
import httpx

from app.config import settings
from app.core.fs_utils import atomic_write_json

logger = logging.getLogger("palworld.webhooks")

DEFAULT_CONFIG: Dict[str, Any] = {
    "connection": {
        "custom_address_enabled": False,
        "display_address": "",
        "display_port": ""
    },
    "discord": {
        "enabled": False,
        "webhook_url": ""
    },
    "telegram": {
        "enabled": False,
        "bot_token": "",
        "chat_id": ""
    },
    "email": {
        "enabled": False,
        "smtp_host": "",
        "smtp_port": 587,
        "smtp_user": "",
        "smtp_password": "",
        "smtp_use_tls": True,
        "from_email": "",
        "to_emails": ""
    },
    "events": {
        "server_start": True,
        "server_stop": True,
        "server_crash": True,
        "backup_created": True,
        "task_executed": True,
        "player_join": True,
        "player_leave": True
    }
}

class WebhookManager:
    """
    Gestor unificado multicanal de notificaciones para Palworld Server Manager:
    Soporta Discord Webhooks, Telegram Bot y Servidor de Correo SMTP con plantillas
    HTML dark-mode glassmorphic y soporte bilingüe (Español / Inglés).
    """
    def __init__(self):
        self.config_file: Path = settings.data_dir / "webhooks.json"
        self.config: Dict[str, Any] = self.load_config()
        self.client = httpx.AsyncClient(timeout=10.0)

    def load_config(self) -> Dict[str, Any]:
        """Carga la configuración desde webhooks.json o usa valores predeterminados."""
        config = json.loads(json.dumps(DEFAULT_CONFIG))
        # Migración/compatibilidad con runtime_config o .env
        env_discord = settings.runtime_config.get("discord_webhook_url", "") or os.getenv("DISCORD_WEBHOOK_URL", "")
        if env_discord:
            config["discord"]["webhook_url"] = env_discord
            config["discord"]["enabled"] = True

        if self.config_file.exists():
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                    if isinstance(saved, dict):
                        for k, v in saved.items():
                            if k in config and isinstance(v, dict):
                                config[k].update(v)
                            else:
                                config[k] = v
            except Exception as e:
                logger.warning(f"Error cargando webhooks.json: {e}")
        return config

    def save_config(self, new_config: Dict[str, Any]) -> Dict[str, Any]:
        """Guarda la configuración atómicamente a disco."""
        for section in ["connection", "discord", "telegram", "email", "events"]:
            if section in new_config and isinstance(new_config[section], dict):
                if section not in self.config or not isinstance(self.config[section], dict):
                    self.config[section] = {}
                self.config[section].update(new_config[section])

        # Sincronizar también con runtime_config para compatibilidad
        if "discord" in new_config and "webhook_url" in new_config["discord"]:
            settings.runtime_config["discord_webhook_url"] = new_config["discord"]["webhook_url"]

        try:
            atomic_write_json(self.config_file, self.config, indent=2)
        except Exception as e:
            logger.error(f"Error guardando webhooks.json: {e}")
            raise RuntimeError(f"Error guardando configuración de webhooks: {e}")

        return self.config

    def _get_server_info(self) -> Dict[str, Any]:
        name = settings.server_name or "Palworld Dedicated Server"
        conn_cfg = self.config.get("connection", {})
        custom_enabled = bool(conn_cfg.get("custom_address_enabled", False))
        display_addr = str(conn_cfg.get("display_address", "")).strip()
        display_port = str(conn_cfg.get("display_port", "")).strip()

        if custom_enabled and display_addr:
            if display_port:
                full_addr = f"{display_addr}:{display_port}"
                port_str = f"{display_port} UDP"
            else:
                full_addr = display_addr
                port_str = display_addr
        else:
            full_addr = f"127.0.0.1:{settings.server_port}"
            port_str = f"{settings.server_port} UDP"

        return {
            "name": name,
            "port": port_str,
            "address": full_addr,
            "is_custom": custom_enabled and bool(display_addr),
            "type": "Palworld Dedicated Server",
            "version": "SteamCMD"
        }

    def _build_default_fields(self, event_type: str, color: int = 0x388bfd) -> List[Dict[str, Any]]:
        info = self._get_server_info()
        name = info["name"]
        port = info["port"]
        address = info["address"]
        is_custom = info.get("is_custom", False)

        status_badge = "En Línea"
        if event_type in ("server_stop", "SHUTDOWN"):
            status_badge = "Detenido"
        elif event_type in ("server_crash", "CRASH"):
            status_badge = "Caída / Error"
        elif event_type in ("STARTING", "starting"):
            status_badge = "Iniciando..."
        elif event_type in ("backup_created", "BACKUP_OK"):
            status_badge = "Backup OK"
        elif event_type in ("player_join", "PLAYER_JOIN"):
            status_badge = "Domador Conectado"
        elif event_type in ("player_leave", "PLAYER_LEAVE"):
            status_badge = "Domador Desconectado"
        elif event_type in ("test", "TEST"):
            status_badge = "Canal Verificado"

        fields = [
            {"name": "Servidor", "value": f"`{name}`", "inline": True},
            {"name": "Conexión (Playit / IP)" if is_custom else "Puerto", "value": f"`{address if is_custom else port}`", "inline": True},
            {"name": "Estado", "value": status_badge, "inline": True}
        ]
        if is_custom and port and port != address:
            fields.append({"name": "Puerto Asignado", "value": f"`{port}`", "inline": True})
        return fields

    # --- Dispatchers ---

    async def send_discord(self, title: str, message: str, color: int = 0x388bfd, fields: Optional[List[Dict[str, Any]]] = None) -> None:
        cfg = self.config.get("discord", {})
        url = cfg.get("webhook_url", "").strip() or settings.runtime_config.get("discord_webhook_url", "")
        if not url:
            raise ValueError("URL de Discord Webhook no configurada")

        effective_fields = fields if fields is not None else self._build_default_fields("info", color)
        now_local = datetime.now()
        footer_time = now_local.strftime("%d/%m/%Y %H:%M")

        embed = {
            "title": title,
            "description": message,
            "color": color,
            "fields": effective_fields,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "footer": {
                "text": f"Palworld Server Manager • {footer_time}",
                "icon_url": "https://raw.githubusercontent.com/GMS-EC/palword-docker-server/main/web/static/img/logo.png"
            }
        }

        payload = {
            "username": "Palworld Server Manager",
            "avatar_url": "https://raw.githubusercontent.com/GMS-EC/palword-docker-server/main/web/static/img/logo.png",
            "embeds": [embed]
        }

        resp = await self.client.post(url, json=payload)
        if resp.status_code >= 400:
            raise RuntimeError(f"Discord API devolvió error {resp.status_code}: {resp.text}")

    async def send_telegram(self, title: str, message: str, fields: Optional[List[Dict[str, Any]]] = None) -> None:
        cfg = self.config.get("telegram", {})
        token = cfg.get("bot_token", "").strip()
        chat_id = cfg.get("chat_id", "").strip()
        if not token or not chat_id:
            raise ValueError("Bot Token o Chat ID de Telegram no configurados")

        effective_fields = fields if fields is not None else self._build_default_fields("info")
        clean_msg = message
        while "**" in clean_msg:
            clean_msg = clean_msg.replace("**", "<b>", 1).replace("**", "</b>", 1)

        html_lines = [
            f"<b>{title}</b>",
            "",
            clean_msg,
            ""
        ]

        if effective_fields:
            for f in effective_fields:
                fname = f.get("name", "")
                fval = str(f.get("value", "")).replace("`", "")
                html_lines.append(f"{fname}: <code>{fval}</code>")
            html_lines.append("")

        now_str = datetime.now().strftime("%d/%m/%Y %H:%M")
        html_lines.append(f"<i>{now_str} • Palworld Manager</i>")

        payload = {
            "chat_id": chat_id,
            "text": "\n".join(html_lines),
            "parse_mode": "HTML"
        }

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        resp = await self.client.post(url, json=payload)
        if resp.status_code >= 400:
            raise RuntimeError(f"Telegram API devolvió error {resp.status_code}: {resp.text}")

    def _send_email_sync(self, subject: str, body: str, color: int = 0x388bfd, fields: Optional[List[Dict[str, Any]]] = None) -> None:
        cfg = self.config.get("email", {})
        host = cfg.get("smtp_host", "").strip()
        port = int(cfg.get("smtp_port", 587) or 587)
        user = cfg.get("smtp_user", "").strip()
        pwd = cfg.get("smtp_password", "")
        use_tls = cfg.get("smtp_use_tls", True)
        from_email = cfg.get("from_email", "").strip() or user
        to_raw = cfg.get("to_emails", "").strip()

        if not host or not to_raw:
            raise ValueError("Host SMTP o destinatarios de correo no configurados")

        recipients = [e.strip() for e in to_raw.replace(";", ",").split(",") if e.strip()]
        if not recipients:
            raise ValueError("No hay destinatarios válidos especificados")

        server_info = self._get_server_info()
        server_name = server_info["name"]
        effective_fields = fields if fields is not None else self._build_default_fields("info", color)
        color_hex = f"#{color:06x}"
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"[{server_name}] {subject}"
        msg["From"] = from_email
        msg["To"] = ", ".join(recipients)

        plain_lines = [
            f"=== {subject} ===",
            f"Servidor: {server_name}",
            f"Fecha: {now_str}",
            "",
            body.replace("**", ""),
            ""
        ]
        if effective_fields:
            plain_lines.append("Detalles:")
            for f in effective_fields:
                val = str(f.get("value", "")).replace("`", "")
                plain_lines.append(f"  • {f.get('name', '')}: {val}")
        plain_lines.append("\nPalworld Server Manager — Docker")
        body_plain = "\n".join(plain_lines)

        fields_rows = ""
        if effective_fields:
            for f in effective_fields:
                fname = f.get("name", "")
                fval = str(f.get("value", "")).replace("`", "")
                fields_rows += f"""
                <tr>
                  <td style="padding: 10px 16px; border-bottom: 1px solid #21262d; font-size: 13px; font-weight: 600; color: #8b949e; width: 38%;">
                    {fname}
                  </td>
                  <td style="padding: 10px 16px; border-bottom: 1px solid #21262d; font-size: 13px; color: #f0f6fc;">
                    <code style="background: rgba(110, 118, 129, 0.2); padding: 2px 7px; border-radius: 4px; font-family: monospace; font-size: 12px;">{fval}</code>
                  </td>
                </tr>
                """

        body_html = body.replace("\n", "<br>")
        while "**" in body_html:
            body_html = body_html.replace("**", "<strong>", 1).replace("**", "</strong>", 1)

        fields_table_html = f"""
        <table width="100%" border="0" cellspacing="0" cellpadding="0" style="background-color: #0d1117; border: 1px solid #21262d; border-radius: 8px; margin-bottom: 10px; overflow: hidden;">
          {fields_rows}
        </table>
        """ if fields_rows else ""

        html_content = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <title>{subject}</title>
</head>
<body style="margin:0; padding:24px 12px; background-color:#0b0f17; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif; color:#e6edf3;">
  <table width="100%" border="0" cellspacing="0" cellpadding="0" style="max-width:580px; margin:0 auto; background-color:#161b22; border:1px solid #30363d; border-radius:12px; overflow:hidden;">
    <tr>
      <td style="padding:18px 24px; background:linear-gradient(135deg, #1c2433 0%, #111622 100%); border-bottom:1px solid #30363d;">
        <table width="100%" border="0" cellspacing="0" cellpadding="0">
          <tr>
            <td style="vertical-align:middle;">
              <span style="font-size:13px; font-weight:800; letter-spacing:1.5px; color:#58a6ff; text-transform:uppercase;">PALWORLD</span>
              <span style="font-size:11px; color:#8b949e; margin-left:6px;">| Server Manager</span>
            </td>
            <td style="text-align:right; vertical-align:middle;">
              <span style="display:inline-block; padding:4px 10px; background:rgba(56, 139, 253, 0.15); border:1px solid rgba(56, 139, 253, 0.3); border-radius:12px; font-size:11px; font-weight:600; color:#58a6ff;">
                {server_name}
              </span>
            </td>
          </tr>
        </table>
      </td>
    </tr>
    <tr><td style="height:3px; background-color:{color_hex};"></td></tr>
    <tr>
      <td style="padding:24px 24px 20px 24px;">
        <h2 style="margin:0 0 16px 0; color:#f0f6fc; font-size:18px; font-weight:700;">{subject}</h2>
        <div style="background-color:#0d1117; border-left:3px solid {color_hex}; border-radius:4px; padding:14px 16px; margin-bottom:20px;">
          <p style="margin:0; color:#cbd5e1; font-size:14px; line-height:1.6;">{body_html}</p>
        </div>
        {fields_table_html}
      </td>
    </tr>
    <tr>
      <td style="padding:14px 24px; background-color:#0d1117; border-top:1px solid #21262d; text-align:center;">
        <p style="margin:0; font-size:11px; color:#8b949e;">
          Notificación generada por <strong>Palworld Server Manager</strong>.<br>
          <span style="color:#6e7681;">{now_str}</span>
        </p>
      </td>
    </tr>
  </table>
</body>
</html>"""

        msg.attach(MIMEText(body_plain, "plain", "utf-8"))
        msg.attach(MIMEText(html_content, "html", "utf-8"))

        if port == 465:
            server = smtplib.SMTP_SSL(host, port, timeout=15)
        else:
            server = smtplib.SMTP(host, port, timeout=15)
            if use_tls:
                server.starttls()

        try:
            if user and pwd:
                server.login(user, pwd)
            server.sendmail(from_email, recipients, msg.as_string())
        finally:
            try:
                server.quit()
            except Exception:
                pass

    async def send_email(self, title: str, message: str, color: int = 0x388bfd, fields: Optional[List[Dict[str, Any]]] = None) -> None:
        await asyncio.to_thread(self._send_email_sync, title, message, color, fields)

    async def test_channel(self, channel: str) -> Dict[str, Any]:
        """Envía una prueba de conexión al canal seleccionado."""
        server_info = self._get_server_info()
        name = server_info["name"]
        conn_note = f" (Dirección: `{server_info['address']}`)" if server_info.get("is_custom") else ""
        test_title = "Prueba de Notificación — Palworld"
        test_msg = f"¡Conexión verificada exitosamente! Las alertas automáticas del servidor de Palworld **{name}**{conn_note} están operativas."
        test_fields = self._build_default_fields("test", 0x5865f2)

        try:
            if channel == "discord":
                await self.send_discord(test_title, test_msg, color=0x5865f2, fields=test_fields)
            elif channel == "telegram":
                await self.send_telegram(test_title, test_msg, fields=test_fields)
            elif channel == "email":
                await self.send_email(test_title, test_msg, color=0x5865f2, fields=test_fields)
            else:
                return {"status": "error", "message": f"Canal desconocido: '{channel}'"}

            return {"status": "success", "message": f"Notificación de prueba enviada a {channel.capitalize()} con éxito."}
        except Exception as e:
            return {"status": "error", "message": f"Error al enviar notificación a {channel}: {str(e)}"}

    def dispatch(self, event_type: str, title: str, message: str, color: int = 0x388bfd, fields: Optional[List[Dict[str, Any]]] = None) -> None:
        """Dispara la notificación en segundo plano a todos los canales configurados."""
        events_cfg = self.config.get("events", {})
        if not events_cfg.get(event_type, True):
            return

        effective_fields = fields if fields is not None else self._build_default_fields(event_type, color)
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._async_dispatch_all(title, message, color, effective_fields))
        except RuntimeError:
            try:
                asyncio.run(self._async_dispatch_all(title, message, color, effective_fields))
            except Exception as e:
                logger.error(f"Error al enviar webhook dispatch '{event_type}': {e}")

    async def _async_dispatch_all(self, title: str, message: str, color: int, fields: Optional[List[Dict[str, Any]]]) -> None:
        tasks = []
        if self.config.get("discord", {}).get("enabled"):
            tasks.append(self._safe_call(self.send_discord(title, message, color, fields), "Discord"))
        if self.config.get("telegram", {}).get("enabled"):
            tasks.append(self._safe_call(self.send_telegram(title, message, fields), "Telegram"))
        if self.config.get("email", {}).get("enabled"):
            tasks.append(self._safe_call(self.send_email(title, message, color, fields), "Email"))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _safe_call(self, coro, name: str) -> None:
        try:
            await coro
        except Exception as e:
            logger.debug(f"Error enviando notificación a {name}: {e}")

    # --- Métodos de compatibilidad y conveniencia para el ciclo de vida del servidor ---

    async def notify_starting(self):
        self.dispatch("server_start", "Servidor de Palworld Iniciando", f"El servidor **{settings.server_name}** está iniciando y cargando el mundo.", color=0xf59e0b)

    async def notify_started(self):
        info = self._get_server_info()
        conn_msg = f"\n🎮 **Conéctate en:** `{info['address']}`" if info.get("is_custom") else ""
        self.dispatch("server_start", "Servidor de Palworld En Línea", f"¡El servidor **{settings.server_name}** ha arrancado con éxito y está listo para recibir domadores!{conn_msg}", color=0x10b981)

    async def notify_stopped(self):
        self.dispatch("server_stop", "Servidor de Palworld Detenido", f"El servidor **{settings.server_name}** se ha detenido correctamente.", color=0xef4444)

    async def notify_crash(self):
        self.dispatch("server_crash", "Caída Detectada en Palworld", f"El proceso del servidor **{settings.server_name}** se detuvo inesperadamente.", color=0xd97706)

    async def notify_backup(self, filename: str, size_mb: float):
        self.dispatch("backup_created", "Copia de Seguridad Completada", f"Se ha creado el respaldo **{filename}** ({size_mb} MB) correctamente.", color=0x06b6d4)

    async def notify_player_join(self, player_name: str):
        self.dispatch("player_join", "Domador Conectado", f"**{player_name}** ha entrado a las Islas Palpagos.", color=0x3b82f6)

    async def notify_player_leave(self, player_name: str):
        self.dispatch("player_leave", "Domador Desconectado", f"**{player_name}** ha salido del servidor.", color=0x64748b)

    async def notify_task_executed(self, task_name: str, success: bool = True):
        color = 0x10b981 if success else 0xef4444
        status_txt = "ejecutada con éxito" if success else "falló en su ejecución"
        self.dispatch("task_executed", f"Tarea Programada: {task_name}", f"La tarea programada **{task_name}** ha sido {status_txt}.", color=color)

    async def notify_test(self) -> bool:
        res = await self.test_channel("discord")
        return res.get("status") == "success"

webhook_manager = WebhookManager()
