# Phase B: Clean Environment Test

This procedure verifies NPC Voice Studio without changing the known-good
`npc-voice` environment. Run all commands from the repository root in a fresh
PowerShell session.

## Audited Runtime Dependencies

Direct NPC Voice Studio dependencies:

- `omnivoice==0.2.1`: model and voice-generation API.
- `torch==2.8.0+cu128`: tensor runtime and CUDA execution.
- `torchaudio==2.8.0+cu128`: OmniVoice audio resampling; pinned with Torch.
- `gradio==6.22.0`: local user interface and file serving.
- `huggingface-hub==1.26.0`: pinned model snapshot download.
- `soundfile==0.14.0`: duration inspection and generated WAV writing.

First-level dependencies declared by OmniVoice and pinned to the validated set:

- `accelerate==1.14.0`
- `librosa==0.11.0`
- `numpy==2.4.6`
- `pydub==0.25.1`
- `tensorboardX==2.6.5`
- `transformers==5.14.1`
- `webdataset==1.0.2`

Their lower-level dependencies are resolved normally by pip. `unittest`, CSV,
ZIP creation, filesystem handling, logging, and threading come from Python's
standard library. There are no additional development-only packages. Tests use
NumPy and SoundFile, which are already runtime dependencies.

F5-TTS and TorchCodec are not runtime dependencies and must not be installed by
this specification.

## External Dependencies

- **Required:** a compatible NVIDIA display driver for the validated GPU path.
  The validated machine uses driver `610.88` with an RTX 5070 Ti.
- **Required for a first run:** network access to Hugging Face and roughly
  3.1 GiB of free model-cache space, plus space for the Python environment and
  generated audio.
- **Provided by wheels/environment:** the PyTorch CUDA 12.8 runtime libraries.
  A separately installed CUDA Toolkit is not required for inference.
- **Windows runtime:** CPython and PyTorch require their normal Microsoft Visual
  C++ runtime DLLs. Conda and the PyTorch wheel supplied these on the validated
  machine; imports in the clean environment verify them.
- **FFmpeg:** not required for WAV, FLAC, OGG, MP3, or other formats readable by
  the SoundFile/libsndfile build. Reference duration validation uses SoundFile
  before OmniVoice runs. Unsupported containers such as M4A are therefore
  rejected before OmniVoice's librosa/audioread fallback can use FFmpeg.

The developer machine currently finds `C:\ffmpeg\ffmpeg.exe` through `PATH`,
but the supported reference-audio path does not depend on it. FFmpeg is not
bundled or installed by this phase.

## Create The Clean Environment

Do not run these commands from `npc-voice`:

```powershell
conda create -n npc-voice-clean python=3.11
conda activate npc-voice-clean
```

Prevent user-site packages from masking missing dependencies, then install only
from the repository specification. `--no-cache-dir` avoids relying on a shared
pip wheel cache:

```powershell
$env:PYTHONNOUSERSITE = "1"
python -m pip install --no-cache-dir -r requirements.txt
```

`requirements.txt` selects the CUDA 12.8 PyTorch wheels from:

```text
https://download.pytorch.org/whl/cu128
```

## Verify Packages And CUDA

```powershell
python -m pip check
python scripts/check_environment.py
python -m unittest discover -s tests -v
```

The checker validates Python 3.11, all curated package versions, Torch CUDA
12.8, CUDA availability, GPU detection, the absence of F5-TTS/TorchCodec, and a
centralized data directory outside the repository.

Useful independent diagnostics:

```powershell
python -c "import torch, torchaudio; print(torch.__version__); print(torchaudio.__version__); print(torch.version.cuda); print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0))"
python -c "import omnivoice, gradio, soundfile, huggingface_hub; print('imports OK')"
```

## Fresh Model Download

The application requests `k2-fsa/OmniVoice` at revision:

```text
c5fdb5ccb189668d56333f77ba2629f4cd7535f4
```

The validated cache occupies about 3.04 GiB and includes the audio tokenizer.
Hugging Face normally uses `%USERPROFILE%\.cache\huggingface`. Use an isolated,
new directory for the clean test so the working cache remains untouched:

```powershell
$testId = Get-Date -Format "yyyyMMdd-HHmmss"
$testRoot = Join-Path $env:LOCALAPPDATA "NPC Voice Studio\repro-$testId"
$env:HF_HOME = Join-Path $testRoot "huggingface"
$env:HF_HUB_CACHE = Join-Path $env:HF_HOME "hub"
$env:HF_XET_CACHE = Join-Path $env:HF_HOME "xet"
$env:NPC_VOICE_STUDIO_DATA_DIR = Join-Path $testRoot "app-data"
Remove-Item Env:HF_HUB_OFFLINE -ErrorAction SilentlyContinue
Remove-Item Env:TRANSFORMERS_CACHE -ErrorAction SilentlyContinue

if (Test-Path -LiteralPath $env:HF_HOME) {
    throw "Fresh cache path already exists: $env:HF_HOME"
}

python -c "from src.omnivoice_service import OmniVoiceService; service = OmniVoiceService(); print(service.model_revision, service.device)"

$snapshot = Join-Path $env:HF_HUB_CACHE "models--k2-fsa--OmniVoice\snapshots\c5fdb5ccb189668d56333f77ba2629f4cd7535f4"
if (-not (Test-Path -LiteralPath $snapshot)) {
    throw "Pinned model snapshot was not downloaded."
}
```

Do not delete the normal Hugging Face cache. The isolated `repro-*` directory
can be reviewed and removed separately after the test.

## Application And Data Verification

Keep the isolated `HF_HOME`, `HF_HUB_CACHE`, and
`NPC_VOICE_STUDIO_DATA_DIR` values set, then launch:

```powershell
python app.py
```

Verify in the UI:

1. The server binds only to `127.0.0.1` and reports OmniVoice ready on CUDA.
2. Create from Sample generates and downloads a WAV.
3. Design Voice and Random Voice each generate and download a WAV.
4. Save a generated voice, select it in Voice Library, generate from it, then
   delete it.
5. Import a batch CSV, generate all lines, review one line, regenerate it, and
   download the ZIP.
6. Generated files, batch files, profiles, and logs appear only beneath
   `$env:NPC_VOICE_STUDIO_DATA_DIR`, not the repository.

Run cloning from the command line with a local reference and exact transcript:

```powershell
python scripts/test_generation.py reference.wav --reference-text "Exact words spoken in the reference audio."
```

## FFmpeg Independence Check

In the clean-environment PowerShell session, remove only the developer FFmpeg
entry from that process's `PATH`, then repeat a WAV cloning test:

```powershell
$env:PATH = (($env:PATH -split ";") | Where-Object { $_ -ne "C:\ffmpeg" }) -join ";"
where.exe ffmpeg
python scripts/test_generation.py reference.wav --reference-text "Exact words spoken in the reference audio."
```

`where.exe ffmpeg` should find nothing, while supported reference formats should
still work.

## Failure Checks

These checks use only disposable environment-variable overrides:

1. **Empty/offline model cache:** choose another nonexistent `HF_HOME`, set
   `$env:HF_HUB_OFFLINE = "1"`, launch `python app.py`, and open the page. The UI
   should open and report that OmniVoice is unavailable rather than terminating.
2. **CUDA unavailable:** set `$env:CUDA_VISIBLE_DEVICES = "-1"`, confirm
   `torch.cuda.is_available()` is false, then launch the UI. The interface must
   still open; model initialization may fall back to CPU or report a concise
   failure depending on available RAM.
3. **Output unavailable:** set `NPC_VOICE_STUDIO_DATA_DIR` to the path of a
   disposable regular file rather than a directory. The UI should open with
   console logging, and generation should report that the data directory is not
   writable.

Close each test process before changing its environment variables. Do not run
failure tests against the normal application-data or Hugging Face cache paths.

## Hidden-Machine Dependency Checklist

- Existing Hugging Face cache: **accidental for prior tests**, isolated above.
- `C:\ffmpeg` on `PATH`: **accidental and currently unnecessary**.
- System CUDA Toolkit 12.4 and cuDNN PATH entries: **optional for development**;
  the CUDA 12.8 PyTorch wheel supplies inference runtime libraries.
- NVIDIA driver: **required** for GPU inference.
- Global/user Python packages: **not required**; `PYTHONNOUSERSITE=1` enforces it.
- Conda environment variables: **none found in the known-good environment**.
- Repository working directory: **required only as source/import context**, not
  for mutable data.
- `%LOCALAPPDATA%`: **required default location** for mutable application data;
  `NPC_VOICE_STUDIO_DATA_DIR` is the documented test override.
