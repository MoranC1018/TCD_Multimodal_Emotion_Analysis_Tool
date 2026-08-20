# YouTube Licence Audit

This package audits YouTube links in DOCX files using the YouTube Data API.
It appends clean licence columns to the checked document and writes detailed
audit evidence to gitignored output/log folders.

## Pipeline Run

Place one or more `.docx` files in `procurement/license_check/input/`, set
`YOUTUBE_API_KEY` in the process environment (or use the launcher's protected
credential setting), then run:

```bash
python -m procurement.license_check.run_license_check
```

The pipeline writes checked documents and summaries to
`procurement/license_check/output/`, with debug logs in
`procurement/license_check/logs/`.

## Direct Audit Run

```bash
python procurement/license_check/audit_docx.py INPUT.docx --output OUTPUT.docx
```

Useful direct options:

```bash
python procurement/license_check/audit_docx.py INPUT.docx --output OUTPUT.docx --api-key YOUR_KEY
python procurement/license_check/audit_docx.py INPUT.docx --output OUTPUT.docx --terms-json procurement/license_check/license_terms_dictionary.json
```

## Outputs

The checked DOCX receives only the readable user-facing columns:

- `License`
- `Date Checked`

Detailed evidence is kept out of the source table and written to generated
audit logs, summaries, and debug CSVs.

If the YouTube API does not return a licence, the audit records
`UNKNOWN / NOT RETURNED`. The full procurement pipeline then samples that row
as Standard YouTube License and leaves a note in the manifest, so the row is
not silently skipped.

## Licence Term Dictionary

Edit `license_terms_dictionary.json` when future audits need updated phrase
patterns. Keep Creative Commons, restrictive, royalty-free, and ambiguous terms
separate so the audit notes remain readable.

Do not put secrets in `config.env`. Do not commit generated checked documents,
audit summaries, debug CSVs, or logs.
