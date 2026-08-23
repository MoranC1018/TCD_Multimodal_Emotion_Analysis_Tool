from __future__ import annotations

import http.client
import json
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

    def test_authenticated_analysis_http_response_exposes_canonical_video_status(self) -> None:
        token = launcher.API_TOKEN
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "video"
            output = root / "reports"
            csv_path = source / "Speaker A" / "video.csv"
            csv_path.parent.mkdir(parents=True)
            csv_path.write_text(
                "#INFO\n#Category,Timestamp,FEA(Emotions),FEA(Emotions)\n"
                "#DATA\nRow,Timestamp,Anger,Engagement\n1,0,10,20\n",
                encoding="utf-8",
            )
            payload = {
                "outputRoot": str(output),
                "writeCombinedWorkbook": False,
                "includeConstructComparison": True,
                "includeProbabilitySheets": True,
                "confidenceLevel": 0.95,
                "headlinePolicy": "weighted",
                "defaultReference": 0,
                "referenceOverrides": {},
                "speakerGroups": [],
                "writeGraphs": True,
                "includeLogscale": False,
                "includeLandmarks": False,
                "includeTiming": False,
                "excludeGeometry": False,
                "modalities": [
                    {"name": "video", "sourceMethod": "run", "sourcePath": str(source)}
                ],
            }
            body = json.dumps(payload).encode("utf-8")
            with (
                patch.object(launcher.backend, "terms_are_accepted", return_value=True),
                patch.object(launcher, "start_process", return_value=91),
                patch.object(launcher.APP_STATE, "log"),
                self.running_server() as server,
            ):
                host, port = server.server_address
                status, _headers, response_body = self.request(
                    server,
                    "POST",
                    "/api/run-analysis-workflow",
                    headers={
                        "Content-Type": "application/json",
                        "Content-Length": str(len(body)),
                        "Origin": f"http://{host}:{port}",
                        "X-Launcher-Token": token,
                    },
                    body=body,
                )

        response = json.loads(response_body)
        self.assertEqual(status, 200)
        self.assertEqual(response["videoStatus"]["provider"], "imotions_affdex")
        self.assertIn("--video-source", response["command"])
        self.assertNotIn("--imotions-source", response["command"])

    def test_authenticated_legacy_analysis_http_route_is_gone_before_provider_dispatch(self) -> None:
        token = launcher.API_TOKEN
        observed: list[tuple[str, int, int, int, dict[str, object]]] = []
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "video"
            output = root / "reports"
            source.mkdir()
            output.mkdir()
            with (
                patch.object(launcher.backend, "terms_are_accepted", return_value=True),
                patch.object(
                    launcher.backend,
                    "build_analysis_command",
                    return_value=["python", "legacy-analysis.py"],
                ) as build_command,
                patch.object(launcher, "start_process", return_value=92) as start_process,
                patch.object(launcher.APP_STATE, "log"),
                self.running_server() as server,
            ):
                host, port = server.server_address
                for mode in ("imotions", "native_face"):
                    payload = {
                        "mode": mode,
                        "sourcePath": str(source),
                        "outputRoot": str(output),
                    }
                    body = json.dumps(payload).encode("utf-8")
                    before_build = build_command.call_count
                    before_start = start_process.call_count
                    status, _headers, response_body = self.request(
                        server,
                        "POST",
                        "/api/run-analysis",
                        headers={
                            "Content-Type": "application/json",
                            "Content-Length": str(len(body)),
                            "Origin": f"http://{host}:{port}",
                            "X-Launcher-Token": token,
                        },
                        body=body,
                    )
                    observed.append(
                        (
                            mode,
                            status,
                            build_command.call_count - before_build,
                            start_process.call_count - before_start,
                            json.loads(response_body),
                        )
                    )

        expected_error = (
            "This legacy analysis endpoint is gone. Use /api/run-analysis-workflow "
            "with the canonical Video modality."
        )
        self.assertEqual(
            observed,
            [
                ("imotions", 410, 0, 0, {"error": expected_error}),
                ("native_face", 410, 0, 0, {"error": expected_error}),
            ],
        )

    def test_legacy_analysis_http_route_still_enforces_token_and_origin_before_migration(self) -> None:
        token = launcher.API_TOKEN
        body = b"{}"
        with (
            patch.object(launcher.backend, "terms_are_accepted", return_value=True),
            patch.object(launcher.backend, "build_analysis_command") as build_command,
            patch.object(launcher, "start_process") as start_process,
            self.running_server() as server,
        ):
            host, port = server.server_address
            missing_token = self.request(
                server,
                "POST",
                "/api/run-analysis",
                headers={
                    "Content-Type": "application/json",
                    "Content-Length": str(len(body)),
                    "Origin": f"http://{host}:{port}",
                },
                body=body,
            )
            cross_origin = self.request(
                server,
                "POST",
                "/api/run-analysis",
                headers={
                    "Content-Type": "application/json",
                    "Content-Length": str(len(body)),
                    "Origin": "https://attacker.example",
                    "X-Launcher-Token": token,
                },
                body=body,
            )

        self.assertEqual(missing_token[0], 403)
        self.assertEqual(json.loads(missing_token[2]), {"error": "Invalid launcher request token."})
        self.assertEqual(cross_origin[0], 403)
        self.assertEqual(json.loads(cross_origin[2]), {"error": "Invalid launcher request origin."})
        build_command.assert_not_called()
        start_process.assert_not_called()


if __name__ == "__main__":
    unittest.main()
