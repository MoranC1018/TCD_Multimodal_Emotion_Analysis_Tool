# Preferred categorical Audio backend: validation and limits

The preferred checkpoint requires its author's custom Vox-Profile wrapper. The
previous generic Transformers loader could not provide that architecture and
the normal policy selected the four-class SUPERB fallback. The corrected adapter
uses the custom wrapper, checks the pinned checkpoint structure, restores its
saved positional alias and supplies the attention configuration required by
Transformers 4.53.3. The separate audEering dimensional model remains separate.

## Required setup and CLI behavior

Install the repository requirements, which now include `loralib==0.1.2`. Obtain
and review the external [author wrapper](https://github.com/tiantiaf0627/vox-profile-release)
and set `VOX_PROFILE_RELEASE_DIR` to its checkout. The installer does not download
or patch that source. Its older full requirements must not replace this
repository's environment. The preferred wrapper also requires cached/downloadable
Whisper base and feature-extractor artifacts in addition to the emotion weights.

```powershell
$env:VOX_PROFILE_RELEASE_DIR = 'C:\models\vox-profile-release'
.\.venv\Scripts\python.exe processing\audio_analysis\run_audio_analysis.py single 'C:\data\clip.mp4' --output 'C:\results\clip' --device cuda --require-preferred-categorical
```

The strict flag is supported by both main single/batch commands, the alternative
single/batch entry points and the typed automation field
`require_preferred_categorical: true`. It rejects skipping emotion models and
wrong or unpinned injected bundles. A preferred-load failure stops before existing
results are replaced. Without strict mode, the supported fallback policy remains;
inspect the actual selected model and warnings in the result manifest.

The reviewed upstream wrapper calls `.cuda()` for features in both forward
branches. It is not a portable CPU implementation. The new CPU preflight rejects
actual `.cuda()` source calls before importing that wrapper or loading weights.
Comments and strings do not trigger it. This targets a known incompatibility;
passing the check does not certify arbitrary external code.

The CPU runtime checks below used a pre-existing, reviewed external change of
those two feature transfers to `.to(x.device)`. The production adapter does not
apply it. A CPU request with the original source therefore either uses the
documented fallback or, in strict mode, fails with an actionable message.

## Actual runtime evidence

Validation used real weights and source-derived mono 16 kHz PCM16 inputs. Three
ten-second windows covered an initial interval, an interior interval and a
fractional-start final interval, from 44.1 and 48 kHz stereo sources. These are
bounded warm-cache tests on one Windows host, not a clean installation test or an
emotion-accuracy benchmark.

| Check | Observed outcome |
|---|---|
| Production adapter with Torch 2.6.0+cu124 and Transformers 4.53.3 | All three nine-probability vectors matched the independent author-wrapper CUDA corpus, maximum absolute difference below 1e-15. |
| Actual standalone strict CUDA CLI | Completed: preferred pin, separate audEering pin, nine finite categorical probabilities, three finite dimensional outputs, 88 finite eGeMAPS features and exact retained PCM16 input samples. |
| Actual standalone strict CPU CLI with reviewed portable wrapper | Process exited 0 and published the same required features, pins and exact input samples. The original GPU-reference numerical gate failed: 1.2364e-5 versus the predeclared 1.05e-5 including CSV rounding. |
| Production adapter with repository-pinned Torch 2.11.0+cpu and Transformers 4.53.3 | All three predictions finite and same top labels. Original absolute CPU-versus-CUDA tolerance 1e-5 failed; largest error 6.995e-5 probability, approximately 0.007 displayed points. This failed gate remains recorded. |
| Independent author-wrapper CPU reference, Torch 2.6.0 | All three matched the production CPU adapter at the unchanged 1e-5 tolerance; maximum difference 7.749e-7. |
| Independent actual CPU CLI versus author CPU | Passed at the unchanged 1e-5 threshold, maximum error 1.2623e-6 even before the rounding allowance; independently verified the actual CSV, inputs, model/tool hashes and finite features. This separate check does not replace the original GPU-reference failure. |
| Controlled author CUDA precision experiment | Keeping matmul TF32 disabled, switching only cuDNN TF32 from permitted to disabled brought all three GPU vectors within 1e-5 of both CPU references. Re-enabling it exactly reproduced the first GPU vectors. |

The precision experiment isolates the observed discrepancy to the cuDNN setting
on those inputs. FP32 tensor dtype alone does not describe all computation
precision. The original corpus did not explicitly record backend flags; the
subsequent controlled run reproduced it with cuDNN TF32 permitted. Do not claim
bitwise or 1e-5 equivalence across arbitrary devices, Torch builds, precision
settings or batch sizes. Preserve these choices when reproducing research.

The canonical investigation processed all 60 recordings and 21,271 existing
intervals with the preferred categorical checkpoint, FP32 tensors and batch size
one. Its inference loop took 47.51 minutes on an RTX 3070, excluding initial model
loading. This included decoding, hashing and output writing; it did not repeat
Face, Text, audEering or OpenSMILE over that corpus. The production CLI check
above exercised those Audio dependencies on one real clip. This is not a general
end-to-end corpus runtime or installation failure rate.

## Dependency and provenance boundaries

- Preferred checkpoint: `tiantiaf/whisper-large-v3-msp-podcast-emotion`, revision
  `b92dab65151206a603810ec8b72eb528b9dd983c`; weight SHA-256
  `b79de629e5c0a59f65f59274287ef417aad08b4dc13add77d1a658fcc9669491`.
- Reviewed external vendor HEAD: `85100e60844a3f324a139e24fb9225aa6d8e45d1`,
  with the two pre-existing device substitutions described above. Working-file
  SHA-256: `2f2ceb633e337e87eb0835f192eefa3a6784d5e0e56e0d20f22f2c986a2296a7`.
- CUDA bridge: Transformers 4.53.3, Tokenizers 0.21.4, Hugging Face Hub 0.36.2,
  Torch 2.6.0+cu124 and loralib 0.1.2 in an isolated compatibility environment.
- CPU route: Torch 2.11.0+cpu and Transformers 4.53.3 from the main environment,
  with a private loralib 0.1.2 overlay. That existing environment lacked loralib;
  it was not silently upgraded. The requirements addition supplies it for future
  installations but does not repair an already-created environment automatically.
- audEering revision: `6eba34a2485ea31cb03600241787c3a5edab8626`.
- Audio reconstruction: FFmpeg 7.1.1 and PCM16; real CLI eGeMAPS: bundled
  OpenSMILE 3.0.0. This does not replace the installation guide's separate
  FFmpeg requirements for Face/TorchCodec.

The adapter leaves approximately 3.63 GB of unused FP32 decoder weights in CPU
RAM and places the active encoder/heads on the selected device. The complete
model, transient loading copies and activations still require memory. The tested
8 GB GPU is evidence for this workload, not a universal hardware requirement.

The final complete repository suite after the CPU preflight change ran on
9 September 2026: **1,445 passed, 15 skipped, 327 subtests passed in 202.64 seconds**.
Fourteen skips require Windows symlink privileges; one covers native termination
semantics that differ on Windows. The four new CPU preflight regression cases
failed before implementation and passed afterward. The combined preferred-model
and typed-policy subset passed 52 cases.

Private corpus data and original diagnostic logs are retained with the research
investigation rather than included in this sanitized repository. The repeatable
repository regression tests cover malformed checkpoint keys/shapes, missing or
invalid positions, attention preparation, partial device placement, malformed
probabilities, strict policy propagation and output preservation on startup errors.

## Interpretation and release claims

Happiness multiplied by 100 displays a categorical probability; audEering Valence
uses `200*v-100`. Face Joy is a different model's facial-expression score. A shared
range does not establish equal emotional intensity, and no cross-modal calibration
is established by a smaller numerical gap. Unsupported fallback categories remain
blank. Target identity, language/domain validity and model error rates require
appropriate reviewed or labelled evaluation. Test success does not supply those
labels or certify the paper's substantive claims.
