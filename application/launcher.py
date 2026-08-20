"""Local desktop launcher for the Multimodal Emotion Analysis Tool.

The desktop UI calls this server for filesystem browsing, source scanning, and
starting long-running procurement or processing subprocesses.
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import math
import mimetypes
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qs, quote, unquote, urlparse

from procurement.procurement_beta.readiness import build_readiness_report
from procurement.external_tools import credential_free_media_environment, resolve_nvidia_smi
from application import backend


REPO_ROOT = Path(__file__).resolve().parents[1]
STATIC_ROOT = Path(__file__).resolve().parent / "static"
STATIC_INDEX = (STATIC_ROOT / "index.html").resolve()
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8766
ACCESS_EXEMPT_POSTS = {"/api/close", "/api/revoke-access"}
API_TOKEN = secrets.token_urlsafe(32)
MAX_JSON_BODY_BYTES = 2 * 1024 * 1024
MAX_FOCUS_SEGMENTS = 10_000
CONTENT_SECURITY_POLICY = "; ".join(
    (
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self'",
        "img-src 'self' data: https://i.ytimg.com",
        "media-src 'self'",
        "connect-src 'self'",
        "frame-src https://www.youtube-nocookie.com",
        "font-src 'self'",
        "object-src 'none'",
        "base-uri 'none'",
        "frame-ancestors 'none'",
        "form-action 'self'",
    )
)
APP_TITLE = backend.PRODUCT_NAME
APP_USER_MODEL_ID = "TrinityCollegeDublin.MultimodalEmotionAnalysisTool"
WEBVIEW_STORAGE_ROOT = (
    Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    / "MultimodalEmotionAnalysisTool"
    / "WebView2"
)
PROCESS_TERMINATION_LOCK = threading.Lock()


@dataclass(frozen=True)
class FocusManifestHandoff:
    path: Path
    sha256: str
    expected_source: str


class NativeWindowApi:
    """Small pywebview bridge for actions that browsers cannot guarantee."""

    def __init__(self) -> None:
        # pywebview exposes public js_api attributes recursively. Keeping the
        # native Window private prevents COM objects from being inspected on a
        # bridge worker thread.
        self._window = None

    def bind_window(self, window) -> None:
        self._window = window

    def close_window(self) -> bool:
        """Close the native host after the UI has completed its API request."""

        if self._window is None:
            return False
        self._window.destroy()
        return True

    def toggle_fullscreen(self) -> bool:
        """Toggle native full-screen mode for the F11 keyboard shortcut."""

        if self._window is None:
            return False
        self._window.toggle_fullscreen()
        return True

    def browse_for_path(self, kind: str) -> dict[str, object]:
        """Use the WebView2-owned picker instead of starting Tk on a worker."""

        if self._window is None:
            return {"path": "", "cancelled": True}

        normalized_kind = str(kind or "folder").casefold()
        if normalized_kind in {"folder", "output"}:
            selection = self._window.create_file_dialog(dialog_type=20)
        elif normalized_kind == "source-file":
            selection = self._window.create_file_dialog(
                dialog_type=10,
                file_types=(
                    "Supported sources (*.csv;*.docx;*.mp4;*.mov;*.mkv;*.webm;*.avi)",
                    "Catalog files (*.csv;*.docx)",
                    "CSV files (*.csv)",
                    "DOCX files (*.docx)",
                    "Video files (*.mp4;*.mov;*.mkv;*.webm;*.avi)",
                ),
            )
        elif normalized_kind == "docx":
            selection = self._window.create_file_dialog(
                dialog_type=10,
                file_types=("DOCX files (*.docx)", "All files (*.*)"),
            )
        else:
            selection = self._window.create_file_dialog(
                dialog_type=10,
                file_types=(
                    "Video files (*.mp4;*.mov;*.mkv;*.webm;*.avi)",
                    "All files (*.*)",
                ),
            )

        path = str(selection[0]) if selection else ""
        return {"path": path, "cancelled": not bool(path)}


class LauncherState:
    """Thread-safe state shared between HTTP requests and subprocess output."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.logs: list[str] = []
        self.status = "idle"
        self.returncode: int | None = None
        self.command: list[str] = []
        self.process: subprocess.Popen[str] | None = None
        self.starting = False
        self.shutdown_requested = False
        self.allowed_media_paths: set[str] = set()
        self.allowed_video_ids: set[str] = set()
        self.allowed_focus_identities: set[backend.FocusSourceIdentity] = set()
        self.allowed_durations: dict[backend.FocusSourceIdentity, float] = {}
        self.allowed_catalog_path = ""
        self.allowed_catalog_sha256 = ""
        self.allowed_catalog_source_ids: set[str] = set()
        self.allowed_catalog_records: dict[str, backend.VideoItem] = {}
        self.next_run_id = 0
        self.active_run_id = 0
        self.cancelled_run_ids: set[int] = set()
        self.job_handles: dict[int, int] = {}
        self.last_client_seen = 0.0
        self.client_seen = threading.Event()
        self.progress: dict[str, object] = {
            "mode": "",
            "label": "Ready",
            "current": 0,
            "total": 0,
        }

    def append(self, line: str, *, echo: bool = True) -> None:
        cleaned = line.rstrip("\r\n")
        with self.lock:
            self.logs.append(cleaned)
            self.logs = self.logs[-1200:]
            # Progress is inferred from subprocess output, so the UI can
            # stay decoupled from each underlying command-line tool.
            progress = parse_progress_line(cleaned)
            if progress:
                completed_output = progress.pop("completedOutput", None)
                if isinstance(completed_output, dict):
                    completed_outputs = dict(self.progress.get("completedOutputs") or {})
                    modality = str(completed_output.get("modality") or "").strip()
                    path = str(completed_output.get("path") or "").strip()
                    if modality and path:
                        completed_outputs[modality] = path
                        self.progress["completedOutputs"] = completed_outputs
                self.progress.update({key: value for key, value in progress.items() if value is not None})
        if echo:
            print(cleaned, flush=True)

    def log(self, message: str) -> None:
        self.append(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")

    def snapshot(self, *, include_configuration: bool = False) -> dict[str, object]:
        """Return live run state, optionally including slower local configuration."""

        with self.lock:
            # Keep the run logically active until finish_process publishes the
            # return code and clears the handle in this same critical section.
            # The OS can mark a short child exited just before the output reader
            # has drained its final line; polling here used to expose an
            # impossible-looking running=False/status=running snapshot.
            running = self.starting or self.process is not None
            snapshot = {
                "status": "running" if running else self.status,
                "running": running,
                "returncode": self.returncode,
                "runId": self.active_run_id,
                "command": self.command,
                "progress": dict(self.progress),
            }
        if include_configuration:
            # OneDrive and credential reads can be slow. They must not hold the
            # process-state lock needed by close and stop actions.
            snapshot.update(
                {
                    "defaultOutputRoot": str(backend.default_output_root(REPO_ROOT)),
                    "defaultAudioOutputRoot": str(backend.default_audio_output_root(REPO_ROOT)),
                    "defaultAnalysisOutputRoot": str(backend.default_analysis_output_root(REPO_ROOT)),
                    "settings": backend.public_ui_settings(REPO_ROOT),
                    "access": backend.load_eula_state(REPO_ROOT),
                }
            )
        return snapshot

    def reserve_process(self, command: list[str], *, mode: str, total: int) -> int | None:
        """Atomically reserve the single subprocess slot before Popen runs."""

        with self.lock:
            if self.shutdown_requested or self.starting or self.process is not None:
                return None
            self.next_run_id += 1
            self.active_run_id = self.next_run_id
            self.cancelled_run_ids.discard(self.active_run_id)
            self.starting = True
            self.command = command
            self.status = "running"
            self.returncode = None
            self.progress = {
                "mode": mode,
                "label": "Starting run...",
                "current": 0,
                "total": max(0, total),
                "stage": "",
                "failedStage": "",
                "error": "",
                "completedOutputs": {},
            }
            return self.active_run_id

    def attach_process(self, process: subprocess.Popen[str], run_id: int | None = None) -> bool:
        """Attach a child and report whether shutdown or cancellation won."""

        with self.lock:
            if run_id is not None and run_id != self.active_run_id:
                return True
            self.process = process
            self.starting = False
            return self.shutdown_requested or self.active_run_id in self.cancelled_run_ids

    def request_process_stop(self) -> tuple[bool, subprocess.Popen[str] | None]:
        """Cancel a reserved run or return its attached child for termination."""

        with self.lock:
            if not self.starting and self.process is None:
                return False, None
            self.cancelled_run_ids.add(self.active_run_id)
            self.status = "stopping"
            self.progress["label"] = "Stopping..."
            return True, self.process

    def attach_job_handle(self, run_id: int, handle: int) -> None:
        with self.lock:
            if run_id != self.active_run_id:
                close_windows_handle(handle)
                return
            self.job_handles[run_id] = handle

    def request_shutdown(self) -> None:
        with self.lock:
            self.shutdown_requested = True

    def reset_shutdown(self) -> None:
        with self.lock:
            self.shutdown_requested = False

    def reset_client_seen(self) -> None:
        with self.lock:
            self.last_client_seen = 0.0
        self.client_seen.clear()

    def fail_process_start(self, message: str, run_id: int | None = None) -> None:
        with self.lock:
            if run_id is not None and run_id != self.active_run_id:
                return
            self.starting = False
            self.status = "failed"
            self.returncode = None
            self.progress["label"] = message
            self.cancelled_run_ids.discard(self.active_run_id)

    def finish_process(self, returncode: int, run_id: int | None = None) -> bool:
        job_handle = None
        with self.lock:
            if run_id is not None and run_id != self.active_run_id:
                return False
            if not self.starting and self.process is None:
                return False
            was_cancelled = self.active_run_id in self.cancelled_run_ids
            self.starting = False
            self.status = "stopped" if was_cancelled else "complete" if returncode == 0 else "failed"
            self.returncode = returncode
            if was_cancelled:
                self.progress["label"] = "Stopped"
            elif returncode == 0:
                self.progress["label"] = "Complete"
            elif not self.progress.get("error"):
                self.progress["label"] = "Failed"
            if returncode == 0 and not was_cancelled and self.progress.get("total"):
                self.progress["current"] = self.progress["total"]
            self.process = None
            job_handle = self.job_handles.pop(self.active_run_id, None)
            self.cancelled_run_ids.discard(self.active_run_id)
        if job_handle is not None:
            close_windows_handle(job_handle)
        return True

    def append_for_run(self, line: str, run_id: int) -> None:
        with self.lock:
            if run_id != self.active_run_id:
                return
        self.append(line)

    def clear_logs(self) -> None:
        with self.lock:
            self.logs = []

    def set_allowed_media_paths(self, paths: Iterable[Path]) -> None:
        with self.lock:
            self.allowed_media_paths = {
                os.path.normcase(str(path.expanduser().resolve()))
                for path in paths
            }

    def set_allowed_media_items(self, items: Iterable[backend.VideoItem]) -> None:
        paths: set[str] = set()
        video_ids: set[str] = set()
        identities: set[backend.FocusSourceIdentity] = set()
        durations: dict[backend.FocusSourceIdentity, float] = {}
        for item in items:
            try:
                identity = backend.focus_source_identity(item)
            except ValueError:
                continue
            identities.add(identity)
            if item.source_kind in {"folder", "file"} and item.source_path:
                paths.add(os.path.normcase(str(Path(item.source_path).expanduser().resolve())))
            else:
                supplied_video_id = str(item.video_id or "").strip()
                video_id = (
                    supplied_video_id
                    if re.fullmatch(r"[A-Za-z0-9_-]{11}", supplied_video_id)
                    else backend.run_docx_extractions.get_youtube_video_id(item.youtube_url)
                )
                if not video_id:
                    continue
                video_ids.add(video_id)
            if item.duration_seconds is not None and float(item.duration_seconds) > 0:
                durations[identity] = float(item.duration_seconds)
        with self.lock:
            self.allowed_media_paths = paths
            self.allowed_video_ids = video_ids
            self.allowed_focus_identities = identities
            self.allowed_durations = durations

    def set_allowed_catalog_scan(self, result: backend.ScanResult) -> None:
        """Remember the exact catalog snapshot whose SourceIDs the server issued."""

        with self.lock:
            if result.source_kind != "catalog":
                self.allowed_catalog_path = ""
                self.allowed_catalog_sha256 = ""
                self.allowed_catalog_source_ids = set()
                self.allowed_catalog_records = {}
                return
            self.allowed_catalog_path = os.path.normcase(str(Path(result.source_path).expanduser().resolve()))
            self.allowed_catalog_sha256 = str(result.catalog_sha256).casefold()
            self.allowed_catalog_source_ids = {str(item.source_id or item.id) for item in result.sources}
            self.allowed_catalog_records = {
                str(item.source_id or item.id): item
                for item in result.sources
            }

    def clear_allowed_catalog_scan(self) -> None:
        """Drop stale SourceID authorization before attempting a new scan."""

        with self.lock:
            self.allowed_catalog_path = ""
            self.allowed_catalog_sha256 = ""
            self.allowed_catalog_source_ids = set()
            self.allowed_catalog_records = {}

    def validate_catalog_selection(
        self,
        catalog_path: Path,
        catalog_sha256: str,
        selected_source_ids: Iterable[str],
    ) -> None:
        """Authorize selected IDs only against the latest exact server scan."""

        resolved = os.path.normcase(str(catalog_path.expanduser().resolve()))
        selected = [str(source_id) for source_id in selected_source_ids]
        with self.lock:
            if resolved != self.allowed_catalog_path or str(catalog_sha256).casefold() != self.allowed_catalog_sha256:
                raise ValueError("Catalog selection does not match the latest server scan; scan it again.")
            if not selected or len(selected) != len(set(selected)):
                raise ValueError("Choose one or more unique catalog source IDs.")
            unknown = [source_id for source_id in selected if source_id not in self.allowed_catalog_source_ids]
            if unknown:
                raise ValueError(f"Catalog selection contains unknown source IDs: {', '.join(unknown)}")

    def validate_audio_catalog_selection(
        self,
        source_path: Path,
        catalog_sha256: str,
        selected_source_ids: Iterable[str],
    ) -> backend.ScanResult:
        """Bind audio SourceIDs to the sealed manifest under the chosen batch root."""

        selected = [str(source_id) for source_id in selected_source_ids]
        catalog_run = backend.scan_audio_catalog_run(source_path)
        if catalog_run is None:
            raise ValueError("The chosen audio source has no sealed catalog manifest.")
        if str(catalog_sha256).casefold() != catalog_run.catalog_sha256:
            raise ValueError("Audio catalog selection does not match the chosen audio source manifest.")
        if not selected or len(selected) != len(set(selected)):
            raise ValueError("Choose one or more unique catalog source IDs for audio processing.")
        available = {str(item.source_id or item.id) for item in catalog_run.sources}
        unknown = [source_id for source_id in selected if source_id not in available]
        if unknown:
            raise ValueError(f"Audio catalog selection contains unknown source IDs: {', '.join(unknown)}")
        return catalog_run

    def is_allowed_media_path(self, path: Path) -> bool:
        resolved = os.path.normcase(str(path.expanduser().resolve()))
        with self.lock:
            return resolved in self.allowed_media_paths

    def catalog_record_for_segment(
        self,
        segment: Mapping[str, object],
        identity: backend.FocusSourceIdentity,
    ) -> backend.VideoItem | None:
        """Return the server-scanned catalog record bound to a Focus SourceID."""

        source_id = str(segment.get("source_id") or "")
        with self.lock:
            catalog_active = bool(self.allowed_catalog_path)
            record = self.allowed_catalog_records.get(source_id)
        if not catalog_active:
            return None
        if record is None:
            raise ValueError(f"Focus segment has an unknown catalog SourceID: {source_id or '<blank>'}")
        if backend.focus_source_identity(record) != identity:
            raise ValueError(f"Focus segment identity does not match catalog SourceID {source_id}.")
        return record

    def allowed_duration_for_segment(self, segment: dict[str, object]) -> float | None:
        try:
            identity = backend.focus_source_identity(segment)
        except ValueError:
            return None
        with self.lock:
            if identity not in self.allowed_focus_identities:
                return None
            return self.allowed_durations.get(identity)

    def is_allowed_segment_reference(self, segment: dict[str, object]) -> bool:
        try:
            identity = backend.focus_source_identity(segment)
        except ValueError:
            return False
        with self.lock:
            return identity in self.allowed_focus_identities

    def mark_client_seen(self) -> None:
        with self.lock:
            self.last_client_seen = time.monotonic()
        self.client_seen.set()


APP_STATE = LauncherState()


def resolve_static_request_target(request_path: str) -> Path | None:
    """Resolve one canonical static route without accepting traversal aliases."""

    if request_path in {"", "/"}:
        relative_text = "index.html"
    elif request_path.startswith("/static/"):
        relative_text = unquote(request_path.removeprefix("/static/"))
    else:
        return None

    if not relative_text or "\x00" in relative_text or "\\" in relative_text:
        raise ValueError("Invalid static request path.")
    parts = relative_text.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("Invalid static request path.")
    relative = Path(*parts)
    if relative.is_absolute() or relative.drive or relative.root:
        raise ValueError("Invalid static request path.")
    try:
        target = (STATIC_ROOT / relative).resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValueError("Invalid static request path.") from exc
    static_root = STATIC_ROOT.resolve()
    if static_root not in target.parents and target != static_root:
        raise ValueError("Invalid static request path.")
    return target


class LauncherHttpServer(ThreadingHTTPServer):
    """HTTP server whose request workers cannot hold the desktop app open."""

    daemon_threads = True
    block_on_close = False
    allow_reuse_address = False

    def server_bind(self) -> None:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class VideoStackUiHandler(BaseHTTPRequestHandler):
    """Small JSON/static-file server used by the standalone launcher window."""

    server_version = "MultimodalEmotionAnalysisLauncher/1.0"

    def end_headers(self) -> None:
        """Attach the same restrictive browser boundary to every response."""

        self.send_header("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def log_message(self, format: str, *args: object) -> None:
        return

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if not self.request_authority_is_valid():
            self.send_error_json(HTTPStatus.MISDIRECTED_REQUEST, "Invalid launcher authority.")
            return
        try:
            static_target = resolve_static_request_target(parsed.path)
        except ValueError:
            self.send_error_json(HTTPStatus.NOT_FOUND, "Unknown static resource.")
            return
        if static_target == STATIC_INDEX and not self.token_is_valid(parsed):
            self.send_error_json(HTTPStatus.FORBIDDEN, "Invalid launcher bootstrap token.")
            return
        if (parsed.path.startswith("/api/") or parsed.path == "/media") and not self.privileged_origin_is_valid(parsed):
            self.send_error_json(HTTPStatus.FORBIDDEN, "Invalid launcher request origin.")
            return
        if parsed.path == "/api/state":
            if not self.token_is_valid(parsed):
                self.send_error_json(HTTPStatus.FORBIDDEN, "Invalid launcher request token.")
                return
            if not backend.terms_are_accepted(REPO_ROOT):
                self.send_access_denied(schedule_shutdown=True)
                return
            APP_STATE.mark_client_seen()
            include_configuration = str(
                parse_qs(parsed.query).get("configuration", [""])[0]
            ).casefold() in {"1", "true", "yes"}
            self.send_json(APP_STATE.snapshot(include_configuration=include_configuration))
            return
        if parsed.path == "/api/procurement-beta/readiness":
            if not self.token_is_valid(parsed):
                self.send_error_json(HTTPStatus.FORBIDDEN, "Invalid launcher request token.")
                return
            if not backend.terms_are_accepted(REPO_ROOT):
                self.send_access_denied(schedule_shutdown=True)
                return
            self.send_json(build_readiness_report())
            return
        if parsed.path == "/media":
            if not self.token_is_valid(parsed):
                self.send_error_json(HTTPStatus.FORBIDDEN, "Invalid launcher request token.")
                return
            if not backend.terms_are_accepted(REPO_ROOT):
                self.send_access_denied(schedule_shutdown=True)
                return
            self.serve_media(parsed)
            return
        if not backend.terms_are_accepted(REPO_ROOT):
            self.send_access_denied(schedule_shutdown=True)
            return
        self.serve_static(static_target)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            if not self.request_authority_is_valid():
                self.send_error_json(HTTPStatus.MISDIRECTED_REQUEST, "Invalid launcher authority.")
                return
            if not self.token_is_valid(parsed):
                self.send_error_json(HTTPStatus.FORBIDDEN, "Invalid launcher request token.")
                return
            if not self.privileged_origin_is_valid(parsed):
                self.send_error_json(HTTPStatus.FORBIDDEN, "Invalid launcher request origin.")
                return
            payload = self.read_json_body()
            if parsed.path not in ACCESS_EXEMPT_POSTS and not backend.terms_are_accepted(REPO_ROOT):
                self.send_access_denied(schedule_shutdown=True)
                return
            if parsed.path == "/api/scan":
                self.handle_scan(payload)
            elif parsed.path == "/api/run":
                self.handle_run(payload)
            elif parsed.path == "/api/run-audio":
                self.handle_run_audio(payload)
            elif parsed.path == "/api/audio-catalog":
                self.handle_audio_catalog(payload)
            elif parsed.path == "/api/run-analysis":
                self.handle_run_analysis(payload)
            elif parsed.path == "/api/run-analysis-workflow":
                self.handle_run_analysis_workflow(payload)
            elif parsed.path == "/api/analysis-speakers":
                self.handle_analysis_speakers(payload)
            elif parsed.path == "/api/settings":
                self.handle_settings(payload)
            elif parsed.path == "/api/revoke-access":
                self.handle_revoke_access()
            elif parsed.path == "/api/close":
                self.handle_close()
            elif parsed.path == "/api/stop":
                self.handle_stop()
            elif parsed.path == "/api/clear-logs":
                APP_STATE.clear_logs()
                self.send_json(APP_STATE.snapshot())
            elif parsed.path == "/api/browse":
                self.handle_browse(payload)
            elif parsed.path == "/api/validate-path":
                self.handle_validate_path(payload)
            else:
                self.send_error_json(HTTPStatus.NOT_FOUND, "Unknown API endpoint.")
        except ValueError as exc:
            APP_STATE.log(f"INPUT ERROR: {exc}")
            self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception as exc:
            APP_STATE.log(f"ERROR: {exc}")
            self.send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def read_json_body(self) -> dict[str, object]:
        content_type = self.headers.get("Content-Type", "")
        try:
            length = int(self.headers.get("Content-Length", "0") or "0")
        except ValueError as exc:
            raise ValueError("Invalid Content-Length header.") from exc
        if length < 0 or length > MAX_JSON_BODY_BYTES:
            raise ValueError(f"Request body must be no larger than {MAX_JSON_BODY_BYTES // (1024 * 1024)} MB.")
        if length > 0 and "application/json" not in content_type.casefold():
            raise ValueError("Expected application/json request body.")
        if length == 0:
            return {}
        try:
            raw = self.rfile.read(length).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("Request body must be valid UTF-8 JSON.") from exc
        if not raw.strip():
            return {}
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("Expected a JSON object.")
        return data

    def token_is_valid(self, parsed) -> bool:
        """Require the per-launch token for API/media control surfaces."""

        query_token = parse_qs(parsed.query).get("token", [""])[0]
        header_token = self.headers.get("X-Launcher-Token", "")
        return launcher_token_is_valid(header_token, query_token)

    def request_authority_is_valid(self) -> bool:
        """Accept only the exact loopback authority this server bound."""

        supplied = str(self.headers.get("Host") or "").strip().casefold()
        expected = launcher_authority(self.server.server_address).casefold()
        return bool(supplied and secrets.compare_digest(supplied, expected))

    def privileged_origin_is_valid(self, parsed) -> bool:
        """Bind browser control/media requests to the launcher-created origin."""

        supplied = str(self.headers.get("Origin") or "").strip()
        expected = launcher_origin(self.server.server_address)
        if supplied:
            return secrets.compare_digest(supplied.casefold(), expected.casefold())

        fetch_site = str(self.headers.get("Sec-Fetch-Site") or "").strip().casefold()
        if fetch_site == "same-origin":
            return True

        # A native, non-browser controller may omit Origin and Fetch Metadata,
        # but it must send the capability in the non-URL header.
        header_token = str(self.headers.get("X-Launcher-Token") or "")
        query_token = parse_qs(parsed.query).get("token", [""])[0]
        return bool(not fetch_site and header_token and not query_token and launcher_token_is_valid(header_token, ""))

    def handle_scan(self, payload: dict[str, object]) -> None:
        """Scan the selected source and return grouped video metadata."""

        raw_path = str(payload.get("path") or "").strip()
        if not raw_path:
            self.send_error_json(
                HTTPStatus.BAD_REQUEST,
                "Enter a YouTube URL, local folder, DOCX list, or supported video file.",
            )
            return
        APP_STATE.clear_allowed_catalog_scan()
        APP_STATE.log(f"Scanning source: {raw_path}")
        result = backend.scan_input_source(raw_path, logger=lambda message: APP_STATE.log(f"Scan: {message}"))
        APP_STATE.set_allowed_media_items(
            video for group in result.groups for video in group.videos
        )
        APP_STATE.set_allowed_catalog_scan(result)
        video_count = sum(len(group.videos) for group in result.groups)
        APP_STATE.log(f"Scan complete: {plural(video_count, 'video')} across {plural(len(result.groups), 'speaker group')}.")
        self.send_json(backend.scan_result_to_json(result))

    def handle_run(self, payload: dict[str, object]) -> None:
        """Start a procurement command from the selected UI mode."""

        raw_source_path = required_payload_text(payload, "sourcePath")
        if raw_source_path is None:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "Choose a source before running procurement.")
            return
        selected_speakers = payload_text_list(payload.get("selectedSpeakers"))
        selected_source_ids = payload_text_list(payload.get("selectedSourceIds"))
        catalog_sha256 = str(payload.get("catalogSha256") or "").strip().casefold()
        cleaned_source = backend.clean_user_supplied_path(raw_source_path)
        direct_youtube_source = bool(backend.run_docx_extractions.get_youtube_video_id(cleaned_source))
        catalog_source: Path | None = None
        if not direct_youtube_source:
            candidate = Path(cleaned_source).expanduser().resolve()
            if candidate.suffix.casefold() in {".csv", ".docx"}:
                catalog_source = candidate
        if catalog_source is not None:
            APP_STATE.validate_catalog_selection(catalog_source, catalog_sha256, selected_source_ids)
            source_path = catalog_source
        else:
            if not selected_speakers:
                raise ValueError("Select at least one speaker before running procurement.")
            source_path = backend.prepare_source_for_run(raw_source_path, REPO_ROOT, logger=APP_STATE.log)

        output_root = Path(
            backend.clean_user_supplied_path(str(payload.get("outputRoot") or backend.default_output_root(REPO_ROOT)))
        ).expanduser()
        mode = str(payload.get("mode") or "standard")
        settings = backend.load_ui_settings(REPO_ROOT)
        clean_resources = backend.clean_speaker_resource_settings(settings)
        segment_handoff = (
            write_segment_manifest(
                output_root,
                payload,
                selected_speakers=selected_speakers,
                expected_source=raw_source_path,
                processing_source=source_path,
            )
            if mode == "manual"
            else None
        )
        request = backend.RunRequest(
            mode=mode,
            source_path=source_path,
            output_root=output_root,
            segment_manifest=segment_handoff.path if segment_handoff else None,
            segment_manifest_sha256=segment_handoff.sha256 if segment_handoff else "",
            segment_expected_source=segment_handoff.expected_source if segment_handoff else "",
            selected_speakers=selected_speakers,
            selected_ids=selected_source_ids,
            catalog_sha256=catalog_sha256,
            internal_youtube_source=direct_youtube_source,
            max_segment_seconds=payload_int(payload, "maxSegmentSeconds", 30),
            percentage=payload_float(payload, "percentage", 0.10),
            beta_output_mode=str(payload.get("betaOutputMode") or "clean"),
            beta_min_clean_seconds=payload_float(payload, "betaMinCleanSeconds", 10.0),
            beta_gap_seconds=payload_float(payload, "betaGapSeconds", 0.5),
            beta_identity_stills=payload_int(payload, "betaIdentityStills", 20),
            beta_scan_fps=payload_float(payload, "betaScanFps", 1.0),
            beta_validation_fps=payload_float(payload, "betaValidationFps", 4.0),
            beta_max_download_height=payload_int(payload, "betaMaxDownloadHeight", 720),
            beta_face_confidence=payload_float(payload, "betaFaceConfidence", 0.65),
            beta_speaker_confidence=payload_float(payload, "betaSpeakerConfidence", 0.65),
            beta_worker_count=payload_int(payload, "betaWorkerCount", 1),
            beta_device=str(payload.get("betaDevice") or "auto"),
            beta_keep_debug=payload_bool(payload, "betaKeepDebug", False),
            beta_resource_guard_percent=float(clean_resources["resource_guard_percent"]),
            beta_resource_poll_seconds=float(clean_resources["resource_poll_seconds"]),
            beta_resource_guard_timeout_seconds=float(clean_resources["resource_guard_timeout_seconds"]),
            beta_parallel_detector_streams=payload_bool(payload, "betaParallelDetectorStreams", False),
            beta_reference_audio=Path(str(payload["betaReferenceAudio"])).expanduser()
            if str(payload.get("betaReferenceAudio") or "").strip()
            else None,
            beta_only_video_ids=payload_text_list(payload.get("betaOnlyVideoIds")),
            beta_random_one=payload_bool(payload, "betaRandomOne", False),
            beta_random_seed=str(payload.get("betaRandomSeed") or "").strip(),
            beta_isolated_video_processes=payload_bool(payload, "betaIsolatedVideoProcesses", True),
            beta_skip_first_videos=payload_int(payload, "betaSkipFirstVideos", 0),
            beta_skip_completed_outputs=payload_bool(payload, "betaSkipCompletedOutputs", True),
            beta_video_cooldown_seconds=payload_float(payload, "betaVideoCooldownSeconds", 60.0),
            beta_max_affinity_cores=int(clean_resources["max_affinity_cores"]),
            beta_native_threads=int(clean_resources["native_threads"]),
            beta_cpu_throttle_high_percent=float(clean_resources["cpu_high_percent"]),
            beta_cpu_throttle_low_percent=float(clean_resources["cpu_low_percent"]),
            beta_ram_throttle_high_percent=float(clean_resources["ram_high_percent"]),
            beta_ram_throttle_low_percent=float(clean_resources["ram_low_percent"]),
        )
        command = backend.build_run_command(request, repo_root=REPO_ROOT)
        video_count = max(0, payload_int(payload, "videoCount", 0))
        APP_STATE.log(
            f"Starting {mode} procurement for {plural(video_count, 'video item')} into {output_root.expanduser().resolve()}."
        )
        run_id = start_process(command, mode=mode, total=video_count)
        if run_id is None:
            self.send_error_json(HTTPStatus.CONFLICT, "A procurement run is already active.")
            return
        self.send_json({"started": True, "runId": run_id, "command": command})

    def handle_run_audio(self, payload: dict[str, object]) -> None:
        """Start the audio processing pipeline with UI-selected options."""

        raw_source_path = required_payload_text(payload, "sourcePath")
        if raw_source_path is None:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "Choose an audio processing source first.")
            return
        source_path = Path(raw_source_path)

        output_root = Path(
            backend.clean_user_supplied_path(str(payload.get("outputRoot") or backend.default_audio_output_root(REPO_ROOT)))
        ).expanduser()
        mode = str(payload.get("mode") or "batch")
        selected_source_ids = payload_text_list(payload.get("selectedSourceIds"))
        catalog_sha256 = str(payload.get("catalogSha256") or "").strip().casefold()
        validate_processing_paths(
            source_path,
            output_root,
            label="Audio",
            source_kind="file" if mode == "single" else "file-or-folder",
        )
        if selected_source_ids:
            APP_STATE.validate_audio_catalog_selection(source_path, catalog_sha256, selected_source_ids)
        elif catalog_sha256:
            raise ValueError("Choose one or more catalog sources for audio processing.")
        elif mode.casefold() == "batch" and source_path.is_dir() and backend.scan_audio_catalog_run(source_path) is not None:
            raise ValueError("Choose one or more catalog sources for audio processing.")
        request = backend.AudioRunRequest(
            mode=mode,
            source_path=source_path,
            output_root=output_root,
            window_seconds=payload_float(payload, "windowSeconds", 10.0),
            stride_seconds=payload_float(payload, "strideSeconds", 5.0),
            opensmile_feature_set=str(payload.get("opensmileFeatureSet") or "egemaps"),
            include_emotions=payload_bool(payload, "includeEmotions", True),
            device=str(payload.get("device") or "auto"),
            keep_temp_audio=payload_bool(payload, "keepTempAudio", False),
            debug=payload_bool(payload, "debug", False),
            stop_on_error=payload_bool(payload, "stopOnError", False),
            selected_source_ids=tuple(selected_source_ids),
            catalog_sha256=catalog_sha256,
        )
        command = backend.build_audio_command(request, repo_root=REPO_ROOT)
        APP_STATE.log(f"Starting audio {mode} processing from {source_path.expanduser().resolve()}.")
        APP_STATE.log(f"Audio output root: {output_root.expanduser().resolve()}")
        run_id = start_process(command, mode=f"audio-{mode}", total=0)
        if run_id is None:
            self.send_error_json(HTTPStatus.CONFLICT, "A processing run is already active.")
            return
        self.send_json({"started": True, "runId": run_id, "command": command})

    def handle_audio_catalog(self, payload: dict[str, object]) -> None:
        """Return catalog metadata sealed into the selected audio batch folder."""

        raw_source_path = required_payload_text(payload, "sourcePath")
        if raw_source_path is None:
            raise ValueError("Choose an audio source folder first.")
        source_path = validate_existing_path(Path(raw_source_path), kind="folder")
        result = backend.scan_audio_catalog_run(source_path)
        if result is None:
            self.send_json({"catalog": False, "source_path": str(source_path)})
            return
        response = backend.scan_result_to_json(result)
        response["catalog"] = True
        self.send_json(response)

    def handle_run_analysis(self, payload: dict[str, object]) -> None:
        """Start the existing post-processing analysis scripts from the UI."""

        raw_source_path = required_payload_text(payload, "sourcePath")
        if raw_source_path is None:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "Choose an analysis source first.")
            return
        source_path = Path(raw_source_path)

        output_root = Path(
            backend.clean_user_supplied_path(str(payload.get("outputRoot") or backend.default_analysis_output_root(REPO_ROOT)))
        ).expanduser()
        mode = str(payload.get("mode") or "imotions")
        validate_processing_paths(
            source_path,
            output_root,
            label="Analysis",
            source_kind="folder",
        )
        request = backend.AnalysisRunRequest(
            mode=mode,
            source_path=source_path,
            output_root=output_root,
            write_graphs=payload_bool(payload, "writeGraphs", True),
            include_logscale=payload_bool(payload, "includeLogscale", False),
            include_landmarks=payload_bool(payload, "includeLandmarks", False),
            include_timing=payload_bool(payload, "includeTiming", False),
            exclude_geometry=payload_bool(payload, "excludeGeometry", False),
        )
        command = backend.build_analysis_command(request, repo_root=REPO_ROOT)
        APP_STATE.log(f"Starting {mode} analysis from {source_path.expanduser().resolve()}.")
        APP_STATE.log(f"Analysis output root: {output_root.expanduser().resolve()}")
        run_id = start_process(command, mode=f"analysis-{mode}", total=0)
        if run_id is None:
            self.send_error_json(HTTPStatus.CONFLICT, "A pipeline run is already active.")
            return
        self.send_json({"started": True, "runId": run_id, "command": command})

    def handle_run_analysis_workflow(self, payload: dict[str, object]) -> None:
        """Start one combined analysis coordinator for reviewed modality inputs."""

        request = analysis_workflow_request_from_payload(payload)
        for modality in request.modalities:
            validate_processing_paths(
                modality.source_path,
                request.output_root,
                label=f"{modality.name} analysis workflow",
                source_kind="folder",
                output_must_be_directory=True,
            )
        command = backend.build_analysis_workflow_command(request, repo_root=REPO_ROOT)
        APP_STATE.log(f"Starting combined analysis workflow into {request.output_root.expanduser().resolve()}.")
        run_id = start_process(command, mode="analysis-workflow", total=0)
        if run_id is None:
            self.send_error_json(HTTPStatus.CONFLICT, "A pipeline run is already active.")
            return
        self.send_json({"started": True, "runId": run_id, "command": command})

    def handle_analysis_speakers(self, payload: dict[str, object]) -> None:
        """Return selectable canonical speakers from existing analysis sources."""

        modalities = analysis_speaker_discovery_modalities_from_payload(payload)
        self.send_json(backend.discover_analysis_speakers(modalities))

    def handle_settings(self, payload: dict[str, object]) -> None:
        """Persist local launcher settings such as API keys."""

        backend.save_ui_settings(REPO_ROOT, payload)
        self.send_json({"settings": backend.public_ui_settings(REPO_ROOT)})

    def handle_revoke_access(self) -> None:
        """Set the EULA file to false and stop the local launcher."""

        APP_STATE.request_shutdown()
        access = backend.write_eula_state(REPO_ROOT, False)
        APP_STATE.log(f"Access revoked. EULA file updated: {access['eulaPath']}")
        self.send_json({"revoked": True, "access": access})
        begin_shutdown_cleanup(
            "Stopping active process before revoking access.",
            server=self.server,
        )

    def handle_close(self) -> None:
        """Ask the local server to stop after the response reaches the UI."""

        APP_STATE.request_shutdown()
        APP_STATE.log("Launcher close requested from the UI.")
        self.send_json({"closing": True})
        begin_shutdown_cleanup(
            "Stopping active process because the application is closing.",
            server=self.server,
        )

    def handle_stop(self) -> None:
        if terminate_active_process("Stopping active process."):
            self.send_json({"stopping": True})
            return
        self.send_json({"stopping": False})

    def handle_browse(self, payload: dict[str, object]) -> None:
        kind = str(payload.get("kind") or "folder")
        try:
            path = browse_for_path(kind)
        except Exception as exc:
            self.send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, f"Browse dialog failed: {exc}")
            return
        self.send_json({"path": str(path) if path else "", "cancelled": path is None})

    def handle_validate_path(self, payload: dict[str, object]) -> None:
        """Validate imported or pre-existing output paths before UI progression."""

        raw_path = required_payload_text(payload, "path")
        if raw_path is None:
            raise ValueError("Choose a path first.")
        kind = str(payload.get("kind") or "folder").casefold()
        resolved = validate_existing_path(Path(raw_path), kind=kind)
        self.send_json({"valid": True, "path": str(resolved), "kind": kind})

    def serve_static(self, target: Path | None) -> None:
        """Serve only files from the bundled static UI directory."""

        if target is None:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if not target.exists() or not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        data = target.read_bytes()
        if target == STATIC_INDEX:
            data = data.decode("utf-8").replace("__LAUNCHER_TOKEN__", API_TOKEN).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(data)

    def serve_media(self, parsed) -> None:
        """Stream an authorized local video for the Focus segment selector."""

        params = parse_qs(parsed.query)
        raw_path = params.get("path", [""])[0]
        media_path = Path(raw_path).expanduser().resolve()
        if not media_path.exists() or not media_path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if media_path.suffix.casefold() not in backend.VIDEO_EXTENSIONS or not APP_STATE.is_allowed_media_path(media_path):
            self.send_error(HTTPStatus.FORBIDDEN)
            return

        file_size = media_path.stat().st_size
        if file_size <= 0:
            self.send_error(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
            return

        status = HTTPStatus.OK
        range_header = self.headers.get("Range")
        if range_header:
            try:
                start, end = parse_http_byte_range(range_header, file_size)
            except ValueError:
                self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                self.send_header("Content-Range", f"bytes */{file_size}")
                self.send_header("Content-Length", "0")
                self.send_header("Referrer-Policy", "no-referrer")
                self.end_headers()
                return
            status = HTTPStatus.PARTIAL_CONTENT
        else:
            start, end = 0, file_size - 1
        length = end - start + 1

        self.send_response(status)
        self.send_header("Content-Type", mimetypes.guess_type(str(media_path))[0] or "application/octet-stream")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        self.send_header("Referrer-Policy", "no-referrer")
        if status == HTTPStatus.PARTIAL_CONTENT:
            self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
        self.end_headers()
        with media_path.open("rb") as handle:
            handle.seek(start)
            remaining = length
            while remaining > 0:
                chunk = handle.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def send_json(self, payload: dict[str, object], status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(data)

    def send_error_json(self, status: HTTPStatus, message: str) -> None:
        self.send_json({"error": message}, status=status)

    def send_access_denied(self, *, schedule_shutdown: bool = False) -> None:
        self.send_json(
            {
                "error": "Terms are not accepted. Restart the launcher and accept the terms prompt to continue.",
                "accessRevoked": True,
                "access": backend.load_eula_state(REPO_ROOT),
            },
            status=HTTPStatus.FORBIDDEN,
        )
        if schedule_shutdown:
            APP_STATE.request_shutdown()
            begin_shutdown_cleanup(
                "Stopping active process because terms are no longer accepted.",
                server=self.server,
            )


def parse_http_byte_range(range_header: str, file_size: int) -> tuple[int, int]:
    """Parse one RFC 7233 byte range, including suffix ranges used by players."""

    if file_size <= 0:
        raise ValueError("Cannot range an empty file.")
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", str(range_header or "").strip())
    if not match or (not match.group(1) and not match.group(2)):
        raise ValueError("Unsupported byte range.")

    start_text, end_text = match.groups()
    if not start_text:
        suffix_length = int(end_text)
        if suffix_length <= 0:
            raise ValueError("Suffix range must be positive.")
        return max(0, file_size - suffix_length), file_size - 1

    start = int(start_text)
    if start >= file_size:
        raise ValueError("Range starts after the end of the file.")
    end = int(end_text) if end_text else file_size - 1
    if end < start:
        raise ValueError("Range end precedes its start.")
    return start, min(end, file_size - 1)


def write_segment_manifest(
    output_root: Path,
    payload: dict[str, object],
    *,
    selected_speakers: list[str] | None = None,
    expected_source: str | Path | None = None,
    processing_source: str | Path,
) -> FocusManifestHandoff:
    """Validate and persist Focus selections for the procurement subprocess."""

    manifest = payload.get("segmentManifest")
    if not isinstance(manifest, dict):
        raise ValueError("Focus mode needs at least one selected segment.")
    if expected_source is not None and not source_references_match(manifest.get("source_path"), expected_source):
        raise ValueError("Focus selections belong to a different source. Scan the current source again.")
    selected_segments = validate_segment_manifest(
        manifest,
        selected_speakers=selected_speakers,
        require_scanned_source=True,
    )
    normalized_manifest = dict(manifest)
    normalized_manifest["selected_segments"] = selected_segments
    normalized_manifest["processing_source_path"] = str(Path(processing_source).expanduser().resolve())
    normalized_manifest["selected_total_seconds"] = round(
        sum(float(item["length_seconds"]) for item in selected_segments), 3
    )
    manifest_dir = output_root.expanduser().resolve() / "_ui_manifests"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    target = manifest_dir / f"focus_segments_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    manifest_bytes = (json.dumps(normalized_manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    digest = hashlib.sha256(manifest_bytes).hexdigest()
    target.write_bytes(manifest_bytes)
    APP_STATE.log(f"Focus segment manifest written: {target}")
    return FocusManifestHandoff(
        path=target,
        sha256=digest,
        expected_source=str(expected_source or normalized_manifest.get("source_path") or ""),
    )


def validate_segment_manifest(
    manifest: dict[str, object],
    *,
    selected_speakers: list[str] | None = None,
    require_scanned_source: bool = False,
) -> list[dict[str, object]]:
    """Normalize Focus intervals and reject invalid or overlapping selections."""

    selected_segments = manifest.get("selected_segments")
    if not isinstance(selected_segments, list) or not selected_segments:
        raise ValueError("Focus mode needs at least one selected segment.")
    if len(selected_segments) > MAX_FOCUS_SEGMENTS:
        raise ValueError(f"Focus mode supports at most {MAX_FOCUS_SEGMENTS} selected segments.")
    try:
        gap_seconds = float(manifest.get("gap_seconds") or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("Focus gap must be a number between 0 and 60 seconds.") from exc
    if not math.isfinite(gap_seconds) or not 0 <= gap_seconds <= 60:
        raise ValueError("Focus gap must be between 0 and 60 seconds.")
    grouped: dict[tuple[str, str], list[tuple[float, float]]] = {}
    allowed_speakers = {
        backend.run_docx_extractions.speaker_match_key(value)
        for value in selected_speakers or []
        if backend.run_docx_extractions.speaker_match_key(value)
    }
    normalized: list[dict[str, object]] = []
    for index, raw_segment in enumerate(selected_segments, start=1):
        if not isinstance(raw_segment, dict):
            raise ValueError(f"Focus segment {index} must be an object.")
        try:
            identity = backend.focus_source_identity(raw_segment)
        except ValueError as exc:
            raise ValueError(f"Focus segment {index} has an invalid source identity: {exc}") from exc
        if allowed_speakers and backend.run_docx_extractions.speaker_match_key(raw_segment.get("speaker")) not in allowed_speakers:
            raise ValueError(f"Focus segment {index} belongs to an unchecked speaker.")
        if require_scanned_source and not APP_STATE.is_allowed_segment_reference(raw_segment):
            raise ValueError(f"Focus segment {index} is not one of the videos in the current scan.")
        try:
            start = float(raw_segment.get("start_seconds"))
            end = float(raw_segment.get("end_seconds"))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Focus segment {index} has invalid times.") from exc
        if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end - start < 0.5:
            raise ValueError(f"Focus segment {index} must be at least 0.5 seconds and start at or after zero.")
        if require_scanned_source:
            duration = APP_STATE.allowed_duration_for_segment(raw_segment)
            if duration is None and identity.kind in {"file", "folder"}:
                source_path = str(raw_segment.get("source_path") or "").strip()
                if source_path and Path(source_path).expanduser().is_file():
                    duration = backend.read_duration_seconds(Path(source_path).expanduser())
            if duration is None or duration <= 0:
                raise ValueError(
                    f"Focus segment {index} cannot be validated because the scanned video duration is unavailable."
                )
            if end > duration + 0.05:
                raise ValueError(
                    f"Focus segment {index} ends at {end:.3f}s, after the video duration of {duration:.3f}s."
                )
        catalog_record = APP_STATE.catalog_record_for_segment(raw_segment, identity)
        if catalog_record is not None:
            overlap_key = ("source-id", catalog_record.source_id or catalog_record.id)
        else:
            overlap_key = (identity.kind, f"{identity.reference}:{identity.youtube_id}")
        intervals = grouped.setdefault(overlap_key, [])
        if any(start < old_end and end > old_start for old_start, old_end in intervals):
            raise ValueError(f"Focus segment {index} overlaps another selection from the same video.")
        intervals.append((start, end))
        item = dict(raw_segment)
        if catalog_record is not None:
            item["source_id"] = catalog_record.source_id or catalog_record.id
            item["metadata"] = dict(catalog_record.metadata)
            item["youtube_language"] = catalog_record.youtube_language
        else:
            metadata = item.get("metadata", {})
            if not isinstance(metadata, dict) or any(
                not isinstance(key, str) or not isinstance(value, str)
                for key, value in metadata.items()
            ):
                raise ValueError(f"Focus segment {index} metadata must contain text labels and values.")
            youtube_language = item.get("youtube_language", "")
            if not isinstance(youtube_language, str):
                raise ValueError(f"Focus segment {index} YouTube language must be text.")
        item["start_seconds"] = round(start, 3)
        item["end_seconds"] = round(end, 3)
        item["length_seconds"] = round(end - start, 3)
        normalized.append(item)
    return normalized


def source_references_match(left: object, right: object) -> bool:
    """Compare scanned and submitted source references across URL/path forms."""

    return backend.source_references_match(left, right)


def plural(count: int, singular: str, plural_value: str | None = None) -> str:
    return f"{count} {singular if count == 1 else plural_value or singular + 's'}"


def required_payload_text(payload: dict[str, object], key: str) -> str | None:
    """Return a stripped string value, treating blanks as missing."""

    value = backend.clean_user_supplied_path(str(payload.get(key) or ""))
    return value or None


def payload_text_list(value: object) -> list[str]:
    """Return non-empty text tokens from a comma/space separated payload field."""

    if isinstance(value, list):
        raw_items = value
    else:
        raw_items = re.split(r"[,;\s]+", str(value or ""))
    return [str(item).strip() for item in raw_items if str(item).strip()]


def analysis_workflow_request_from_payload(payload: dict[str, object]) -> backend.AnalysisWorkflowRunRequest:
    """Parse the complete combined-analysis payload without coercing its shape."""

    expected_keys = {
        "outputRoot",
        "writeCombinedWorkbook",
        "includeConstructComparison",
        "includeProbabilitySheets",
        "confidenceLevel",
        "headlinePolicy",
        "defaultReference",
        "referenceOverrides",
        "speakerGroups",
        "writeGraphs",
        "includeLogscale",
        "includeLandmarks",
        "includeTiming",
        "excludeGeometry",
        "modalities",
    }
    supplied_keys = set(payload)
    if supplied_keys != expected_keys:
        missing = sorted(expected_keys - supplied_keys)
        unknown = sorted(supplied_keys - expected_keys)
        details = []
        if missing:
            details.append(f"missing: {', '.join(missing)}")
        if unknown:
            details.append(f"unknown: {', '.join(unknown)}")
        raise ValueError(f"Invalid combined analysis workflow payload ({'; '.join(details)}).")

    output_root = Path(_workflow_required_text(payload["outputRoot"], "outputRoot")).expanduser()
    modalities = _analysis_modalities_from_payload(payload["modalities"])
    write_combined_workbook = _workflow_bool(payload["writeCombinedWorkbook"], "writeCombinedWorkbook")

    groups_value = payload["speakerGroups"]
    if not isinstance(groups_value, list):
        raise ValueError("speakerGroups must be a list.")
    groups: list[backend.AnalysisSpeakerGroupRunRequest] = []
    group_ids: set[str] = set()
    group_names: set[str] = set()
    assigned_speakers: set[str] = set()
    if len(groups_value) > 4:
        raise ValueError("The combined workbook supports at most four speaker groups.")
    for item in groups_value:
        if not isinstance(item, dict) or set(item) != {"id", "name", "speakerKeys"}:
            raise ValueError("Each speaker group must contain only id, name, and speakerKeys.")
        group_id = _workflow_required_text(item["id"], "speakerGroups.id")
        group_name = _workflow_required_text(item["name"], "speakerGroups.name")
        speaker_keys = item["speakerKeys"]
        if not isinstance(speaker_keys, list) or not speaker_keys:
            raise ValueError("speakerGroups.speakerKeys must be a non-empty list.")
        clean_speaker_keys = backend.canonical_analysis_speaker_ids(
            _workflow_required_text(key, "speakerGroups.speakerKeys") for key in speaker_keys
        )
        if len(clean_speaker_keys) > 3:
            raise ValueError("Each speaker group may contain at most three speakers.")
        if group_id in group_ids or group_name in group_names:
            raise ValueError("Speaker group ids and names must be unique.")
        if len(set(clean_speaker_keys)) != len(clean_speaker_keys) or assigned_speakers.intersection(clean_speaker_keys):
            raise ValueError("Each speaker may belong to only one speaker group.")
        groups.append(backend.AnalysisSpeakerGroupRunRequest(group_id, group_name, clean_speaker_keys))
        group_ids.add(group_id)
        group_names.add(group_name)
        assigned_speakers.update(clean_speaker_keys)
    if write_combined_workbook and not groups:
        raise ValueError("Choose at least one speaker group for the combined workbook.")

    overrides_value = payload["referenceOverrides"]
    if not isinstance(overrides_value, dict):
        raise ValueError("referenceOverrides must be an object.")
    reference_overrides = {
        _workflow_required_text(key, "referenceOverrides key"): _workflow_finite_number(value, "referenceOverrides value")
        for key, value in overrides_value.items()
    }
    confidence_level = _workflow_finite_number(payload["confidenceLevel"], "confidenceLevel")
    if not 0.0 < confidence_level < 1.0:
        raise ValueError("confidenceLevel must be between 0 and 1.")
    headline_policy = _workflow_required_text(payload["headlinePolicy"], "headlinePolicy").casefold()
    if headline_policy not in {"weighted", "equal"}:
        raise ValueError("headlinePolicy must be weighted or equal.")
    return backend.AnalysisWorkflowRunRequest(
        output_root=output_root,
        modalities=modalities,
        speaker_groups=tuple(groups),
        write_combined_workbook=write_combined_workbook,
        include_construct_comparison=_workflow_bool(
            payload["includeConstructComparison"],
            "includeConstructComparison",
        ),
        include_probability_sheets=_workflow_bool(
            payload["includeProbabilitySheets"],
            "includeProbabilitySheets",
        ),
        confidence_level=confidence_level,
        headline_policy=headline_policy,
        default_reference=_workflow_finite_number(payload["defaultReference"], "defaultReference"),
        reference_overrides=reference_overrides,
        write_graphs=_workflow_bool(payload["writeGraphs"], "writeGraphs"),
        include_logscale=_workflow_bool(payload["includeLogscale"], "includeLogscale"),
        include_landmarks=_workflow_bool(payload["includeLandmarks"], "includeLandmarks"),
        include_timing=_workflow_bool(payload["includeTiming"], "includeTiming"),
        exclude_geometry=_workflow_bool(payload["excludeGeometry"], "excludeGeometry"),
    )


def analysis_speaker_discovery_modalities_from_payload(
    payload: dict[str, object],
) -> tuple[backend.AnalysisModalityRunRequest, ...]:
    """Parse the read-only speaker discovery request and require source folders."""

    if set(payload) != {"modalities"}:
        raise ValueError("Analysis speaker discovery payload must contain only modalities.")
    modalities = _analysis_modalities_from_payload(payload["modalities"])
    for modality in modalities:
        source_path = modality.source_path.expanduser().resolve()
        if not source_path.exists():
            raise ValueError(f"{modality.name} analysis speaker source does not exist: {source_path}")
        if not source_path.is_dir():
            raise ValueError(f"{modality.name} analysis speaker source must be a folder: {source_path}")
    return modalities


def _analysis_modalities_from_payload(
    modalities_value: object,
) -> tuple[backend.AnalysisModalityRunRequest, ...]:
    if not isinstance(modalities_value, list) or not modalities_value:
        raise ValueError("modalities must be a non-empty list.")
    modalities: list[backend.AnalysisModalityRunRequest] = []
    modality_names: set[str] = set()
    for item in modalities_value:
        if not isinstance(item, dict) or set(item) != {"name", "sourceMethod", "sourcePath"}:
            raise ValueError("Each modality must contain only name, sourceMethod, and sourcePath.")
        name = _workflow_required_text(item["name"], "modalities.name").casefold()
        if name not in {"imotions", "audio", "text"}:
            raise ValueError(f"Unsupported analysis workflow modality: {name}")
        if name in modality_names:
            raise ValueError(f"Duplicate analysis workflow modality: {name}")
        source_method = _workflow_required_text(item["sourceMethod"], "modalities.sourceMethod").casefold()
        if source_method not in {"run", "import"}:
            raise ValueError(f"Unsupported source method for {name}: {source_method}")
        if name == "text" and source_method != "import":
            raise ValueError("Text results are import-only in the combined workflow.")
        modalities.append(
            backend.AnalysisModalityRunRequest(
                name=name,
                source_method=source_method,
                source_path=Path(_workflow_required_text(item["sourcePath"], "modalities.sourcePath")).expanduser(),
            )
        )
        modality_names.add(name)
    return tuple(modalities)


def _workflow_required_text(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a nonblank string.")
    clean_value = backend.clean_user_supplied_path(value)
    if not clean_value:
        raise ValueError(f"{label} must be a nonblank string.")
    return clean_value


def _workflow_bool(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{label} must be true or false.")
    return value


def _workflow_finite_number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite number.")
    numeric_value = float(value)
    if not math.isfinite(numeric_value):
        raise ValueError(f"{label} must be a finite number.")
    return numeric_value


def payload_float(payload: dict[str, object], key: str, default: float) -> float:
    """Read a finite numeric payload value without replacing a valid zero."""

    value = payload.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        return float(default)
    if isinstance(value, bool):
        raise ValueError(f"{key} must be a number.")
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{key} must be a number.") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"{key} must be a finite number.")
    return parsed


def payload_int(payload: dict[str, object], key: str, default: int) -> int:
    """Read an integer payload value while rejecting silent truncation."""

    parsed = payload_float(payload, key, float(default))
    if not parsed.is_integer():
        raise ValueError(f"{key} must be a whole number.")
    return int(parsed)


def payload_bool(payload: dict[str, object], key: str, default: bool) -> bool:
    """Read one JSON-style boolean and reject ambiguous truthy strings."""

    value = payload.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        return bool(default)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in {0, 1}:
        return bool(value)
    cleaned = str(value).strip().casefold()
    if cleaned in {"true", "yes", "on"}:
        return True
    if cleaned in {"false", "no", "off"}:
        return False
    raise ValueError(f"{key} must be true or false.")


def validate_processing_paths(
    source_path: Path,
    output_root: Path,
    *,
    label: str,
    source_kind: str,
    output_must_be_directory: bool = False,
) -> None:
    """Reject missing, mistyped, or overlapping processing paths."""

    source = source_path.expanduser().resolve()
    output = output_root.expanduser().resolve()
    if not source.exists():
        raise ValueError(f"{label} source does not exist: {source}")
    if source_kind == "folder" and not source.is_dir():
        raise ValueError(f"{label} source must be a folder: {source}")
    if source_kind == "file" and not source.is_file():
        raise ValueError(f"{label} source must be a file: {source}")
    if source_kind == "file" and source.suffix.casefold() not in backend.VIDEO_EXTENSIONS:
        supported = ", ".join(sorted(backend.VIDEO_EXTENSIONS))
        raise ValueError(f"{label} source must be a supported video ({supported}): {source}")
    if source_kind == "file-or-folder" and not (source.is_file() or source.is_dir()):
        raise ValueError(f"{label} source must be a file or folder: {source}")
    if output_must_be_directory and output.exists() and not output.is_dir():
        raise ValueError(f"{label} output must be a folder: {output}")
    if source == output or source in output.parents or output in source.parents:
        raise ValueError(f"{label} input and output paths must not overlap.")


def validate_existing_path(path: Path, *, kind: str) -> Path:
    """Return a resolved existing path of the type requested by the UI."""

    resolved = path.expanduser().resolve()
    if kind not in {"folder", "file", "file-or-folder"}:
        raise ValueError(f"Unsupported path type: {kind}")
    if not resolved.exists():
        raise ValueError(f"Path does not exist: {resolved}")
    if kind == "folder" and not resolved.is_dir():
        raise ValueError(f"Path must be a folder: {resolved}")
    if kind == "file" and not resolved.is_file():
        raise ValueError(f"Path must be a file: {resolved}")
    if kind == "file-or-folder" and not (resolved.is_file() or resolved.is_dir()):
        raise ValueError(f"Path must be a file or folder: {resolved}")
    return resolved


def launcher_authority(server_address: tuple[object, ...]) -> str:
    """Format the exact Host authority for an IPv4 or IPv6 loopback server."""

    host = str(server_address[0])
    port = int(server_address[1])
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        authority_host = host
    else:
        authority_host = f"[{address.compressed}]" if address.version == 6 else address.compressed
    return f"{authority_host}:{port}"


def launcher_origin(server_address: tuple[object, ...]) -> str:
    return f"http://{launcher_authority(server_address)}"


def launcher_token_is_valid(
    header_token: str,
    query_token: str,
    expected_token: str | None = None,
) -> bool:
    """Validate either the custom header token or the media query token."""

    return secrets.compare_digest(header_token or query_token, expected_token or API_TOKEN)


def parse_progress_line(line: str) -> dict[str, object] | None:
    """Convert known subprocess log lines into lightweight UI progress."""

    text = str(line or "").strip()
    if not text:
        return None
    workflow_failure = re.fullmatch(r"WorkflowError(?: \[([^\]]+)\])?:\s*(.+)", text, flags=re.IGNORECASE)
    if workflow_failure:
        failed_stage = (workflow_failure.group(1) or "workflow").strip()
        error = workflow_failure.group(2).strip()[:1000]
        return {
            "failedStage": failed_stage,
            "error": error,
            "label": error,
        }
    workflow_start = re.fullmatch(
        r"Starting (Video / iMotions|Audio) analysis",
        text,
        flags=re.IGNORECASE,
    )
    if workflow_start:
        label = workflow_start.group(1)
        return {"stage": f"{label} analysis", "current": None, "label": f"Analysing {label}"}
    if text.casefold() == "starting combined workbook":
        return {"stage": "combined workbook", "current": None, "label": "Building combined workbook"}
    workflow_complete = re.fullmatch(
        r"Completed (Video / iMotions|Audio) analysis:\s*(.+)",
        text,
        flags=re.IGNORECASE,
    )
    if workflow_complete:
        label = workflow_complete.group(1)
        modality = "video" if label.casefold().startswith("video") else "audio"
        return {
            "stage": f"{label} analysis",
            "current": None,
            "label": f"{label} analysis complete",
            "completedOutput": {"modality": modality, "path": workflow_complete.group(2).strip()},
        }
    if text.casefold() == "completed combined workbook":
        return {"stage": "combined workbook", "current": None, "label": "Combined workbook complete"}
    isolated_start = re.search(r"Starting isolated child for global video\s+(\d+)/(\d+):\s*(.+)", text, flags=re.IGNORECASE)
    if isolated_start:
        current = max(0, int(isolated_start.group(1)) - 1)
        total = int(isolated_start.group(2))
        return {"current": current, "total": total, "label": f"Processing {isolated_start.group(3)}"}
    isolated_skip = re.search(r"Skipping completed global video\s+(\d+)/(\d+):\s*(.+)", text, flags=re.IGNORECASE)
    if isolated_skip:
        current = int(isolated_skip.group(1))
        total = int(isolated_skip.group(2))
        return {"current": current, "total": total, "label": f"Skipped completed {isolated_skip.group(3)}"}
    beta_complete = re.search(r"Clean speaker beta complete:\s*(\d+)\s+processed,\s*(\d+)\s+failed", text, flags=re.IGNORECASE)
    if beta_complete:
        processed = int(beta_complete.group(1))
        failed = int(beta_complete.group(2))
        return {"current": processed + failed, "label": f"{processed} clean speaker videos processed, {failed} failed"}
    beta_processed = re.search(r"^Clean speaker beta processed videos:\s*(\d+)", text, flags=re.IGNORECASE)
    if beta_processed:
        processed = int(beta_processed.group(1))
        return {"current": processed, "label": f"{processed} clean speaker videos processed"}
    pipeline_item = re.search(r"^\[(\d+)/(\d+)\]\s+(.+)$", text)
    if pipeline_item:
        current = int(pipeline_item.group(1)) - 1
        total = int(pipeline_item.group(2))
        return {"current": max(0, current), "total": total, "label": f"Processing {pipeline_item.group(3)}"}
    complete = re.search(r"complete:\s*(\d+)\s+processed,\s*(\d+)\s+failed", text, flags=re.IGNORECASE)
    if complete:
        processed = int(complete.group(1))
        failed = int(complete.group(2))
        return {"current": processed + failed, "label": f"{processed} processed, {failed} failed"}
    if text.casefold() == "pipeline complete.":
        return {"current": None, "label": "Pipeline complete"}
    processing = re.search(r"^(?:=+\s*)?Processing\s+(.+)$", text, flags=re.IGNORECASE)
    if processing:
        return {"current": None, "label": f"Processing {processing.group(1)}"}
    if "Focus stitched output:" in text or "Manual stitched output:" in text:
        return {"current": None, "label": "Focus segments stitched"}
    audio_processed = re.search(r"^Processed videos:\s*(\d+)", text, flags=re.IGNORECASE)
    if audio_processed:
        processed = int(audio_processed.group(1))
        return {"current": processed, "label": f"{processed} audio videos processed"}
    audio_failed = re.search(r"^Failed videos:\s*(\d+)", text, flags=re.IGNORECASE)
    if audio_failed:
        failed = int(audio_failed.group(1))
        return {"current": None, "label": f"{failed} audio videos failed"}
    return None


def start_process(command: list[str], *, mode: str, total: int) -> int | None:
    """Start a long-running tool and mirror its output into launcher state."""

    run_id = APP_STATE.reserve_process(command, mode=mode, total=total)
    if run_id is None:
        return None
    APP_STATE.log(f"PS> {subprocess.list2cmdline(command)}")
    env = child_process_environment(command)
    env["PYTHONUNBUFFERED"] = "1"
    settings = backend.load_ui_settings(REPO_ROOT)
    if bool(settings.get("resourceLimitsEnabled", True)):
        native_threads = str(int(settings.get("nativeThreads") or 1))
        for name in (
            "OMP_NUM_THREADS",
            "MKL_NUM_THREADS",
            "OPENBLAS_NUM_THREADS",
            "NUMEXPR_NUM_THREADS",
            "VECLIB_MAXIMUM_THREADS",
            "ONNX_NUM_THREADS",
            "ORT_NUM_THREADS",
        ):
            env[name] = native_threads
        env["MEA_NATIVE_THREADS"] = native_threads
    cookies_browser = str(settings.get("youtubeCookiesBrowser") or "").strip()
    if cookies_browser:
        env["YT_DLP_COOKIES_FROM_BROWSER"] = cookies_browser
    try:
        process = subprocess.Popen(
            command,
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=env,
        )
    except Exception as exc:
        APP_STATE.fail_process_start(f"Failed to start process: {exc}", run_id)
        raise
    job_handle = assign_process_to_kill_job(process)
    if job_handle is not None:
        APP_STATE.attach_job_handle(run_id, job_handle)
    elif os.name == "nt":
        APP_STATE.log("Process safety: Windows Job Object unavailable; using verified process-tree cleanup.")
    stop_after_start = APP_STATE.attach_process(process, run_id)
    if stop_after_start:
        APP_STATE.log("The run was cancelled while its child process was starting; stopping it now.")
        terminate_process_tree(process)
        APP_STATE.finish_process(-1, run_id)
        return run_id
    try:
        configure_process_resources(process, settings)
    except Exception as exc:
        # Resource controls are protective. A platform-specific affinity or
        # telemetry failure must never leave a running child without a reader.
        APP_STATE.log(f"Resource controls could not be configured ({exc}); continuing with monitoring disabled.")
    thread = threading.Thread(target=read_process_output, args=(process, run_id), daemon=True)
    thread.start()
    return run_id


def child_process_environment(
    command: list[str],
    *,
    base_environment: dict[str, str] | None = None,
) -> dict[str, str]:
    """Return a child environment containing only credentials its module needs."""

    env = dict(os.environ if base_environment is None else base_environment)
    for name in ("YOUTUBE_API_KEY", "HF_TOKEN", "HUGGINGFACE_TOKEN", "HUGGING_FACE_HUB_TOKEN"):
        env.pop(name, None)

    module = ""
    try:
        module = command[command.index("-m") + 1].strip().casefold()
    except (ValueError, IndexError):
        pass

    if module == "procurement.run_pipeline":
        api_key = backend.load_youtube_api_key()
        if api_key:
            env["YOUTUBE_API_KEY"] = api_key
    elif module.startswith("procurement.procurement_beta"):
        huggingface_token = backend.load_huggingface_token()
        if huggingface_token:
            env["HF_TOKEN"] = huggingface_token
    elif module == "procurement.catalog_runner":
        api_key = backend.load_youtube_api_key()
        if api_key:
            env["YOUTUBE_API_KEY"] = api_key
        try:
            catalog_mode = command[command.index("--mode") + 1].strip().casefold()
        except (ValueError, IndexError):
            catalog_mode = "standard"
        if catalog_mode == "clean-speaker-beta":
            huggingface_token = backend.load_huggingface_token()
            if huggingface_token:
                env["HF_TOKEN"] = huggingface_token
    return env


def read_process_output(process: subprocess.Popen[str], run_id: int) -> None:
    returncode = -1
    try:
        assert process.stdout is not None
        for line in process.stdout:
            APP_STATE.append_for_run(line.rstrip("\r\n"), run_id)
        returncode = process.wait()
    except Exception as exc:
        APP_STATE.append_for_run(f"Process output reader failed: {exc}", run_id)
        terminate_process_tree(process)
        polled_returncode = process.poll()
        returncode = polled_returncode if polled_returncode is not None else -1
    if APP_STATE.finish_process(returncode, run_id):
        APP_STATE.log(f"Process exited with code {returncode}.")


def cpu_affinity_indices(
    logical_cpu_count: int,
    maximum_percent: float,
    maximum_cores: int = 0,
) -> list[int]:
    """Translate a CPU percentage into a stable inherited core affinity."""

    logical = max(1, int(logical_cpu_count))
    percentage = max(1.0, min(100.0, float(maximum_percent)))
    allowed_count = max(1, min(logical, math.ceil(logical * percentage / 100.0)))
    if int(maximum_cores) > 0:
        allowed_count = min(allowed_count, int(maximum_cores))
    return list(range(allowed_count))


def ram_limit_status(
    settings: dict[str, object],
    *,
    system_used_percent: float,
    process_tree_rss_bytes: int,
) -> tuple[bool, str]:
    """Return whether the configured RAM ceiling has been reached."""

    mode = str(settings.get("ramLimitMode") or "percent").casefold()
    if mode == "gb":
        limit_gb = float(settings.get("maxRamGb") or 16.0)
        used_gb = process_tree_rss_bytes / (1024 ** 3)
        return used_gb >= limit_gb, f"tool RAM {used_gb:.1f}/{limit_gb:.1f} GB"
    limit_percent = float(settings.get("maxRamPercent") or 90.0)
    return system_used_percent >= limit_percent, f"system RAM {system_used_percent:.1f}/{limit_percent:.1f}%"


def configure_process_resources(
    process: subprocess.Popen[str],
    settings: dict[str, object],
) -> None:
    """Apply the release resource policy to a new pipeline process."""

    if not bool(settings.get("resourceLimitsEnabled", True)):
        APP_STATE.log("Resource controls are disabled in Settings.")
        return
    try:
        import psutil
    except ImportError:
        APP_STATE.log("Resource controls unavailable: install psutil.")
        return

    try:
        managed = psutil.Process(process.pid)
        affinity = cpu_affinity_indices(
            os.cpu_count() or 1,
            float(settings.get("maxCpuPercent") or 90.0),
            int(settings.get("maxCpuCores") or 0),
        )
        managed.cpu_affinity(affinity)
        APP_STATE.log(f"Resource control: CPU affinity limited to {len(affinity)}/{os.cpu_count() or 1} logical cores.")
    except (psutil.AccessDenied, psutil.NoSuchProcess, AttributeError, OSError, ValueError) as exc:
        APP_STATE.log(f"Resource control: CPU affinity could not be applied ({exc}).")

    monitor = threading.Thread(
        target=monitor_process_resources,
        args=(process, dict(settings)),
        daemon=True,
        name=f"resource-monitor-{process.pid}",
    )
    monitor.start()


def monitor_process_resources(
    process: subprocess.Popen[str],
    settings: dict[str, object],
) -> None:
    """Pause resource-heavy work and hard-stop sustained RAM pressure."""

    try:
        import psutil
    except ImportError:
        return
    poll_seconds = float(settings.get("resourcePollSeconds") or 2.0)
    max_cpu_percent = float(settings.get("maxCpuPercent") or 90.0)
    max_gpu_percent = float(settings.get("maxGpuPercent") or 95.0)
    suspended = False
    ram_pressure_started: float | None = None

    while process.poll() is None:
        processes = get_process_tree(psutil, process.pid)
        if not processes:
            return
        tree_rss = sum(safe_process_rss(item, psutil) for item in processes)
        system_ram_percent = float(psutil.virtual_memory().percent)
        cpu_percent = float(psutil.cpu_percent(interval=0.1))
        ram_high, ram_label = ram_limit_status(
            settings,
            system_used_percent=system_ram_percent,
            process_tree_rss_bytes=tree_rss,
        )
        gpu_percent = read_nvidia_gpu_percent()
        cpu_high = cpu_percent >= max_cpu_percent
        gpu_high = gpu_percent is not None and gpu_percent >= max_gpu_percent

        if ram_high or cpu_high or gpu_high:
            if ram_high and ram_pressure_started is None:
                ram_pressure_started = time.monotonic()
            if not suspended:
                reasons = [ram_label] if ram_high else []
                if cpu_high:
                    reasons.append(f"CPU {cpu_percent:.1f}/{max_cpu_percent:.1f}%")
                if gpu_high:
                    reasons.append(f"GPU {gpu_percent:.1f}/{max_gpu_percent:.1f}%")
                if set_process_tree_suspended(processes, psutil, suspended=True):
                    suspended = True
                    APP_STATE.log(f"Resource control paused the tool: {', '.join(reasons)}.")
                else:
                    APP_STATE.log("Resource control could not pause the process tree; it will retry.")
            if ram_high and ram_pressure_started is not None and time.monotonic() - ram_pressure_started >= 30.0:
                APP_STATE.log(
                    "Resource control stopped the pipeline after RAM remained above its limit for 30 seconds."
                )
                terminate_process_tree(process)
                return
        else:
            ram_pressure_started = None
            if suspended and resource_levels_are_below_resume_threshold(
                settings,
                system_ram_percent=system_ram_percent,
                process_tree_rss_bytes=tree_rss,
                cpu_percent=cpu_percent,
                gpu_percent=gpu_percent,
            ):
                if set_process_tree_suspended(processes, psutil, suspended=False):
                    suspended = False
                    APP_STATE.log("Resource control resumed the tool.")
        time.sleep(max(0.5, poll_seconds))


def resource_levels_are_below_resume_threshold(
    settings: dict[str, object],
    *,
    system_ram_percent: float,
    process_tree_rss_bytes: int,
    cpu_percent: float | None = None,
    gpu_percent: float | None,
) -> bool:
    """Use hysteresis so a paused process does not rapidly stop and start."""

    if str(settings.get("ramLimitMode") or "percent").casefold() == "gb":
        ram_ready = process_tree_rss_bytes / (1024 ** 3) <= float(settings.get("maxRamGb") or 16.0) * 0.95
    else:
        ram_ready = system_ram_percent <= max(0.0, float(settings.get("maxRamPercent") or 90.0) - 5.0)
    cpu_ready = cpu_percent is None or cpu_percent <= max(0.0, float(settings.get("maxCpuPercent") or 90.0) - 5.0)
    gpu_ready = gpu_percent is None or gpu_percent <= max(0.0, float(settings.get("maxGpuPercent") or 95.0) - 5.0)
    return ram_ready and cpu_ready and gpu_ready


def get_process_tree(psutil_module, process_id: int) -> list[object]:
    try:
        parent = psutil_module.Process(process_id)
        return [parent, *parent.children(recursive=True)]
    except (psutil_module.NoSuchProcess, psutil_module.AccessDenied):
        return []


def safe_process_rss(process: object, psutil_module) -> int:
    try:
        return int(process.memory_info().rss)
    except (psutil_module.NoSuchProcess, psutil_module.AccessDenied):
        return 0


def set_process_tree_suspended(processes: list[object], psutil_module, *, suspended: bool) -> bool:
    """Change process state and report whether at least one process changed."""

    ordered = processes if suspended else list(reversed(processes))
    changed = False
    for item in ordered:
        try:
            item.suspend() if suspended else item.resume()
            changed = True
        except (psutil_module.NoSuchProcess, psutil_module.AccessDenied):
            continue
    return changed


def read_nvidia_gpu_percent() -> float | None:
    """Return peak system NVIDIA GPU utilization, if telemetry is available."""

    try:
        result = subprocess.run(
            [
                str(resolve_nvidia_smi()),
                "--query-gpu=utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            env=credential_free_media_environment(),
        )
        values = [float(line.strip()) for line in result.stdout.splitlines() if line.strip()]
        return max(values) if values else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def terminate_process_tree(process: subprocess.Popen[str]) -> None:
    """Terminate a pipeline and its descendants so workers are not orphaned."""

    try:
        import psutil
    except ImportError:
        process.terminate()
        return
    processes = get_process_tree(psutil, process.pid)
    if not processes:
        try:
            process.terminate()
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        except OSError:
            pass
        return
    for item in reversed(processes):
        try:
            item.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    _, alive = psutil.wait_procs(processes, timeout=5)
    for item in alive:
        try:
            item.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    if alive:
        psutil.wait_procs(alive, timeout=5)
    if process.poll() is None:
        try:
            process.kill()
            process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            pass


def assign_process_to_kill_job(process: subprocess.Popen[str]) -> int | None:
    """Put a Windows child in a job that dies if the launcher process exits."""

    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class IoCounters(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_ulonglong),
                ("WriteOperationCount", ctypes.c_ulonglong),
                ("OtherOperationCount", ctypes.c_ulonglong),
                ("ReadTransferCount", ctypes.c_ulonglong),
                ("WriteTransferCount", ctypes.c_ulonglong),
                ("OtherTransferCount", ctypes.c_ulonglong),
            ]

        class BasicLimitInformation(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class ExtendedLimitInformation(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BasicLimitInformation),
                ("IoInfo", IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL

        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            return None
        information = ExtendedLimitInformation()
        information.BasicLimitInformation.LimitFlags = 0x00002000
        if not kernel32.SetInformationJobObject(
            handle,
            9,
            ctypes.byref(information),
            ctypes.sizeof(information),
        ):
            close_windows_handle(int(handle))
            return None
        process_handle = wintypes.HANDLE(int(getattr(process, "_handle")))
        if not kernel32.AssignProcessToJobObject(handle, process_handle):
            close_windows_handle(int(handle))
            return None
        return int(handle)
    except (AttributeError, OSError, TypeError, ValueError):
        return None


def close_windows_handle(handle: int) -> None:
    if os.name != "nt" or not handle:
        return
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.CloseHandle(wintypes.HANDLE(handle))
    except (OSError, TypeError, ValueError):
        pass


def process_is_running() -> bool:
    with APP_STATE.lock:
        return APP_STATE.starting or APP_STATE.process is not None


def terminate_active_process(reason: str) -> bool:
    """Terminate the running child process if one exists."""

    with PROCESS_TERMINATION_LOCK:
        requested, process = APP_STATE.request_process_stop()
        if not requested:
            return False
        with APP_STATE.lock:
            run_id = APP_STATE.active_run_id
        APP_STATE.log(reason)
        if process is not None:
            returncode = process.poll()
            if returncode is None:
                terminate_process_tree(process)
                returncode = process.poll()
            APP_STATE.finish_process(returncode if returncode is not None else -1, run_id)
        return True


def begin_shutdown_cleanup(reason: str, *, server=None) -> threading.Thread:
    """Perform slow child/server shutdown away from native and HTTP UI threads."""

    APP_STATE.request_shutdown()

    def cleanup() -> None:
        terminate_active_process(reason)
        if server is not None:
            server.shutdown()

    thread = threading.Thread(
        target=cleanup,
        daemon=False,
        name="launcher-shutdown-cleanup",
    )
    thread.start()
    return thread


def browse_for_path(kind: str) -> Path | None:
    """Open a native Windows picker for folders, DOCX files, or videos."""

    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        if kind == "source-file":
            value = filedialog.askopenfilename(
                title="Select DOCX list or video",
                filetypes=[
                    ("Supported sources", "*.docx *.mp4 *.mov *.mkv *.webm *.avi"),
                    ("DOCX files", "*.docx"),
                    ("Video files", "*.mp4 *.mov *.mkv *.webm *.avi"),
                ],
            )
        elif kind == "docx":
            value = filedialog.askopenfilename(
                title="Select DOCX video list",
                filetypes=[("DOCX files", "*.docx"), ("All files", "*.*")],
            )
        elif kind == "video":
            value = filedialog.askopenfilename(
                title="Select video",
                filetypes=[("Video files", "*.mp4 *.mov *.mkv *.webm *.avi"), ("All files", "*.*")],
            )
        else:
            value = filedialog.askdirectory(title="Select folder")
    finally:
        root.destroy()
    return Path(value) if value else None


def open_app_window(url: str) -> subprocess.Popen[bytes] | None:
    """Fallback to browser app mode when the native desktop shell is unavailable."""

    candidates = [
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    ]
    for executable in candidates:
        if executable.exists():
            process = subprocess.Popen(
                [
                    str(executable),
                    f"--app={url}",
                    "--new-window",
                    "--no-first-run",
                    "--no-default-browser-check",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=credential_free_media_environment(),
            )
            APP_STATE.log(f"Opened standalone app window via {executable.name}.")
            return process

    if hasattr(os, "startfile"):
        os.startfile(url)  # type: ignore[attr-defined]
        APP_STATE.log("Opened default URL handler because no app-mode browser was found.")
    return None


def monitor_browser_session(
    server: LauncherHttpServer,
    browser_process: subprocess.Popen[bytes] | None,
    *,
    startup_timeout_seconds: float = 30.0,
    heartbeat_timeout_seconds: float = 90.0,
) -> None:
    """Stop the local server after the browser fallback stops polling it."""

    if not APP_STATE.client_seen.wait(timeout=startup_timeout_seconds):
        APP_STATE.log("Browser window did not connect; stopping the launcher.")
        APP_STATE.request_shutdown()
        server.shutdown()
        return

    while not APP_STATE.shutdown_requested:
        with APP_STATE.lock:
            last_seen = APP_STATE.last_client_seen
        if last_seen and time.monotonic() - last_seen > heartbeat_timeout_seconds:
            APP_STATE.log("Browser window disconnected; stopping the launcher.")
            APP_STATE.request_shutdown()
            terminate_active_process("Stopping active process because the browser window closed.")
            server.shutdown()
            return
        if browser_process is not None and browser_process.poll() is not None:
            # Edge may hand the app window to an existing process, so only the
            # heartbeat decides whether the UI is really gone.
            browser_process = None
        time.sleep(2.0)


def acquire_single_instance_lock(repo_root: Path):
    """Hold an OS file lock so two launchers cannot run the same checkout."""

    lock_path = repo_root.expanduser().resolve() / "_local" / "launcher.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+b")
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"0")
        handle.flush()
    handle.seek(0)
    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, BlockingIOError):
        handle.close()
        return None
    return handle


def release_single_instance_lock(handle) -> None:
    if handle is None:
        return
    try:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()
        return


def set_windows_app_identity() -> None:
    """Give the native window its own Windows taskbar grouping identity."""

    if os.name != "nt":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception as exc:
        APP_STATE.log(f"Could not set the Windows app identity: {exc}")


def native_window_options() -> dict[str, object]:
    """Return unconstrained desktop defaults that work at any aspect ratio."""

    return {
        "width": 1400,
        "height": 900,
        "min_size": (640, 480),
        "resizable": True,
        "maximized": True,
        "background_color": "#eef2f6",
    }


def native_webview_start_options() -> dict[str, object]:
    """Use a persistent profile so pywebview never deletes it on the UI thread."""

    return {
        "gui": "edgechromium",
        "debug": False,
        "private_mode": False,
        "storage_path": str(WEBVIEW_STORAGE_ROOT),
    }


def run_native_app_window(url: str) -> bool:
    """Run the local UI in WebView2 so Windows does not present it as Edge."""

    try:
        import webview
    except ImportError:
        APP_STATE.log("Native desktop shell is not installed; using browser app mode.")
        return False

    try:
        set_windows_app_identity()
        WEBVIEW_STORAGE_ROOT.mkdir(parents=True, exist_ok=True)
        native_api = NativeWindowApi()
        window = webview.create_window(
            APP_TITLE,
            url,
            js_api=native_api,
            **native_window_options(),
        )
        native_api.bind_window(window)
        cleanup_lock = threading.Lock()
        cleanup_threads: list[threading.Thread] = []

        def stop_pipeline_on_close(*_args) -> None:
            """Start potentially slow process-tree cleanup away from the UI loop."""

            with cleanup_lock:
                if cleanup_threads:
                    return
                APP_STATE.request_shutdown()
                cleanup_thread = begin_shutdown_cleanup(
                    "Stopping active process because the application window was closed.",
                )
                cleanup_threads.append(cleanup_thread)

        window.events.closing += stop_pipeline_on_close
        APP_STATE.log("Opening resizable native WebView2 window (F11 toggles full screen).")
        webview.start(**native_webview_start_options())
        if cleanup_threads:
            cleanup_threads[0].join(timeout=10)
            if cleanup_threads[0].is_alive():
                APP_STATE.log("Pipeline shutdown is still completing in the background.")
        return True
    except Exception as exc:
        APP_STATE.log(f"Native desktop shell failed: {type(exc).__name__}: {exc}")
        return False


def ensure_eula_accepted(repo_root: Path, *, prompt_acceptance=None) -> bool:
    """Prompt for EULA acceptance when the local terms file is false."""

    access = backend.load_eula_state(repo_root)
    if access["termsAccepted"]:
        return True

    eula_file = Path(str(access["eulaPath"]))
    APP_STATE.log("Terms are not accepted; showing native acceptance prompt.")
    APP_STATE.log(f"EULA file: {eula_file}")
    prompt = prompt_acceptance or prompt_eula_acceptance
    if not prompt(eula_file):
        APP_STATE.log("Terms were declined; launcher UI will not open.")
        return False

    accepted = backend.write_eula_state(repo_root, True)
    APP_STATE.log(f"Terms accepted. EULA file updated: {accepted['eulaPath']}")
    return True


def prompt_eula_acceptance(eula_file: Path) -> bool:
    """Show a native desktop prompt with explicit accept/decline actions."""

    message = (
        "Only process videos, audio, text, and derived data that you are permitted to use.\n\n"
        "API keys are stored locally on this computer. Outputs may contain sensitive inferred information.\n\n"
        f"Acceptance will be recorded in:\n{eula_file}"
    )
    try:
        import tkinter as tk

        root = tk.Tk()
        root.title(f"{APP_TITLE} Terms")
        root.attributes("-topmost", True)
        root.resizable(False, False)
        accepted = {"value": False}

        def accept() -> None:
            accepted["value"] = True
            root.destroy()

        def decline() -> None:
            root.destroy()

        frame = tk.Frame(root, padx=24, pady=20)
        frame.grid(row=0, column=0)
        title = tk.Label(frame, text="Terms of use", font=("Segoe UI", 14, "bold"), anchor="w")
        title.grid(row=0, column=0, columnspan=2, sticky="w")
        body = tk.Label(frame, text=message, justify="left", wraplength=520, anchor="w")
        body.grid(row=1, column=0, columnspan=2, sticky="w", pady=(12, 18))
        decline_button = tk.Button(frame, text="Decline and close", command=decline, width=18)
        decline_button.grid(row=2, column=0, sticky="e", padx=(0, 10))
        accept_button = tk.Button(frame, text="Accept terms and continue", command=accept, width=24)
        accept_button.grid(row=2, column=1, sticky="e")
        accept_button.focus_set()
        root.protocol("WM_DELETE_WINDOW", decline)
        root.mainloop()
        return accepted["value"]
    except Exception:
        APP_STATE.log("Could not show the native terms prompt.")
        return False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=f"Launch the local {APP_TITLE}.")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-browser", action="store_true")
    return parser.parse_args()


def create_server(host: str, preferred_port: int) -> LauncherHttpServer:
    """Bind the first available port in a small predictable range."""

    try:
        address = ipaddress.ip_address(socket.gethostbyname(host))
    except (OSError, ValueError) as exc:
        raise ValueError(f"Launcher host is invalid: {host}") from exc
    if not address.is_loopback:
        raise ValueError("The desktop launcher may bind only to a loopback address.")
    last_error: OSError | None = None
    for port in range(preferred_port, preferred_port + 25):
        try:
            return LauncherHttpServer((host, port), VideoStackUiHandler)
        except OSError as exc:
            last_error = exc
    raise RuntimeError(f"Could not bind a local launcher UI port: {last_error}")


def run_launcher(args: argparse.Namespace) -> int:
    """Run one already-locked desktop launcher instance."""

    APP_STATE.reset_shutdown()
    APP_STATE.reset_client_seen()
    if not ensure_eula_accepted(REPO_ROOT):
        return 1

    server = create_server(args.host, args.port)
    host, port = server.server_address
    origin = launcher_origin(server.server_address)
    public_url = f"{origin}/"
    bootstrap_url = f"{public_url}?token={quote(API_TOKEN, safe='')}"
    APP_STATE.log(f"{APP_TITLE} launcher started.")
    APP_STATE.log(f"Repository: {REPO_ROOT}")
    APP_STATE.log(f"Open: {public_url}")
    APP_STATE.log("Ready.")
    if not args.no_browser:
        server_thread = threading.Thread(
            target=server.serve_forever,
            daemon=True,
            name="launcher-http-server",
        )
        server_thread.start()
        if run_native_app_window(bootstrap_url):
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=5)
            APP_STATE.log("Launcher stopped.")
            return 0
        browser_process = open_app_window(bootstrap_url)
        try:
            monitor_browser_session(server, browser_process)
            server_thread.join(timeout=5)
        except KeyboardInterrupt:
            server.shutdown()
            APP_STATE.log("Launcher stopped.")
        finally:
            server.server_close()
        return 0
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        APP_STATE.log("Launcher stopped.")
        return 0
    return 0


def main() -> int:
    args = parse_args()
    instance_lock = acquire_single_instance_lock(REPO_ROOT)
    if instance_lock is None:
        print("The Multimodal Emotion Analysis Tool is already running.", flush=True)
        return 2
    try:
        return run_launcher(args)
    finally:
        release_single_instance_lock(instance_lock)


if __name__ == "__main__":
    raise SystemExit(main())
