# Phase C2: User-Facing Runtime and Model Bootstrap

Phase C2 adds a lightweight Windows launcher around the proven C1 managed
runtime. It does not build an installer or launcher executable.

## Architecture

`scripts\launch_npc_voice_studio.ps1` is the temporary user-facing entry point.
It uses Windows Forms already available on Windows, so setup does not require a
pre-existing Python installation or a large launcher framework.

The launcher performs this sequence:

1. resolve the per-user application directories;
2. check Windows x64, write access, disk space, NVIDIA driver visibility, and
   the pinned uv binary;
3. delegate Python/runtime installation and repair to the C1 bootstrap;
4. run the model setup helper with the managed Python;
5. validate the exact local OmniVoice snapshot without network access;
6. download the pinned model automatically when it is missing;
7. force Hugging Face offline mode and start the staged application source;
8. wait for the loopback Gradio server and open the local browser.

The launcher never searches for system Python, Conda, or system uv.

## Shared Release Manifest

`runtime_manifest.json` is the packaging source of truth for:

- NPC Voice Studio version `0.1.0`;
- runtime schema version;
- managed CPython `3.11.15`;
- uv `0.13.5` and its verified executable SHA-256;
- the conservative setup disk-space threshold;
- model repository, immutable revision, approximate size, terms summary, and
  authoritative model-card URL.

The future release supplies the verified uv binary at `tools\uv\uv.exe` as a
build/release artifact. It is not downloaded dynamically and is not committed
in Phase C2.

## Preflight

The current launcher fails before a large setup when any of these checks fail:

- operating system is not Windows x64;
- application-data directories are not writable;
- less than 16 GiB is available when setup or repair may be needed;
- `nvidia-smi` cannot detect a usable NVIDIA driver/GPU;
- the packaged uv binary is missing, has the wrong version, or has the wrong
  SHA-256.

The 16 GiB threshold is deliberately conservative. C1 observed a multi-gigabyte
CUDA Torch wheel and retained uv cache in addition to the managed environment;
the pinned model is approximately 3.3 GB. Temporary download/extraction space
and a safety margin are included. A standalone CUDA Toolkit is not required.

## Setup UI and Logging

The Windows Forms launcher displays a small choice window and a marquee setup
window with phases such as:

- Checking system...
- Preparing Python runtime...
- Installing AI dependencies...
- Verifying GPU support...
- Checking/Preparing OmniVoice model...
- Starting NPC Voice Studio...

Raw uv, Python, and Hugging Face output is written to:

```text
%LOCALAPPDATA%\NPC Voice Studio\logs\setup.log
```

The setup log rotates to `setup.previous.log` after 5 MB. Setup code never logs
dialogue, transcripts, voice recordings, or generated voice contents.

## OmniVoice Model Terms Notice

Before the first model download, the setup progress and log identify:

- model and project name: `k2-fsa/OmniVoice`;
- immutable model revision;
- approximate download size and local storage directory;
- upstream model-card URL;
- the upstream distinction between Apache-2.0 code and pretrained weights
  identified by the model card as `CC-BY-NC` (version unspecified there);
- that the pretrained model is restricted to non-commercial use under its
  applicable terms;
- that NPC Voice Studio does not grant rights to the model;
- that the complete terms and attribution remain available in
  `THIRD_PARTY_NOTICES.md`.

The model download begins automatically after the managed runtime is ready; no
second blocking terms dialog is shown. The initial launcher choice still lets
the user cancel before setup starts. Existing acknowledgement state files from
older alpha builds are removed because they no longer control model setup.

## Model Download, Validation, and Offline Use

`scripts\setup_model.py` uses `huggingface_hub.snapshot_download()` with:

- repository `k2-fsa/OmniVoice`;
- revision `c5fdb5ccb189668d56333f77ba2629f4cd7535f4`;
- cache directory `<app-root>\models\hub`;
- `force_download=False`.

Hugging Face's content-addressed cache supplies concurrent download, safe blob
reuse, and retry/resume behavior. The launcher never deletes the cache during
an ordinary retry.

Every launch first calls `snapshot_download(..., local_files_only=True)` for the
exact commit and checks core snapshot files. A complete model receives
`models\omnivoice_ready.json`. A missing or incomplete snapshot enters the
download flow; a complete snapshot skips it.

After validation, the application starts with:

```text
HF_HOME=<app-root>\models
HF_HUB_CACHE=<app-root>\models\hub
HF_XET_CACHE=<app-root>\models\xet
HF_HUB_OFFLINE=1
HF_HUB_DISABLE_TELEMETRY=1
```

Normal second launch therefore does not contact Hugging Face.

## Source Staging and Versioning

The C1 staging helper now copies a fixed runtime payload from the launcher's own
installed source root, replacing stale `src` and runtime-script files. It writes
`runtime\project\app_source.json` containing:

- application version;
- deterministic source-payload SHA-256;
- staged file list;
- staging timestamp.

The runtime readiness marker includes the application version and source hash.
The managed interpreter always executes `runtime\project\app.py`, not a script
selected from the current directory or another Git checkout. In Phase C3, the
installer must place the versioned source payload beside the launcher.

## Development Commands

The future packaged layout uses `tools\uv\uv.exe` automatically. During C2
development, supply the verified artifact explicitly:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\launch_npc_voice_studio.ps1 `
    -UvPath C:\path\to\verified\uv.exe
```

Headless setup-only smoke test:

```powershell
$env:NPC_VOICE_STUDIO_DATA_DIR = Join-Path $env:LOCALAPPDATA "NPC Voice Studio C2 Test"
powershell -ExecutionPolicy Bypass -File scripts\launch_npc_voice_studio.ps1 `
    -Headless -NoLaunch `
    -UvPath C:\path\to\verified\uv.exe
```

Automated/headless repair requires explicit confirmation:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\launch_npc_voice_studio.ps1 `
    -Headless -Repair -ConfirmRepair -NoLaunch `
    -UvPath C:\path\to\verified\uv.exe
```

The interactive **Repair Runtime** button displays confirmation and delegates to
the proven C1 repair path. It removes/rebuilds only `.venv` and the runtime
readiness marker. Models, saved voices, generated audio, and logs are preserved.

## Phase C3 Blockers

- Build/sign a small launcher executable or signed native wrapper for this flow.
- Ship the verified uv artifact and versioned source payload in installer media.
- Add installer ownership/uninstall rules for immutable source versus user data.
- Decide proxy credential UX and enterprise/offline installation policy.
- Decide runtime/source upgrade, rollback, and interrupted-upgrade behavior.
- Add Authenticode signing and reputation testing for installer/launcher assets.
- Validate first-run disk threshold and driver detection on minimum supported
  Windows/NVIDIA hardware.
- Perform clean-machine accessibility, DPI, antivirus, proxy, and restricted-user
  testing of the Windows Forms launcher.
