# NPC Voice Studio

NPC Voice Studio is a local AI voice-generation tool for game modders using
[OmniVoice](https://github.com/k2-fsa/OmniVoice). It supports voice
cloning from a short sample, voice design, random voice creation, reusable
voice profiles, and batch dialogue generation. It supports Windows 11 
and NVIDIA GPUs.


## Features

- Clone a voice from reference audio and its matching transcript.
- Design a voice from supported speaker characteristics.
- Generate original random voice candidates.
- Save generated or cloned voices for reuse.
- Generate and download individual WAV files.
- Generate multiple dialogue lines from CSV and download a ZIP archive.
- Use OmniVoice dialogue tags and CMU/ARPAbet pronunciation overrides.
- Run locally through a loopback-only Gradio interface.

## Using the Windows Installer

For normal use, download the v1.0 Windows installer from
[GitHub Releases](https://github.com/gpargianas/npc-voice-studio/releases):

```text
NPC-Voice-Studio-1.0-win-x64.exe
```

The installer does not require administrator privileges. On first launch,
NPC Voice Studio installs its managed Python and CUDA-enabled AI runtime, then
downloads and validates the pinned OmniVoice model. This requires an internet
connection, several minutes, and approximately 18 GiB of free disk space.

After setup completes, normal launches and voice generation work offline. The
application includes a **Repair Runtime** option that preserves models, saved
voices, generated audio, and logs.

You do not need to install Python, Conda, uv, pip, FFmpeg, or the CUDA Toolkit.
A compatible NVIDIA GPU and driver are required.

## Running from Source

The tested source-development target is Windows 10/11 x64 with an NVIDIA GPU.

Install manually:

- [Git](https://git-scm.com/)
- [uv 0.13.5](https://github.com/astral-sh/uv/releases/tag/0.13.5)
- A compatible NVIDIA driver

Python, Conda, pip, FFmpeg, and the CUDA Toolkit are not required separately.
uv installs Python 3.11.15 and creates the environment from `uv.lock`, which is
the dependency source of truth for this project.

From PowerShell:

```powershell
git clone https://github.com/gpargianas/npc-voice-studio.git
cd npc-voice-studio

uv --version
# Expected: uv 0.13.5

uv python install 3.11.15

uv sync `
    --frozen `
    --no-dev `
    --no-install-project `
    --managed-python `
    --python 3.11.15

.\.venv\Scripts\python.exe .\scripts\check_environment.py
.\.venv\Scripts\python.exe .\scripts\setup_model.py --install
.\.venv\Scripts\python.exe .\app.py
```

The model setup command downloads and validates the pinned OmniVoice model locally
(approximately 3.3 GB).

Open the local URL printed by Gradio, normally:

```text
http://127.0.0.1:7860
```

## Application Data

On Windows, data is stored under:

```text
%LOCALAPPDATA%\NPC Voice Studio\
    runtime\
    models\
    voice_profiles\
    generated_audio\
    logs\
```


## Reference Audio

For voice cloning, use clear speech with an exact matching transcript.

- Best results: approximately 3–10 seconds.
- Maximum accepted length: 15 seconds.
- Samples longer than 10 seconds display a quality warning.
- Samples longer than 15 seconds are rejected.

Only use recordings and voices you have permission to use. Do not use voice
cloning for impersonation, fraud, scams, or unlawful activity.

## Local Operation and Privacy

- The interface binds to `127.0.0.1` only.
- Gradio sharing is disabled.
- Gradio analytics are disabled.
- Voice recordings, transcripts, generated audio, and saved voices remain on
  the local computer.
- Internet access is required for initial runtime/model setup or a repair when
  required cache files are unavailable.

Application diagnostics are written to:

```text
%LOCALAPPDATA%\NPC Voice Studio\logs\
```

Logs do not intentionally contain dialogue text, transcripts, recordings, or
generated audio contents.

## OmniVoice Model

NPC Voice Studio pins `k2-fsa/OmniVoice` to the tested revision:

```text
c5fdb5ccb189668d56333f77ba2629f4cd7535f4
```

NPC Voice Studio's Apache-2.0 application license does not grant rights to the
pretrained model. The upstream model card identifies the pretrained weights as
CC-BY-NC and restricts them to non-commercial use. Review
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) and the pinned upstream model
[card](https://huggingface.co/k2-fsa/OmniVoice/blob/c5fdb5ccb189668d56333f77ba2629f4cd7535f4/README.md)
before use.

## License

NPC Voice Studio's original source code is licensed under the
[Apache License 2.0](LICENSE). Third-party software and pretrained model files
remain under their respective licenses and terms; see
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
