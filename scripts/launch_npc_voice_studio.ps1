param(
    [string]$UvPath,
    [switch]$Headless,
    [switch]$Repair,
    [switch]$ConfirmRepair,
    [switch]$NoBrowser,
    [switch]$NoLaunch,
    [long]$SimulatedFreeBytes = -1
)

$ErrorActionPreference = "Stop"
$SourceRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ManifestPath = Join-Path $SourceRoot "runtime_manifest.json"
$Manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
$AppRoot = if ($env:NPC_VOICE_STUDIO_DATA_DIR) {
    [IO.Path]::GetFullPath($env:NPC_VOICE_STUDIO_DATA_DIR)
} else {
    Join-Path $env:LOCALAPPDATA "NPC Voice Studio"
}
$RuntimeRoot = Join-Path $AppRoot "runtime"
$ProjectRoot = Join-Path $RuntimeRoot "project"
$ManagedPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$ModelsRoot = Join-Path $AppRoot "models"
$LogsRoot = Join-Path $AppRoot "logs"
$SetupLog = Join-Path $LogsRoot "setup.log"
$StatusFile = Join-Path $RuntimeRoot "setup_status.txt"
$ModelResultFile = Join-Path $RuntimeRoot "model_setup_result.json"
$ModelReadyMarker = Join-Path $ModelsRoot "omnivoice_ready.json"
$RuntimeReadyMarker = Join-Path $RuntimeRoot "runtime_ready.json"
$script:AppIconPath = Join-Path $SourceRoot "assets\app_icon.ico"
$MinimumSetupFreeBytes = [long]$Manifest.minimum_setup_free_bytes

# Keep subprocess output and paths reliable for non-ASCII Windows usernames and
# install directories, including when output is redirected to the setup log.
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONDONTWRITEBYTECODE = "1"

$script:ProgressForm = $null
$script:StatusLabel = $null
$script:DetailLabel = $null
$script:ElapsedLabel = $null
$script:ProgressBar = $null
$script:SetupStartedAt = Get-Date
$script:LastStatus = ""
$script:LastDetail = ""
$script:LastPercent = -1

function Initialize-SetupLog {
    New-Item -ItemType Directory -Force -Path $LogsRoot | Out-Null
    if ((Test-Path -LiteralPath $SetupLog) -and (Get-Item -LiteralPath $SetupLog).Length -gt 5MB) {
        $PreviousLog = Join-Path $LogsRoot "setup.previous.log"
        Move-Item -LiteralPath $SetupLog -Destination $PreviousLog -Force
    }
}

function Write-SetupLog([string]$Message) {
    $Line = "{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Add-Content -LiteralPath $SetupLog -Value $Line -Encoding UTF8
}

function Set-FormIcon($Form) {
    try {
        if (Test-Path -LiteralPath $script:AppIconPath -PathType Leaf) {
            $Form.Icon = New-Object Drawing.Icon -ArgumentList $script:AppIconPath
        }
    } catch {
        # Branding must never prevent setup or repair from starting.
        Write-SetupLog "WARNING: The application icon could not be loaded: $($_.Exception.Message)"
    }
}

function Set-SetupStatus(
    [string]$Message,
    [int]$Percent = -1,
    [string]$Detail = ""
) {
    $Changed = (
        $Message -and (
            $Message -ne $script:LastStatus -or
            $Detail -ne $script:LastDetail -or
            $Percent -ne $script:LastPercent
        )
    )
    if ($Changed) {
        $script:LastStatus = $Message
        $script:LastDetail = $Detail
        $script:LastPercent = $Percent
        $LogMessage = if ($Percent -ge 0) { "[$Percent%] $Message" } else { $Message }
        if ($Detail) { $LogMessage += " $Detail" }
        Write-SetupLog $LogMessage
    }
    if (-not $Headless -and $script:StatusLabel) {
        $script:StatusLabel.Text = $Message
        if ($script:DetailLabel) { $script:DetailLabel.Text = $Detail }
        if ($script:ProgressBar -and $Percent -ge 0) {
            $script:ProgressBar.Value = [Math]::Max(0, [Math]::Min(100, $Percent))
        }
        [Windows.Forms.Application]::DoEvents()
    } elseif ($Changed) {
        Write-Host $LogMessage
    }
}

function Update-SetupElapsedTime {
    if (-not $Headless -and $script:ElapsedLabel) {
        $Elapsed = (Get-Date) - $script:SetupStartedAt
        $script:ElapsedLabel.Text = "Elapsed: {0:hh\:mm\:ss}" -f $Elapsed
        [Windows.Forms.Application]::DoEvents()
    }
}

function Write-SetupStatusPayload(
    [string]$Message,
    [int]$Percent,
    [string]$Detail = ""
) {
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $StatusFile) | Out-Null
    $Payload = [ordered]@{
        operation = $Message
        percent = $Percent
        detail = $Detail
    } | ConvertTo-Json -Compress
    Set-Content -LiteralPath $StatusFile -Value $Payload -Encoding UTF8
}

function Read-SetupStatusPayload {
    if (-not (Test-Path -LiteralPath $StatusFile -PathType Leaf)) { return $null }
    $RawStatus = (Get-Content -LiteralPath $StatusFile -Raw).Trim()
    if (-not $RawStatus) { return $null }
    try {
        $Payload = $RawStatus | ConvertFrom-Json
        if ($Payload.operation) {
            return [PSCustomObject]@{
                Message = [string]$Payload.operation
                Percent = [int]$Payload.percent
                Detail = [string]$Payload.detail
            }
        }
    } catch {
        # Backward-compatible with a partially upgraded plain-text status file.
    }
    return [PSCustomObject]@{ Message = $RawStatus; Percent = -1; Detail = "" }
}

function Reset-ModelSetupResult {
    Remove-Item -LiteralPath $ModelResultFile -Force -ErrorAction SilentlyContinue
}

function Read-ModelSetupResult {
    if (-not (Test-Path -LiteralPath $ModelResultFile -PathType Leaf)) {
        return $null
    }
    try {
        $Result = Get-Content -LiteralPath $ModelResultFile -Raw | ConvertFrom-Json
        if (-not $Result.state) { return $null }
        return $Result
    } catch {
        return $null
    }
}

function Write-ModelSetupResult([string]$State, [string]$Message = "") {
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $ModelResultFile) | Out-Null
    [ordered]@{
        state = $State
        message = $Message
        snapshot_path = $null
    } | ConvertTo-Json -Compress | Set-Content -LiteralPath $ModelResultFile -Encoding UTF8
}

function Show-UserError([string]$Message) {
    Write-SetupLog "ERROR: $Message"
    $FullMessage = "$Message`r`n`r`nSetup log:`r`n$SetupLog"
    if ($Headless) {
        throw $FullMessage
    }
    [Windows.Forms.MessageBox]::Show(
        $FullMessage,
        "NPC Voice Studio Setup",
        [Windows.Forms.MessageBoxButtons]::OK,
        [Windows.Forms.MessageBoxIcon]::Error
    ) | Out-Null
    throw $Message
}

function Test-DirectoryWritable([string]$Directory) {
    New-Item -ItemType Directory -Force -Path $Directory | Out-Null
    $Probe = Join-Path $Directory (".write-test-" + [Guid]::NewGuid().ToString("N"))
    try {
        Set-Content -LiteralPath $Probe -Value "ok" -Encoding ASCII
    } finally {
        Remove-Item -LiteralPath $Probe -Force -ErrorAction SilentlyContinue
    }
}

function Resolve-PinnedUv {
    $Candidate = if ($UvPath) { $UvPath } else { Join-Path $SourceRoot "tools\uv\uv.exe" }
    if (-not (Test-Path -LiteralPath $Candidate -PathType Leaf)) {
        Show-UserError "The verified uv runtime tool is missing. Reinstall NPC Voice Studio or supply the packaged uv.exe."
    }
    $Resolved = (Resolve-Path -LiteralPath $Candidate).Path
    $ExpectedHash = ([string]$Manifest.uv_sha256).ToUpperInvariant()
    if ((Get-FileHash -LiteralPath $Resolved -Algorithm SHA256).Hash -ne $ExpectedHash) {
        Show-UserError "The packaged uv runtime tool failed its integrity check. Reinstall NPC Voice Studio."
    }
    $Version = (& $Resolved --version | Out-String).Trim()
    if ($Version -notmatch "^uv $([regex]::Escape([string]$Manifest.uv_version)) ") {
        Show-UserError "The packaged uv runtime tool has the wrong version. Reinstall NPC Voice Studio."
    }
    return $Resolved
}

function Find-NvidiaSmi {
    $Command = Get-Command "nvidia-smi.exe" -ErrorAction SilentlyContinue
    if ($Command) {
        return $Command.Source
    }
    $KnownPath = Join-Path $env:ProgramFiles "NVIDIA Corporation\NVSMI\nvidia-smi.exe"
    if (Test-Path -LiteralPath $KnownPath -PathType Leaf) {
        return $KnownPath
    }
    return $null
}

function Test-BasicRuntimeMarker {
    if (-not (Test-Path -LiteralPath $RuntimeReadyMarker -PathType Leaf) -or
        -not (Test-Path -LiteralPath $ManagedPython -PathType Leaf)) {
        return $false
    }
    try {
        $Marker = Get-Content -LiteralPath $RuntimeReadyMarker -Raw | ConvertFrom-Json
        $LockHash = (Get-FileHash -LiteralPath (Join-Path $SourceRoot "uv.lock") -Algorithm SHA256).Hash.ToLowerInvariant()
        return (
            [string]$Marker.python_version -eq [string]$Manifest.python_version -and
            [string]$Marker.uv_version -eq [string]$Manifest.uv_version -and
            [string]$Marker.lockfile_sha256 -eq $LockHash -and
            [string]$Marker.application_version -eq [string]$Manifest.application_version
        )
    } catch {
        return $false
    }
}

function Test-BasicModelMarker {
    if (-not (Test-Path -LiteralPath $ModelReadyMarker -PathType Leaf)) {
        return $false
    }
    try {
        $Marker = Get-Content -LiteralPath $ModelReadyMarker -Raw | ConvertFrom-Json
        return (
            [string]$Marker.model_repository -eq [string]$Manifest.model.repository -and
            [string]$Marker.model_revision -eq [string]$Manifest.model.revision -and
            (Test-Path -LiteralPath ([string]$Marker.snapshot_path) -PathType Container)
        )
    } catch {
        return $false
    }
}

function Assert-SetupDiskSpace {
    $FreeBytes = if ($SimulatedFreeBytes -ge 0) {
        $SimulatedFreeBytes
    } else {
        ([IO.DriveInfo]::new([IO.Path]::GetPathRoot($AppRoot))).AvailableFreeSpace
    }
    Write-SetupLog ("Available disk space: {0:N2} GiB" -f ($FreeBytes / 1GB))
    if ($FreeBytes -lt $MinimumSetupFreeBytes) {
        $RequiredGiB = [Math]::Ceiling($MinimumSetupFreeBytes / 1GB)
        Show-UserError "At least $RequiredGiB GiB of free disk space is required for first-time setup or repair."
    }
}

function Test-SystemPreflight {
    Set-SetupStatus "Checking your system..." 3
    if ($env:OS -ne "Windows_NT" -or
        [Runtime.InteropServices.RuntimeInformation]::OSArchitecture -ne "X64") {
        Show-UserError "NPC Voice Studio v0.1 requires 64-bit Windows."
    }
    if ($AppRoot.StartsWith($SourceRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        Show-UserError "The application data directory cannot be inside the installed application source."
    }
    try {
        foreach ($Directory in @($AppRoot, $RuntimeRoot, $ModelsRoot, $LogsRoot)) {
            Test-DirectoryWritable $Directory
        }
    } catch {
        Show-UserError "NPC Voice Studio cannot write to its application-data directory."
    }

    $SetupRequired = $Action -eq "repair" -or -not ((Test-BasicRuntimeMarker) -and (Test-BasicModelMarker))
    if ($SetupRequired) {
        Assert-SetupDiskSpace
    }

    $NvidiaSmi = Find-NvidiaSmi
    if (-not $NvidiaSmi) {
        Show-UserError "A supported NVIDIA GPU and driver were not detected. NPC Voice Studio v0.1 is NVIDIA-only."
    }
    $GpuInfo = (& $NvidiaSmi --query-gpu=name,driver_version --format=csv,noheader 2>&1 | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $GpuInfo) {
        Show-UserError "The NVIDIA driver could not be queried. Update or repair the NVIDIA driver and retry."
    }
    Write-SetupLog "NVIDIA detected: $GpuInfo"
    $ResolvedUv = Resolve-PinnedUv
    return $ResolvedUv
}

function Quote-ProcessArgument([string]$Value) {
    return '"' + $Value.Replace('"', '\"') + '"'
}

function Invoke-SetupProcess(
    [string]$FilePath,
    [string[]]$Arguments,
    [string]$InitialStatus,
    [int]$InitialPercent,
    [string]$InitialDetail = ""
) {
    Set-SetupStatus $InitialStatus $InitialPercent $InitialDetail
    Write-SetupStatusPayload $InitialStatus $InitialPercent $InitialDetail
    $Token = [Guid]::NewGuid().ToString("N")
    $StdOutPath = Join-Path $LogsRoot ".setup-$Token.out"
    $StdErrPath = Join-Path $LogsRoot ".setup-$Token.err"
    $ArgumentLine = ($Arguments | ForEach-Object { Quote-ProcessArgument $_ }) -join " "
    Write-SetupLog "Running setup component: $([IO.Path]::GetFileName($FilePath))"
    $StartParameters = @{
        FilePath = $FilePath
        ArgumentList = $ArgumentLine
        RedirectStandardOutput = $StdOutPath
        RedirectStandardError = $StdErrPath
        WindowStyle = "Hidden"
        PassThru = $true
    }
    $Process = Start-Process @StartParameters
    while (-not $Process.HasExited) {
        $CurrentStatus = Read-SetupStatusPayload
        if ($CurrentStatus) {
            Set-SetupStatus $CurrentStatus.Message $CurrentStatus.Percent $CurrentStatus.Detail
        }
        Update-SetupElapsedTime
        if (-not $Headless) {
            [Windows.Forms.Application]::DoEvents()
        }
        Start-Sleep -Milliseconds 200
    }
    $Process.WaitForExit()
    $ComponentExitCode = [int]$Process.ExitCode
    foreach ($OutputPath in @($StdOutPath, $StdErrPath)) {
        if (Test-Path -LiteralPath $OutputPath) {
            $Output = Get-Content -LiteralPath $OutputPath -Raw
            if ($Output) {
                Add-Content -LiteralPath $SetupLog -Value $Output.TrimEnd() -Encoding UTF8
            }
            Remove-Item -LiteralPath $OutputPath -Force -ErrorAction SilentlyContinue
        }
    }
    Write-SetupLog "Setup component exit code: $ComponentExitCode"
    return $ComponentExitCode
}

function Show-LauncherChoice {
    $Form = New-Object Windows.Forms.Form
    $Form.Text = "NPC Voice Studio"
    $Form.StartPosition = "CenterScreen"
    $Form.ClientSize = New-Object Drawing.Size(500, 230)
    $Form.FormBorderStyle = "FixedDialog"
    $Form.MaximizeBox = $false
    Set-FormIcon $Form

    $Title = New-Object Windows.Forms.Label
    $Title.Text = "NPC Voice Studio"
    $Title.Font = New-Object Drawing.Font("Segoe UI", 18, [Drawing.FontStyle]::Bold)
    $Title.AutoSize = $true
    $Title.Location = New-Object Drawing.Point(28, 24)
    $Form.Controls.Add($Title)

    $Description = New-Object Windows.Forms.Label
    $Description.Text = "Start the local application, or repair only its managed AI runtime."
    $Description.Font = New-Object Drawing.Font("Segoe UI", 10)
    $Description.AutoSize = $true
    $Description.Location = New-Object Drawing.Point(31, 72)
    $Form.Controls.Add($Description)

    $StartButton = New-Object Windows.Forms.Button
    $StartButton.Text = "Start NPC Voice Studio"
    $StartButton.Size = New-Object Drawing.Size(200, 42)
    $StartButton.Location = New-Object Drawing.Point(32, 125)
    $StartButton.Add_Click({ $Form.Tag = "start"; $Form.DialogResult = "OK"; $Form.Close() })
    $Form.Controls.Add($StartButton)
    $Form.AcceptButton = $StartButton

    $RepairButton = New-Object Windows.Forms.Button
    $RepairButton.Text = "Repair Runtime"
    $RepairButton.Size = New-Object Drawing.Size(150, 42)
    $RepairButton.Location = New-Object Drawing.Point(245, 125)
    $RepairButton.Add_Click({ $Form.Tag = "repair"; $Form.DialogResult = "OK"; $Form.Close() })
    $Form.Controls.Add($RepairButton)

    $CancelButton = New-Object Windows.Forms.Button
    $CancelButton.Text = "Cancel"
    $CancelButton.Size = New-Object Drawing.Size(70, 42)
    $CancelButton.Location = New-Object Drawing.Point(400, 125)
    $CancelButton.Add_Click({ $Form.DialogResult = "Cancel"; $Form.Close() })
    $Form.Controls.Add($CancelButton)

    $Result = $Form.ShowDialog()
    if ($Result -ne "OK") { return $null }
    return [string]$Form.Tag
}

function Show-ProgressWindow {
    $script:ProgressForm = New-Object Windows.Forms.Form
    $script:ProgressForm.Text = "NPC Voice Studio Setup"
    $script:ProgressForm.StartPosition = "CenterScreen"
    $script:ProgressForm.ClientSize = New-Object Drawing.Size(560, 235)
    $script:ProgressForm.FormBorderStyle = "FixedDialog"
    $script:ProgressForm.ControlBox = $false
    Set-FormIcon $script:ProgressForm

    $Heading = New-Object Windows.Forms.Label
    $Heading.Text = "Preparing NPC Voice Studio"
    $Heading.Font = New-Object Drawing.Font("Segoe UI", 16, [Drawing.FontStyle]::Bold)
    $Heading.AutoSize = $true
    $Heading.Location = New-Object Drawing.Point(28, 25)
    $script:ProgressForm.Controls.Add($Heading)

    $script:StatusLabel = New-Object Windows.Forms.Label
    $script:StatusLabel.Text = "Checking system..."
    $script:StatusLabel.Font = New-Object Drawing.Font("Segoe UI", 10)
    $script:StatusLabel.AutoSize = $false
    $script:StatusLabel.Size = New-Object Drawing.Size(500, 24)
    $script:StatusLabel.Location = New-Object Drawing.Point(31, 73)
    $script:ProgressForm.Controls.Add($script:StatusLabel)

    $script:DetailLabel = New-Object Windows.Forms.Label
    $script:DetailLabel.Text = ""
    $script:DetailLabel.Font = New-Object Drawing.Font("Segoe UI", 9)
    $script:DetailLabel.AutoSize = $false
    $script:DetailLabel.Size = New-Object Drawing.Size(500, 45)
    $script:DetailLabel.Location = New-Object Drawing.Point(31, 100)
    $script:ProgressForm.Controls.Add($script:DetailLabel)

    $script:ProgressBar = New-Object Windows.Forms.ProgressBar
    $script:ProgressBar.Style = "Continuous"
    $script:ProgressBar.Minimum = 0
    $script:ProgressBar.Maximum = 100
    $script:ProgressBar.Value = 0
    $script:ProgressBar.Size = New-Object Drawing.Size(495, 22)
    $script:ProgressBar.Location = New-Object Drawing.Point(32, 153)
    $script:ProgressForm.Controls.Add($script:ProgressBar)

    $script:ElapsedLabel = New-Object Windows.Forms.Label
    $script:ElapsedLabel.Text = "Elapsed: 00:00:00"
    $script:ElapsedLabel.Font = New-Object Drawing.Font("Segoe UI", 9)
    $script:ElapsedLabel.AutoSize = $true
    $script:ElapsedLabel.Location = New-Object Drawing.Point(31, 188)
    $script:ProgressForm.Controls.Add($script:ElapsedLabel)

    $script:SetupStartedAt = Get-Date
    $script:ProgressForm.Show()
    [Windows.Forms.Application]::DoEvents()
}

function Find-FreeLocalPort {
    foreach ($Port in 7860..7869) {
        try {
            $Listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $Port)
            $Listener.Start()
            $Listener.Stop()
            return $Port
        } catch { }
    }
    Show-UserError "NPC Voice Studio could not find an available local port between 7860 and 7869."
}

function Start-LocalApplication {
    Set-SetupStatus "Starting NPC Voice Studio..." 97
    $Port = Find-FreeLocalPort
    $env:NPC_VOICE_STUDIO_DATA_DIR = $AppRoot
    $env:HF_HOME = $ModelsRoot
    $env:HF_HUB_CACHE = Join-Path $ModelsRoot "hub"
    $env:HF_XET_CACHE = Join-Path $ModelsRoot "xet"
    $env:HF_HUB_OFFLINE = "1"
    $env:HF_HUB_DISABLE_TELEMETRY = "1"
    $env:GRADIO_SERVER_PORT = [string]$Port
    $AppPath = Join-Path $ProjectRoot "app.py"
    $Application = Start-Process -FilePath $ManagedPython -ArgumentList (Quote-ProcessArgument $AppPath) -WindowStyle Hidden -PassThru
    $Url = "http://127.0.0.1:$Port/"
    $Deadline = (Get-Date).AddSeconds(90)
    while ((Get-Date) -lt $Deadline) {
        if ($Application.HasExited) {
            Show-UserError "NPC Voice Studio stopped before its local interface became available."
        }
        try {
            $Response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 2
            if ($Response.StatusCode -eq 200) {
                Write-SetupLog "Local interface ready at $Url"
                if (-not $NoBrowser) {
                    Start-Process $Url
                }
                return
            }
        } catch { }
        if (-not $Headless) { [Windows.Forms.Application]::DoEvents() }
        Start-Sleep -Milliseconds 500
    }
    Stop-Process -Id $Application.Id -Force -ErrorAction SilentlyContinue
    Show-UserError "NPC Voice Studio did not start within 90 seconds."
}

try {
    Initialize-SetupLog
    Write-SetupLog "Launcher started for NPC Voice Studio $($Manifest.application_version)."
    if (-not $Headless) {
        Add-Type -AssemblyName System.Windows.Forms
        Add-Type -AssemblyName System.Drawing
    }

    $Action = if ($Repair) { "repair" } elseif ($Headless) { "start" } else { Show-LauncherChoice }
    if (-not $Action) { exit 0 }
    if ($Action -eq "repair" -and -not $ConfirmRepair) {
        if ($Headless) {
            Show-UserError "Runtime repair requires -ConfirmRepair."
        }
        $Confirmation = [Windows.Forms.MessageBox]::Show(
            "Repair rebuilds only the managed Python runtime. Models, saved voices, generated audio, and logs are preserved.",
            "Confirm Runtime Repair",
            [Windows.Forms.MessageBoxButtons]::YesNo,
            [Windows.Forms.MessageBoxIcon]::Warning
        )
        if ($Confirmation -ne "Yes") { exit 0 }
    }

    if (-not $Headless) { Show-ProgressWindow }
    $PinnedUv = Test-SystemPreflight

    $BootstrapArguments = @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
        (Join-Path $SourceRoot "scripts\bootstrap_runtime.ps1"),
        "-UvPath", $PinnedUv,
        "-NoLaunch",
        "-StatusFile", $StatusFile
    )
    if ($Action -eq "repair") { $BootstrapArguments += "-Repair" }
    # Reuse the host that launched this script; do not accidentally fall back to
    # an obsolete powershell.exe elsewhere on PATH.
    $PowerShellHost = (Get-Process -Id $PID).Path
    $BootstrapExit = Invoke-SetupProcess `
        -FilePath $PowerShellHost `
        -Arguments $BootstrapArguments `
        -InitialStatus "Checking managed Python..." `
        -InitialPercent 8
    $RuntimeMarkerValid = Test-BasicRuntimeMarker
    Write-SetupLog "Managed runtime result: exit=$BootstrapExit marker_valid=$RuntimeMarkerValid"
    if ($BootstrapExit -ne 0 -or -not $RuntimeMarkerValid) {
        Show-UserError "The managed AI runtime could not be installed or verified."
    }

    $ModelScript = Join-Path $ProjectRoot "scripts\setup_model.py"
    Reset-ModelSetupResult
    $CheckExit = Invoke-SetupProcess `
        -FilePath $ManagedPython `
        -Arguments @("-u", $ModelScript, "--check", "--status-file", $StatusFile, "--result-file", $ModelResultFile) `
        -InitialStatus "Checking OmniVoice model..." `
        -InitialPercent 72
    $CheckResult = Read-ModelSetupResult
    $ModelMarkerValid = Test-BasicModelMarker
    $CheckState = if ($CheckResult) { [string]$CheckResult.state } else { "missing_result" }
    Write-SetupLog "Model check result: exit=$CheckExit state=$CheckState marker_valid=$ModelMarkerValid"

    $ModelIsReady = (
        $CheckExit -eq 0 -and
        $CheckState -eq "ready" -and
        $ModelMarkerValid
    )
    $ModelSetupRequired = (
        $CheckState -eq "setup_required" -or
        ($CheckExit -eq 2 -and -not $ModelMarkerValid)
    )
    if (-not $ModelIsReady -and -not $ModelSetupRequired) {
        Show-UserError "The OmniVoice model cache could not be checked."
    }

    if ($ModelSetupRequired) {
        Assert-SetupDiskSpace
        $ModelTermsDetail = "The pretrained weights have separate CC-BY-NC/non-commercial terms; see THIRD_PARTY_NOTICES.md."
        Set-SetupStatus "Preparing OmniVoice model download..." 73 $ModelTermsDetail
        Write-SetupLog "OmniVoice model notice: repository=$($Manifest.model.repository) revision=$($Manifest.model.revision) license=$($Manifest.model.license_identifier) card=$($Manifest.model.model_card_url)"

        # A prior offline launch must not leak into the explicit download phase.
        Remove-Item Env:HF_HUB_OFFLINE -ErrorAction SilentlyContinue
        while ($true) {
            Reset-ModelSetupResult
            $InstallExit = Invoke-SetupProcess `
                -FilePath $ManagedPython `
                -Arguments @("-u", $ModelScript, "--install", "--status-file", $StatusFile, "--result-file", $ModelResultFile) `
                -InitialStatus "Preparing OmniVoice model (~3.3 GB)..." `
                -InitialPercent 75 `
                -InitialDetail "This can take several minutes. This model only needs to be downloaded once."
            $InstallResult = Read-ModelSetupResult
            $InstallState = if ($InstallResult) { [string]$InstallResult.state } else { "missing_result" }
            $ModelMarkerValid = Test-BasicModelMarker
            Write-SetupLog "Model install result: exit=$InstallExit state=$InstallState marker_valid=$ModelMarkerValid"
            if ($InstallExit -eq 0 -and $InstallState -eq "ready" -and $ModelMarkerValid) {
                break
            }
            if ($Headless) {
                Show-UserError "The OmniVoice model download failed. Check the internet connection and retry."
            }
            $FailureKind = if ($InstallState -eq "validation_failed") { "validation" } else { "download" }
            $Retry = [Windows.Forms.MessageBox]::Show(
                "The OmniVoice model $FailureKind failed. Existing valid cache files were kept. Retry now?`r`n`r`nSetup log:`r`n$SetupLog",
                "Model Setup Failed",
                [Windows.Forms.MessageBoxButtons]::RetryCancel,
                [Windows.Forms.MessageBoxIcon]::Warning
            )
            if ($Retry -ne "Retry") {
                Show-UserError "OmniVoice model setup did not complete."
            }
        }
    }

    if (-not (Test-BasicModelMarker)) {
        Show-UserError "The pinned OmniVoice model is not ready. Restart setup to download or repair it."
    }

    if ($NoLaunch) {
        Set-SetupStatus "NPC Voice Studio is ready." 100
    } else {
        Start-LocalApplication
    }
    if (-not $Headless -and $script:ProgressForm) {
        $script:ProgressForm.Close()
    }
    Write-SetupLog "Launcher completed successfully."
    exit 0
} catch {
    if ($script:ProgressForm) { $script:ProgressForm.Close() }
    if ($Headless) {
        Write-Error $_.Exception.Message
    }
    exit 1
}
