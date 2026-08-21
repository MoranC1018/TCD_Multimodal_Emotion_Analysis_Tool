from __future__ import annotations

import csv
import json
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from analysis.tests.test_text_segments import (
    write_rocksteady_csv,
    write_whisper_json,
)
from analysis.text_pipeline.postprocess import analyse_text_segments_folder
from analysis.text_pipeline.batch import (
    analyse_text_segment_pair,
    validate_pair_lineage_contract,
)
from analysis.text_pipeline.ownership import (
    BATCH_MANIFEST_FILE,
    OUTPUT_OWNER_FILE,
    text_output_lock,
)


class TextPairPostprocessingTests(unittest.TestCase):
    def _fixture(
        self,
        root: Path,
        *,
        selected_video: str = "001_France_Test_Speaker_20250101",
        extra_video: str | None = None,
    ) -> tuple[Path, Path, Path, Path, Path]:
        extra_video = extra_video or selected_video
        selected = root / "selected_input"
        extra = root / "extra_input"
        whisper = root / "whisper"
        prepare = root / "prepare"
        output = root / "published"
        prepare.mkdir(parents=True)
        write_rocksteady_csv(
            selected / "France" / "Test_Speaker" / f"{selected_video}.csv"
        )
        write_rocksteady_csv(
            extra / "France" / "Test_Speaker" / f"{extra_video}.csv",
            include_moral=True,
        )
        write_whisper_json(whisper, selected_video)
        if extra_video != selected_video:
            write_whisper_json(whisper, extra_video)
        return selected, extra, whisper, prepare, output

    def test_pair_publishes_one_run_id_and_parent_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            selected, extra, whisper, prepare, output = self._fixture(root)

            result = analyse_text_segment_pair(
                selected,
                extra,
                output,
                whisper_root=whisper,
                prepare_root=prepare,
                write_graphs=False,
                run_id="pair-run-001",
            )

            self.assertEqual(result.run_id, "pair-run-001")
            self.assertEqual(result.identity_count, 1)
            self.assertEqual(result.selected.output_dir, output.resolve() / "selected")
            self.assertEqual(result.extra.output_dir, output.resolve() / "extra")
            self.assertTrue(result.selected.video_summary_path.is_file())
            self.assertTrue(result.extra.video_summary_path.is_file())
            multimodal = output / "multimodal"
            self.assertTrue((multimodal / "README.md").is_file())
            self.assertTrue((multimodal / "construct_mapping.csv").is_file())
            self.assertTrue((multimodal / "video_level_summary.csv").is_file())
            self.assertTrue((multimodal / "speaker_level_summary.csv").is_file())
            segment_files = list((multimodal / "segment_level").rglob("*.csv"))
            self.assertEqual(len(segment_files), 1)
            with (multimodal / "video_level_summary.csv").open(
                encoding="utf-8", newline=""
            ) as handle:
                headers = next(csv.reader(handle))
            self.assertIn("Positive Sentiment", headers)
            self.assertIn("Negative Sentiment", headers)
            self.assertIn("Arousal / Activation", headers)
            self.assertIn("Dominance / Power", headers)
            self.assertIn("Affiliation / Social orientation", headers)
            self.assertTrue(list((multimodal / "graphs").rglob("*.svg")))

            batch = json.loads((output / BATCH_MANIFEST_FILE).read_text(encoding="utf-8"))
            self.assertEqual(batch["schema_version"], "1.0")
            self.assertEqual(batch["kind"], "text-postprocessing-selected-extra-pair")
            self.assertEqual(batch["run_id"], "pair-run-001")
            self.assertEqual(batch["status"], "completed")
            self.assertEqual(batch["identity_inventory"]["count"], 1)
            self.assertEqual(batch["start_here"]["multimodal"], "multimodal/video_level_summary.csv")
            self.assertEqual(len(batch["variants"]["selected"]["categories"]), 7)
            self.assertEqual(len(batch["variants"]["extra"]["categories"]), 8)
            for variant in ("selected", "extra"):
                variant_manifest = json.loads(
                    (output / variant / "output_manifest.json").read_text(encoding="utf-8")
                )
                self.assertEqual(variant_manifest["run_id"], "pair-run-001")
                self.assertEqual(variant_manifest["variant"], variant)
                self.assertTrue((output / variant / OUTPUT_OWNER_FILE).is_file())
            self.assertTrue((output / OUTPUT_OWNER_FILE).is_file())

    def test_catalog_pair_publishes_and_hash_binds_exact_sidecars_and_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            selected, extra, whisper, prepare, output = self._fixture(root)
            whisper_path = next(whisper.rglob("*.json"))
            whisper_payload = json.loads(whisper_path.read_text(encoding="utf-8"))
            whisper_payload["source_id"] = "source-0001"
            whisper_path.write_text(json.dumps(whisper_payload), encoding="utf-8")
            context = {
                "source_id": "source-0001",
                "speaker": "test-speaker",
                "speaker_display": "Test Speaker",
                "source_kind": "youtube",
                "resolved_link": "https://www.youtube.com/watch?v=example0001",
                "catalog_sha256": "a" * 64,
                "user_metadata": {"Country": "France"},
                "system_metadata": {"title": "Interview"},
                "output_mapping": {"video_directory": str(root / "catalog" / "source-0001")},
                "run_root": str(root / "catalog"),
            }
            manifest_bytes = b'{"format_version":1}\n'
            metadata_bytes = b"SourceID\nsource-0001\n"
            discovery = SimpleNamespace(
                catalog_sha256="a" * 64,
                sidecar_pair=(manifest_bytes, metadata_bytes),
                jobs=(SimpleNamespace(source_id="source-0001", source_context=context),),
            )

            analyse_text_segment_pair(
                selected,
                extra,
                output,
                whisper_root=whisper,
                prepare_root=prepare,
                write_graphs=False,
                catalog_discovery=discovery,
            )

            batch = json.loads((output / BATCH_MANIFEST_FILE).read_text(encoding="utf-8"))
            binding = batch["source_binding"]
            self.assertEqual((output / binding["source_manifest"]).read_bytes(), manifest_bytes)
            self.assertEqual((output / binding["source_metadata"]).read_bytes(), metadata_bytes)
            self.assertEqual(binding["catalog_sha256"], "a" * 64)
            self.assertEqual(binding["source_contexts"][0]["source_id"], "source-0001")

    def test_pair_accepts_procurement_speaker_video_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            selected = root / "selected_input"
            extra = root / "extra_input"
            whisper = root / "whisper"
            prepare = root / "prepare"
            output = root / "published"
            prepare.mkdir()
            speaker = "Test Speaker"
            video = "YouTubeti_[abc123]"
            write_rocksteady_csv(selected / speaker / f"{video}.csv")
            write_rocksteady_csv(extra / speaker / f"{video}.csv", include_moral=True)
            write_whisper_json(whisper, video, country="", speaker=speaker)

            result = analyse_text_segment_pair(
                selected,
                extra,
                output,
                whisper_root=whisper,
                prepare_root=prepare,
                write_graphs=False,
            )

            self.assertEqual(result.identity_count, 1)
            batch = json.loads((output / BATCH_MANIFEST_FILE).read_text(encoding="utf-8"))
            self.assertEqual(
                batch["identity_inventory"]["identities"],
                [f"{speaker}/{video}"],
            )
            self.assertTrue(
                (
                    output
                    / "multimodal"
                    / "segment_level"
                    / speaker
                    / f"{video}_constructs.csv"
                ).is_file()
            )

    def test_identity_mismatch_preserves_previous_complete_pair(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            selected, extra, whisper, prepare, output = self._fixture(root)
            analyse_text_segment_pair(
                selected,
                extra,
                output,
                whisper_root=whisper,
                prepare_root=prepare,
                write_graphs=False,
                run_id="good-run",
            )
            previous_batch = (output / BATCH_MANIFEST_FILE).read_bytes()

            old_extra = next(extra.rglob("*.csv"))
            old_extra.unlink()
            mismatched_video = "002_France_Test_Speaker_20250201"
            write_rocksteady_csv(
                extra / "France" / "Test_Speaker" / f"{mismatched_video}.csv",
                include_moral=True,
            )
            write_whisper_json(whisper, mismatched_video)

            with self.assertRaisesRegex(ValueError, "identity sets differ"):
                analyse_text_segment_pair(
                    selected,
                    extra,
                    output,
                    whisper_root=whisper,
                    prepare_root=prepare,
                    write_graphs=False,
                    run_id="bad-run",
                )

            self.assertEqual((output / BATCH_MANIFEST_FILE).read_bytes(), previous_batch)
            self.assertEqual(
                json.loads(previous_batch)["run_id"],
                "good-run",
            )

    def test_final_publication_failure_preserves_previous_complete_pair(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            selected, extra, whisper, prepare, output = self._fixture(root)
            analyse_text_segment_pair(
                selected,
                extra,
                output,
                whisper_root=whisper,
                prepare_root=prepare,
                write_graphs=False,
                run_id="published-run",
            )
            previous_batch = (output / BATCH_MANIFEST_FILE).read_bytes()

            with patch(
                "analysis.text_pipeline.batch.replace_output_dir",
                side_effect=PermissionError("simulated final publication failure"),
            ):
                with self.assertRaisesRegex(PermissionError, "publication failure"):
                    analyse_text_segment_pair(
                        selected,
                        extra,
                        output,
                        whisper_root=whisper,
                        prepare_root=prepare,
                        write_graphs=False,
                        run_id="unpublished-run",
                    )

            self.assertEqual((output / BATCH_MANIFEST_FILE).read_bytes(), previous_batch)
            self.assertFalse(any(output.parent.glob(f".{output.name}_pair_*")))

    def test_keyboard_interrupt_removes_unpublished_pair_staging(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            selected, extra, whisper, prepare, output = self._fixture(root)

            with patch(
                "analysis.text_pipeline.batch.analyse_text_segments_folder",
                side_effect=KeyboardInterrupt,
            ):
                with self.assertRaises(KeyboardInterrupt):
                    analyse_text_segment_pair(
                        selected,
                        extra,
                        output,
                        whisper_root=whisper,
                        prepare_root=prepare,
                        write_graphs=False,
                        run_id="cancelled-pair",
                    )

            self.assertFalse(output.exists())
            self.assertFalse(any(output.parent.glob(f".{output.name}_pair_*")))

    def test_foreign_nonempty_outputs_are_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            selected, extra, whisper, prepare, output = self._fixture(root)
            output.mkdir()
            (output / "user_notes.txt").write_text("do not delete", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "Refusing to replace a non-empty"):
                analyse_text_segment_pair(
                    selected,
                    extra,
                    output,
                    whisper_root=whisper,
                    prepare_root=prepare,
                    write_graphs=False,
                )
            self.assertEqual((output / "user_notes.txt").read_text(), "do not delete")

            single_output = root / "foreign_single"
            single_output.mkdir()
            (single_output / "user_notes.txt").write_text("keep", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Refusing to replace a non-empty"):
                analyse_text_segments_folder(
                    selected,
                    output_root=single_output,
                    whisper_root=whisper,
                    prepare_root=prepare,
                    write_graphs=False,
                )
            self.assertEqual((single_output / "user_notes.txt").read_text(), "keep")

    def test_output_source_overlap_is_rejected_before_generation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            selected, extra, whisper, prepare, _ = self._fixture(root)
            with self.assertRaisesRegex(ValueError, "must not overlap"):
                analyse_text_segments_folder(
                    selected,
                    output_root=selected / "generated_output",
                    whisper_root=whisper,
                    prepare_root=prepare,
                    write_graphs=False,
                )
            with self.assertRaisesRegex(ValueError, "must not overlap"):
                analyse_text_segment_pair(
                    selected,
                    extra,
                    root,
                    whisper_root=whisper,
                    prepare_root=prepare,
                    write_graphs=False,
                )

    def test_pair_and_default_variant_share_the_same_family_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            family = Path(temp_dir).resolve() / "text_output"
            captured: list[Path] = []

            @contextmanager
            def capture_lock(lock_path: Path, *, purpose: str):
                self.assertIn("text postprocessing", purpose)
                captured.append(lock_path)
                yield

            with patch(
                "analysis.text_pipeline.ownership.exclusive_process_lock",
                side_effect=capture_lock,
            ):
                with text_output_lock(
                    family / "selected",
                    scope="variant",
                    variant="selected",
                ):
                    pass
                with text_output_lock(family, scope="pair"):
                    pass
            self.assertEqual(len(captured), 2)
            self.assertEqual(captured[0], captured[1])

    def test_ownerless_legacy_variant_is_safely_upgraded(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            selected, _, whisper, prepare, _ = self._fixture(root)
            output = root / "variant_output"
            analyse_text_segments_folder(
                selected,
                output_root=output,
                whisper_root=whisper,
                prepare_root=prepare,
                write_graphs=False,
                run_id="owned-run",
            )

            (output / OUTPUT_OWNER_FILE).unlink()
            manifest_path = output / "output_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["output_inventory"] = [
                item
                for item in manifest["output_inventory"]
                if item["path"] != OUTPUT_OWNER_FILE
            ]
            manifest.pop("kind", None)
            manifest.pop("run_id", None)
            manifest.pop("variant", None)
            manifest["schema_version"] = "2.0"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            result = analyse_text_segments_folder(
                selected,
                output_root=output,
                whisper_root=whisper,
                prepare_root=prepare,
                write_graphs=False,
                run_id="upgraded-run",
            )
            upgraded = json.loads(result.output_manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(upgraded["run_id"], "upgraded-run")
            self.assertEqual(upgraded["publication"]["previous_target_state"], "legacy")
            self.assertTrue((output / OUTPUT_OWNER_FILE).is_file())

    def test_ownerless_legacy_pair_parent_is_safely_upgraded(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            selected, extra, whisper, prepare, output = self._fixture(root)
            analyse_text_segment_pair(
                selected,
                extra,
                output,
                whisper_root=whisper,
                prepare_root=prepare,
                write_graphs=False,
                run_id="first-pair",
            )
            (output / OUTPUT_OWNER_FILE).unlink()
            (output / BATCH_MANIFEST_FILE).unlink()

            result = analyse_text_segment_pair(
                selected,
                extra,
                output,
                whisper_root=whisper,
                prepare_root=prepare,
                write_graphs=False,
                run_id="upgraded-pair",
            )
            batch = json.loads(result.batch_manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(batch["publication"]["previous_target_state"], "legacy")
            self.assertEqual(batch["run_id"], "upgraded-pair")
            self.assertTrue((output / OUTPUT_OWNER_FILE).is_file())

    def test_verified_pair_requires_exact_selected_to_extra_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            extra_root = Path(temp_dir) / "extra"
            adapter_manifest = (
                extra_root / "_manifests" / "rocksteady_run_manifest.json"
            ).resolve()
            digest = "a" * 64
            selected_manifest = {
                "upstream_provenance": {
                    "status": "verified_sha256",
                    "kind": "derived-rocksteady-category-view",
                    "manifest_path": str(Path(temp_dir) / "selected" / "derived_view_manifest.json"),
                    "manifest_sha256": "b" * 64,
                    "details": {
                        "source_root": str(extra_root.resolve()),
                        "source_manifest_path": str(adapter_manifest),
                        "source_manifest_sha256": digest,
                    },
                }
            }
            extra_manifest = {
                "inputs": {"rocksteady_csv_root": str(extra_root.resolve())},
                "upstream_provenance": {
                    "status": "verified_sha256",
                    "kind": "rocksteady-adapter-batch",
                    "manifest_path": str(adapter_manifest),
                    "manifest_sha256": digest,
                    "details": {},
                },
            }

            lineage = validate_pair_lineage_contract(selected_manifest, extra_manifest)
            self.assertEqual(lineage["status"], "verified_sha256")
            self.assertEqual(lineage["source_adapter_manifest_sha256"], digest)

            selected_manifest["upstream_provenance"]["details"][
                "source_manifest_sha256"
            ] = "c" * 64
            with self.assertRaisesRegex(ValueError, "different RockSteady adapter manifest"):
                validate_pair_lineage_contract(selected_manifest, extra_manifest)

    def test_pair_rejects_mixed_verified_and_legacy_lineage(self) -> None:
        selected = {
            "upstream_provenance": {
                "status": "legacy_unverified",
                "kind": "standalone-rocksteady-csv",
                "details": {},
            }
        }
        extra = {
            "upstream_provenance": {
                "status": "verified_sha256",
                "kind": "rocksteady-adapter-batch",
                "details": {},
            }
        }
        with self.assertRaisesRegex(ValueError, "mixes verified and unverified"):
            validate_pair_lineage_contract(selected, extra)


if __name__ == "__main__":
    unittest.main()
