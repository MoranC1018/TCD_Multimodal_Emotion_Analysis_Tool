from __future__ import annotations

import sys
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parent
REPOSITORY_ROOT = PACKAGE_ROOT.parents[1]
for import_root in (REPOSITORY_ROOT, PACKAGE_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from audio_pipeline.cli import main


if __name__ == "__main__":
    main()
