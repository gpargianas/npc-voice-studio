# Third-Party Notices

NPC Voice Studio's original source code is licensed under the Apache License
2.0 in `LICENSE`. That license does not replace, relicense, or grant rights to
third-party software or pretrained model files.

This document is an attribution and license summary for the v0.1 alpha release.
Authoritative upstream license files and model cards control. The exact Python
package inventory is frozen in `uv.lock`; package distributions installed into
the managed runtime retain their own metadata and license files.

## OmniVoice

- Project: OmniVoice, by the k2-fsa project and contributors
- Source: <https://github.com/k2-fsa/OmniVoice>
- Code package: Apache License 2.0
- Pretrained model: `k2-fsa/OmniVoice`
- Pinned revision: `c5fdb5ccb189668d56333f77ba2629f4cd7535f4`
- Model card: <https://huggingface.co/k2-fsa/OmniVoice/blob/c5fdb5ccb189668d56333f77ba2629f4cd7535f4/README.md>

The upstream model card states that OmniVoice code is Apache-2.0 while the
pretrained model is licensed under CC-BY-NC because of training-data
constraints. The model card does not identify a specific CC-BY-NC version.
The pretrained weights are restricted to non-commercial use under their
applicable terms. They are not bundled in the installer, are not licensed by
NPC Voice Studio, and are downloaded automatically during first-use setup after
the locked runtime is installed. This notice does not grant commercial-use
rights or replace the upstream model terms.

The OmniVoice model may include or rely on components with additional upstream
terms. Users are responsible for reviewing the pinned model card and applicable
component terms for their intended use.

## Bundled uv executable

- Project: uv, by Astral Software Inc. and contributors
- Version: 0.13.5
- Source: <https://github.com/astral-sh/uv>
- License: Apache License 2.0 OR MIT License

The installer bundles only the verified Windows x64 `uv.exe` artifact. uv is
used to install the managed CPython runtime and locked Python dependencies.

## Inno Setup

- Project: Inno Setup, by Jordan Russell and Martijn Laan
- Source: <https://jrsoftware.org/isinfo.php>
- License: Inno Setup License

Inno Setup is used to build the Windows installer. Its installer runtime is
part of the generated setup executable; the compiler is not installed with NPC
Voice Studio.

## Runtime software installed on first launch

The installer does not bundle Python, PyTorch, OmniVoice, Gradio, or their
Python dependencies. The pinned uv workflow obtains them on first launch from
the sources recorded in `uv.lock`. Principal projects include:

| Project | Pinned version | Upstream license summary | Source |
|---|---:|---|---|
| CPython | 3.11.15 | Python Software Foundation License | <https://www.python.org/> |
| PyTorch | 2.8.0+cu128 | BSD-style | <https://github.com/pytorch/pytorch> |
| Torchaudio | 2.8.0+cu128 | BSD-style | <https://github.com/pytorch/audio> |
| OmniVoice code | 0.2.1 | Apache-2.0 | <https://github.com/k2-fsa/OmniVoice> |
| Gradio | 6.22.0 | Apache-2.0 | <https://github.com/gradio-app/gradio> |
| Hugging Face Hub | 1.26.0 | Apache-2.0 | <https://github.com/huggingface/huggingface_hub> |
| Transformers | 5.14.1 | Apache-2.0 | <https://github.com/huggingface/transformers> |
| Accelerate | 1.14.0 | Apache-2.0 | <https://github.com/huggingface/accelerate> |
| NumPy | 2.4.6 | BSD-3-Clause | <https://github.com/numpy/numpy> |
| SoundFile | 0.14.0 | BSD-3-Clause | <https://github.com/bastibe/python-soundfile> |
| librosa | 0.11.0 | ISC | <https://github.com/librosa/librosa> |
| pydub | 0.25.1 | MIT | <https://github.com/jiaaro/pydub> |
| tensorboardX | 2.6.5 | MIT | <https://github.com/lanpa/tensorboardX> |
| webdataset | 1.0.2 | BSD-style | <https://github.com/webdataset/webdataset> |

Transitive dependencies and their exact versions are listed in `uv.lock`.
Nothing in the NPC Voice Studio application license changes their terms.
