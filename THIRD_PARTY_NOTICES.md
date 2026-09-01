# Third-Party Notices

The root `LICENSE` applies only to software and documentation authored for the
**Multimodal Emotion Analysis Tool**. It does not replace or relicense bundled
third-party software, model weights, institutional marks, datasets, media, or
other external material. Each such component remains governed by its own terms.

## Bundled OpenSMILE Distribution

This repository includes a bundled Windows distribution of **OpenSMILE
3.0.0**, revision `e882501`, built on 2020-10-21. Its upstream source is the
[audEERING OpenSMILE repository](https://github.com/audeering/opensmile).

OpenSMILE is **not** licensed under this project's MIT License. It is supplied
under the **audEERING Research License Agreement** at:

`processing/audio_analysis/opensmile-3.0-win-x64/LICENSE`

That licence permits use, copying, reproduction, and distribution for
non-commercial purposes subject to its restrictions. It also defines limited
commercial-research conditions; further commercial use, and direct or indirect
product use, requires an additional commercial licence or written approval
from audEERING GmbH. Users must read the complete licence before use or
redistribution.

The complete local notice tree must remain with the distribution:

- `processing/audio_analysis/opensmile-3.0-win-x64/LICENSE`
- `processing/audio_analysis/opensmile-3.0-win-x64/licenses/`

The `licenses/` directory contains notices for third-party components used by
the OpenSMILE distribution. Do not remove, replace, or treat those files as
covered by the root MIT License.

When publishing research that uses OpenSMILE, acknowledge the software and
cite:

> Florian Eyben, Martin Wöllmer, and Björn Schuller. “openSMILE - The Munich
> Versatile and Fast Open-Source Audio Feature Extractor.” Proceedings of ACM
> Multimedia, 2010. https://doi.org/10.1145/1873951.1874246

Record the exact OpenSMILE version, revision, configuration, and feature set in
the study archive.

## Native Face And Text Dependencies

The native Face engine uses **Py-Feat 2.1.1** and its Detectorv2 checkpoint
files. Py-Feat, its transitive dependencies, and every downloaded detector,
landmark, AU, emotion, and identity checkpoint retain their upstream software
and model terms. Downloaded checkpoint bytes are not covered by the root MIT
License and must not be committed without a separate rights review.

The native Text engine uses **OpenAI Whisper**, **PyTorch**, **TorchAudio**,
**TorchVision**, and **TorchCodec**. Their packages and downloaded Whisper
weights remain governed by their respective upstream licences and model terms;
the downloaded weights are outside the root MIT License.

**PyArrow** supplies Parquet serialization for the verified Face artifact.
PyArrow and its bundled third-party components retain the notices distributed
by the Apache Arrow project.

## External Media And Java Runtimes

**FFmpeg/ffprobe** and complete shared-library builds are external runtime
dependencies. Their applicable LGPL/GPL configuration and component notices
depend on the exact build selected by the installer and remain outside this
project's root MIT License.

A **Java Development Kit** supplies `java` and `javac` for the Text adapter.
The JDK remains governed by its distributor's licence and notices.

**RockSteady 0.4** is third-party, separately licensed software and is not
licensed under this project's root MIT License. A project-authorized copy of
the application JAR is versioned through Git LFS at
`external/RockSteady/rocksteady-desktop-application-0.4#2018-05-16.jar`;
downstream use and redistribution remain subject to RockSteady's own terms.
The setup script does not obtain a separate RockSteady distribution.

## Other Dependencies, Models, And Marks

Python packages, external tools, and model downloads retain their upstream
licences and model terms. The Clean Speaker dependency inventory and source
citations are recorded in
`procurement/procurement_beta/THIRD_PARTY_NOTICES.md`. Gated Hugging Face
models, optional local wrappers, downloaded media, and credentials are not
licensed by the root MIT License and should not be added to a release without
a separate rights review.

The names, wordmarks, crests, logos, and other marks of Trinity College Dublin
and affiliated institutions are not licensed by the root MIT License. Their use
is subject to the relevant institution's brand and permission requirements.
