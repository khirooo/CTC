# Entry point for the ctc.ps1 / install.ps1 Pester suite. Runs every
# *.Tests.ps1 file in this directory and exits non-zero on any failure.
# Windows-only tests (tagged 'Windows') are excluded automatically when this
# runs off-Windows, so the suite is still meaningful on macOS/Linux CI.

$ErrorActionPreference = 'Stop'

$pester = Get-Module -ListAvailable Pester | Where-Object { $_.Version -ge [version]'5.0.0' } | Select-Object -First 1
if (-not $pester) {
    [Console]::Error.WriteLine("Pester 5+ not found. Install with: Install-Module Pester -MinimumVersion 5.0 -Scope CurrentUser -Force -SkipPublisherCheck")
    exit 1
}
Import-Module Pester -MinimumVersion 5.0.0 -RequiredVersion $pester.Version -Force

$config = New-PesterConfiguration
$config.Run.Path = $PSScriptRoot
$config.Run.Exit = $false
$config.Output.Verbosity = 'Detailed'

# NOTE: do not name this $IsWindows -- PowerShell 6+ has a read-only
# automatic variable of that exact name (case-insensitive), and assigning to
# it throws "Cannot overwrite variable IsWindows because it is read-only".
$runningOnWindows = ($env:OS -eq 'Windows_NT')
if (-not $runningOnWindows) {
    $config.Filter.ExcludeTag = @('Windows')
}

$result = Invoke-Pester -Configuration $config

if ($result.FailedCount -gt 0) {
    exit 1
}
exit 0
