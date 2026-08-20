# Video Sampling

Use this folder when you already have a checked DOCX file and only need to
download the 10 percent samples:

```bash
python procurement/video_sampling/run_from_docx.py INPUT.docx
```

The script reads the speaker from the second column, creates speaker-named
folders, downloads raw clips, and normally stitches them into
`stitched_imotions.mp4` for iMotions. It also writes
`extraction_metadata.json` and `_extraction_complete.json` so later runs can
reuse completed folders safely.

Useful options:

```bash
python procurement/video_sampling/run_from_docx.py INPUT.docx --limit 3
python procurement/video_sampling/run_from_docx.py INPUT.docx --force
python procurement/video_sampling/run_from_docx.py INPUT.docx --no-stitch
```

For full Creative Commons downloads, use:

```bash
python procurement/video_sampling/full_video_download.py URL
```
