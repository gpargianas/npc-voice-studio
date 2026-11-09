# Release Storage Audit

Audit date: 2026-10-29  
Release: NPC Voice Studio 0.1.0 alpha, Windows x64

This audit used disposable clean installation and application-data roots. Sizes
below are logical file sizes, so hardlinked uv cache and `.venv` files are
counted once in each directory even though NTFS stores their shared content
once.

## Clean-install measurements

| Area | Before bytes / files | After bytes / files |
|---|---:|---:|
| Installed program | 36,652,995 / 32 | 36,644,393 / 32 |
| Application data total | 19,411,337,300 / 66,917 | 19,339,429,741 / 62,797 |
| Runtime total | 16,143,731,730 / 66,898 | 16,071,520,602 / 62,779 |
| Managed Python | 144,413,115 / 8,240 | 72,206,558 / 4,121 |
| `.venv` | 8,001,542,822 / 29,325 | 8,001,542,815 / 29,325 |
| uv cache | 7,997,546,270 / 29,312 | 7,997,546,252 / 29,312 |
| uv data | 0 / 0 | 0 / 0 |
| Model total | 3,267,473,347 / 18 | 3,267,472,969 / 17 |
| Hugging Face hub cache | 3,267,472,568 / 15 | 3,267,472,568 / 15 |
| Xet cache | 0 / 1 | 0 / 1 |
| Voice profiles | 0 / 0 | 0 / 0 |
| Generated audio | 0 / 0 | 0 / 0 |
| Logs | 132,223 / 1 | 436,170 / 1 |

The pre-generation logical total changed from 19,447,990,295 bytes
(18.112352 GiB) to 19,376,074,134 bytes (18.045375 GiB), a measured reduction
of 71,916,161 bytes (68.585 MiB, or 0.369787%). Most of that cross-run difference is the
managed-Python minor-version path being a junction in the final run instead of
another enumerated tree; it is not a dependency removal or a guaranteed
physical saving. The guaranteed product cleanup is the obsolete 377-byte model
acknowledgement plus a smaller installed source payload.

## Largest `.venv` package directories

| Directory | Logical MiB |
|---|---:|
| torch | 7,041.26 |
| llvmlite | 115.34 |
| scipy | 85.46 |
| gradio | 71.66 |
| transformers | 44.64 |
| pandas | 36.65 |
| sklearn | 25.83 |
| sympy | 25.37 |
| numpy.libs | 20.02 |
| numpy | 19.67 |
| scipy.libs | 19.32 |
| PIL | 13.96 |
| torchaudio | 13.44 |
| numba | 11.58 |
| torio | 9.25 |
| hf_xet | 8.92 |
| tokenizers | 7.29 |
| networkx | 6.65 |
| pydantic_core | 5.52 |

## uv cache decision

The 7.448295 GiB logical uv cache is almost entirely `archive-v0`
(7,997,491,491 bytes). A representative 1,028,843,008-byte Torch CUDA DLL has
two hardlinks: one under `.venv` and one under `uv-cache\archive-v0`.

- `uv cache prune` found no unused entries and changed no measured size.
- `uv cache clean` removed 7.4 GiB of logical cache names but released only
  14,450,688 bytes (13.781 MiB) on the tested NTFS volume.
- Normal offline generation still worked after the clean, but Runtime Repair
  then needed to redownload the locked AI runtime.
- With the cache retained, Runtime Repair completed offline and rebuilt the
  environment from the cache.

Therefore the release does not automatically prune or clean uv's cache. Manual
deletion of uv's internal directories is also avoided. This follows uv's
documented cache commands and preserves repair reliability:
<https://docs.astral.sh/uv/concepts/cache/>.

## Model cache decision

The app-managed model directory contains one exact 3.043071 GiB pinned hub
snapshot, the ready marker, and a zero-byte Xet cache structure. The obsolete
model acknowledgement file is removed. No duplicate revision, incomplete
payload, or stale downloaded model was found. Empty Xet staging/log structure
is retained because it saves no bytes and belongs to the downloader.

Hugging Face documents its file and Xet caches as separate cache systems. The
application preserves this layout, exact-revision validation, resume behavior,
and offline local-only resolution:
<https://huggingface.co/docs/huggingface_hub/guides/manage-cache>.

## Dependency audit

`pyproject.toml` has 13 exact direct roots and the managed environment has 89
installed third-party distributions. Every installed distribution is reachable
from those roots through package metadata; no orphaned distribution was found.
The apparent large transitive packages are required, including:

- llvmlite, numba, scipy, and scikit-learn through librosa;
- pandas and Pillow through Gradio;
- sympy and networkx through Torch;
- hf-xet through huggingface-hub;
- tensorboardX and webdataset through OmniVoice.

No dependency, Torch/CUDA component, OmniVoice component, Gradio component, or
lock entry was removed.

## Regression evidence

- 70 automated tests passed.
- Packaged clean first run installed the runtime and automatically downloaded
  the exact pinned model without a second acknowledgement prompt.
- CUDA Auto Voice generation succeeded with `HF_HUB_OFFLINE=1`.
- Offline second launch took the runtime/model fast path and generation passed.
- Offline Runtime Repair passed with the uv cache retained.
- Saved voice audio/transcript, generated files, and model state survived
  repair; post-repair cloning generation passed.

