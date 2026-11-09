param(
    [string]$UvPath,
    [switch]$Repair,
    [switch]$NoLaunch,
    [string]$StatusFile
)

$ErrorActionPreference = "Stop"
$SourceRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Manifest = Get-Content -LiteralPath (Join-Path $SourceRoot "runtime_manifest.json") -Raw | ConvertFrom-Json
$ExpectedUvVersion = [string]$Manifest.uv_version
$ExpectedUvSha256 = ([string]$Manifest.uv_sha256).ToUpperInvariant()
$PythonVersion = [string]$Manifest.python_version
. (Join-Path $PSScriptRoot "managed_python_bootstrap.ps1")

function Set-BootstrapStatus(
    [string]$Message,
    [int]$Percent,
    [string]$Detail = ""
) {
    if ($StatusFile) {
        $StatusDirectory = Split-Path -Parent $StatusFile
        if ($StatusDirectory) {
            New-Item -ItemType Directory -Force -Path $StatusDirectory | Out-Null
        }
        $Payload = [ordered]@{
            operation = $Message
            percent = [Math]::Max(0, [Math]::Min(100, $Percent))
            detail = $Detail
        } | ConvertTo-Json -Compress
        $TemporaryStatus = "$StatusFile.tmp"
        Set-Content -LiteralPath $TemporaryStatus -Value $Payload -Encoding UTF8
        Move-Item -LiteralPath $TemporaryStatus -Destination $StatusFile -Force
    }
}

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
$env:UV_DATA_DIR = Join-Path $RuntimeRoot "uv-data"
$env:UV_PYTHON_BIN_DIR = Join-Path $RuntimeRoot "python-bin"
$env:UV_NO_PROGRESS = "1"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONDONTWRITEBYTECODE = "1"

New-Item -ItemType Directory -Force -Path $RuntimeRoot | Out-Null

Set-BootstrapStatus "Checking managed Python..." 8
$PythonStatusCallback = {
    param([string]$Message, [int]$Percent, [string]$Detail)
    Set-BootstrapStatus $Message $Percent $Detail
}
$ResolvedPython = Resolve-AppManagedPython `
    -UvPath $UvPath `
    -PythonVersion $PythonVersion `
    -ManagedInstallRoot $env:UV_PYTHON_INSTALL_DIR `
    -StatusCallback $PythonStatusCallback

Set-BootstrapStatus "Preparing AI runtime..." 15

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
if ($StatusFile) {
    $Arguments += @("--status-file", $StatusFile)
}

& $ResolvedPython -u @Arguments
$BootstrapExitCode = [int]$LASTEXITCODE
if ($BootstrapExitCode -ne 0) {
    throw "NPC Voice Studio managed runtime bootstrap failed."
}

# The Python bootstrap creates this only after environment and GPU checks pass.
$RuntimeReadyMarker = Join-Path $RuntimeRoot "runtime_ready.json"
if (-not (Test-Path -LiteralPath $RuntimeReadyMarker -PathType Leaf)) {
    throw "NPC Voice Studio managed runtime verification did not create its readiness marker."
}

# Make the component result explicit. A recoverable uv install/link failure must
# never become the PowerShell process result after exact Python verification.
$global:LASTEXITCODE = 0
exit 0
