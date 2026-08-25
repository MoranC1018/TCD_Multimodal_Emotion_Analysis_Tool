import math
import unittest

from audio_pipeline.windows import make_windows


class WindowingTests(unittest.TestCase):
    def test_window_generation_rejects_nonfinite_or_excessive_workloads(self):
        with self.assertRaisesRegex(ValueError, "finite"):
            make_windows(math.inf, 10.0, 5.0)
        with self.assertRaisesRegex(ValueError, "window limit"):
            make_windows(10_001.0, 1.0, 1.0, max_windows=10_000)

    def test_overlapping_windows_cover_short_tail(self):
        windows = make_windows(duration_seconds=23.0, window_seconds=10.0, stride_seconds=5.0)

        self.assertEqual(
            [(round(item.start, 3), round(item.end, 3), item.row) for item in windows],
            [
                (0.0, 10.0, 1),
                (5.0, 15.0, 2),
                (10.0, 20.0, 3),
                (13.0, 23.0, 4),
            ],
        )

    def test_very_short_audio_uses_one_window(self):
        windows = make_windows(duration_seconds=2.4, window_seconds=10.0, stride_seconds=5.0)

        self.assertEqual(len(windows), 1)
        self.assertEqual(windows[0].start, 0.0)
        self.assertEqual(windows[0].end, 2.4)

    def test_tiny_tail_does_not_duplicate_almost_the_entire_window(self):
        windows = make_windows(duration_seconds=12.010688, window_seconds=12.0, stride_seconds=12.0)

        self.assertEqual(
            [(item.start, item.end, item.row) for item in windows],
            [(0.0, 12.0, 1)],
        )


if __name__ == "__main__":
    unittest.main()
