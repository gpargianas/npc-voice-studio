# Phase C1: uv Managed Runtime

Phase C1 establishes the future packaged runtime without building an installer.
The existing `npc-voice` and `npc-voice-clean` Conda environments are reference
environments only and are never modified by the bootstrap.

Phase C2's user-facing orchestration is documented in
[`phase-c2-user-bootstrap.md`](phase-c2-user-bootstrap.md); it delegates runtime
installation and repair back to this C1 implementation.

## Source Of Truth

- `pyproject.toml` declares Python 3.11, the validated direct dependencies, and
  the explicit PyTorch CUDA 12.8 index.
- `uv.lock` freezes the complete Windows x64 dependency graph and package hashes.
- `requirements.txt` remains temporarily for manual/Conda development setup.
- The packaged runtime pins CPython `3.11.15`, Torch/Torchaudio `2.8.0+cu128`,
  OmniVoice `0.2.1`, and uv `0.13.5`.

The Phase B clean Conda environment used Python 3.11.17 and validated the same
dependency graph. Phase C1 intentionally retains the requested packaged-runtime
pin of Python 3.11.15.

## PyTorch Index

Only Torch and Torchaudio are assigned to the explicit CUDA index:

```toml
[[tool.uv.index]]
name = "pytorch-cu128"
url = "https://download.pytorch.org/whl/cu128"
explicit = true

[tool.uv.sources]
torch = { index = "pytorch-cu128" }
torchaudio = { index = "pytorch-cu128" }
```

The uv project is restricted to Windows AMD64. CPU, AMD, Linux, and macOS
resolutions are intentionally outside v0.1.

## Pinned uv Binary

The tested binary is the official Astral `uv 0.13.5` Windows x64 release.
Future packaged media places it at:

```text
tools\uv\uv.exe
```

During development, pass its path explicitly. The bootstrap does not search
`PATH` and verifies both the exact version and extracted executable SHA-256:

```text
f45d1cb9d9140ca6d3f4005fdfc0ebeccf849fd04d1dc85804155cb923f1597b
```

Release and archive integrity details are recorded in `tools/uv/README.md`.
The bootstrap never downloads an arbitrary uv release at runtime.

## Runtime Layout

The default layout is:

```text
%LOCALAPPDATA%\NPC Voice Studio\
    runtime\
        python\
        project\
            .venv\
        uv-cache\
        runtime_ready.json
    models\
    voice_profiles\
    generated_audio\
    logs\
```

`NPC_VOICE_STUDIO_DATA_DIR` may redirect the root for a disposable development
test, but the bootstrap rejects a root inside the source repository.

The bootstrap sets these model-cache variables before starting the app:

```text
HF_HOME=<app-root>\models
HF_HUB_CACHE=<app-root>\models\hub
HF_XET_CACHE=<app-root>\models\xet
```

Runtime synchronization imports OmniVoice but does not initialize it, so model
download remains separate and occurs only when the application initializes the
pinned model revision.

## Bootstrap Command

From the repository root, using the verified development copy of uv:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\bootstrap_runtime.ps1 `
    -UvPath C:\path\to\verified\uv.exe
```

Use `-NoLaunch` to install and verify without starting Gradio. The bootstrap:

1. verifies uv version and SHA-256;
2. looks for exact uv-managed CPython 3.11.15 beneath `runtime\python` and,
   when it is absent, explicitly installs it before looking it up again;
3. stages runtime source beneath `runtime\project`;
4. executes `uv sync --frozen` into `runtime\project\.venv`;
5. runs `scripts/check_environment.py` with that exact managed interpreter;
6. writes the readiness marker only after verification succeeds;
7. launches `app.py` with the managed `.venv\Scripts\python.exe`.

No Python or uv executable is selected from `PATH`, and there is no Conda or
developer-Python fallback.

## Readiness Marker

`runtime_ready.json` records:

- runtime schema version;
- exact Python version;
- exact uv version;
- SHA-256 of `uv.lock`;
- platform;
- verification timestamp.

A missing/invalid marker, changed lockfile, missing managed interpreter, or
failed environment check prevents the runtime from being accepted. Failed or
partial installations never receive a marker.

## Clean Runtime Test

Choose a disposable directory outside the repository, then run the bootstrap
against an empty runtime:

```powershell
$env:NPC_VOICE_STUDIO_DATA_DIR = Join-Path $env:LOCALAPPDATA "NPC Voice Studio C1 Test"
$testRoot = $env:NPC_VOICE_STUDIO_DATA_DIR
if (Test-Path -LiteralPath (Join-Path $testRoot "runtime")) {
    throw "The test runtime must start empty."
}

powershell -ExecutionPolicy Bypass -File scripts\bootstrap_runtime.ps1 `
    -UvPath C:\path\to\verified\uv.exe
```

Verify the UI opens, OmniVoice initializes on CUDA, and one voice generation
succeeds. Generated audio must be beneath `$testRoot\generated_audio`, and the
model cache must be beneath `$testRoot\models`.

Close the UI and run the same bootstrap command again. The second launch must
print `Managed runtime is ready; dependency sync skipped.` and start normally.

## Repair Test

The explicit repair path removes only the managed `.venv` and readiness marker:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\bootstrap_runtime.ps1 `
    -UvPath C:\path\to\verified\uv.exe -Repair -NoLaunch
```

After repair, confirm:

- `runtime\project\.venv` was recreated and verified;
- `runtime_ready.json` contains the current lock hash;
- `models`, `voice_profiles`, `generated_audio`, and `logs` are unchanged.

Removing only `runtime_ready.json` and launching normally is the lighter repair
scenario: uv performs a frozen synchronization and recreates the marker.

## Failure Behavior

The bootstrap exits nonzero with a direct error when:

- the pinned uv binary is missing, has the wrong hash, or has the wrong version;
- Windows x64 requirements are not met;
- the runtime directory is not writable;
- managed Python installation or lookup fails;
- frozen dependency synchronization fails;
- `check_environment.py` fails, including CUDA verification.

No failure path marks a partial runtime ready or falls back to another Python.
A failed initial `uv python find` is the expected clean-machine state; a failed
`uv python install 3.11.15` remains fatal and is recorded in the setup log.

## Installer Blockers Remaining

- Include the verified uv binary in release media and preserve its checksum.
- Decide how immutable application source is staged/versioned by the installer.
- Add installer UX for first-run runtime download progress and retry.
- Add disk-space, proxy, offline, and antivirus-interference messaging.
- Decide runtime upgrade/rollback and application-version compatibility policy.
- Sign the launcher, installer, and bundled uv payload.
- Run the clean launch, second launch, repair, and actual OmniVoice generation
  tests on a Windows machine representative of the minimum supported system.
