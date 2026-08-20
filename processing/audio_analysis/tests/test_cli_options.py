import unittest

from audio_pipeline.cli import build_parser


class CliOptionsTests(unittest.TestCase):
    def test_model_control_options_are_available_for_batch_and_single(self):
        parser = build_parser()

        batch_args = parser.parse_args(["batch", "downloads", "--skip-emotion-models", "--device", "cpu"])
        single_args = parser.parse_args(["single", "clip.mp4", "--skip-emotion-models", "--device", "cuda"])

        self.assertTrue(batch_args.skip_emotion_models)
        self.assertEqual(batch_args.device, "cpu")
        self.assertTrue(single_args.skip_emotion_models)
        self.assertEqual(single_args.device, "cuda")

    def test_doctor_subcommand_is_available(self):
        parser = build_parser()

        args = parser.parse_args(["doctor"])

        self.assertEqual(args.command, "doctor")

    def test_batch_accepts_repeated_source_ids_but_single_does_not(self):
        parser = build_parser()

        batch_args = parser.parse_args(
            [
                "batch",
                "downloads",
                "--catalog-sha256",
                "a" * 64,
                "--source-id",
                "source-0002",
                "--source-id",
                "source-0001",
            ]
        )

        self.assertEqual(batch_args.source_id, ["source-0002", "source-0001"])
        self.assertEqual(batch_args.catalog_sha256, "a" * 64)
        with self.assertRaises(SystemExit):
            parser.parse_args(["single", "clip.mp4", "--source-id", "source-0001"])


if __name__ == "__main__":
    unittest.main()
