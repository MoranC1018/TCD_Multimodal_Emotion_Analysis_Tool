from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXCLUDED_TRACKED_ROOTS = (
    "processing/audio_analysis/opensmile-3.0-win-x64/",
)


def tracked_project_text_files() -> list[tuple[str, str]]:
    completed = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
    )
    tracked: list[tuple[str, str]] = []
    for raw_path in completed.stdout.split(b"\0"):
        if not raw_path:
            continue
        relative_path = raw_path.decode("utf-8")
        if relative_path.startswith(EXCLUDED_TRACKED_ROOTS):
            continue
        try:
            text = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        tracked.append((relative_path, text))
    return tracked


class AsciiPunctuationContractTests(unittest.TestCase):
    def test_tracked_project_text_uses_no_em_dash(self) -> None:
        em_dash = chr(0x2014)
        occurrences: list[str] = []
        for relative_path, text in tracked_project_text_files():
            for line_number, line in enumerate(text.splitlines(), start=1):
                search_from = 0
                while True:
                    column = line.find(em_dash, search_from)
                    if column < 0:
                        break
                    occurrences.append(
                        f"{relative_path}:{line_number}:{column + 1}: {line.strip()}"
                    )
                    search_from = column + 1
        self.assertEqual(
            occurrences,
            [],
            "Tracked project-owned text contains U+2014:\n" + "\n".join(occurrences),
        )


if __name__ == "__main__":
    unittest.main()
