from __future__ import annotations

import http.client
import tempfile
import threading
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from application import launcher


class LauncherHttpSecurityTests(unittest.TestCase):
    @contextmanager
    def running_server(self):
        server = launcher.LauncherHttpServer(("127.0.0.1", 0), launcher.VideoStackUiHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield server
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    @staticmethod
    def request(server, method: str, target: str, *, headers=None, body: bytes | None = None):
        host, port = server.server_address
        connection = http.client.HTTPConnection(host, port, timeout=5)
        try:
            connection.request(method, target, body=body, headers=headers or {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def test_bootstrap_rejects_wrong_host_without_disclosing_token(self) -> None:
        token = launcher.API_TOKEN
        with (
            patch.object(launcher.backend, "terms_are_accepted", return_value=True),
            self.running_server() as server,
        ):
            status, _headers, body = self.request(
                server,
                "GET",
                f"/?token={token}",
                headers={"Host": "attacker.example"},
            )

        self.assertEqual(status, 421)
        self.assertNotIn(token.encode("utf-8"), body)

    def test_bootstrap_requires_token_before_injecting_it(self) -> None:
        token = launcher.API_TOKEN
        with (
            patch.object(launcher.backend, "terms_are_accepted", return_value=True),
            self.running_server() as server,
        ):
            status, _headers, body = self.request(server, "GET", "/")

        self.assertEqual(status, 403)
        self.assertNotIn(token.encode("utf-8"), body)

    def test_bootstrap_rejects_dot_segment_index_alias(self) -> None:
        token = launcher.API_TOKEN
        with (
            patch.object(launcher.backend, "terms_are_accepted", return_value=True),
            self.running_server() as server,
        ):
            status, _headers, body = self.request(
                server,
                "GET",
                "/static/alias/../index.html",
            )

        self.assertEqual(status, 404)
        self.assertNotIn(token.encode("utf-8"), body)

    def test_bootstrap_requires_token_for_encoded_index_alias(self) -> None:
        token = launcher.API_TOKEN
        with (
            patch.object(launcher.backend, "terms_are_accepted", return_value=True),
            self.running_server() as server,
        ):
            status, _headers, body = self.request(
                server,
                "GET",
                "/static/%69ndex.html",
            )

        self.assertEqual(status, 403)
        self.assertNotIn(token.encode("utf-8"), body)

    def test_bootstrap_rejects_encoded_dot_segment_index_alias(self) -> None:
        token = launcher.API_TOKEN
        with (
            patch.object(launcher.backend, "terms_are_accepted", return_value=True),
            self.running_server() as server,
        ):
            status, _headers, body = self.request(
                server,
                "GET",
                "/static/alias/%2e%2e/index.html",
            )

        self.assertEqual(status, 404)
        self.assertNotIn(token.encode("utf-8"), body)

    def test_authenticated_bootstrap_does_not_refer_token_url(self) -> None:
        token = launcher.API_TOKEN
        with (
            patch.object(launcher.backend, "terms_are_accepted", return_value=True),
            self.running_server() as server,
        ):
            status, headers, body = self.request(server, "GET", f"/?token={token}")

        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Referrer-Policy"), "no-referrer")
        self.assertIn(token.encode("utf-8"), body)

    def test_bootstrap_csp_allows_only_self_scripts_and_nocookie_frames(self) -> None:
        token = launcher.API_TOKEN
        with (
            patch.object(launcher.backend, "terms_are_accepted", return_value=True),
            self.running_server() as server,
        ):
            status, headers, _body = self.request(server, "GET", f"/?token={token}")

        policy = headers.get("Content-Security-Policy", "")
        self.assertEqual(status, 200)
        self.assertIn("script-src 'self'", policy)
        self.assertIn("frame-src https://www.youtube-nocookie.com", policy)
        self.assertNotIn("'unsafe-inline'", policy)

    def test_cross_origin_state_change_is_rejected_before_dispatch(self) -> None:
        token = launcher.API_TOKEN
        launcher.APP_STATE.clear_logs()
        launcher.APP_STATE.append("keep this log")
        with (
            patch.object(launcher.backend, "terms_are_accepted", return_value=True),
            self.running_server() as server,
        ):
            status, _headers, _body = self.request(
                server,
                "POST",
                "/api/clear-logs",
                headers={
                    "Content-Type": "application/json",
                    "Content-Length": "2",
                    "Origin": "https://attacker.example",
                    "X-Launcher-Token": token,
                },
                body=b"{}",
            )

        self.assertEqual(status, 403)
        self.assertIn("keep this log", launcher.APP_STATE.logs)

    def test_cross_origin_media_request_is_rejected(self) -> None:
        token = launcher.API_TOKEN
        with tempfile.TemporaryDirectory() as temp_dir:
            media_path = Path(temp_dir) / "clip.mp4"
            media_path.write_bytes(b"video-bytes")
            launcher.APP_STATE.set_allowed_media_paths([media_path])
            with (
                patch.object(launcher.backend, "terms_are_accepted", return_value=True),
                self.running_server() as server,
            ):
                status, _headers, body = self.request(
                    server,
                    "GET",
                    f"/media?path={media_path}&token={token}",
                    headers={"Origin": "https://attacker.example"},
                )

        self.assertEqual(status, 403)
        self.assertNotEqual(body, b"video-bytes")

    def test_exact_same_origin_api_request_remains_available(self) -> None:
        token = launcher.API_TOKEN
        with (
            patch.object(launcher.backend, "terms_are_accepted", return_value=True),
            self.running_server() as server,
        ):
            host, port = server.server_address
            status, _headers, body = self.request(
                server,
                "GET",
                "/api/state",
                headers={
                    "Origin": f"http://{host}:{port}",
                    "X-Launcher-Token": token,
                },
            )

        self.assertEqual(status, 200)
        self.assertIn(b'"status"', body)


if __name__ == "__main__":
    unittest.main()
