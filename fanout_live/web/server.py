from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass, field
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from ..config import ConfigError
from ..config.store import (
    ensure_config_file,
    load_raw_config,
    rotate_source_stream_key,
    save_raw_config,
)
from ..relay.controller import RelayController

STATIC_DIR = Path(__file__).with_name("static")
SESSION_COOKIE_NAME = "rms_session"
AUTH_FILE_NAME = "web_auth.json"
PASSWORD_HASH_ITERATIONS = 260_000


@dataclass
class AuthSettings:
    username: str = "admin"
    enabled_setting: bool = False
    password_hash: str = ""
    path: Path | None = None
    sessions: set[str] = field(default_factory=set)

    @classmethod
    def load(cls, path: Path) -> "AuthSettings":
        if not path.exists():
            return cls(path=path)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ConfigError(f"Auth settings are invalid JSON: {exc}") from exc
        if not isinstance(raw, dict):
            raise ConfigError("Auth settings must be a JSON object.")
        username = raw.get("username", "admin")
        enabled = raw.get("enabled", False)
        password_hash = raw.get("password_hash", "")
        if not isinstance(username, str) or not username.strip():
            raise ConfigError("Auth username must be a non-empty string.")
        if not isinstance(enabled, bool):
            raise ConfigError("Auth enabled must be true or false.")
        if not isinstance(password_hash, str):
            raise ConfigError("Auth password hash must be a string.")
        return cls(
            username=username.strip(),
            enabled_setting=enabled,
            password_hash=password_hash,
            path=path,
        )

    @property
    def enabled(self) -> bool:
        return self.enabled_setting and bool(self.password_hash)

    def check_credentials(self, username: str, password: str) -> bool:
        if not self.enabled:
            return False
        return hmac.compare_digest(username, self.username) and self._verify_password(password)

    def public_settings(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "username": self.username,
            "passwordSet": bool(self.password_hash),
        }

    def update(self, *, enabled: bool, username: str, password: str = "") -> None:
        username = username.strip()
        if not username:
            raise ConfigError("Auth username must be a non-empty string.")
        if enabled and not password and not self.password_hash:
            raise ConfigError("Set a password before enabling login.")

        credentials_changed = username != self.username or bool(password)
        self.username = username
        self.enabled_setting = enabled
        if password:
            self.password_hash = self._hash_password(password)
        if credentials_changed:
            self.sessions.clear()
        if not enabled:
            self.password_hash = ""
            self.sessions.clear()
        self.save()

    def save(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "enabled": self.enabled,
            "username": self.username,
            "password_hash": self.password_hash,
        }
        self.path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def create_session(self) -> str:
        session_id = secrets.token_urlsafe(32)
        session_hash = self._hash_session(session_id)
        self.sessions.add(session_hash)
        return session_id

    def has_session(self, session_id: str) -> bool:
        session_hash = self._hash_session(session_id)
        return session_hash in self.sessions

    def remove_session(self, session_id: str) -> None:
        session_hash = self._hash_session(session_id)
        self.sessions.discard(session_hash)

    def _hash_session(self, session_id: str) -> str:
        return hashlib.sha256(session_id.encode("utf-8")).hexdigest()

    def _hash_password(self, password: str) -> str:
        salt = secrets.token_urlsafe(16)
        password_hash = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            PASSWORD_HASH_ITERATIONS,
        ).hex()
        return f"pbkdf2_sha256${PASSWORD_HASH_ITERATIONS}${salt}${password_hash}"

    def _verify_password(self, password: str) -> bool:
        try:
            algorithm, iterations, salt, expected_hash = self.password_hash.split("$", 3)
            if algorithm != "pbkdf2_sha256":
                return False
            actual_hash = hashlib.pbkdf2_hmac(
                "sha256",
                password.encode("utf-8"),
                salt.encode("utf-8"),
                int(iterations),
            ).hex()
        except (ValueError, TypeError):
            return False
        return hmac.compare_digest(actual_hash, expected_hash)


class ReusableThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def run_web_server(
    config_path: Path,
    host: str,
    port: int,
    *,
    auth_settings: AuthSettings | None = None,
) -> None:
    ensure_config_file(config_path)
    controller = RelayController(config_path)
    auth_settings = auth_settings or AuthSettings.load(config_path.parent / AUTH_FILE_NAME)

    auth_config = auth_settings

    class Handler(WebHandler):
        relay_controller = controller
        relay_config_path = config_path
        auth_settings = auth_config

    server = ReusableThreadingHTTPServer((host, port), Handler)
    print(f"Web UI: http://{host}:{port}")
    print(f"Config: {config_path}")
    if auth_settings.enabled:
        print(f"Web UI login enabled for user: {auth_settings.username}")
    else:
        print("Web UI login disabled. Enable it from Settings > Security.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopping web UI...")
    finally:
        controller.stop()
        server.server_close()


class WebHandler(SimpleHTTPRequestHandler):
    relay_controller: RelayController
    relay_config_path: Path
    auth_settings: AuthSettings

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def log_message(self, format: str, *args: Any) -> None:
        print(f"{self.address_string()} - {format % args}")

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("Pragma", "no-cache")
        super().end_headers()

    def do_GET(self) -> None:
        if self.path == "/api/health":
            self._send_json({"ok": True})
            return
        if self.path == "/api/auth/status":
            self._send_json(
                {
                    "enabled": self.auth_settings.enabled,
                    "authenticated": self._is_authenticated(),
                    "username": self.auth_settings.username if self.auth_settings.enabled else None,
                }
            )
            return
        if not self._is_request_allowed():
            self._send_unauthorized()
            return
        if self.path == "/api/auth/settings":
            self._send_json(self.auth_settings.public_settings())
            return
        if self.path == "/api/config":
            self._send_json(load_raw_config(self.relay_config_path))
            return
        if self.path == "/api/status":
            self._send_json(self.relay_controller.status())
            return
        if self.path.startswith("/preview/"):
            self._send_preview()
            return
        super().do_GET()

    def do_PUT(self) -> None:
        if not self._is_request_allowed():
            self._send_unauthorized()
            return
        if self.path == "/api/auth/settings":
            self._handle_auth_settings_update()
            return
        if self.path != "/api/config":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            payload = self._read_json()
            saved = save_raw_config(self.relay_config_path, payload)
        except (ConfigError, json.JSONDecodeError) as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        self._send_json(saved)

    def do_POST(self) -> None:
        if self.path == "/api/auth/login":
            self._handle_login()
            return
        if self.path == "/api/auth/logout":
            self._handle_logout()
            return
        if self.path == "/api/rtmp/publish":
            self._handle_rtmp_publish()
            return
        if self.path == "/api/rtmp/publish_done":
            self._handle_rtmp_publish_done()
            return
        if not self._is_request_allowed():
            self._send_unauthorized()
            return
        try:
            if self.path == "/api/relay/start":
                self._send_json(self.relay_controller.start())
                return
            if self.path == "/api/relay/stop":
                self._send_json(self.relay_controller.stop())
                return
            if self.path == "/api/source-key/rotate":
                payload = self._read_json()
                source_id = str(payload.get("source_id", payload.get("source", "")))
                self._send_json(rotate_source_stream_key(self.relay_config_path, source_id))
                return
        except ConfigError as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return

        self.send_error(HTTPStatus.NOT_FOUND)

    def _handle_rtmp_publish(self) -> None:
        try:
            app, stream = self._read_rtmp_callback()
            self._send_json(self.relay_controller.publish(app=app, stream=stream))
        except ConfigError as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.FORBIDDEN)

    def _handle_rtmp_publish_done(self) -> None:
        try:
            app, stream = self._read_rtmp_callback()
            self._send_json(self.relay_controller.publish_done(app=app, stream=stream))
        except ConfigError as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def _handle_auth_settings_update(self) -> None:
        was_enabled = self.auth_settings.enabled
        old_username = self.auth_settings.username
        try:
            payload = self._read_json()
            enabled = payload.get("enabled", False)
            username = payload.get("username", self.auth_settings.username)
            password = payload.get("password", "")
            if not isinstance(enabled, bool):
                raise ConfigError("Auth enabled must be true or false.")
            if not isinstance(username, str):
                raise ConfigError("Auth username must be a string.")
            if not isinstance(password, str):
                raise ConfigError("Auth password must be a string.")
            self.auth_settings.update(
                enabled=enabled,
                username=username,
                password=password,
            )
        except (ConfigError, json.JSONDecodeError) as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        cookies = []
        credentials_changed = bool(password) or username.strip() != old_username
        if self.auth_settings.enabled and (not was_enabled or credentials_changed):
            cookies.append(self._session_cookie(self.auth_settings.create_session()))
        if not self.auth_settings.enabled:
            cookies.append(self._expired_session_cookie())
        self._send_json(self.auth_settings.public_settings(), cookies=cookies)

    def _handle_login(self) -> None:
        if not self.auth_settings.enabled:
            self._send_json({"authenticated": True, "enabled": False})
            return
        try:
            payload = self._read_json()
        except (ConfigError, json.JSONDecodeError) as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return

        username = str(payload.get("username", ""))
        password = str(payload.get("password", ""))
        if not self.auth_settings.check_credentials(username, password):
            self._send_json({"error": "Invalid username or password."}, HTTPStatus.UNAUTHORIZED)
            return

        session_id = self.auth_settings.create_session()
        self._send_json(
            {
                "authenticated": True,
                "enabled": True,
                "username": self.auth_settings.username,
            },
            cookies=[self._session_cookie(session_id)],
        )

    def _handle_logout(self) -> None:
        session_id = self._session_id_from_cookie()
        if session_id:
            self.auth_settings.remove_session(session_id)
        self._send_json(
            {
                "authenticated": False,
                "enabled": self.auth_settings.enabled,
                "username": self.auth_settings.username if self.auth_settings.enabled else None,
            },
            cookies=[self._expired_session_cookie()],
        )

    def _is_request_allowed(self) -> bool:
        if not self.auth_settings.enabled:
            return True
        if not self.path.startswith("/api/") and not self.path.startswith("/preview/"):
            return True
        return self._is_authenticated()

    def _is_authenticated(self) -> bool:
        if not self.auth_settings.enabled:
            return True
        session_id = self._session_id_from_cookie()
        return bool(session_id and self.auth_settings.has_session(session_id))

    def _session_id_from_cookie(self) -> str | None:
        raw_cookie = self.headers.get("Cookie")
        if not raw_cookie:
            return None
        cookie = SimpleCookie()
        cookie.load(raw_cookie)
        morsel = cookie.get(SESSION_COOKIE_NAME)
        return morsel.value if morsel else None

    def _session_cookie(self, session_id: str) -> str:
        return (
            f"{SESSION_COOKIE_NAME}={session_id}; Path=/; HttpOnly; SameSite=Lax; "
            "Max-Age=604800"
        )

    def _expired_session_cookie(self) -> str:
        return f"{SESSION_COOKIE_NAME}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0"

    def _send_unauthorized(self) -> None:
        self._send_json(
            {
                "error": "Login required.",
                "authRequired": True,
            },
            HTTPStatus.UNAUTHORIZED,
        )

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        data = self.rfile.read(length)
        payload = json.loads(data.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ConfigError("Request body must be a JSON object.")
        return payload

    def _read_rtmp_callback(self) -> tuple[str, str]:
        client_host = self.client_address[0]
        if client_host not in {"127.0.0.1", "::1"}:
            raise ConfigError("RTMP callbacks are only accepted from localhost.")

        length = int(self.headers.get("Content-Length", "0"))
        data = self.rfile.read(length).decode("utf-8")
        payload = parse_qs(data, keep_blank_values=True)
        app = _first_form_value(payload, "app")
        stream = _first_form_value(payload, "name")
        if not app or not stream:
            raise ConfigError("RTMP callback is missing app or stream name.")
        return app, stream

    def _send_json(
        self,
        payload: dict[str, Any],
        status: HTTPStatus = HTTPStatus.OK,
        *,
        cookies: list[str] | None = None,
    ) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for cookie in cookies or []:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)

    def _send_preview(self) -> None:
        preview_path = self.relay_controller.preview_path
        if not preview_path.exists() or time.time() - preview_path.stat().st_mtime > 10:
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        body = preview_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _first_form_value(payload: dict[str, list[str]], key: str) -> str:
    values = payload.get(key, [])
    return values[0].strip() if values else ""
