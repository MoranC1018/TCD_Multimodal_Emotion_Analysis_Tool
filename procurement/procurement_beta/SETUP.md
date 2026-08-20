# Clean Speaker Segments Setup

This mode is designed for local research machines and reproducible public
research-software handoff. Do not commit API keys, Hugging Face tokens,
downloaded videos, model weights, or generated outputs. Clean Speaker outputs
require researcher review and are not diagnostic results.

## What The Mode Requires

Required command-line tools:

- `ffmpeg` and `ffprobe` for media probing, audio extraction, cutting, and
  stitching.
- `yt-dlp` for YouTube videos referenced by DOCX inputs.

Required Python packages for model-backed clean results:

- `opencv-python` for OpenCV video IO and YuNet/SFace inference.
- `torch` for model execution.
- `speechbrain` for ECAPA speaker embeddings on ungated local voice clustering.
- `psutil` for CPU/RAM telemetry in the resource guard.

Optional packages:

- `pyannote.audio` for gated Hugging Face diarization when researchers have
  accepted the model terms.
- `mediapipe` for future landmark/head-pose quality scoring. The current strict
  clean path does not treat MediaPipe-only detections as identity evidence.

## Windows Setup Steps

1. Install `ffmpeg` and make sure both `ffmpeg` and `ffprobe` are on `PATH`.
   Chocolatey example:

   ```powershell
   choco install ffmpeg
   ```

2. Install or update Python dependencies in the environment that launches this
   repository:

   ```powershell
   python -m pip install --upgrade yt-dlp opencv-python torch speechbrain psutil pyannote.audio
   ```

3. Create a free Hugging Face account and access token if using gated Hugging
   Face models.

4. If using the optional pyannote diarization path, accept the model terms:

   - https://huggingface.co/pyannote/speaker-diarization-3.1
   - https://huggingface.co/pyannote/segmentation-3.0

5. Add the token in the launcher Settings panel, or set one of these
   environment variables before starting the launcher:

   ```powershell
   $env:HF_TOKEN = "paste-your-token-here"
   ```

6. Start the launcher:

   ```powershell
   python -m application.launcher
   ```

7. In Procurement, choose `Clean speaker segments`, then select either:

   - `Clean compilation`: keeps every clean overlap and inserts the configured
     black/silent gap, default `0.5` seconds.
   - `Percentage sample`: selects the requested percentage from clean overlaps,
     prioritising the longest uninterrupted sections.

## Model Download And Cache Behavior

The mode downloads OpenCV Zoo YuNet/SFace ONNX model files on first use when
they are not already present. The cache lives outside the repository, normally:

```text
%LOCALAPPDATA%\MultimodalEmotionAnalysisTool\models\opencv_zoo
```

Those files must stay out of git. If a researcher cannot download models on a
locked-down machine, they can place the official ONNX files in that cache
manually.

## Accuracy Rules

The mode is intentionally conservative:

- A face frame must contain exactly one accepted face candidate.
- The candidate must be large enough, central enough, sharp enough, and have an
  embedding.
- The same identity must own at least 60 percent of the random baseline batch.
- If no 60 percent baseline is found, no clean face intervals are emitted.
- A rejected sampled frame splits the face-visible interval. The mode does not
  smooth across no-face frames, projection-screen faces, or audience/cutaway
  frames, because that would create falsely clean clips.
- If model-backed voice clustering is unavailable, audio activity is recorded
  only as a low-confidence diagnostic and cannot create clean speaker segments.
- If OpenCV/FFmpeg cannot decode an individual sampled frame, that timestamp is
  treated as a rejected sample and the scan continues. A decode miss therefore
  splits intervals instead of bridging through unknown video content.

This can produce fewer segments than a permissive detector. That is deliberate:
for research procurement, false positives such as audience cutaways are worse
than rejected footage.

## Performance Expectations

The face track is usually the main accuracy bottleneck. On the local 4,997
second `mZBHkYWKE5M` test video, the OpenCV Zoo YuNet/SFace path scanned at
1 FPS in about 161 seconds on this machine after replacing seek-per-frame reads
with sequential frame grabs. An earlier seek-heavy version took about 434
seconds on the same video.

The main optimizations now in place are:

- sequential video reads with frame grabs instead of a timestamp seek for every
  sampled second;
- YuNet detection on a downscaled frame, with SFace still receiving source-frame
  coordinates for the accepted face;
- skipping SFace embedding work unless the frame has exactly one clear face;
- retaining only face crops and embeddings for candidates, not full 1080p/4K
  frame copies, so long videos do not exhaust memory during analysis;
- removing raw `main_voice_audio.wav` and isolated voice WAV artifacts by
  default. Those large files are kept only when `Keep debug artifacts` /
  `--keep-debug` is enabled;
- skipping the heavy `pyannote.audio` import entirely when no Hugging Face token
  is configured. No-token runs still fail closed for clean voice segments.

Further speed improvements mostly trade away accuracy. Lowering `scan FPS`
reduces runtime, but increases the chance of missing short audience cutaways.
Raising `scan FPS` improves cutaway detection but costs roughly proportional
runtime. The default workflow processes one video at a time so each speaker
folder, manifest, review timeline, and stitched output appears as soon as that
video finishes.

### Resource Guard And Stability

The mode defaults to one video at a time, but `--workers` / the UI
Concurrent videos field can run multiple videos at once on stronger machines.
By default, face analysis then voice analysis run sequentially inside each video
so weaker research laptops do not pin CPU, RAM, and GPU at the same time. The
advanced `--parallel-detectors` / UI toggle can run the two streams together on
stronger workstations when speed is more important than headroom.
The default resource guard waits before download, analysis, and stitching when
available system headroom falls below `15%`:

- RAM free percentage, using `psutil` or Windows memory APIs;
- CPU free percentage, when `psutil` is installed;
- NVIDIA GPU utilization and memory free percentage, when `nvidia-smi` is
  available.

Output disk space is warning-only: the run continues unless another resource is
under pressure, and it warns when the output drive has less than 10 GiB free.

Set `Resource guard %` to a higher value on weaker machines. Set it to `0` only
for controlled benchmark machines. Do not start full-suite runs as hidden
background jobs during validation; use the launcher so the stop button and log
surface are visible.

For large suites, prefer an output folder on a local non-synced drive. Sync
services can be used after the run finishes.

Recent local smoke checks:

- A cached 4,310 second long-form reference video completed face analysis after
  decoder warnings near the end and wrote 20 same-person face crops.
- The non-debug CLI path completed in about 228 seconds for face analysis and
  about 89 seconds for local low-confidence audio activity. Because no Hugging
  Face token was configured on that machine, the manifest correctly recorded
  `no_clean_segments` rather than stitching a questionable output.

## Research And License Sources

Review `THIRD_PARTY_NOTICES.md` before packaging or sharing an environment. It
records upstream repositories, licenses, model-term requirements, and papers for
FFmpeg, yt-dlp, OpenCV Zoo YuNet/SFace, MediaPipe, psutil, pyannote.audio, and
SpeechBrain.

Also review the repository root `THIRD_PARTY_NOTICES.md` for the overall MIT
boundary and bundled OpenSMILE 3.0.0 provenance. Dependency-specific terms take
precedence over the project licence.

Do not redistribute FFmpeg binaries, model weights, or Hugging Face model files
unless the recipient packaging has been checked against the exact upstream
license and model terms.
