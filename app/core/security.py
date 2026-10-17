import time
import hmac
import hashlib
from typing import Optional
from fastapi import Request, HTTPException, status
from app.config import settings

SESSION_COOKIE_NAME = "pal_session"
SESSION_MAX_AGE_SECONDS = 7 * 24 * 3600  # 7 días de sesión

# Protección contra ataques de fuerza bruta en login
_FAILED_LOGINS: dict[str, list[float]] = {}
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_SECONDS = 300  # 5 minutos

def _clean_ip(ip: str) -> str:
    return ip.strip() if ip else "unknown"

def check_login_rate_limit(client_ip: str) -> bool:
    """Verifica si la IP excedió los intentos fallidos de login permitidos."""
    ip = _clean_ip(client_ip)
    now = time.time()
    attempts = _FAILED_LOGINS.get(ip, [])
    attempts = [t for t in attempts if now - t < LOCKOUT_SECONDS]
    _FAILED_LOGINS[ip] = attempts
    return len(attempts) >= MAX_FAILED_ATTEMPTS

def record_failed_login(client_ip: str) -> None:
    ip = _clean_ip(client_ip)
    now = time.time()
    if ip not in _FAILED_LOGINS:
        _FAILED_LOGINS[ip] = []
    _FAILED_LOGINS[ip].append(now)

def reset_failed_login(client_ip: str) -> None:
    ip = _clean_ip(client_ip)
    _FAILED_LOGINS.pop(ip, None)

def create_session_token(username: str) -> str:
    """Genera un token de sesión criptográficamente firmado."""
    timestamp = str(int(time.time()))
    payload = f"{username}:{timestamp}"
    signature = hmac.new(
        settings.secret_key.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()
    return f"{payload}:{signature}"

def verify_session_token(token: Optional[str]) -> Optional[str]:
    """Verifica la firma y expiración del token."""
    if not token or ":" not in token:
        return None
    try:
        parts = token.split(":")
        if len(parts) != 3:
            return None
        username, timestamp_str, received_sig = parts
        timestamp = int(timestamp_str)
        if time.time() - timestamp > SESSION_MAX_AGE_SECONDS:
            return None

        payload = f"{username}:{timestamp_str}"
        expected_sig = hmac.new(
            settings.secret_key.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()

        if hmac.compare_digest(received_sig, expected_sig):
            return username
    except Exception:
        pass
    return None

def verify_admin_credentials(username: str, password: str) -> bool:
    """Compara credenciales en tiempo constante."""
    u_match = hmac.compare_digest(username.strip(), settings.admin_user.strip())
    p_match = hmac.compare_digest(password, settings.admin_password)
    return u_match and p_match

def is_authenticated(request: Request) -> bool:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    return verify_session_token(token) is not None

def require_auth(request: Request) -> str:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    username = verify_session_token(token)
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No autorizado: sesión expirada o inválida."
        )
    return username
