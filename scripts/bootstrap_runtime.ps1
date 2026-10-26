param(
    [string]$UvPath,
    [switch]$Repair,
    [switch]$NoLaunch
)

$ErrorActionPreference = "Stop"
$ExpectedUvVersion = "0.13.5"
$ExpectedUvSha256 = "F45D1CB9D9140CA6D3F4005FDFC0EBECCF849FD04D1DC85804155CB923F1597B"
$PythonVersion = "3.11.15"
$SourceRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

if ([System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture -ne "X64") {
    throw "NPC Voice Studio v0.1 requires Windows x64."
}

if (-not $UvPath) {
    # The installer will place the pinned binary here; PATH is never searched.
    $UvPath = Join-Path $SourceRoot "tools\uv\uv.exe"
}
if (-not (Test-Path -LiteralPath $UvPath -PathType Leaf)) {
    throw "Pinned uv.exe was not found. Supply -UvPath or bundle tools\uv\uv.exe."
}
$UvPath = (Resolve-Path -LiteralPath $UvPath).Path

$UvHash = (Get-FileHash -LiteralPath $UvPath -Algorithm SHA256).Hash
if ($UvHash -ne $ExpectedUvSha256) {
    throw "uv.exe failed its SHA-256 integrity check."
}
$UvVersionOutput = (& $UvPath --version | Out-String).Trim()
if ($UvVersionOutput -notmatch "^uv $([regex]::Escape($ExpectedUvVersion)) ") {
    throw "Expected uv $ExpectedUvVersion, found: $UvVersionOutput"
}

$AppRoot = if ($env:NPC_VOICE_STUDIO_DATA_DIR) {
    [IO.Path]::GetFullPath($env:NPC_VOICE_STUDIO_DATA_DIR)
} else {
    Join-Path $env:LOCALAPPDATA "NPC Voice Studio"
}
$AppRoot = [IO.Path]::GetFullPath($AppRoot)
if ($AppRoot.StartsWith($SourceRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw "The app-managed runtime cannot be created inside the source repository."
}
$RuntimeRoot = Join-Path $AppRoot "runtime"
$env:UV_PYTHON_INSTALL_DIR = Join-Path $RuntimeRoot "python"
$env:UV_CACHE_DIR = Join-Path $RuntimeRoot "uv-cache"
$env:UV_NO_PROGRESS = "1"

New-Item -ItemType Directory -Force -Path $RuntimeRoot | Out-Null

Write-Host "Locating managed Python $PythonVersion..."
$BootstrapPython = (& $UvPath python find $PythonVersion --managed-python 2>$null | Out-String).Trim()
$PythonFindExitCode = $LASTEXITCODE
$PythonInstallExitCode = 0
if ($PythonFindExitCode -ne 0 -or -not (Test-Path -LiteralPath $BootstrapPython)) {
    Write-Host "Installing managed Python $PythonVersion..."
    & $UvPath python install $PythonVersion --install-dir $env:UV_PYTHON_INSTALL_DIR
    $PythonInstallExitCode = $LASTEXITCODE
    $BootstrapPython = (& $UvPath python find $PythonVersion --managed-python | Out-String).Trim()
    $PythonFindExitCode = $LASTEXITCODE
}
if ($PythonFindExitCode -ne 0 -or -not (Test-Path -LiteralPath $BootstrapPython)) {
    throw "uv could not install or locate managed Python $PythonVersion (install exit code $PythonInstallExitCode)."
}
$ManagedRoot = (Resolve-Path -LiteralPath $env:UV_PYTHON_INSTALL_DIR).Path
$ResolvedPython = (Resolve-Path -LiteralPath $BootstrapPython).Path
if (-not $ResolvedPython.StartsWith($ManagedRoot + [IO.Path]::DirectorySeparatorChar)) {
    throw "Refusing to use Python outside the app-managed runtime."
}
if ($PythonInstallExitCode -ne 0) {
    # uv can fail while creating its optional minor-version link after the exact
    # interpreter is installed. Continue only after locating it under our root;
    # the Python version and complete environment are verified again below.
    Write-Warning "uv reported exit code $PythonInstallExitCode after installation, but the exact managed interpreter was verified."
}

$Arguments = @(
    (Join-Path $SourceRoot "scripts\bootstrap_runtime.py"),
    "--source-root", $SourceRoot,
    "--uv-path", $UvPath
)
if ($Repair) {
    $Arguments += "--repair"
}
if ($NoLaunch) {
    $Arguments += "--no-launch"
}

& $ResolvedPython @Arguments
if ($LASTEXITCODE -ne 0) {
    throw "NPC Voice Studio managed runtime bootstrap failed."
}
