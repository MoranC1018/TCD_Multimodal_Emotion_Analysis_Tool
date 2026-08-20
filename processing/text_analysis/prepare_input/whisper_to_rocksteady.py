"""
Whisper JSON -> Plain Text Converter
=====================================

Extracts text from Whisper transcription JSON files and writes it as plain
text. For bilingual JSONs, picks the requested language (text_en or text_fr);
for non-bilingual JSONs, always uses text (the original transcription).
Recursively processes subfolders; output directory mirrors the input structure.

Usage:
    python whisper_to_rocksteady.py video.json
    python whisper_to_rocksteady.py input/
    python whisper_to_rocksteady.py input/ -o output/
    python whisper_to_rocksteady.py input/ --lang fr

Output:
    prepare_input/rocksteady_input/<mirrored/path>/<name>.txt   (default)

Author: Jiaming Liu
"""

import argparse
import json
import sys
from pathlib import Path

LANG_KEY = {"en": "text_en", "fr": "text_fr"}


def extract_text(data, lang="en"):
    task = data.get("task", "transcribe")
    if task == "bilingual":
        key = LANG_KEY.get(lang, "text_en")
    else:
        key = "text"
    return " ".join(
        seg.get(key, "").strip()
        for seg in data.get("segments", [])
        if seg.get(key, "").strip()
    )


def collect_json_files(input_path):
    p = Path(input_path)
    if p.is_file():
        if p.suffix.lower() != ".json":
            print(f"ERROR: input file is not a .json: {p}", file=sys.stderr)
            sys.exit(1)
        return p.parent, [p]
    if p.is_dir():
        files = sorted(p.rglob("*.json"))
        if not files:
            print(f"ERROR: no .json files found under {p}", file=sys.stderr)
            sys.exit(1)
        return p, files
    print(f"ERROR: input not found: {p}", file=sys.stderr)
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Extract text from Whisper JSON, preserving folder structure"
    )
    parser.add_argument("input", help="A Whisper JSON file or a folder of them")
    parser.add_argument("-o", "--output", default=None,
                        help="Output root folder (default: rocksteady_input_<lang>/)")
    parser.add_argument("--lang", choices=["en", "fr"], default="en",
                        help="Output language for bilingual JSONs: en (default) or fr")
    args = parser.parse_args()

    input_root, json_files = collect_json_files(args.input)
    out_root = Path(args.output) if args.output else Path(__file__).parent / "rocksteady_input"

    ok = 0
    for jf in json_files:
        try:
            with open(jf, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"  WARNING: skipping {jf}: {e}", file=sys.stderr)
            continue

        text = extract_text(data, lang=args.lang)
        if not text:
            print(f"  WARNING: {jf.name} has no text, skipping.", file=sys.stderr)
            continue

        rel = jf.relative_to(input_root)
        out_path = out_root / rel.with_suffix(".txt")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text, encoding="utf-8")
        print(f"  {jf} -> {out_path}")
        ok += 1

    if ok == 0:
        print("ERROR: no valid text written.", file=sys.stderr)
        sys.exit(1)

    print(f"\nDone. {ok} file(s) written under {out_root}/")


if __name__ == "__main__":
    main()
