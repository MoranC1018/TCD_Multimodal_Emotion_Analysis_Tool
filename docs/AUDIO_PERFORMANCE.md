# Audio performance and preserved results

The optimization in this change avoids starting another FFmpeg process for
each emotion-model window. Audio is already decoded once to mono 16 kHz PCM16.
Copying the required samples from that WAV preserves the input to both emotion
models, while FFmpeg remains the conversion path for other formats. OpenSMILE,
model choices, window boundaries, stride, scaling and statistical weighting are
unchanged. Video/Face and Text performance were outside this assessment.

## Measured result

Two sequential ABBA comparisons used a 60-second synthetic repeated speech/video
fixture, 10-second windows, 5-second stride, 11 windows, Windows CPU execution and
four native threads. Each comparison loaded the actual SUPERB categorical
fallback and audEERING dimensional models once and reused them for its four
trials. All exported model and acoustic data rows were identical across each
comparison; this was actual inference, not mocked predictions.

| Comparison | FFmpeg window export, median whole-video processing | PCM window export, median whole-video processing | Observed reduction |
| --- | --- | --- | --- |
| Prototype | 21.66 s | 19.11 s | 11.8% |
| Implemented fast path | 23.51 s | 21.34 s | 9.3% |

These timings exclude the one-time model load (9.34 seconds in the first
comparison), include extraction/OpenSMILE/inference/report writing, and are
observations on one host and one fixture. The ABBA order reduces simple warm-up
bias; it does not eliminate machine load, filesystem/cache variation or provide
a population estimate. Do not promise a 9–12% improvement on other recordings.

The first baseline spent about 18.37 of 22.91 seconds in emotion processing,
including 1.29 seconds in its 11 FFmpeg window exports. Model inference remains the
main cost; eliminating decoder startup cannot make the whole workflow arbitrarily
fast. The batch processor already loads its model bundle once per batch.

## Correctness checks

The new regression suite compares decoded PCM against actual FFmpeg at integer,
fractional and near-half-sample boundaries, including tail clipping and paths
with spaces/Unicode. Noncanonical stereo 8 kHz input still follows FFmpeg conversion.
Positive durations that quantize below one sample retain FFmpeg's existing path.
Outputs naming the source file, including an existing hard link, are rejected
before writing. Independent review compared 92 canonical cases and four fallback
formats against actual FFmpeg and verified source preservation.
Timestamp formatting remains six decimals and sample selection uses nearest
sample rounding. Full model comparisons verify the final exported tables, beyond
the smaller sample-equivalence checks. This establishes software equivalence on
the stated fixtures; it does not measure emotion recognition accuracy.

## Repeat on a representative recording

From the repository root, after the supported setup, use a new evidence folder:

```powershell
.\.venv\Scripts\python.exe tools/benchmark_audio_windows.py 'C:\data\representative.mp4' --output 'C:\evidence\audio-benchmark-NEW' --device cpu --native-threads 4
```

The command runs the same source four times, saves both paths' outputs and a
JSON report, and returns nonzero if data differ. It may need model downloads on
first use. Set `HF_HUB_OFFLINE=1` only after the required models are cached.
Record the source commit, environment inventory and device with the result.
Use a short representative clip first: four long runs can be expensive.

## Further tuning

- Process folders in one batch to amortize model startup. Keep cache/reuse
  checks enabled where that modality supports them.
- Measure native thread counts on the actual host. More threads can add
  overhead; one thread prioritizes headroom over throughput. Resource limits
  can deliberately pause a busy machine, so retain their settings with timings.
- CUDA is an available engine option, but was not tested in this CPU audit.
  Validate matched dependencies, memory use and representative outputs before
  using GPU timings or changing the study's execution protocol.
- Batched emotion inference and GPU processing could provide larger gains,
  but need model-specific padding/masking, memory and numeric-equivalence tests.
  They are not implemented or claimed as validated here.

Increasing stride, shortening model windows, dropping a modality or selecting a
different model can reduce work but changes the measurement protocol. Such
changes require a research decision and are not this optimization.
