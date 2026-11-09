function Invoke-AppNativeCommand {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [switch]$SuppressStandardError
    )

    # A missing uv-managed interpreter is reported on stderr. Temporarily use
    # non-terminating native-command behavior so callers can inspect the exit
    # code instead of inheriting the bootstrap's global Stop policy.
    $PreviousErrorActionPreference = $ErrorActionPreference
    $NativePreference = Get-Variable -Name PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue
    if ($NativePreference) {
        $PreviousNativePreference = $PSNativeCommandUseErrorActionPreference
    }

    $Output = @()
    $Failure = $null
    $ExitCode = -1
    try {
        $ErrorActionPreference = "Continue"
        if ($NativePreference) {
            $PSNativeCommandUseErrorActionPreference = $false
        }
        if ($SuppressStandardError) {
            $Output = @(& $FilePath @Arguments 2>$null)
        } else {
            $Output = @(& $FilePath @Arguments 2>&1)
        }
        $ExitCode = [int]$LASTEXITCODE
    } catch {
        $Failure = $_.Exception.Message
        if ($null -ne $LASTEXITCODE) {
            $ExitCode = [int]$LASTEXITCODE
        }
    } finally {
        $ErrorActionPreference = $PreviousErrorActionPreference
        if ($NativePreference) {
            $PSNativeCommandUseErrorActionPreference = $PreviousNativePreference
        }
    }

    [PSCustomObject]@{
        ExitCode = $ExitCode
        Output = @($Output | ForEach-Object { [string]$_ })
        Failure = $Failure
    }
}

function Resolve-AppManagedPython {
    param(
        [Parameter(Mandatory = $true)][string]$UvPath,
        [Parameter(Mandatory = $true)][string]$PythonVersion,
        [Parameter(Mandatory = $true)][string]$ManagedInstallRoot,
        [scriptblock]$StatusCallback
    )

    Write-Host "Locating managed Python $PythonVersion..."
    $FindResult = Invoke-AppNativeCommand `
        -FilePath $UvPath `
        -Arguments @("python", "find", $PythonVersion, "--managed-python") `
        -SuppressStandardError
    $BootstrapPython = ($FindResult.Output -join [Environment]::NewLine).Trim()
    $InstallResult = $null

    if ($FindResult.ExitCode -ne 0 -or -not $BootstrapPython -or -not (Test-Path -LiteralPath $BootstrapPython -PathType Leaf)) {
        if ($StatusCallback) {
            & $StatusCallback "Installing Python runtime..." 10 "Downloading the exact app-managed Python $PythonVersion interpreter."
        }
        Write-Host "Managed Python $PythonVersion is not installed; downloading it with bundled uv..."
        $InstallResult = Invoke-AppNativeCommand `
            -FilePath $UvPath `
            -Arguments @("python", "install", $PythonVersion, "--install-dir", $ManagedInstallRoot)
        foreach ($Line in $InstallResult.Output) {
            Write-Host $Line
        }

        # uv 0.13.5 can return nonzero after installing the exact interpreter
        # if its optional minor-version link cannot be created. Always perform
        # a managed-only lookup and exact version check before deciding whether
        # the installation genuinely failed.
        $FindResult = Invoke-AppNativeCommand `
            -FilePath $UvPath `
            -Arguments @("python", "find", $PythonVersion, "--managed-python") `
            -SuppressStandardError
        $BootstrapPython = ($FindResult.Output -join [Environment]::NewLine).Trim()
    }

    if ($FindResult.ExitCode -ne 0 -or -not $BootstrapPython -or -not (Test-Path -LiteralPath $BootstrapPython -PathType Leaf)) {
        if ($InstallResult -and $InstallResult.ExitCode -ne 0) {
            $FailureDetail = if ($InstallResult.Failure) { " $($InstallResult.Failure)" } else { "" }
            throw "uv failed to install managed Python $PythonVersion (exit code $($InstallResult.ExitCode)).$FailureDetail Check the setup log and internet connection, then retry."
        }
        throw "uv could not locate managed Python $PythonVersion after installation. Check the setup log and retry."
    }

    $ManagedRoot = (Resolve-Path -LiteralPath $ManagedInstallRoot).Path
    $ResolvedPython = (Resolve-Path -LiteralPath $BootstrapPython).Path
    if (-not $ResolvedPython.StartsWith($ManagedRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to use Python outside the app-managed runtime."
    }

    $VersionResult = Invoke-AppNativeCommand `
        -FilePath $ResolvedPython `
        -Arguments @("-c", "import platform; print(platform.python_version())") `
        -SuppressStandardError
    $ActualVersion = ($VersionResult.Output -join [Environment]::NewLine).Trim()
    if ($VersionResult.ExitCode -ne 0 -or $ActualVersion -ne $PythonVersion) {
        $ReportedVersion = if ($ActualVersion) { $ActualVersion } else { "unavailable" }
        if ($InstallResult -and $InstallResult.ExitCode -ne 0) {
            throw "uv failed to install a usable managed Python $PythonVersion (exit code $($InstallResult.ExitCode)); verification found $ReportedVersion."
        }
        throw "Managed Python verification failed; expected $PythonVersion, found $ReportedVersion."
    }

    if ($InstallResult -and $InstallResult.ExitCode -ne 0) {
        # uv 0.13.5 may finish installing Python and then fail only while
        # creating an optional Windows minor-version link (os error 448).
        # Recovery is accepted solely after path and exact-version checks.
        Write-Host "WARNING: uv reported exit code $($InstallResult.ExitCode) after installation, but the exact app-managed Python $PythonVersion interpreter was found and verified."
    }

    # A recovered native exit code must not escape into the component boundary.
    $global:LASTEXITCODE = 0
    return $ResolvedPython
}
