param(
    [string]$UvPath,
    [string]$InnoCompilerPath,
    [string]$TestPythonPath,
    [switch]$AllowDirty,
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$SourceRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Manifest = Get-Content -LiteralPath (Join-Path $SourceRoot "runtime_manifest.json") -Raw | ConvertFrom-Json
$Version = [string]$Manifest.application_version
$ReleaseRoot = Join-Path $SourceRoot "release"
$StageRoot = Join-Path $ReleaseRoot "stage"
$ObjectRoot = Join-Path $ReleaseRoot "obj"
$DistRoot = Join-Path $SourceRoot "dist"
$InstallerName = "NPC-Voice-Studio-$Version-alpha-win-x64.exe"

function Assert-ChildPath([string]$Path, [string]$Parent) {
    $FullPath = [IO.Path]::GetFullPath($Path)
    $FullParent = [IO.Path]::GetFullPath($Parent).TrimEnd([IO.Path]::DirectorySeparatorChar)
    if (-not $FullPath.StartsWith($FullParent + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Unsafe build path outside repository: $FullPath"
    }
}

function Reset-BuildDirectory([string]$Path) {
    Assert-ChildPath $Path $SourceRoot
    if (Test-Path -LiteralPath $Path) {
        Remove-Item -LiteralPath $Path -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $Path | Out-Null
}

function Copy-ReleaseFile([string]$RelativePath) {
    $Source = Join-Path $SourceRoot $RelativePath
    if (-not (Test-Path -LiteralPath $Source -PathType Leaf)) {
        throw "Required release file is missing: $RelativePath"
    }
    $Destination = Join-Path $StageRoot $RelativePath
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Destination) | Out-Null
    Copy-Item -LiteralPath $Source -Destination $Destination
}

function Resolve-BuildTool([string]$ExplicitPath, [string[]]$Candidates, [string]$Description) {
    if ($ExplicitPath) {
        if (-not (Test-Path -LiteralPath $ExplicitPath -PathType Leaf)) {
            throw "$Description was not found: $ExplicitPath"
        }
        return (Resolve-Path -LiteralPath $ExplicitPath).Path
    }
    foreach ($Candidate in $Candidates) {
        if ($Candidate -and (Test-Path -LiteralPath $Candidate -PathType Leaf)) {
            return (Resolve-Path -LiteralPath $Candidate).Path
        }
    }
    throw "$Description was not found. Supply its path explicitly."
}

Write-Host "Validating NPC Voice Studio $Version alpha release..."
if (-not $AllowDirty) {
    $GitStatus = (& git -C $SourceRoot status --porcelain | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) { throw "Git repository validation failed." }
    if ($GitStatus) { throw "Release builds require a clean Git worktree. Use -AllowDirty only for local smoke builds." }
}

$ProjectVersion = Select-String -LiteralPath (Join-Path $SourceRoot "pyproject.toml") -Pattern '^version\s*=\s*"([^\"]+)"$'
if (-not $ProjectVersion -or $ProjectVersion.Matches[0].Groups[1].Value -ne $Version) {
    throw "pyproject.toml and runtime_manifest.json application versions do not match."
}
$ServiceSource = Get-Content -LiteralPath (Join-Path $SourceRoot "src\omnivoice_service.py") -Raw
if (-not $ServiceSource.Contains("load_model_spec") -or -not $ServiceSource.Contains("resolve_installed_model")) {
    throw "OmniVoiceService must resolve the manifest-pinned installed model."
}

if (-not $UvPath) { $UvPath = Join-Path $SourceRoot "tools\uv\uv.exe" }
$UvPath = Resolve-BuildTool $UvPath @() "Verified uv.exe"
$UvHash = (Get-FileHash -LiteralPath $UvPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($UvHash -ne ([string]$Manifest.uv_sha256).ToLowerInvariant()) {
    throw "uv.exe failed its SHA-256 integrity check."
}
$UvVersion = (& $UvPath --version | Out-String).Trim()
if ($UvVersion -notmatch "^uv $([regex]::Escape([string]$Manifest.uv_version)) ") {
    throw "Expected uv $($Manifest.uv_version), found: $UvVersion"
}

foreach ($RequiredDocument in @("LICENSE", "THIRD_PARTY_NOTICES.md")) {
    if (-not (Test-Path -LiteralPath (Join-Path $SourceRoot $RequiredDocument) -PathType Leaf)) {
        throw "Required release document is missing: $RequiredDocument"
    }
}
foreach ($RequiredIcon in @("assets\app_icon.png", "assets\app_icon.ico")) {
    if (-not (Test-Path -LiteralPath (Join-Path $SourceRoot $RequiredIcon) -PathType Leaf)) {
        throw "Required release icon is missing: $RequiredIcon"
    }
}

Reset-BuildDirectory $ReleaseRoot
Reset-BuildDirectory $DistRoot

if (-not $SkipTests) {
    if (-not $TestPythonPath) {
        $PythonCommand = Get-Command "python.exe" -ErrorAction SilentlyContinue
        if (-not $PythonCommand) { throw "A Python 3.11 test interpreter is required for release validation." }
        $TestPythonPath = $PythonCommand.Source
    }
    $TestPythonPath = Resolve-BuildTool $TestPythonPath @() "Python test interpreter"
    & $TestPythonPath -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) else 1)"
    if ($LASTEXITCODE -ne 0) { throw "Release tests require Python 3.11." }
    $TestTempRoot = Join-Path $ReleaseRoot "test-temp"
    New-Item -ItemType Directory -Force -Path $TestTempRoot | Out-Null
    $PreviousTemp = $env:TEMP
    $PreviousTmp = $env:TMP
    $env:TEMP = $TestTempRoot
    $env:TMP = $TestTempRoot
    & $TestPythonPath -m unittest discover -s (Join-Path $SourceRoot "tests") -v
    $TestExitCode = $LASTEXITCODE
    $env:TEMP = $PreviousTemp
    $env:TMP = $PreviousTmp
    if ($TestExitCode -ne 0) { throw "Automated tests failed." }
    Remove-Item -LiteralPath $TestTempRoot -Recurse -Force
}

New-Item -ItemType Directory -Force -Path $StageRoot, $ObjectRoot | Out-Null

$Compiler = Resolve-BuildTool "" @(
    (Join-Path $env:WINDIR "Microsoft.NET\Framework64\v4.0.30319\csc.exe"),
    (Join-Path $env:WINDIR "Microsoft.NET\Framework\v4.0.30319\csc.exe")
) "64-bit .NET Framework C# compiler"

$VersionParts = $Version.Split('.')
if ($VersionParts.Count -ne 3) { throw "Application version must use major.minor.patch format." }
$AssemblyVersion = "$Version.0"
$GeneratedVersionSource = Join-Path $ObjectRoot "LauncherVersion.cs"
@"
using System.Reflection;
[assembly: AssemblyTitle("NPC Voice Studio")]
[assembly: AssemblyProduct("NPC Voice Studio")]
[assembly: AssemblyCompany("NPC Voice Studio contributors")]
[assembly: AssemblyCopyright("Copyright NPC Voice Studio contributors")]
[assembly: AssemblyVersion("$AssemblyVersion")]
[assembly: AssemblyFileVersion("$AssemblyVersion")]
[assembly: AssemblyInformationalVersion("$Version-alpha")]
"@ | Set-Content -LiteralPath $GeneratedVersionSource -Encoding UTF8

$LauncherOutput = Join-Path $StageRoot "NPC Voice Studio.exe"
& $Compiler /nologo /target:winexe /platform:x64 /optimize+ `
    "/out:$LauncherOutput" `
    "/win32manifest:$(Join-Path $SourceRoot 'launcher\app.manifest')" `
    "/win32icon:$(Join-Path $SourceRoot 'assets\app_icon.ico')" `
    /reference:System.Windows.Forms.dll `
    (Join-Path $SourceRoot "launcher\NpcVoiceStudioLauncher.cs") `
    $GeneratedVersionSource
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $LauncherOutput)) {
    throw "Launcher compilation failed."
}

foreach ($File in @(
    "app.py",
    "pyproject.toml",
    "uv.lock",
    "runtime_manifest.json",
    "README.md",
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
    "assets\app_icon.png",
    "assets\app_icon.ico",
    "scripts\launch_npc_voice_studio.ps1",
    "scripts\bootstrap_runtime.ps1",
    "scripts\managed_python_bootstrap.ps1",
    "scripts\bootstrap_runtime.py",
    "scripts\check_environment.py",
    "scripts\setup_model.py",
    "docs\phase-c1-uv-runtime.md",
    "docs\phase-c2-user-bootstrap.md",
    "docs\phase-c3-clean-machine-test.md",
    "docs\phase-c3-windows-release.md",
    "tools\uv\README.md"
)) {
    Copy-ReleaseFile $File
}

$SourceDirectory = Join-Path $SourceRoot "src"
$StageSourceDirectory = Join-Path $StageRoot "src"
New-Item -ItemType Directory -Force -Path $StageSourceDirectory | Out-Null
Get-ChildItem -LiteralPath $SourceDirectory -File -Filter "*.py" | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $StageSourceDirectory $_.Name)
}
$StageUvDirectory = Join-Path $StageRoot "tools\uv"
New-Item -ItemType Directory -Force -Path $StageUvDirectory | Out-Null
Copy-Item -LiteralPath $UvPath -Destination (Join-Path $StageUvDirectory "uv.exe")

$Forbidden = Get-ChildItem -LiteralPath $StageRoot -Recurse -Force | Where-Object {
    $_.Name -in @(".git", ".venv", "__pycache__", "tests", "voice_profiles", "generated_audio", "models", "logs") -or
    $_.Extension -in @(".pyc", ".pyo", ".safetensors", ".pt", ".pth")
}
if ($Forbidden) {
    throw "Forbidden development, user-data, or model content entered the release stage: $($Forbidden[0].FullName)"
}

if (-not $InnoCompilerPath) {
    $InnoCompilerPath = Resolve-BuildTool "" @(
        (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
        (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe")
    ) "Inno Setup 6 compiler"
} else {
    $InnoCompilerPath = Resolve-BuildTool $InnoCompilerPath @() "Inno Setup 6 compiler"
}

$InnoScript = Join-Path $SourceRoot "installer\NPCVoiceStudio.iss"
& $InnoCompilerPath "/DAppVersion=$Version" "/DSourceDir=$StageRoot" "/DOutputDir=$DistRoot" $InnoScript
if ($LASTEXITCODE -ne 0) { throw "Inno Setup compilation failed." }

$InstallerPath = Join-Path $DistRoot $InstallerName
if (-not (Test-Path -LiteralPath $InstallerPath -PathType Leaf)) {
    throw "Expected installer was not produced: $InstallerPath"
}
$InstallerHash = (Get-FileHash -LiteralPath $InstallerPath -Algorithm SHA256).Hash.ToLowerInvariant()
$ChecksumPath = "$InstallerPath.sha256"
Set-Content -LiteralPath $ChecksumPath -Value "$InstallerHash *$InstallerName" -Encoding ASCII

Write-Host "Release build complete:"
Write-Host "  Launcher: $LauncherOutput ($((Get-Item $LauncherOutput).Length) bytes)"
Write-Host "  Installer: $InstallerPath ($((Get-Item $InstallerPath).Length) bytes)"
Write-Host "  SHA-256: $InstallerHash"
