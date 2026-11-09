# Bundled uv Location

The future Windows package places the pinned x64 binary here as `uv.exe`.
The binary is intentionally not committed during Phase C1.

- Version: `uv 0.13.5`
- Release: `https://github.com/astral-sh/uv/releases/tag/0.13.5`
- Archive: `uv-x86_64-pc-windows-msvc.zip`
- Archive SHA-256: `a38b8d1902b7cfbc76b423ba1bb456f623f42064cdc72628b6075b89afd1019a`
- Extracted `uv.exe` SHA-256: `f45d1cb9d9140ca6d3f4005fdfc0ebeccf849fd04d1dc85804155cb923f1597b`

The bootstrap verifies the executable hash and exact version before use. During
development, pass the same verified binary explicitly with `-UvPath`.

`runtime_manifest.json` is the shared machine-readable source for this version
and checksum. The Phase C2 launcher and C1 bootstrap both verify it; neither
searches the user's `PATH` or downloads a replacement.
