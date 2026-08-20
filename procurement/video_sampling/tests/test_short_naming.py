import unittest

from procurement.video_sampling.naming import make_video_output_folder_name


class ShortVideoNamingTests(unittest.TestCase):
    def test_video_output_folder_name_uses_first_ten_compact_title_chars_and_video_id(self):
        name = make_video_output_folder_name(" A very long video title with spaces! ", "XUPj0Ig2f68")

        self.assertEqual(name, "Averylongv_[XUPj0Ig2f68]")
        self.assertNotIn(" ", name)

    def test_video_output_folder_name_keeps_full_video_suffix(self):
        name = make_video_output_folder_name("Election speech", "abc123", suffix="_full_video")

        self.assertEqual(name, "Electionsp_[abc123]_full_video")


if __name__ == "__main__":
    unittest.main()
