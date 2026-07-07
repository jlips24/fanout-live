from __future__ import annotations

import io
import json
from email.message import Message
from http import HTTPStatus
from unittest import TestCase

from fanout_live.web import SESSION_COOKIE_NAME, AuthSettings, WebHandler


class TestableWebHandler(WebHandler):
    def __init__(self, auth_settings: AuthSettings, path: str = "/") -> None:
        self.auth_settings = auth_settings
        self.path = path
        self.headers = Message()
        self.sent_json = None

    def _send_json(self, payload, status=HTTPStatus.OK, *, cookies=None):
        self.sent_json = {
            "payload": payload,
            "status": status,
            "cookies": cookies or [],
        }


class WebAuthTest(TestCase):
    def test_auth_disabled_allows_sensitive_paths(self) -> None:
        handler = TestableWebHandler(AuthSettings(), "/api/config")

        self.assertTrue(handler._is_request_allowed())
        self.assertTrue(handler._is_authenticated())

    def test_auth_enabled_requires_session_for_sensitive_paths(self) -> None:
        auth_settings = self.enabled_auth()
        handler = TestableWebHandler(auth_settings, "/api/config")

        self.assertFalse(handler._is_request_allowed())
        self.assertFalse(handler._is_authenticated())

        session_id = auth_settings.create_session()
        handler.headers["Cookie"] = f"{SESSION_COOKIE_NAME}={session_id}"

        self.assertTrue(handler._is_request_allowed())
        self.assertTrue(handler._is_authenticated())

    def test_static_assets_remain_available_for_login_screen(self) -> None:
        handler = TestableWebHandler(self.enabled_auth(), "/app.js")

        self.assertTrue(handler._is_request_allowed())

    def test_login_sets_httponly_session_cookie(self) -> None:
        handler = self.login_handler({"username": "admin", "password": "secret"})

        handler._handle_login()

        self.assertEqual(handler.sent_json["status"], HTTPStatus.OK)
        self.assertEqual(handler.sent_json["payload"]["authenticated"], True)
        cookie = handler.sent_json["cookies"][0]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Lax", cookie)
        self.assertIn("Max-Age=604800", cookie)

    def test_wrong_password_is_rejected(self) -> None:
        handler = self.login_handler({"username": "admin", "password": "wrong"})

        handler._handle_login()

        self.assertEqual(handler.sent_json["status"], HTTPStatus.UNAUTHORIZED)
        self.assertEqual(handler.sent_json["payload"]["error"], "Invalid username or password.")

    def test_logout_removes_session_and_expires_cookie(self) -> None:
        auth_settings = self.enabled_auth()
        session_id = auth_settings.create_session()
        handler = TestableWebHandler(auth_settings, "/api/auth/logout")
        handler.headers["Cookie"] = f"{SESSION_COOKIE_NAME}={session_id}"

        handler._handle_logout()

        self.assertFalse(auth_settings.has_session(session_id))
        self.assertEqual(handler.sent_json["status"], HTTPStatus.OK)
        self.assertIn("Max-Age=0", handler.sent_json["cookies"][0])

    def test_settings_update_enables_login_and_sets_session_cookie(self) -> None:
        handler = self.settings_handler(
            AuthSettings(),
            {"enabled": True, "username": "owner", "password": "secret"},
        )

        handler._handle_auth_settings_update()

        self.assertEqual(handler.sent_json["status"], HTTPStatus.OK)
        self.assertEqual(handler.sent_json["payload"]["enabled"], True)
        self.assertEqual(handler.sent_json["payload"]["username"], "owner")
        self.assertEqual(handler.sent_json["payload"]["passwordSet"], True)
        self.assertIn("HttpOnly", handler.sent_json["cookies"][0])

    def test_settings_update_requires_password_before_enabling(self) -> None:
        handler = self.settings_handler(
            AuthSettings(),
            {"enabled": True, "username": "owner", "password": ""},
        )

        handler._handle_auth_settings_update()

        self.assertEqual(handler.sent_json["status"], HTTPStatus.BAD_REQUEST)
        self.assertEqual(
            handler.sent_json["payload"]["error"],
            "Set a password before enabling login.",
        )

    def test_settings_update_disables_login_and_expires_cookie(self) -> None:
        auth_settings = self.enabled_auth()
        session_id = auth_settings.create_session()
        handler = self.settings_handler(
            auth_settings,
            {"enabled": False, "username": "admin", "password": ""},
        )
        handler.headers["Cookie"] = f"{SESSION_COOKIE_NAME}={session_id}"

        handler._handle_auth_settings_update()

        self.assertEqual(handler.sent_json["status"], HTTPStatus.OK)
        self.assertEqual(handler.sent_json["payload"]["enabled"], False)
        self.assertFalse(auth_settings.has_session(session_id))
        self.assertIn("Max-Age=0", handler.sent_json["cookies"][0])

    def enabled_auth(self) -> AuthSettings:
        auth_settings = AuthSettings()
        auth_settings.update(enabled=True, username="admin", password="secret")
        return auth_settings

    def login_handler(self, payload: dict[str, str]) -> TestableWebHandler:
        return self.settings_handler(self.enabled_auth(), payload)

    def settings_handler(
        self,
        auth_settings: AuthSettings,
        payload: dict[str, str | bool],
    ) -> TestableWebHandler:
        body = json.dumps(payload).encode("utf-8")
        handler = TestableWebHandler(auth_settings)
        handler.headers["Content-Length"] = str(len(body))
        handler.rfile = io.BytesIO(body)
        return handler
