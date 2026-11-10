# Building the Windows Installer

NPC Voice Studio uses a reproducible PowerShell build script to create its
Windows x64 launcher and Inno Setup installer. Release builds do not bundle
Python, Torch, OmniVoice, or model weights; those are installed by the
first-launch bootstrap.

## Requirements

- Windows 10 or 11 x64
- Git
- Inno Setup 6 (the release build was validated with 6.7.3)
- The exact `uv 0.13.5` Windows x64 executable whose SHA-256 matches
  `runtime_manifest.json`
- A Python 3.11 interpreter for the automated test suite
- The Windows-provided .NET Framework C# compiler

## Build

Run from the repository root in PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_windows_release.ps1 `
    -UvPath C:\path\to\uv.exe `
    -InnoCompilerPath "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" `
    -TestPythonPath C:\path\to\python.exe
```

The working tree must be clean. The script verifies project and manifest
versions, validates the supplied uv executable, runs the tests, compiles the
small launcher, stages an explicit immutable payload, rejects caches and user
data, invokes Inno Setup, and writes an installer checksum.

`-AllowDirty` and `-SkipTests` are intended only for local packaging smoke
tests and should not be used for distributed builds.

The output is:

```text
dist\
    NPC-Voice-Studio-0.1.0-alpha-win-x64.exe
    NPC-Voice-Studio-0.1.0-alpha-win-x64.exe.sha256
```

## Signing

Unsigned builds normally trigger Windows SmartScreen warnings. When an
Authenticode certificate is available, sign the launcher after compilation
and before staging, then sign the completed installer before publishing its
checksum. Never store certificate files or passwords in the repository.

Verify signed artifacts with:

```powershell
signtool verify /pa /all /v "release\stage\NPC Voice Studio.exe"
signtool verify /pa /all /v "dist\NPC-Voice-Studio-0.1.0-alpha-win-x64.exe"
```

Normal uninstall removes installer-owned application files and shortcuts but
preserves models, saved voices, generated audio, and logs under
`%LOCALAPPDATA%\NPC Voice Studio`.
