# Parse Text Output

This folder holds the raw CSV export from RockSteady, which feeds into the
postprocessing split and analyse steps.

## What goes here

After running RockSteady on the `.txt` files in `prepare_input/rocksteady_input/`,
export the results in **Percentage** mode and save the file here:

```
processing/text_analysis/parse_output/output_percentage.csv
```

This file is gitignored (generated output). Do not commit it.

## Next step

Once `output_percentage.csv` is in place, run the postprocessing pipeline:

```bash
# Split combined export into one CSV per speaker:
python -m postprocessing.text split \
    --input processing/text_analysis/parse_output/output_percentage.csv \
    --reference processing/text_analysis/prepare_input/rocksteady_input \
    --output-dir postprocessing/text_output/MY_RUN

# Generate histograms, chi-squared, and Spearman reports:
python -m postprocessing.text analyse postprocessing/text_output/MY_RUN
```

Reports are written to `postprocessing/output/MY_RUN/`.

## Why Percentage mode?

RockSteady offers three output modes: Total, Percentage, and Z-Score.
**Percentage** is used because values are already in 0–100 range, directly
comparable across speeches of different lengths, and require no further
transformation before histogram binning.
