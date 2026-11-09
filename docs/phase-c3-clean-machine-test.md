# Phase C3 Clean-Machine Acceptance Test

This is the definitive acceptance procedure for the v0.1 Windows alpha. A
development-machine smoke test is useful but does not replace this procedure.

## Test machine

Use a physical or genuinely clean Windows 10/11 x64 installation with a
supported NVIDIA GPU and current NVIDIA driver. Before starting, confirm the
machine has:

- no Python or Conda installation required by NPC Voice Studio;
- no uv installation;
- no FFmpeg installation required by NPC Voice Studio;
- no existing `%LOCALAPPDATA%\NPC Voice Studio\runtime`;
- no existing `%LOCALAPPDATA%\NPC Voice Studio\models`;
- no development repository or Git-checkout dependency;
- at least 16 GiB free on the Local AppData volume;
- internet access for first-use runtime and model downloads.

Record the Windows version, GPU model, NVIDIA driver version, available disk
space, installer SHA-256, and whether the build is signed.

## Installation and first launch

1. Verify the published `.sha256` file against the installer.
2. Run `NPC-Voice-Studio-0.1.0-alpha-win-x64.exe` as a normal user.
3. Confirm the default path is
   `%LOCALAPPDATA%\Programs\NPC Voice Studio` and no elevation is requested.
4. Enable or decline the optional Desktop shortcut and finish installation.
5. Launch from the Start Menu or setup completion page.
6. Confirm the system preflight and progress UI appear without a terminal.
7. Confirm managed Python/runtime setup completes under
   `%LOCALAPPDATA%\NPC Voice Studio\runtime`.
8. Confirm setup discloses that the pretrained weights have separate
   CC-BY-NC/non-commercial terms and points to `THIRD_PARTY_NOTICES.md` without
   opening a second blocking acknowledgement dialog.
9. Confirm the pinned model download starts automatically after runtime setup.
10. Confirm model files are stored under
    `%LOCALAPPDATA%\NPC Voice Studio\models`.
11. Confirm the browser opens a `127.0.0.1` URL and the application works.
12. Generate and play one short voice result.
13. Save one test voice to My Voices and note one generated output file.

## Offline second launch and repair

1. Close the application and disconnect the machine from the internet.
2. Reopen NPC Voice Studio from the Start Menu.
3. Confirm runtime installation and model download are skipped.
4. Generate another voice successfully while offline.
5. Close it, reopen the launcher, and choose **Repair Runtime**.
6. Confirm repair requires explicit confirmation.
7. Complete repair, still preserving model files, the saved voice, generated
   audio, and logs.
8. Reconnect only if repair requires locked package artifacts not already in the
   uv cache, and record that result.
9. Generate another voice after repair.

## Uninstall and reinstall

1. Uninstall through Windows Installed Apps / Add or Remove Programs.
2. Confirm `%LOCALAPPDATA%\Programs\NPC Voice Studio` and its shortcuts are
   removed.
3. Confirm `%LOCALAPPDATA%\NPC Voice Studio` remains and still contains the
   model, saved voice, generated audio, and logs.
4. Reinstall the same version and confirm installer rerun/reinstall behavior is
   understandable and user data is reused.
5. Launch offline and confirm the preserved model and voice remain usable.

## Path and operational edge cases

Repeat the relevant install/launch checks where practical with:

- a Windows username containing spaces;
- a non-ASCII Windows username;
- an installation path containing spaces;
- a restricted non-administrator account;
- port 7860 already occupied (the launcher should select 7861-7869);
- an interrupted first-run setup followed by retry;
- installer rerun over the same version;
- reinstall after uninstall;
- an upgrade build using the same Inno `AppId`, preserving user data.

## Acceptance record

Do not call the alpha production-ready. Record pass/fail and evidence for every
step, including SmartScreen behavior. An unsigned alpha is expected to show a
Windows SmartScreen warning. Any dependency on Python, Conda, uv, FFmpeg, a Git
checkout, or administrator access is a release blocker.
