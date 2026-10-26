# NPC Voice Studio

Local zero-shot voice cloning, voice design, random voice creation, reusable
voices, and batch generation using OmniVoice.

## Validated Development Stack

- Python 3.11
- OmniVoice 0.2.1
- PyTorch and Torchaudio 2.8.0 with CUDA 12.8
- Gradio 6.22.0
- An NVIDIA CUDA-capable GPU is the currently validated path

`requirements.txt` pins the direct runtime requirements and OmniVoice's
first-level dependencies for the validated stack. It is a source-install
specification, not a Windows installer lock.

## Clean Environment Verification

The reproducibility procedure, isolated model-cache test, external dependency
audit, and failure checks are documented in
[`docs/clean-environment-test.md`](docs/clean-environment-test.md). The process
uses a separate `npc-voice-clean` Conda environment and does not modify the
known-good `npc-voice` environment.

## Managed Runtime Foundation

`pyproject.toml` and `uv.lock` are the source of truth for the future packaged
Windows runtime. `requirements.txt` remains temporarily for manual and Conda
development compatibility. See
[`docs/phase-c1-uv-runtime.md`](docs/phase-c1-uv-runtime.md) for the bootstrap,
clean-launch, and repair procedures.

## Run The UI

Activate the existing environment and run from the project root:

```powershell
conda activate npc-voice
python app.py
```

The UI binds to `127.0.0.1`, Gradio sharing is disabled, and Gradio analytics
are disabled. OmniVoice is initialized after the UI opens so startup failures
can be shown without terminating the interface.

## Runtime Data

On Windows, mutable data is stored under:

```text
%LOCALAPPDATA%\NPC Voice Studio\
    generated_audio\
    voice_profiles\
    logs\
```

Set `NPC_VOICE_STUDIO_DATA_DIR` to override this root for development. On
non-Windows systems the fallback is `$XDG_DATA_HOME/npc-voice-studio`, or
`~/.local/share/npc-voice-studio` when `XDG_DATA_HOME` is unset.

Older development data in the repository's `generated_audio/` and
`voice_profiles/` folders is not moved or deleted automatically.

## Model Revision

The application pins `k2-fsa/OmniVoice` to the tested Hugging Face revision:

```text
c5fdb5ccb189668d56333f77ba2629f4cd7535f4
```

The model is downloaded by Hugging Face when that revision is not already in
the local cache. Model-load failures are recorded in the application log.

## Run The Smoke Test

Provide a local reference audio file and its exact transcript:

```powershell
python scripts/test_generation.py reference.wav `
    --reference-text "Exact words spoken in the reference audio."
```

By default the result is written to the centralized `generated_audio` directory.
Keep cloning references clear, accurately transcribed, and no longer than 15
seconds; approximately 3-10 seconds is recommended.
