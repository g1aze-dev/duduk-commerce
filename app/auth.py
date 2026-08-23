"""
Общая авторизация для админки.
Здесь же — серверная защита от подбора пароля (в отличие от счётчика
в sessionStorage на фронте, который ничего не блокирует по-настоящему).
"""
import time
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import secrets

from .config import ADMIN_PASSWORD

security = HTTPBasic()

MAX_ATTEMPTS = 5          # попыток
LOCKOUT_SECONDS = 300      # блокировка на 5 минут после превышения

# Простое in-memory хранилище неудачных попыток по IP.
# Для одного процесса этого достаточно; если инстансов сервера
# станет несколько — нужно будет вынести в Redis.
_failed_attempts: dict[str, list[float]] = {}


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _is_locked_out(ip: str) -> int | None:
    """Возвращает кол-во секунд до разблокировки, если IP заблокирован."""
    now = time.time()
    attempts = [t for t in _failed_attempts.get(ip, []) if now - t < LOCKOUT_SECONDS]
    _failed_attempts[ip] = attempts
    if len(attempts) >= MAX_ATTEMPTS:
        remaining = int(LOCKOUT_SECONDS - (now - attempts[0]))
        return max(remaining, 1)
    return None


def _register_failure(ip: str):
    _failed_attempts.setdefault(ip, []).append(time.time())


def _register_success(ip: str):
    _failed_attempts.pop(ip, None)


def verify_admin(request: Request, credentials: HTTPBasicCredentials = Depends(security)) -> str:
    ip = _client_ip(request)

    locked_for = _is_locked_out(ip)
    if locked_for is not None:
        raise HTTPException(
            status_code=429,
            detail=f"Слишком много неудачных попыток входа. Повторите через {locked_for} сек.",
        )

    ok_pass = secrets.compare_digest(credentials.password.encode(), ADMIN_PASSWORD.encode())
    ok_user = secrets.compare_digest(credentials.username.encode(), b"admin")

    if not (ok_pass and ok_user):
        _register_failure(ip)
        raise HTTPException(
            status_code=401,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Basic"},
        )

    _register_success(ip)
    return credentials.username
