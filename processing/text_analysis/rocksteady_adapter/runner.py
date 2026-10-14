"""Build, invoke, validate, and resume the headless RockSteady adapter."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from procurement.external_tools import credential_free_media_environment

from processing.io_utils import (
    assert_confined_input_file,
    assert_no_output_path_aliases,
    atomic_write_json,
    exclusive_process_lock,
    lexical_absolute_path,
    make_staging_directory,
    publish_directory,
)
from processing.text_analysis.contracts import inventory_digest, validate_text_identity
from processing.text_analysis.prepare_input.integrity import (
    validate_prepare_batch_artifacts,
)
from processing.text_analysis.rocksteady_transaction import rocksteady_pair_transaction
from processing.text_analysis.filesystem import (
    OWNER_FILE,
    OWNER_NAME,
    assert_safe_output_target,
    assert_replaceable_stage_target,
    create_stage_directory,
    replace_stage_directory,
)
from spreadsheet_safety import SpreadsheetSafeWriter, neutralize_spreadsheet_value


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
ADAPTER_ROOT = Path(__file__).resolve().parent
DEFAULT_ROCKSTEADY_HOME = REPOSITORY_ROOT / "external" / "RockSteady"
APPLICATION_JAR_NAME = "rocksteady-desktop-application-0.4#2018-05-16.jar"
DEFAULT_DICTIONARY = "affectDictionaries/General Language (En)(2011-07-05).dict.xml"
MAIN_CLASS = "ie.tcd.multimodal.rocksteady.RockSteadyCli"
IDENTITY_COLUMNS = ("Title", "Date of First Article", "Articles", "Terms", "URL")
SEGMENT_PATTERN = re.compile(r".+__segment_(\d{6})\.txt$", re.IGNORECASE)
ROCKSTEADY_STAGE = "rocksteady"
ROCKSTEADY_CACHE_OWNER = "multimodal-emotion-analysis-rocksteady-cache"
ROCKSTEADY_CACHE_SCHEMA_VERSION = "1.0"
ROCKSTEADY_BUILD_SCHEMA_VERSION = "1.0"
ROCKSTEADY_HISTORY_SCHEMA_VERSION = "1.0"
ROCKSTEADY_HISTORY_OWNER = "multimodal-emotion-analysis-rocksteady-run-history"


@dataclass(frozen=True)
class DictionarySpec:
    source: str
    path: str


@dataclass(frozen=True)
class Settings:
    dictionaries: tuple[DictionarySpec, ...] = (
        DictionarySpec("embedded", DEFAULT_DICTIONARY),
    )
    combination: str = "merge"
    analyser: str = "simple"
    value_type: str = "total"
    categories: tuple[str, ...] = ()
    threads: int = 1
    minimum_heap: str = "256m"
    maximum_heap: str = "2g"
    timeout_seconds: int = 3600


@dataclass(frozen=True)
class VideoJob:
    input_dir: Path
    output_csv: Path
    identity: str
    manifest_root: Path | None = None
    source_id: str = ""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def resolve_rocksteady_home(
    explicit: Path | None, config_path: Path | None = None
) -> Path:
    if explicit is not None:
        return explicit.resolve()
    if config_path is not None:
        with config_path.open("r", encoding="utf-8") as handle:
            configured_json = json.load(handle)
        if isinstance(configured_json, dict) and configured_json.get("rocksteady_home"):
            configured_path = Path(str(configured_json["rocksteady_home"]))
            if not configured_path.is_absolute():
                configured_path = REPOSITORY_ROOT / configured_path
            return configured_path.resolve()
    configured = os.environ.get("MULTIMODAL_EMOTION_ROCKSTEADY_HOME")
    if configured:
        return Path(configured).resolve()
    return DEFAULT_ROCKSTEADY_HOME.resolve()


def require_executable(name: str) -> str:
    executable = shutil.which(name)
    if executable is None:
        raise RuntimeError(f"Required executable is not available on PATH: {name}")
    resolved = Path(executable).resolve()
    excluded_roots = (Path.cwd().resolve(), REPOSITORY_ROOT.resolve())
    if not resolved.is_file() or any(
        resolved == root or root in resolved.parents for root in excluded_roots
    ):
        raise RuntimeError(
            f"Required executable must resolve outside the current/repository trees: {name}"
        )
    return str(resolved)


def build_adapter(application_jar: Path) -> Path:
    source = (
        ADAPTER_ROOT
        / "java"
        / "ie"
        / "tcd"
        / "multimodal"
        / "rocksteady"
        / "RockSteadyCli.java"
    )
    build_root = ADAPTER_ROOT / "build"
    classes = build_root / "classes"
    target = classes / "ie" / "tcd" / "multimodal" / "rocksteady" / "RockSteadyCli.class"
    build_manifest = classes / ".adapter_build_manifest.json"
    expected = {
        "schema_version": ROCKSTEADY_BUILD_SCHEMA_VERSION,
        "source_sha256": sha256_file(source),
        "application_jar_sha256": sha256_file(application_jar),
        "java_release": 8,
        "main_class": MAIN_CLASS,
    }
    lock_path = build_root / ".classes.compile.lock"
    with exclusive_process_lock(lock_path, purpose="compiling the RockSteady Java adapter"):
        try:
            saved = json.loads(build_manifest.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            saved = None
        if target.is_file() and saved == expected:
            return classes

        staging_pattern = ".classes_staging_*"
        preexisting_staging = {
            path.resolve() for path in build_root.glob(staging_pattern)
        }
        staging: Path | None = None
        try:
            staging = make_staging_directory(build_root, ".classes_staging_")
            subprocess.run(
                [
                    require_executable("javac"),
                    "--release",
                    "8",
                    "-Xlint:-options",
                    "-encoding",
                    "UTF-8",
                    "-cp",
                    str(application_jar),
                    "-d",
                    str(staging),
                    str(source),
                ],
                check=True,
                shell=False,
                env=credential_free_media_environment(),
            )
            staged_target = (
                staging
                / "ie"
                / "tcd"
                / "multimodal"
                / "rocksteady"
                / "RockSteadyCli.class"
            )
            if not staged_target.is_file():
                raise RuntimeError("javac completed without producing RockSteadyCli.class")
            atomic_write_json(staging / build_manifest.name, expected)
            publish_directory(staging, classes)
        except BaseException:
            if staging is not None and staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
            raise
        finally:
            for candidate in build_root.glob(staging_pattern):
                if candidate.resolve() not in preexisting_staging and candidate.is_dir():
                    shutil.rmtree(candidate, ignore_errors=True)
    return classes


def load_settings(config_path: Path | None, args: argparse.Namespace) -> Settings:
    raw: dict[str, object] = {}
    if config_path is not None:
        with config_path.open("r", encoding="utf-8") as handle:
            loaded = json.load(handle)
        if not isinstance(loaded, dict):
            raise ValueError("Adapter config must contain a JSON object")
        raw = loaded
        supported = {
            "rocksteady_home",
            "dictionaries",
            "analyser",
            "value_type",
            "categories",
            "threads",
            "minimum_heap",
            "maximum_heap",
            "timeout_seconds",
        }
        unknown = sorted(set(raw) - supported)
        if unknown:
            raise ValueError(
                "Unknown RockSteady adapter config keys: " + ", ".join(unknown)
            )

    dictionary_block = raw.get("dictionaries", {})
    if not isinstance(dictionary_block, dict):
        raise ValueError("config.dictionaries must be an object")
    unknown_dictionary_keys = sorted(set(dictionary_block) - {"items", "combination"})
    if unknown_dictionary_keys:
        raise ValueError(
            "Unknown config.dictionaries keys: " + ", ".join(unknown_dictionary_keys)
        )
    items = dictionary_block.get(
        "items", [{"source": "embedded", "path": DEFAULT_DICTIONARY}]
    )
    if not isinstance(items, list) or not items:
        raise ValueError("config.dictionaries.items must be a non-empty list")
    dictionaries = tuple(parse_dictionary_item(item) for item in items)
    cli_dictionaries = getattr(args, "dictionary", None)
    if cli_dictionaries:
        dictionaries = tuple(parse_dictionary_cli(item) for item in cli_dictionaries)

    analyser_block = raw.get("analyser", "simple")
    if isinstance(analyser_block, dict):
        unknown_analyser_keys = sorted(set(analyser_block) - {"type", "threads"})
        if unknown_analyser_keys:
            raise ValueError(
                "Unknown config.analyser keys: " + ", ".join(unknown_analyser_keys)
            )
        config_analyser = analyser_block.get("type", "simple")
        config_threads = analyser_block.get("threads", 1)
    else:
        config_analyser = analyser_block
        config_threads = raw.get("threads", 1)

    if getattr(args, "all_categories", False):
        if getattr(args, "category", None):
            raise ValueError("--all-categories cannot be combined with --category")
        categories: tuple[str, ...] = ()
    else:
        categories = tuple(getattr(args, "category", None) or raw.get("categories", ()))

    settings = Settings(
        dictionaries=dictionaries,
        combination=str(
            getattr(args, "dictionary_combination", None)
            or dictionary_block.get("combination", "merge")
        ).lower(),
        analyser=str(getattr(args, "analyser", None) or config_analyser).lower(),
        value_type=str(
            getattr(args, "value_type", None) or raw.get("value_type", "total")
        ).lower(),
        categories=categories,
        threads=int(getattr(args, "threads", None) or config_threads),
        minimum_heap=str(raw.get("minimum_heap", "256m")),
        maximum_heap=str(raw.get("maximum_heap", "2g")),
        timeout_seconds=int(
            getattr(args, "timeout", None) or raw.get("timeout_seconds", 3600)
        ),
    )
    validate_settings(settings)
    return settings


def parse_dictionary_item(item: object) -> DictionarySpec:
    if not isinstance(item, dict):
        raise ValueError("Each dictionary config item must be an object")
    source = str(item.get("source", "")).lower()
    path = str(item.get("path", ""))
    if not source or not path:
        raise ValueError("Each dictionary requires non-empty source and path values")
    return DictionarySpec(source, path)


def parse_dictionary_cli(value: str) -> DictionarySpec:
    source, separator, path = value.partition(":")
    if not separator or not path:
        raise ValueError("--dictionary must use embedded:RESOURCE or file:PATH")
    return DictionarySpec(source.lower(), path)


def validate_settings(settings: Settings) -> None:
    if settings.combination not in {"merge", "override"}:
        raise ValueError("dictionary combination must be merge or override")
    if settings.analyser != "simple":
        raise ValueError(
            "This RockSteady 0.4 JAR has a non-functional POS analyser; use simple"
        )
    if settings.value_type not in {"total", "percentage", "z_score"}:
        raise ValueError("value_type must be total, percentage, or z_score")
    if settings.threads < 1:
        raise ValueError("threads must be at least 1")
    if settings.timeout_seconds < 1:
        raise ValueError("timeout_seconds must be at least 1")
    if len({name.casefold() for name in settings.categories}) != len(settings.categories):
        raise ValueError("categories must not contain case-insensitive duplicates")
    for dictionary in settings.dictionaries:
        if dictionary.source not in {"embedded", "file"}:
            raise ValueError("dictionary source must be embedded or file")
    for heap in (settings.minimum_heap, settings.maximum_heap):
        if not re.fullmatch(r"[1-9]\d*[kKmMgG]", heap):
            raise ValueError(f"Invalid Java heap size: {heap}")
    if heap_bytes(settings.minimum_heap) > heap_bytes(settings.maximum_heap):
        raise ValueError("minimum_heap must not exceed maximum_heap")


def heap_bytes(value: str) -> int:
    factors = {"k": 1024, "m": 1024**2, "g": 1024**3}
    return int(value[:-1]) * factors[value[-1].lower()]


def resolve_dictionary_file(path: str, rocksteady_home: Path) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = rocksteady_home / candidate
    return candidate.resolve()


def java_command(
    job: VideoJob,
    partial_csv: Path,
    rocksteady_home: Path,
    application_jar: Path,
    classes: Path,
    settings: Settings,
) -> list[str]:
    command = [
        require_executable("java"),
        f"-Xms{settings.minimum_heap}",
        f"-Xmx{settings.maximum_heap}",
        "-Djava.awt.headless=true",
        "-cp",
        os.pathsep.join((str(classes), str(application_jar))),
        MAIN_CLASS,
        "--input",
        str(job.input_dir),
        "--output",
        str(partial_csv),
        "--dictionary-combination",
        settings.combination,
        "--analyser",
        settings.analyser,
        "--value-type",
        settings.value_type,
        "--threads",
        str(settings.threads),
    ]
    for dictionary in settings.dictionaries:
        if dictionary.source == "embedded":
            command.extend(("--dictionary-resource", dictionary.path))
        else:
            command.extend(
                ("--dictionary-file", str(resolve_dictionary_file(dictionary.path, rocksteady_home)))
            )
    for category in settings.categories:
        command.extend(("--category", category))
    return command


def java_validation_command(
    rocksteady_home: Path,
    application_jar: Path,
    classes: Path,
    settings: Settings,
) -> list[str]:
    command = [
        require_executable("java"),
        f"-Xms{settings.minimum_heap}",
        f"-Xmx{settings.maximum_heap}",
        "-Djava.awt.headless=true",
        "-cp",
        os.pathsep.join((str(classes), str(application_jar))),
        MAIN_CLASS,
        "--validate-only",
        "--dictionary-combination",
        settings.combination,
        "--analyser",
        settings.analyser,
        "--value-type",
        settings.value_type,
        "--threads",
        str(settings.threads),
    ]
    for dictionary in settings.dictionaries:
        if dictionary.source == "embedded":
            command.extend(("--dictionary-resource", dictionary.path))
        else:
            command.extend(
                ("--dictionary-file", str(resolve_dictionary_file(dictionary.path, rocksteady_home)))
            )
    for category in settings.categories:
        command.extend(("--category", category))
    return command


def run_java(
    command: Sequence[str],
    rocksteady_home: Path,
    timeout_seconds: int,
    success_prefix: str = "ROCKSTEADY_ADAPTER_OK",
) -> str:
    completed = subprocess.run(
        command,
        cwd=rocksteady_home,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        shell=False,
        env=credential_free_media_environment(),
    )
    if completed.returncode != 0:
        message = "\n".join(
            part.strip() for part in (completed.stdout, completed.stderr) if part.strip()
        )
        raise RuntimeError(message or f"RockSteady exited with code {completed.returncode}")
    success = next(
        (line for line in completed.stdout.splitlines() if line.startswith(success_prefix)),
        None,
    )
    if success is None:
        raise RuntimeError(
            f"RockSteady completed without the expected success marker: {success_prefix}"
        )
    return success


def validate_runtime_configuration(
    rocksteady_home: Path,
    application_jar: Path,
    classes: Path,
    settings: Settings,
) -> list[str]:
    output = run_java(
        java_validation_command(rocksteady_home, application_jar, classes, settings),
        rocksteady_home,
        settings.timeout_seconds,
        "ROCKSTEADY_ADAPTER_VALID",
    )
    marker = "ROCKSTEADY_ADAPTER_VALID categories="
    if not output.startswith(marker):
        raise RuntimeError("RockSteady configuration validation returned an invalid marker")
    _, _, names = output.partition(" names=")
    return [] if not names else names.split("|")


def segment_files(input_dir: Path) -> list[Path]:
    input_dir = assert_no_output_path_aliases(
        input_dir, description="RockSteady input"
    ).resolve(strict=True)
    files = sorted(
        (
            assert_confined_input_file(
                candidate, input_dir, description="RockSteady segment"
            )
            for candidate in input_dir.glob("*.txt")
        ),
        key=lambda item: item.name.casefold(),
    )
    if not files:
        raise ValueError(f"No segment .txt files found in {input_dir}")
    invalid = [file.name for file in files if SEGMENT_PATTERN.fullmatch(file.name) is None]
    if invalid:
        raise ValueError(f"Invalid segment filename(s) in {input_dir}: {', '.join(invalid[:5])}")
    expected = [f"{input_dir.name}__segment_{index:06d}.txt" for index in range(1, len(files) + 1)]
    actual = [file.name for file in files]
    if actual != expected:
        raise ValueError(f"Segments must be contiguous and match video name in {input_dir}")
    return files


def validate_csv(
    path: Path,
    input_dir: Path,
    value_type: str,
    *,
    expected_categories: Sequence[str] | None = None,
    expected_sha256: str | None = None,
) -> dict[str, object]:
    """Validate the complete scientific CSV contract, including resume integrity."""

    if expected_sha256 is not None and sha256_file(path) != expected_sha256:
        raise ValueError(f"CSV content hash does not match its manifest: {path}")
    expected_files = segment_files(input_dir)
    expected_titles = [str(neutralize_spreadsheet_value(file.stem)) for file in expected_files]
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = reader.fieldnames
        if headers is None:
            raise ValueError(f"CSV has no header: {path}")
        if headers[: len(IDENTITY_COLUMNS)] != list(IDENTITY_COLUMNS):
            raise ValueError(f"Unexpected RockSteady identity columns in {path}: {headers[:5]}")
        if len(headers) == len(IDENTITY_COLUMNS):
            raise ValueError(f"CSV contains no dictionary-category columns: {path}")
        if len(set(headers)) != len(headers):
            raise ValueError(f"CSV contains duplicate column names: {path}")
        categories = headers[len(IDENTITY_COLUMNS) :]
        safe_expected_categories = (
            [str(neutralize_spreadsheet_value(value)) for value in expected_categories]
            if expected_categories is not None
            else None
        )
        if safe_expected_categories is not None and categories != safe_expected_categories:
            raise ValueError(
                f"CSV categories do not match the validated dictionary configuration: {path}"
            )
        rows = list(reader)
    titles = [row["Title"] for row in rows]
    if titles != expected_titles:
        raise ValueError(f"CSV segment identities/order do not match input: {path}")
    numeric_columns = ["Articles", "Terms", *headers[len(IDENTITY_COLUMNS) :]]
    for row_number, row in enumerate(rows, start=2):
        if row["Articles"] != "1":
            raise ValueError(f"Expected Articles=1 at {path}:{row_number}")
        for column in numeric_columns:
            raw = row[column]
            if raw == "":
                raise ValueError(f"Blank numeric value at {path}:{row_number} column {column}")
            try:
                number = float(raw)
            except ValueError as error:
                raise ValueError(
                    f"Invalid numeric value at {path}:{row_number} column {column}: {raw!r}"
                ) from error
            if not math.isfinite(number):
                raise ValueError(
                    f"Non-finite numeric value at {path}:{row_number} column {column}: {raw!r}"
                )
            if value_type != "z_score" and number < 0:
                raise ValueError(f"Negative value at {path}:{row_number} column {column}")
            if value_type == "total" and not number.is_integer():
                raise ValueError(
                    f"Non-integer total at {path}:{row_number} column {column}: {raw!r}"
                )
        if value_type in {"total", "percentage"}:
            source_text = expected_files[row_number - 2].read_text(
                encoding="utf-8", errors="replace"
            )
            if source_text.strip() and float(row["Terms"]) <= 0:
                raise ValueError(
                    f"RockSteady produced Terms=0 for non-empty input at {path}:{row_number}"
                )
    return {"rows": len(rows), "columns": len(headers), "categories": categories}


def neutralize_csv_file(path: Path) -> None:
    """Neutralize formula-like CSV literals before an adapter artifact is published."""

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    safe_rows = [
        [neutralize_spreadsheet_value(value) for value in row]
        for row in rows
    ]
    if safe_rows == rows:
        return
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.spreadsheet-safe.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="") as handle:
            writer = SpreadsheetSafeWriter(csv.writer(handle, lineterminator="\n"))
            writer.writerows(rows)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def dictionary_fingerprints(
    settings: Settings, rocksteady_home: Path, application_jar: Path
) -> list[dict[str, str]]:
    fingerprints: list[dict[str, str]] = []
    with zipfile.ZipFile(application_jar) as archive:
        for dictionary in settings.dictionaries:
            if dictionary.source == "embedded":
                try:
                    content = archive.read(dictionary.path)
                except KeyError as error:
                    raise ValueError(
                        f"Embedded dictionary not found in RockSteady JAR: {dictionary.path}"
                    ) from error
                digest = hashlib.sha256(content).hexdigest()
            else:
                file = resolve_dictionary_file(dictionary.path, rocksteady_home)
                if not file.is_file():
                    raise FileNotFoundError(f"Dictionary file not found: {file}")
                digest = sha256_file(file)
            fingerprints.append(
                {"source": dictionary.source, "path": dictionary.path, "sha256": digest}
            )
    return fingerprints


def job_fingerprint(
    job: VideoJob,
    files: Sequence[Path],
    settings: Settings,
    jar_hash: str,
    dictionaries: Sequence[dict[str, str]],
    adapter_source_hash: str,
) -> str:
    digest = hashlib.sha256()
    payload = {
        "identity": job.identity,
        "source_id": job.source_id,
        "settings": settings_to_json(settings),
        "jar_sha256": jar_hash,
        "dictionaries": dictionaries,
        "adapter_source_sha256": adapter_source_hash,
    }
    digest.update(json.dumps(payload, sort_keys=True).encode("utf-8"))
    for file in files:
        digest.update(file.name.encode("utf-8"))
        digest.update(bytes.fromhex(sha256_file(file)))
    return digest.hexdigest()


def job_context_fingerprint(
    job: VideoJob,
    settings: Settings,
    jar_hash: str,
    dictionaries: Sequence[dict[str, str]],
    adapter_source_hash: str,
) -> str:
    """Fingerprint every job dependency except the segment file contents."""

    payload = {
        "identity": job.identity,
        "source_id": job.source_id,
        "settings": settings_to_json(settings),
        "jar_sha256": jar_hash,
        "dictionaries": dictionaries,
        "adapter_source_sha256": adapter_source_hash,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def snapshot_job_segments(
    job: VideoJob,
    files: Sequence[Path],
    *,
    expected_fingerprint: str,
    settings: Settings,
    jar_hash: str,
    dictionaries: Sequence[dict[str, str]],
    adapter_source_hash: str,
) -> tuple[tempfile.TemporaryDirectory[str], VideoJob, list[Path]]:
    """Copy the exact fingerprinted segments into an owned immutable input."""

    owner = tempfile.TemporaryDirectory(prefix="mea-rocksteady-input-")
    try:
        snapshot_dir = Path(owner.name) / job.input_dir.name
        snapshot_dir.mkdir()
        for source in files:
            destination = snapshot_dir / source.name
            with source.open("rb") as source_handle, destination.open("xb") as target_handle:
                shutil.copyfileobj(source_handle, target_handle, length=1024 * 1024)
                target_handle.flush()
                os.fsync(target_handle.fileno())
        snapshot_files = segment_files(snapshot_dir)
        snapshot_job = VideoJob(
            snapshot_dir,
            job.output_csv,
            job.identity,
            job.manifest_root,
            job.source_id,
        )
        actual_fingerprint = job_fingerprint(
            snapshot_job,
            snapshot_files,
            settings,
            jar_hash,
            dictionaries,
            adapter_source_hash,
        )
        if actual_fingerprint != expected_fingerprint:
            raise ValueError(
                "RockSteady segment input changed while its immutable snapshot was created."
            )
        return owner, snapshot_job, snapshot_files
    except BaseException:
        owner.cleanup()
        raise


def input_metadata_snapshot(files: Sequence[Path]) -> str:
    """Cheaply detect whether an already content-hashed segment set changed."""

    digest = hashlib.sha256()
    for file in files:
        stat = file.stat()
        digest.update(file.name.encode("utf-8"))
        digest.update(str(stat.st_size).encode("ascii"))
        digest.update(str(stat.st_mtime_ns).encode("ascii"))
    return digest.hexdigest()


def settings_to_json(settings: Settings) -> dict[str, object]:
    result = asdict(settings)
    result["dictionaries"] = [asdict(item) for item in settings.dictionaries]
    result["categories"] = list(settings.categories)
    return result


def _write_batch_manifest(
    path: Path,
    *,
    status: str,
    run_id: str | None,
    upstream_inventory_sha256: str | None,
    records: Sequence[dict[str, object]],
    application_jar: Path,
    jar_hash: str,
    adapter_source_hash: str,
    settings: Settings,
    dictionary_hashes: Sequence[dict[str, str]],
) -> None:
    """Write the complete RockSteady batch identity and result inventory."""

    interrupted = sum(row.get("status") == "interrupted" for row in records)
    summary = {
        "total": len(records),
        "completed": sum(row.get("status") == "completed" for row in records),
        "skipped": sum(row.get("status") == "skipped" for row in records),
        "failed": sum(row.get("status") == "failed" for row in records),
        **({"interrupted": interrupted} if interrupted else {}),
    }
    write_json_atomic(
        path,
        {
            "schema_version": "2.0",
            "kind": "rocksteady-analysis-batch",
            "run_id": run_id,
            "status": status,
            "created_at": utc_now(),
            "upstream_inventory_sha256": upstream_inventory_sha256,
            "inventory_sha256": inventory_digest(records),
            "rocksteady_jar": {
                "name": application_jar.name,
                "sha256": jar_hash,
            },
            "adapter_source_sha256": adapter_source_hash,
            "settings": settings_to_json(settings),
            "dictionaries": list(dictionary_hashes),
            "summary": summary,
            "videos": list(records),
        },
    )


def legacy_manifest_path_for_single(output_csv: Path) -> Path:
    """Return the pre-v2 manifest location beside the output CSV."""
    return output_csv.with_suffix(output_csv.suffix + ".manifest.json")


def manifest_path_for_job(job: VideoJob) -> Path:
    """Return a mirrored manifest path below the output set's `_manifests` dir."""
    identity_parts = tuple(part for part in job.identity.split("/") if part)
    if not identity_parts:
        raise ValueError(f"Invalid empty job identity: {job.identity!r}")

    output_root = (job.manifest_root or job.output_csv.parent).resolve()
    relative = Path(*identity_parts[:-1]) / f"{identity_parts[-1]}.csv.manifest.json"
    return output_root / "_manifests" / relative


def load_authoritative_inventory(
    path: Path, *, input_root: Path | None = None
) -> tuple[set[str], str | None]:
    """Load the completed prepare inventory used to bind this RockSteady run."""

    if input_root is not None:
        identities, digest = validate_prepare_batch_artifacts(input_root, path)
        return identities, digest
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("status") != "completed":
        raise ValueError(f"RockSteady inventory is not completed: {path}")
    videos = payload.get("videos")
    if not isinstance(videos, list):
        raise ValueError(f"RockSteady inventory has no videos list: {path}")
    identities: set[str] = set()
    for item in videos:
        if not isinstance(item, dict) or item.get("status") != "completed":
            raise ValueError(f"RockSteady inventory contains an incomplete video: {path}")
        identity = item.get("identity")
        if not isinstance(identity, str):
            raise ValueError(f"RockSteady inventory contains an invalid identity: {identity!r}")
        identity = validate_text_identity(Path(identity)).as_posix()
        if identity in identities:
            raise ValueError(f"RockSteady inventory contains duplicate identity: {identity}")
        identities.add(identity)
    digest = payload.get("inventory_sha256")
    if digest is not None and not isinstance(digest, str):
        raise ValueError(f"RockSteady inventory digest is invalid: {path}")
    return identities, digest


def load_authoritative_source_ids(path: Path) -> dict[str, str]:
    """Read optional source identifiers from an already validated prepare manifest."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    videos = payload.get("videos") if isinstance(payload, dict) else None
    if not isinstance(videos, list):
        raise ValueError(f"RockSteady inventory has no videos list: {path}")
    source_ids: dict[str, str] = {}
    for item in videos:
        if not isinstance(item, dict) or item.get("status") != "completed":
            raise ValueError(f"RockSteady inventory contains an incomplete video: {path}")
        identity = validate_text_identity(Path(str(item.get("identity") or ""))).as_posix()
        source_id = item.get("source_id", "")
        if source_id is not None and not isinstance(source_id, str):
            raise ValueError(f"RockSteady inventory source_id must be text: {identity}")
        source_ids[identity] = str(source_id or "")
    return source_ids


def read_manifest(path: Path) -> dict[str, object] | None:
    if not path.is_file():
        return None
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def validate_rocksteady_batch_manifest(
    path: Path, *, expected_adapter_source_sha256: str | None = None
) -> dict[str, object]:
    """Validate a completed batch manifest before downstream reuse."""

    manifest_path = Path(path)
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read RockSteady batch manifest {manifest_path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"RockSteady batch manifest is not an object: {manifest_path}")
    if payload.get("schema_version") != "2.0" or payload.get("kind") != "rocksteady-analysis-batch":
        raise ValueError(f"RockSteady batch manifest schema/kind is invalid: {manifest_path}")
    if payload.get("status") != "completed":
        raise ValueError(f"RockSteady batch manifest is not completed: {manifest_path}")
    videos = payload.get("videos")
    if not isinstance(videos, list) or not videos:
        raise ValueError(f"RockSteady batch manifest has no videos: {manifest_path}")
    if payload.get("inventory_sha256") != inventory_digest(videos):
        raise ValueError(f"RockSteady batch inventory digest mismatch: {manifest_path}")
    if any(
        not isinstance(row, dict) or row.get("status") not in {"completed", "skipped"}
        for row in videos
    ):
        raise ValueError(f"RockSteady batch contains incomplete videos: {manifest_path}")
    adapter_hash = payload.get("adapter_source_sha256")
    if not isinstance(adapter_hash, str) or re.fullmatch(r"[0-9a-f]{64}", adapter_hash) is None:
        raise ValueError(f"RockSteady adapter source hash is invalid: {manifest_path}")
    if expected_adapter_source_sha256 is not None and adapter_hash != expected_adapter_source_sha256:
        raise ValueError(f"RockSteady adapter source changed since analysis: {manifest_path}")
    jar = payload.get("rocksteady_jar")
    if (
        not isinstance(jar, dict)
        or not isinstance(jar.get("name"), str)
        or not isinstance(jar.get("sha256"), str)
        or re.fullmatch(r"[0-9a-f]{64}", jar["sha256"]) is None
    ):
        raise ValueError(f"RockSteady JAR identity is invalid: {manifest_path}")
    dictionaries = payload.get("dictionaries")
    if not isinstance(dictionaries, list) or not dictionaries:
        raise ValueError(f"RockSteady dictionary identity is missing: {manifest_path}")
    for dictionary in dictionaries:
        if (
            not isinstance(dictionary, dict)
            or dictionary.get("source") not in {"embedded", "file"}
            or not isinstance(dictionary.get("path"), str)
            or not isinstance(dictionary.get("sha256"), str)
            or re.fullmatch(r"[0-9a-f]{64}", dictionary["sha256"]) is None
        ):
            raise ValueError(f"RockSteady dictionary identity is invalid: {manifest_path}")
    if not isinstance(payload.get("settings"), dict):
        raise ValueError(f"RockSteady settings are missing: {manifest_path}")
    return payload


def write_json_atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".partial")
    try:
        with partial.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(partial, path)
    finally:
        partial.unlink(missing_ok=True)


def discover_jobs(
    input_path: Path,
    output_path: Path,
    *,
    output_is_root: bool = False,
    identities: set[str] | None = None,
    source_ids: Mapping[str, str] | None = None,
) -> tuple[list[VideoJob], bool]:
    input_path = assert_no_output_path_aliases(
        input_path, description="RockSteady input"
    ).resolve(strict=True)
    output_path = assert_safe_output_target(
        lexical_absolute_path(output_path), input_path
    )
    if any(input_path.glob("*.txt")):
        segment_files(input_path)
        identity = "/".join(input_path.parts[-3:]) if len(input_path.parts) >= 3 else input_path.name
        if output_is_root:
            identity_parts = identity.split("/")
            if len(identity_parts) != 3:
                raise ValueError(
                    "--output-root requires a canonical Country/Speaker/Video input path"
                )
            output_csv = output_path.joinpath(
                identity_parts[0], identity_parts[1], f"{identity_parts[2]}.csv"
            )
        else:
            if output_path.suffix.casefold() != ".csv":
                raise ValueError(
                    "Single-video --output must be a .csv file; use --output-root "
                    "to derive the canonical CSV path automatically"
                )
            output_csv = output_path
        if identities is not None and identities != {identity}:
            raise ValueError(
                f"Single RockSteady input identity {identity!r} does not match the inventory"
            )
        manifest_root = output_path if output_is_root else output_csv.parent
        return [
            VideoJob(
                input_path,
                output_csv,
                identity,
                manifest_root,
                (source_ids or {}).get(identity, ""),
            )
        ], True

    jobs: list[VideoJob] = []
    if identities is not None:
        for identity in sorted(identities, key=str.casefold):
            relative = validate_text_identity(Path(identity))
            requested_video = input_path / relative
            video = assert_no_output_path_aliases(
                requested_video, description="RockSteady input"
            ).resolve(strict=True)
            if not video.is_relative_to(input_path) or not video.is_dir():
                raise ValueError(f"Prepared input is missing inventory identity: {identity}")
            segment_files(video)
            jobs.append(
                VideoJob(
                    video,
                    output_path / relative.parent / f"{relative.name}.csv",
                    relative.as_posix(),
                    output_path,
                    (source_ids or {}).get(relative.as_posix(), ""),
                )
            )
        if not jobs:
            raise ValueError("RockSteady inventory contains no prepared Text inputs")
        return jobs, False

    for country in sorted(_visible_directories(input_path), key=lambda p: p.name.casefold()):
        for speaker in sorted(_visible_directories(country), key=lambda p: p.name.casefold()):
            for video in sorted(_visible_directories(speaker), key=lambda p: p.name.casefold()):
                if any(video.glob("*.txt")):
                    identity = f"{country.name}/{speaker.name}/{video.name}"
                    segment_files(video)
                    jobs.append(
                        VideoJob(
                            video.resolve(),
                            output_path / country.name / speaker.name / f"{video.name}.csv",
                            identity,
                            output_path,
                            (source_ids or {}).get(identity, ""),
                        )
                    )
    if not jobs:
        raise ValueError(f"No canonical Country/Speaker/Video inputs found below {input_path}")
    return jobs, False


def _visible_directories(parent: Path) -> list[Path]:
    """List data directories while excluding atomic-write staging folders."""

    directories: list[Path] = []
    for item in parent.iterdir():
        if item.name.startswith("."):
            continue
        safe = assert_no_output_path_aliases(item, description="RockSteady input")
        if safe.is_dir():
            directories.append(safe)
    return directories


def check_runtime(
    rocksteady_home: Path, settings: Settings
) -> tuple[list[str], Path, Path]:
    """Build and validate the repository-local adapter without analysing media."""

    application_jar = rocksteady_home / APPLICATION_JAR_NAME
    if not application_jar.is_file():
        raise FileNotFoundError(f"RockSteady application JAR not found: {application_jar}")
    classes = build_adapter(application_jar)
    available_categories = validate_runtime_configuration(
        rocksteady_home, application_jar, classes, settings
    )
    if not available_categories:
        raise RuntimeError(
            "RockSteady dictionaries/category filters resolved to zero export categories"
        )
    return available_categories, application_jar, classes


def prepare_cache_root(cache_root: Path) -> Path:
    """Create or validate the persistent content-addressed resume cache."""

    root = Path(cache_root).resolve()
    marker = root / ".rocksteady_cache_owner.json"
    expected = {
        "schema_version": ROCKSTEADY_CACHE_SCHEMA_VERSION,
        "owner": ROCKSTEADY_CACHE_OWNER,
    }
    if root.exists():
        if root.is_symlink() or not root.is_dir():
            raise ValueError(f"RockSteady cache root is not a safe directory: {root}")
        entries = list(root.iterdir())
        if entries:
            try:
                payload = json.loads(marker.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise ValueError(
                    f"Refusing to use an unowned non-empty RockSteady cache: {root}"
                ) from exc
            if payload != expected:
                raise ValueError(f"RockSteady cache ownership marker is invalid: {marker}")
    else:
        root.mkdir(parents=True)
    if not marker.is_file():
        atomic_write_json(marker, expected)
    return root


def failed_run_history_root(output_root: Path) -> Path:
    """Return the hidden sibling store that survives snapshot rollback."""

    root = Path(output_root).resolve()
    return root.parent / f".{root.name}.rocksteady-run-history"


def prepare_failed_run_history(output_root: Path) -> Path:
    """Create or validate the owned failure-history directory."""

    history = failed_run_history_root(output_root)
    marker = history / ".rocksteady_run_history_owner.json"
    expected = {
        "schema_version": ROCKSTEADY_HISTORY_SCHEMA_VERSION,
        "owner": ROCKSTEADY_HISTORY_OWNER,
    }
    if history.exists():
        if history.is_symlink() or not history.is_dir():
            raise ValueError(f"RockSteady failure history is not a safe directory: {history}")
        entries = list(history.iterdir())
        if entries:
            try:
                saved = json.loads(marker.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise ValueError(
                    f"Refusing to use an unowned RockSteady failure history: {history}"
                ) from exc
            if saved != expected:
                raise ValueError(f"RockSteady failure-history ownership is invalid: {marker}")
    else:
        history.mkdir(parents=True)
    atomic_write_json(marker, expected)
    return history


def preserve_failed_snapshot_manifest(
    output_root: Path,
    staged_manifest: Path,
    *,
    run_id: str | None,
    error: BaseException | None = None,
) -> Path:
    """Persist a failed/interrupted manifest outside disposable staging."""

    try:
        payload = json.loads(Path(staged_manifest).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        payload = {
            "schema_version": "2.0",
            "kind": "rocksteady-analysis-batch",
            "run_id": run_id,
            "status": "interrupted" if isinstance(error, KeyboardInterrupt) else "failed",
            "created_at": utc_now(),
            "summary": {"total": 0, "completed": 0, "skipped": 0, "failed": 0},
            "videos": [],
        }
    if not isinstance(payload, dict):
        raise ValueError(f"RockSteady staged batch manifest is malformed: {staged_manifest}")
    payload["snapshot_publication"] = {
        "status": "not-published",
        "visible_output_preserved": True,
        "recorded_at": utc_now(),
    }
    if error is not None:
        payload["snapshot_publication"]["error"] = (
            f"{type(error).__name__}: {error}"
        )
    history = prepare_failed_run_history(output_root)
    label = re.sub(r"[^A-Za-z0-9._-]+", "-", run_id or "run").strip(".-") or "run"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    destination = history / f"{timestamp}_{label}_{uuid.uuid4().hex[:8]}.json"
    atomic_write_json(destination, payload)
    return destination


def _cache_entry_paths(cache_root: Path, fingerprint: str) -> tuple[Path, Path]:
    if re.fullmatch(r"[0-9a-f]{64}", fingerprint) is None:
        raise ValueError(f"Invalid RockSteady cache fingerprint: {fingerprint!r}")
    entry = Path(cache_root) / fingerprint[:2] / fingerprint
    return entry / "result.csv", entry / "cache_manifest.json"


def restore_cached_job(
    cache_root: Path,
    job: VideoJob,
    *,
    fingerprint: str,
    value_type: str,
    expected_categories: Sequence[str],
) -> tuple[dict[str, object], str] | None:
    """Restore one verified cached CSV, returning ``None`` for a cache miss."""

    cached_csv, manifest_path = _cache_entry_paths(cache_root, fingerprint)
    manifest = read_manifest(manifest_path)
    if not cached_csv.is_file() or manifest is None:
        return None
    expected_sha256 = manifest.get("output_sha256")
    if (
        manifest.get("schema_version") != ROCKSTEADY_CACHE_SCHEMA_VERSION
        or manifest.get("fingerprint") != fingerprint
        or manifest.get("identity") != job.identity
        or not isinstance(expected_sha256, str)
    ):
        return None
    try:
        validation = validate_csv(
            cached_csv,
            job.input_dir,
            value_type,
            expected_categories=expected_categories,
            expected_sha256=expected_sha256,
        )
    except (OSError, ValueError):
        return None

    job.output_csv.parent.mkdir(parents=True, exist_ok=True)
    partial = job.output_csv.with_name(job.output_csv.name + ".cache-partial")
    try:
        shutil.copy2(cached_csv, partial)
        if sha256_file(partial) != expected_sha256:
            return None
        os.replace(partial, job.output_csv)
    finally:
        partial.unlink(missing_ok=True)
    return validation, expected_sha256


def store_cached_job(
    cache_root: Path,
    job: VideoJob,
    *,
    fingerprint: str,
    output_sha256: str,
    validation: dict[str, object],
) -> None:
    """Publish one successful result to the persistent resume cache."""

    cached_csv, manifest_path = _cache_entry_paths(cache_root, fingerprint)
    cached_csv.parent.mkdir(parents=True, exist_ok=True)
    partial = cached_csv.with_name(cached_csv.name + ".partial")
    try:
        shutil.copy2(job.output_csv, partial)
        if sha256_file(partial) != output_sha256:
            raise RuntimeError(f"RockSteady cache copy failed integrity validation: {job.identity}")
        os.replace(partial, cached_csv)
    finally:
        partial.unlink(missing_ok=True)
    atomic_write_json(
        manifest_path,
        {
            "schema_version": ROCKSTEADY_CACHE_SCHEMA_VERSION,
            "fingerprint": fingerprint,
            "identity": job.identity,
            "output_sha256": output_sha256,
            "validation": validation,
            "created_at": utc_now(),
        },
    )


def process_jobs(
    jobs: Sequence[VideoJob],
    *,
    rocksteady_home: Path,
    settings: Settings,
    force: bool,
    dry_run: bool,
    batch_manifest_path: Path | None,
    upstream_inventory_sha256: str | None = None,
    cache_root: Path | None = None,
    run_id: str | None = None,
) -> tuple[list[dict[str, object]], int]:
    available_categories, application_jar, classes = check_runtime(
        rocksteady_home, settings
    )
    print(
        "Configuration valid: "
        f"{len(settings.dictionaries)} "
        f"{'dictionary' if len(settings.dictionaries) == 1 else 'dictionaries'}, "
        f"{len(available_categories)} selected "
        f"{'category' if len(available_categories) == 1 else 'categories'}"
    )
    if dry_run:
        records = []
        for index, job in enumerate(jobs, start=1):
            files = segment_files(job.input_dir)
            record: dict[str, object] = {
                "identity": job.identity,
                "source_id": job.source_id,
                "output": str(job.output_csv),
                "segments": len(files),
                "status": "planned",
                "categories": available_categories,
            }
            records.append(record)
            print(
                f"[{index}/{len(jobs)}] planned: {job.identity} "
                f"-> {job.output_csv}"
            )
        return records, 0

    jar_hash = sha256_file(application_jar)
    dictionary_hashes = dictionary_fingerprints(settings, rocksteady_home, application_jar)
    adapter_source_hash = sha256_file(
        ADAPTER_ROOT
        / "java"
        / "ie"
        / "tcd"
        / "multimodal"
        / "rocksteady"
        / "RockSteadyCli.java"
    )
    records: list[dict[str, object]] = []
    failures = 0
    if cache_root is not None:
        prepare_cache_root(cache_root)

    for index, job in enumerate(jobs, start=1):
        started_at = utc_now()
        files = segment_files(job.input_dir)
        per_video_manifest = manifest_path_for_job(job)
        previous = read_manifest(per_video_manifest)
        if previous is None:
            previous = read_manifest(legacy_manifest_path_for_single(job.output_csv))
        context_fingerprint = job_context_fingerprint(
            job, settings, jar_hash, dictionary_hashes, adapter_source_hash
        )
        input_snapshot = input_metadata_snapshot(files)
        # Prepared text files are small.  Hash them every time: size/mtime is
        # useful diagnostic evidence but cannot prove that content is unchanged.
        fingerprint = job_fingerprint(
            job, files, settings, jar_hash, dictionary_hashes, adapter_source_hash
        )
        record: dict[str, object] = {
            "identity": job.identity,
            "source_id": job.source_id,
            "output": f"{job.identity}.csv",
            "run_id": run_id,
            "fingerprint": fingerprint,
            "context_fingerprint": context_fingerprint,
            "input_metadata_snapshot": input_snapshot,
            "segments": len(files),
            "started_at": started_at,
        }
        partial: Path | None = None
        input_snapshot_owner: tempfile.TemporaryDirectory[str] | None = None
        fatal_error: BaseException | None = None
        try:
            if (
                not force
                and job.output_csv.is_file()
                and previous is not None
                and previous.get("fingerprint") == fingerprint
                and previous.get("status") in {"completed", "skipped"}
                and isinstance(previous.get("output_sha256"), str)
                and sha256_file(job.output_csv) == previous.get("output_sha256")
            ):
                previous_output_sha256 = str(previous["output_sha256"])
                validation = validate_csv(
                    job.output_csv,
                    job.input_dir,
                    settings.value_type,
                    expected_categories=available_categories,
                    expected_sha256=previous_output_sha256,
                )
                record.update(
                    {
                        "status": "skipped",
                        "resume_source": "current-output",
                        "validation": validation,
                        "output_sha256": previous_output_sha256,
                    }
                )
            else:
                cached = (
                    restore_cached_job(
                        cache_root,
                        job,
                        fingerprint=fingerprint,
                        value_type=settings.value_type,
                        expected_categories=available_categories,
                    )
                    if cache_root is not None and not force
                    else None
                )
                if cached is not None:
                    validation, cached_sha256 = cached
                    record.update(
                        {
                            "status": "skipped",
                            "resume_source": "content-addressed-cache",
                            "validation": validation,
                            "output_sha256": cached_sha256,
                        }
                    )
                else:
                    job.output_csv.parent.mkdir(parents=True, exist_ok=True)
                    input_snapshot_owner, execution_job, _snapshot_files = snapshot_job_segments(
                        job,
                        files,
                        expected_fingerprint=fingerprint,
                        settings=settings,
                        jar_hash=jar_hash,
                        dictionaries=dictionary_hashes,
                        adapter_source_hash=adapter_source_hash,
                    )
                    partial = job.output_csv.with_name(job.output_csv.name + ".partial")
                    if partial.exists():
                        partial.unlink()
                    run_java(
                        java_command(
                            execution_job, partial, rocksteady_home, application_jar, classes, settings
                        ),
                        rocksteady_home,
                        settings.timeout_seconds,
                    )
                    neutralize_csv_file(partial)
                    validation = validate_csv(
                        partial,
                        execution_job.input_dir,
                        settings.value_type,
                        expected_categories=available_categories,
                    )
                    os.replace(partial, job.output_csv)
                    output_sha256 = sha256_file(job.output_csv)
                    record.update(
                        {
                            "status": "completed",
                            "validation": validation,
                            "output_sha256": output_sha256,
                        }
                    )
                    if cache_root is not None:
                        store_cached_job(
                            cache_root,
                            job,
                            fingerprint=fingerprint,
                            output_sha256=output_sha256,
                            validation=validation,
                        )
            record["finished_at"] = utc_now()
        except BaseException as error:  # cleanly terminate Ctrl-C; isolate ordinary failures
            if partial is not None:
                partial.unlink(missing_ok=True)
            interrupted = not isinstance(error, Exception)
            if interrupted:
                fatal_error = error
            else:
                failures += 1
            record.update(
                {
                    "status": "interrupted" if interrupted else "failed",
                    "finished_at": utc_now(),
                    "error": str(error),
                    "error_summary": concise_error(error),
                }
            )
        if input_snapshot_owner is not None:
            input_snapshot_owner.cleanup()
        records.append(record)
        write_json_atomic(per_video_manifest, record)
        print(f"[{index}/{len(jobs)}] {record['status']}: {job.identity}")
        if record["status"] == "failed":
            print(f"  Reason: {record['error_summary']}", file=sys.stderr)
            print(f"  Manifest: {per_video_manifest}", file=sys.stderr)
        if fatal_error is not None:
            if batch_manifest_path is not None:
                _write_batch_manifest(
                    batch_manifest_path,
                    status="interrupted",
                    run_id=run_id,
                    upstream_inventory_sha256=upstream_inventory_sha256,
                    records=records,
                    application_jar=application_jar,
                    jar_hash=jar_hash,
                    adapter_source_hash=adapter_source_hash,
                    settings=settings,
                    dictionary_hashes=dictionary_hashes,
                )
            raise fatal_error

    if batch_manifest_path is not None:
        _write_batch_manifest(
            batch_manifest_path,
            status="failed" if failures else "completed",
            run_id=run_id,
            upstream_inventory_sha256=upstream_inventory_sha256,
            records=records,
            application_jar=application_jar,
            jar_hash=jar_hash,
            adapter_source_hash=adapter_source_hash,
            settings=settings,
            dictionary_hashes=dictionary_hashes,
        )
    return records, failures


def process_jobs_as_snapshot(
    jobs: Sequence[VideoJob],
    *,
    output_root: Path,
    rocksteady_home: Path,
    settings: Settings,
    force: bool,
    dry_run: bool,
    batch_manifest_path: Path | None,
    upstream_inventory_sha256: str | None = None,
    run_id: str | None = None,
    cache_root_override: Path | None = None,
    failure_history_output_root: Path | None = None,
) -> tuple[list[dict[str, object]], int]:
    """Publish the exact current job set as one atomic RockSteady snapshot.

    The visible root is never incrementally mutated.  Valid outputs from the
    current snapshot are copied into staging for resume, and a persistent
    content-addressed cache keeps them reusable even after a later subset run
    publishes a smaller snapshot.
    """

    protected_inputs = tuple(job.input_dir for job in jobs)
    root = assert_safe_output_target(output_root, *protected_inputs)
    history_output_root = (
        assert_safe_output_target(failure_history_output_root, *protected_inputs)
        if failure_history_output_root is not None
        else root
    )
    cache_root = assert_safe_output_target(
        (
            cache_root_override
            if cache_root_override is not None
            else root.parent / f".{root.name}.rocksteady-cache"
        ),
        root,
        *protected_inputs,
    )
    if dry_run:
        return process_jobs(
            jobs,
            rocksteady_home=rocksteady_home,
            settings=settings,
            force=force,
            dry_run=True,
            batch_manifest_path=None,
            upstream_inventory_sha256=upstream_inventory_sha256,
            run_id=run_id,
        )
    if batch_manifest_path is None:
        batch_relative = Path("_manifests") / "rocksteady_run_manifest.json"
    else:
        try:
            batch_relative = Path(batch_manifest_path).resolve().relative_to(root)
        except ValueError as exc:
            raise ValueError(
                "A snapshot batch manifest must be inside its RockSteady output root: "
                f"manifest={batch_manifest_path}, output={root}"
            ) from exc
        if batch_relative == Path(".") or ".." in batch_relative.parts:
            raise ValueError(f"Invalid RockSteady batch manifest path: {batch_manifest_path}")

    lock_path = root.parent / f".{root.name}.rocksteady.lock"
    with rocksteady_pair_transaction(
        root,
        purpose=f"protecting RockSteady output {root} from paired all/core publication",
    ), exclusive_process_lock(lock_path, purpose=f"publishing RockSteady snapshot {root}"):
        assert_replaceable_stage_target(root, ROCKSTEADY_STAGE)
        staging_pattern = f".{root.name}_staging_*"
        preexisting_staging = {
            path.resolve() for path in root.parent.glob(staging_pattern)
        }
        staging: Path | None = None
        try:
            staging = create_stage_directory(root, ROCKSTEADY_STAGE)
            staged_jobs = _stage_snapshot_jobs(jobs, root, staging)
            _copy_current_resume_candidates(jobs, staged_jobs, root)
            records, failures = process_jobs(
                staged_jobs,
                rocksteady_home=rocksteady_home,
                settings=settings,
                force=force,
                dry_run=False,
                batch_manifest_path=staging / batch_relative,
                upstream_inventory_sha256=upstream_inventory_sha256,
                cache_root=cache_root,
                run_id=run_id,
            )
            if failures:
                history_manifest = preserve_failed_snapshot_manifest(
                    history_output_root,
                    staging / batch_relative,
                    run_id=run_id,
                )
                shutil.rmtree(staging, ignore_errors=True)
                print(
                    f"Failed RockSteady run manifest preserved at {history_manifest}",
                    file=sys.stderr,
                )
                return records, failures
            replace_stage_directory(staging, root, ROCKSTEADY_STAGE)
            return records, 0
        except BaseException as error:
            try:
                history_manifest = preserve_failed_snapshot_manifest(
                    history_output_root,
                    (
                        staging / batch_relative
                        if staging is not None
                        else root.parent / ".missing-rocksteady-staged-manifest.json"
                    ),
                    run_id=run_id,
                    error=error,
                )
                print(
                    f"Interrupted RockSteady run manifest preserved at {history_manifest}",
                    file=sys.stderr,
                )
            except Exception as history_error:
                print(
                    "WARNING: RockSteady output was preserved, but its failed run "
                    f"manifest could not be archived: {history_error}",
                    file=sys.stderr,
                )
            finally:
                if staging is not None and staging.exists():
                    shutil.rmtree(staging, ignore_errors=True)
            raise
        finally:
            for candidate in root.parent.glob(staging_pattern):
                if candidate.resolve() not in preexisting_staging and candidate.is_dir():
                    shutil.rmtree(candidate, ignore_errors=True)


def _stage_snapshot_jobs(
    jobs: Sequence[VideoJob], target_root: Path, staging_root: Path
) -> list[VideoJob]:
    staged: list[VideoJob] = []
    identities: set[str] = set()
    relative_outputs: set[str] = set()
    for job in jobs:
        try:
            relative = job.output_csv.resolve().relative_to(target_root)
        except ValueError as exc:
            raise ValueError(
                f"RockSteady job output escapes the snapshot root: {job.output_csv}"
            ) from exc
        folded = relative.as_posix().casefold()
        if relative.is_absolute() or ".." in relative.parts or relative.suffix.casefold() != ".csv":
            raise ValueError(f"Invalid RockSteady snapshot output path: {relative}")
        if job.identity in identities or folded in relative_outputs:
            raise ValueError(f"Duplicate RockSteady snapshot job: {job.identity}")
        identities.add(job.identity)
        relative_outputs.add(folded)
        staged.append(
            VideoJob(
                input_dir=job.input_dir,
                output_csv=staging_root / relative,
                identity=job.identity,
                manifest_root=staging_root,
                source_id=job.source_id,
            )
        )
    if not staged:
        raise ValueError("RockSteady snapshot contains no jobs")
    return staged


def _copy_current_resume_candidates(
    original_jobs: Sequence[VideoJob],
    staged_jobs: Sequence[VideoJob],
    current_root: Path,
) -> None:
    """Seed staging with only current identities; ``process_jobs`` revalidates all bytes."""

    if not current_root.is_dir() or not (current_root / OWNER_FILE).is_file():
        return
    for original, staged in zip(original_jobs, staged_jobs):
        if original.output_csv.is_file() and not original.output_csv.is_symlink():
            staged.output_csv.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(original.output_csv, staged.output_csv)
        old_manifest = manifest_path_for_job(original)
        if old_manifest.is_file() and not old_manifest.is_symlink():
            new_manifest = manifest_path_for_job(staged)
            new_manifest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(old_manifest, new_manifest)


def concise_error(error: BaseException) -> str:
    """Extract the actionable final exception from noisy RockSteady output."""
    text = str(error).strip()
    if not text:
        return error.__class__.__name__
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in reversed(lines):
        if line.startswith("Caused by:"):
            line = line.removeprefix("Caused by:").strip()
            match = re.search(r"(?:Exception|Error):\s*(.+)$", line)
            return match.group(1) if match else line
    for line in reversed(lines):
        if "Exception:" in line or "Error:" in line:
            match = re.search(r"(?:Exception|Error):\s*(.+)$", line)
            return match.group(1) if match else line
    non_stack = [line for line in lines if not line.startswith("at ")]
    return (non_stack or lines)[-1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run RockSteady for one video directory or a prepared Text batch. "
            "Inventory-backed batches support Speaker/Video and legacy "
            "Country/Speaker/Video identities."
        )
    )
    parser.add_argument("input", type=Path, nargs="?")
    output_group = parser.add_mutually_exclusive_group()
    output_group.add_argument(
        "--output",
        type=Path,
        help="Exact CSV path for one video, or output root for batch input",
    )
    output_group.add_argument(
        "--output-root",
        type=Path,
        help="Root below which inventory identities (or legacy canonical paths) are derived",
    )
    parser.add_argument("--config", type=Path)
    parser.add_argument("--rocksteady-home", type=Path)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Build and validate Java, the adapter, dictionaries, and categories, then exit.",
    )
    parser.add_argument(
        "--inventory",
        type=Path,
        help="Completed prepare batch manifest that authoritatively selects video identities.",
    )
    parser.add_argument("--batch-manifest", type=Path, help="Explicit batch manifest path")
    parser.add_argument(
        "--cache-root",
        type=Path,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--failure-history-for",
        type=Path,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--run-id",
        help="Optional parent Text-processing run identifier recorded in manifests.",
    )
    parser.add_argument("--dictionary", action="append")
    parser.add_argument("--dictionary-combination", choices=("merge", "override"))
    parser.add_argument(
        "--analyser",
        choices=("simple",),
        help="RockSteady analyser (0.4 POS is disabled because it returns no tokens)",
    )
    parser.add_argument("--value-type", choices=("total", "percentage", "z_score"))
    parser.add_argument("--category", action="append")
    parser.add_argument(
        "--all-categories",
        action="store_true",
        help="Ignore configured category filters and export every category in the dictionaries.",
    )
    parser.add_argument("--threads", type=int)
    parser.add_argument("--timeout", type=int)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        config_path = args.config
        default_local_config = ADAPTER_ROOT / "config.local.json"
        if config_path is None and default_local_config.is_file():
            config_path = default_local_config
        rocksteady_home = resolve_rocksteady_home(args.rocksteady_home, config_path)
        settings = load_settings(config_path, args)
        if args.check:
            if any(
                value is not None
                for value in (
                    args.input,
                    args.output,
                    args.output_root,
                    args.inventory,
                    args.batch_manifest,
                    args.cache_root,
                    args.failure_history_for,
                    args.run_id,
                )
            ):
                raise ValueError("--check does not accept input or output paths")
            categories, application_jar, _classes = check_runtime(rocksteady_home, settings)
            print(
                "ROCKSTEADY_CHECK_OK "
                f"jar={application_jar.name} dictionaries={len(settings.dictionaries)} "
                f"categories={len(categories)}"
            )
            return 0
        if args.input is None:
            raise ValueError("input is required unless --check is used")
        if args.output is None and args.output_root is None:
            raise ValueError("one of --output or --output-root is required")
        requested_output = args.output_root or args.output
        assert requested_output is not None
        input_path = args.input.resolve()
        output_path = assert_safe_output_target(
            lexical_absolute_path(requested_output), input_path
        )
        identities: set[str] | None = None
        source_ids: dict[str, str] = {}
        upstream_inventory_sha256: str | None = None
        if args.inventory is not None:
            identities, upstream_inventory_sha256 = load_authoritative_inventory(
                args.inventory, input_root=input_path
            )
            source_ids = load_authoritative_source_ids(args.inventory)
        jobs, single = discover_jobs(
            input_path,
            output_path,
            output_is_root=args.output_root is not None,
            identities=identities,
            source_ids=source_ids,
        )
        batch_manifest = (
            args.batch_manifest.resolve()
            if args.batch_manifest is not None
            else (
                None
                if single
                else output_path / "_manifests" / "rocksteady_run_manifest.json"
            )
        )
        snapshot_mode = args.output_root is not None or not single
        if snapshot_mode:
            snapshot_root = assert_safe_output_target(output_path, input_path)
            cache_root_override = (
                assert_safe_output_target(args.cache_root, input_path, snapshot_root)
                if args.cache_root is not None
                else None
            )
            failure_history_output_root = (
                assert_safe_output_target(args.failure_history_for, input_path)
                if args.failure_history_for is not None
                else None
            )
            _, failures = process_jobs_as_snapshot(
                jobs,
                output_root=snapshot_root,
                rocksteady_home=rocksteady_home,
                settings=settings,
                force=args.force,
                dry_run=args.dry_run,
                batch_manifest_path=batch_manifest,
                upstream_inventory_sha256=upstream_inventory_sha256,
                run_id=args.run_id,
                cache_root_override=cache_root_override,
                failure_history_output_root=failure_history_output_root,
            )
        else:
            exact_output = assert_safe_output_target(jobs[0].output_csv, input_path)
            assert_exact_output_outside_owned_snapshot(exact_output)
            lock_path = exact_output.parent / f".{exact_output.name}.rocksteady.lock"
            with exclusive_process_lock(
                lock_path,
                purpose=f"writing RockSteady CSV {exact_output}",
            ):
                _, failures = process_jobs(
                    jobs,
                    rocksteady_home=rocksteady_home,
                    settings=settings,
                    force=args.force,
                    dry_run=args.dry_run,
                    batch_manifest_path=batch_manifest,
                    upstream_inventory_sha256=upstream_inventory_sha256,
                    run_id=args.run_id,
                )
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        message = concise_error(error)
        if getattr(args, "check", False):
            message += (
                ". Run `powershell -ExecutionPolicy Bypass -File scripts/setup.ps1`, "
                "then rerun `python -m processing.text_analysis.rocksteady_adapter --check`"
            )
        parser.error(message)
    return 1 if failures else 0


def assert_exact_output_outside_owned_snapshot(output_csv: Path) -> None:
    """Prevent a single-file write from bypassing canonical snapshot locks."""

    for ancestor in (output_csv.parent, *output_csv.parents):
        marker = ancestor / OWNER_FILE
        if not marker.is_file():
            continue
        try:
            payload = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if (
            isinstance(payload, dict)
            and payload.get("owner") == OWNER_NAME
            and payload.get("stage") == ROCKSTEADY_STAGE
        ):
            raise ValueError(
                "Exact --output cannot mutate a CSV inside an owned RockSteady "
                f"snapshot ({ancestor}); use --output-root so the whole snapshot "
                "is validated and published under its transaction lock"
            )
