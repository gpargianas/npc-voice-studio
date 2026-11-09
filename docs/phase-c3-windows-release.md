# Phase C3: Windows Installer and Alpha Distribution

## Build

The reproducible build entry point is:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_windows_release.ps1 `
    -UvPath C:\release-inputs\uv.exe `
    -InnoCompilerPath "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" `
    -TestPythonPath C:\path\to\python.exe
```

The locally validated installer compiler is Inno Setup `6.7.3`. The compiler is
a build-time tool only and is not included in the NPC Voice Studio payload.

Release builds require a clean Git worktree. `-AllowDirty` exists only for local
packaging smoke tests. `-SkipTests` should not be used for distributed builds.

The script verifies project/manifest/model versions, uv version and SHA-256,
runs the test suite, compiles the launcher, stages an explicit immutable file
list, rejects caches/user data/model weights, invokes Inno Setup, and writes the
installer SHA-256.

The uv binary is a verified release/build input. It is staged as
`tools\uv\uv.exe` but is not downloaded by either the build script or installed
application.

## Tiny launcher

`launcher\NpcVoiceStudioLauncher.cs` compiles with the Windows-provided .NET
Framework 64-bit C# compiler as an x64 GUI executable. It contains no Python,
Torch, OmniVoice, model, or application logic. Its only responsibilities are:

- locate files relative to its installed executable;
- start the installed C2 PowerShell orchestration with `-STA`;
- suppress the terminal window;
- preserve the orchestration exit code;
- append bridge failures to the normal setup log.

The assembly/file version source is generated from `runtime_manifest.json` at
build time. This avoids a second hand-maintained version.

## Installer

`installer\NPCVoiceStudio.iss` creates a per-user Inno Setup installer with:

- default path `%LOCALAPPDATA%\Programs\NPC Voice Studio`;
- `PrivilegesRequired=lowest`;
- Windows 10/11 x64 restriction;
- Start Menu shortcut;
- optional Desktop shortcut;
- Add/Remove Programs entry;
- optional launch after setup;
- stable `AppId` for same-version reinstall and future upgrades;
- no Python, ML runtime, or model installation during setup.

Normal uninstall removes only installer-owned immutable files and shortcuts.
It deliberately leaves `%LOCALAPPDATA%\NPC Voice Studio` untouched and displays
that location after uninstall. C3 does not offer a destructive "delete all
data" option.

No custom application icon currently exists, so the alpha uses the executable
and Inno defaults instead of inventing unreviewed branding.

## Signing points

Unsigned local alpha builds will normally trigger SmartScreen warnings. Do not
fabricate signatures. Once an Authenticode certificate is available, sign the
launcher after compilation and before staging, then sign the completed installer
before publishing its checksum. Example placeholders:

```powershell
signtool sign /fd SHA256 /td SHA256 /tr https://timestamp.example.invalid `
    /f C:\secure\codesigning.pfx /p $env:SIGNING_PASSWORD `
    "release\stage\NPC Voice Studio.exe"

signtool sign /fd SHA256 /td SHA256 /tr https://timestamp.example.invalid `
    /f C:\secure\codesigning.pfx /p $env:SIGNING_PASSWORD `
    "dist\NPC-Voice-Studio-0.1.0-alpha-win-x64.exe"
```

Replace the timestamp URL and certificate arguments with the certificate
provider's authoritative values. After signing, verify both artifacts with
`signtool verify /pa /all /v` and regenerate the installer checksum. Never store
certificate files or passwords in the repository.

## Output

```text
dist\
    NPC-Voice-Studio-0.1.0-alpha-win-x64.exe
    NPC-Voice-Studio-0.1.0-alpha-win-x64.exe.sha256
```

The clean-machine acceptance procedure is in
[`phase-c3-clean-machine-test.md`](phase-c3-clean-machine-test.md).
