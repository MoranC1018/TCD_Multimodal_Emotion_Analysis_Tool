# Procurement Beta Third-Party Notices

The Clean Speaker segment beta is part of the **Multimodal Emotion Analysis
Tool** and is intended for local research workflows. Its dependencies carry
different licences and model terms; the root MIT License does not relicense
them. The repository should not commit model weights, API keys, Hugging Face
tokens, or downloaded videos. Researchers should install dependencies and
accept any model terms on their own machines.

This notice is not legal advice. It records the upstream sources checked for
packaging and research handoff. See the root `THIRD_PARTY_NOTICES.md` for the
project-wide boundary and bundled OpenSMILE provenance.

## Runtime tools

- `ffmpeg` / `ffprobe`: required for video/audio probing, cutting, silence
  detection, and stitching. Install from the official FFmpeg project or a
  trusted package manager. FFmpeg's official legal page says FFmpeg is LGPL
  2.1 or later, but GPL applies when optional GPL-covered parts are enabled.
  Do not redistribute a binary without checking the exact build configuration.
- `yt-dlp`: required for YouTube inputs from DOCX rows. Install separately; do
  not bundle downloaded videos or cookies. The upstream project license file
  places yt-dlp under the Unlicense/public-domain dedication text.

## Face detection and identity

- OpenCV Zoo repository: https://github.com/opencv/opencv_zoo
- YuNet face detector model:
  https://github.com/opencv/opencv_zoo/tree/47534e27c9851bb1128ccc0102f1145e27f23f98/models/face_detection_yunet
  - Upstream model page lists YuNet as a lightweight face detector and provides
    a citation: Wu, Peng, and Yu, "YuNet: A tiny millisecond-level face
    detector", Machine Intelligence Research, 2023.
  - The YuNet directory states that files in that directory are MIT licensed.
- SFace face recognition model:
  https://github.com/opencv/opencv_zoo/tree/47534e27c9851bb1128ccc0102f1145e27f23f98/models/face_recognition_sface
  - Upstream model page references "SFace: Sigmoid-Constrained Hypersphere
    Loss for Robust Face Recognition" and the original code base.
  - The SFace directory states that files in that directory are Apache-2.0
    licensed.
- OpenCV Zoo root license:
  https://github.com/opencv/opencv_zoo/blob/47534e27c9851bb1128ccc0102f1145e27f23f98/LICENSE
  - The root repository license is Apache-2.0; individual model directories may
    add more specific notices as above.
- Model storage:
  - The launcher downloads YuNet/SFace ONNX files to a local user cache such as
    `%LOCALAPPDATA%\MultimodalEmotionAnalysisTool\models\opencv_zoo`.
  - These weights are intentionally not committed to git.
- Current beta use:
  - YuNet detects candidate faces.
  - SFace creates embeddings for same-person matching.
  - A frame is accepted only when exactly one sufficiently large, central,
    sharp candidate face matches the dominant identity baseline.
  - If a 60 percent same-person baseline is not found, the beta writes no clean
    face intervals rather than falling back to a largest-cluster guess.

## Optional landmark/head-pose support

- MediaPipe: https://github.com/google-ai-edge/mediapipe
- License: Apache-2.0, with additional notices in the upstream license file:
  https://github.com/google-ai-edge/mediapipe/blob/master/LICENSE
- Paper: Lugaresi et al., "MediaPipe: A Framework for Building Perception
  Pipelines", arXiv:1906.08172.
- Current beta status: optional only. The strict face identity path does not
  require MediaPipe on this machine and does not use MediaPipe-only detections
  as clean identity evidence.

## Voice diarization and enhancement

- pyannote.audio: https://github.com/pyannote/pyannote-audio
  - License: MIT.
  - Paper: Bredin et al., "pyannote.audio: neural building blocks for speaker
    diarization", arXiv:1911.01255.
- pyannote speaker-diarization 3.1 model:
  https://huggingface.co/pyannote/speaker-diarization-3.1
  - Hugging Face model card lists license `mit`.
  - The model card states that users must accept model conditions and create a
    Hugging Face access token before downloading model files.
  - Do not commit tokens or downloaded gated model files.
- SpeechBrain: https://github.com/speechbrain/speechbrain
  - License: Apache-2.0.
  - Paper: Ravanelli et al., "SpeechBrain: A General-Purpose Speech Toolkit",
    arXiv:2106.04624.
- SpeechBrain SepFormer WHAMR enhancement model:
  https://huggingface.co/speechbrain/sepformer-whamr-enhancement
  - Hugging Face model card lists license `apache-2.0`.
  - Related papers on the model card include SpeechBrain and Subakan et al.,
    "Attention is All You Need in Speech Separation", ICASSP 2021 /
    arXiv:2010.13154.

## Current fallback behavior

When `pyannote.audio` or a Hugging Face token is unavailable, the beta can record
local `ffmpeg` silence-detection intervals as diagnostic audio activity, but
those intervals are deliberately written below the clean confidence threshold.
They should not be described as speaker identity or diarization in methods
sections, and they will not create clean speaker segments by themselves.

Model-backed voice identity requires researchers to install pyannote.audio,
accept the Hugging Face model terms, and provide their own token through
launcher settings or an environment variable such as `HF_TOKEN`. If diarization
fails, the run records the warning and emits no high-confidence clean voice
track. These machine outputs require researcher review and are not diagnostic
results.
