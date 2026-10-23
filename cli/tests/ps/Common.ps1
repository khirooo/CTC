# Shared sandbox-test harness for the ctc.ps1 / install.ps1 Pester suite.
# Dot-sourced by every *.Tests.ps1 file in this directory. Never hits the
# network and never mutates the real user profile: every test runs inside a
# throwaway temp directory that stands in for HOME/USERPROFILE/APPDATA, with
# PATH-first stub executables shadowing copilot/claude/curl.exe/npm/winget.

$script:CtcPsDir = $PSScriptRoot
$script:CtcLibDir = Split-Path -Parent (Split-Path -Parent $CtcPsDir)   # .../cli
$script:CtcScriptPath = Join-Path $CtcLibDir 'ctc.ps1'
$script:CtcInstallScriptPath = Join-Path $CtcLibDir 'install.ps1'
$script:CtcPwshExe = (Get-Command pwsh -ErrorAction SilentlyContinue).Source
if (-not $script:CtcPwshExe) { $script:CtcPwshExe = (Get-Command powershell -ErrorAction SilentlyContinue).Source }

# Every env var either script reads, so a sandboxed test never leaks into (or
# is polluted by) the real environment or a sibling test.
$script:CtcEnvNames = @(
    'USERPROFILE', 'HOME', 'APPDATA', 'LOCALAPPDATA', 'PATH', 'OS',
    'CTC_CONFIG_DIR', 'CTC_ALLOW_NON_WINDOWS', 'CTC_UPDATE_CHECK', 'CTC_LEDGER_POLL',
    'CTC_HOST', 'CTC_SCHEME', 'CTC_PROXY_HOST', 'CTC_PROXY_PORT', 'GHE_DOMAIN', 'CTC_NO_PROXY',
    'NO_PROXY', 'no_proxy', 'CTC_RUN_TAG', 'CTC_SRC', 'CTC_SKIP_EXECPOLICY_CHECK', 'CTC_TEST_ELEVATED',
    'ANTHROPIC_CUSTOM_HEADERS', 'ANTHROPIC_MODEL', 'ANTHROPIC_SMALL_FAST_MODEL', 'ANTHROPIC_BASE_URL',
    'ANTHROPIC_AUTH_TOKEN', 'ENABLE_TOOL_SEARCH', 'CLAUDE_CODE_DISABLE_WORKFLOWS',
    'CLAUDE_CODE_DISABLE_UNKNOWN_MODEL_WINDOW_ENFORCEMENT',
    'GH_HOST', 'GITHUB_API_URL', 'COPILOT_GITHUB_TOKEN', 'HTTPS_PROXY', 'NODE_EXTRA_CA_CERTS',
    'XDG_CONFIG_HOME', 'XDG_STATE_HOME', 'XDG_CACHE_HOME'
)

function Save-CtcTestEnv {
    $saved = @{}
    foreach ($n in $script:CtcEnvNames) { $saved[$n] = [Environment]::GetEnvironmentVariable($n) }
    return $saved
}

function Restore-CtcTestEnv {
    param([hashtable]$Saved)
    foreach ($k in $Saved.Keys) {
        if ($null -eq $Saved[$k]) { [Environment]::SetEnvironmentVariable($k, $null) }
        else { [Environment]::SetEnvironmentVariable($k, $Saved[$k]) }
    }
}

function New-CtcTestSandbox {
    $root = Join-Path ([IO.Path]::GetTempPath()) ('ctc-pester-' + [guid]::NewGuid().ToString('N'))
    $home_ = Join-Path $root 'home'
    $appData = Join-Path $root 'appdata-roaming'
    $localAppData = Join-Path $root 'appdata-local'
    $stubs = Join-Path $root 'stubs'
    foreach ($d in @($root, $home_, $appData, $localAppData, $stubs)) {
        New-Item -ItemType Directory -Path $d -Force | Out-Null
    }
    [PSCustomObject]@{
        Root         = $root
        Home         = $home_
        AppData      = $appData
        LocalAppData = $localAppData
        Stubs        = $stubs
    }
}

function Remove-CtcTestSandbox {
    param($Sandbox)
    if ($Sandbox -and (Test-Path -LiteralPath $Sandbox.Root)) {
        Remove-Item -LiteralPath $Sandbox.Root -Recurse -Force -ErrorAction SilentlyContinue
    }
}

function Initialize-CtcTestEnv {
    # Resets every env var the scripts read to a known, isolated state. Tests
    # then layer their own CTC_HOST/env.json/etc. on top as needed.
    param($Sandbox)
    [Environment]::SetEnvironmentVariable('USERPROFILE', $Sandbox.Home)
    [Environment]::SetEnvironmentVariable('HOME', $Sandbox.Home)
    [Environment]::SetEnvironmentVariable('APPDATA', $Sandbox.AppData)
    [Environment]::SetEnvironmentVariable('LOCALAPPDATA', $Sandbox.LocalAppData)
    [Environment]::SetEnvironmentVariable('CTC_ALLOW_NON_WINDOWS', '1')
    [Environment]::SetEnvironmentVariable('CTC_UPDATE_CHECK', '0')
    [Environment]::SetEnvironmentVariable('CTC_LEDGER_POLL', '0')
    foreach ($n in @(
            'CTC_CONFIG_DIR', 'XDG_CONFIG_HOME', 'XDG_STATE_HOME', 'XDG_CACHE_HOME',
            'NO_PROXY', 'no_proxy', 'CTC_HOST', 'CTC_SCHEME', 'CTC_PROXY_HOST', 'CTC_PROXY_PORT',
            'GHE_DOMAIN', 'CTC_NO_PROXY', 'CTC_RUN_TAG', 'CTC_SRC', 'CTC_SKIP_EXECPOLICY_CHECK',
            'CTC_TEST_ELEVATED', 'ANTHROPIC_CUSTOM_HEADERS', 'ANTHROPIC_MODEL',
            'ANTHROPIC_SMALL_FAST_MODEL', 'ANTHROPIC_BASE_URL', 'ANTHROPIC_AUTH_TOKEN'
        )) {
        [Environment]::SetEnvironmentVariable($n, $null)
    }
    $sep = [IO.Path]::PathSeparator
    [Environment]::SetEnvironmentVariable('PATH', "$($Sandbox.Stubs)$sep$($env:PATH)")
}

function New-CtcStub {
    # Mirrors bash's make_stub: an executable on $Sandbox.Stubs that appends
    # its args to "$Sandbox.Root/<name>.log" (one call per line, space-joined),
    # then runs $Body (sh syntax). On Windows a .cmd stub is written instead.
    param($Sandbox, [Parameter(Mandatory)][string]$Name, [string]$Body = '')
    $logPath = Join-Path $Sandbox.Root "$Name.log"
    if ($env:OS -eq 'Windows_NT') {
        $stubPath = Join-Path $Sandbox.Stubs "$Name.cmd"
        $content = "@echo off`r`necho %*>> `"$logPath`"`r`n$Body`r`n"
        Set-Content -LiteralPath $stubPath -Value $content -Encoding ascii -NoNewline
    } else {
        $stubPath = Join-Path $Sandbox.Stubs $Name
        $content = "#!/bin/sh`necho `"`$@`" >> `"$logPath`"`n$Body`n"
        [IO.File]::WriteAllText($stubPath, $content)
        & chmod +x $stubPath
    }
    return $stubPath
}

function Get-CtcStubLog {
    param($Sandbox, [string]$Name)
    $p = Join-Path $Sandbox.Root "$Name.log"
    if (Test-Path -LiteralPath $p) { return (Get-Content -Raw -LiteralPath $p) }
    return ''
}

function Invoke-CtcScript {
    # Runs ctc.ps1 (or install.ps1 via -ScriptPath) as a REAL child process --
    # not dot-sourced -- so the bottom `exit (Invoke-Ctc*Main ...)` guard, exit
    # codes, and [Console]::Out/Error streams are exercised exactly as a real
    # user invocation would (`ctc.cmd` shells out to `powershell -File ctc.ps1`
    # the same way). Inherits the current process environment, so callers set
    # $env:/[Environment]::SetEnvironmentVariable(...) beforehand.
    param(
        [string]$ScriptPath = $script:CtcScriptPath,
        [string[]]$ScriptArgs = @(),
        [string]$StdIn = $null,
        [int]$TimeoutSec = 20
    )
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $script:CtcPwshExe
    $psi.ArgumentList.Add('-NoProfile') | Out-Null
    $psi.ArgumentList.Add('-NonInteractive') | Out-Null
    $psi.ArgumentList.Add('-File') | Out-Null
    $psi.ArgumentList.Add($ScriptPath) | Out-Null
    foreach ($a in $ScriptArgs) { $psi.ArgumentList.Add($a) | Out-Null }
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.RedirectStandardInput = $true
    $psi.UseShellExecute = $false
    # ProcessStartInfo snapshots the environment at construction time from
    # [Environment]::GetEnvironmentVariable, so changes made via
    # Initialize-CtcTestEnv above are already reflected here.
    $proc = New-Object System.Diagnostics.Process
    $proc.StartInfo = $psi
    [void]$proc.Start()
    if ($null -ne $StdIn) {
        $proc.StandardInput.Write($StdIn)
    }
    $proc.StandardInput.Close()
    $stdout = $proc.StandardOutput.ReadToEnd()
    $stderr = $proc.StandardError.ReadToEnd()
    if (-not $proc.WaitForExit($TimeoutSec * 1000)) {
        try { $proc.Kill() } catch { }
        throw "Invoke-CtcScript: $ScriptPath $($ScriptArgs -join ' ') timed out after ${TimeoutSec}s"
    }
    [PSCustomObject]@{
        ExitCode = $proc.ExitCode
        StdOut   = $stdout
        StdErr   = $stderr
        Combined = $stdout + $stderr
    }
}

function Get-CtcTestConfigDir {
    # Mirrors Get-CtcConfigDir's resolution order in ctc.ps1 exactly, reading
    # from the CURRENT process environment -- so test setup and the real
    # script always agree on where env.json/home/etc. live.
    if (-not [string]::IsNullOrEmpty($env:CTC_CONFIG_DIR)) { return $env:CTC_CONFIG_DIR }
    if (-not [string]::IsNullOrEmpty($env:XDG_CONFIG_HOME)) { return (Join-Path $env:XDG_CONFIG_HOME 'ctc') }
    if (-not [string]::IsNullOrEmpty($env:APPDATA)) { return (Join-Path $env:APPDATA 'ctc') }
    return (Join-Path $env:USERPROFILE '.config\ctc')
}

function Write-CtcLoginEnvJson {
    # Writes a ready-to-use env.json as if `ctc login` had already run (same
    # keys Invoke-CtcLogin itself writes), so launch/menu/dispatch/statusline
    # tests can skip the real login flow (no network, no cert store writes).
    param(
        $Sandbox,
        [string]$GhHost = 'example.ghe.com',
        [string]$Token = 'github_pat_TESTTOKEN1234',
        [string]$Proxy = 'http://ctc.local:8080',
        [switch]$WithFakeCert,
        [hashtable]$ExtraEnv = @{}
    )
    $cfg = Get-CtcTestConfigDir
    $iso = Join-Path $cfg 'home'
    New-Item -ItemType Directory -Path $iso -Force | Out-Null
    $certPath = Join-Path $cfg 'ca.pem'
    if ($WithFakeCert) {
        # Not a real cert -- only used so Test-Path/existence checks pass;
        # Test-CtcCertTrusted itself should be Mocked by callers that need the
        # "trusted" branch, since real cert-store lookups don't apply off-Windows.
        Set-Content -LiteralPath $certPath -Value '-----BEGIN CERTIFICATE-----FAKE-----END CERTIFICATE-----' -Encoding ascii
    }
    $envObj = [ordered]@{
        HOME                 = $iso
        USERPROFILE          = $iso
        XDG_CONFIG_HOME      = (Join-Path $iso '.config')
        XDG_STATE_HOME       = (Join-Path $iso '.local\state')
        XDG_CACHE_HOME       = (Join-Path $iso '.cache')
        GH_HOST              = $GhHost
        GITHUB_API_URL       = "https://$GhHost/api/v3"
        COPILOT_GITHUB_TOKEN = $Token
        HTTPS_PROXY          = $Proxy
        NODE_EXTRA_CA_CERTS  = $certPath
    }
    foreach ($k in $ExtraEnv.Keys) { $envObj[$k] = $ExtraEnv[$k] }
    New-Item -ItemType Directory -Path $cfg -Force | Out-Null
    ($envObj | ConvertTo-Json) | Set-Content -LiteralPath (Join-Path $cfg 'env.json') -Encoding UTF8
    [PSCustomObject]@{ ConfigDir = $cfg; IsoHome = $iso; CertPath = $certPath }
}
