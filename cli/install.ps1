#Requires -Version 5.1
<#
.SYNOPSIS
    CTC launcher installer for Windows. Usage (the website shows this one-liner):
      curl.exe -fsSLko "$env:TEMP\ctc-install.ps1" https://<ctc-host>/install.ps1
      powershell -NoProfile -File "$env:TEMP\ctc-install.ps1" [-Token <t>]

.DESCRIPTION
    Windows PowerShell 5.1-compatible port of cli/install.sh. Installs ctc.ps1
    + a ctc.cmd shim under %LOCALAPPDATA%\Programs\ctc, adds the shim's folder
    to the User PATH, bootstraps the GitHub Copilot CLI, and optionally runs
    `ctc login` non-interactively. Needs NO administrator rights: everything
    happens at the per-user (HKCU / %LOCALAPPDATA%) level.

    Internal functions never call `exit` directly; `exit` fires exactly once
    at the bottom, guarded so dot-sourcing (Pester) never kills the caller.
#>
param(
    [string]$Token
)

# ---------------------------------------------------------------------------
# Build-time defaults — same anchors as the top of ctc.ps1 (see
# files/ps-anchors.md for the agreed sed substitutions). Keep each line
# verbatim and occurring exactly once.
# ---------------------------------------------------------------------------
$CTC_HOST_DEFAULT = 'ctc.local'
$CTC_SCHEME_DEFAULT = 'https'

# Out-of-band exit-code channel for Invoke-CtcInstallMain and the bottom
# dispatch guard -- mirrors the identical pattern (and rationale) in ctc.ps1:
# `exit (Foo)` / `$x = Foo` capture a function's ENTIRE success-stream output
# (every Write-Output/[Console] write reachable through the pipeline *and*
# any native child-process stdout, such as `npm install`'s live progress)
# into one in-memory value instead of letting it reach the real console.
# Invoke-CtcInstallMain and Install-CtcCopilotCli are therefore always called
# as bare, unconsumed statements and report their result through this
# variable; `return` in those functions is used only for flow control.
$script:CtcInstallExitCode = 0

function Get-CtcEnvOrDefault {
    param([string]$Name, [string]$Default)
    $val = [Environment]::GetEnvironmentVariable($Name)
    if ([string]::IsNullOrEmpty($val)) { return $Default }
    return $val
}

function Assert-CtcInstallWindows {
    if ($env:CTC_ALLOW_NON_WINDOWS -eq '1') { return $true }
    if ($env:OS -eq 'Windows_NT') { return $true }
    [Console]::Error.WriteLine('ctc: Windows only for now. See TDD.md section 6.3 for the manual setup on other systems.')
    return $false
}

# ---------------------------------------------------------------------------
# ExecutionPolicy preflight. Nothing here elevates or bypasses anything: if
# the effective policy would block ctc.ps1/ctc.cmd from running, we print the
# ONE command the user themselves needs to run (as their own, unprivileged
# user) and stop — we never set it for them (that would itself need the kind
# of hidden, unattended policy change EDR tooling flags).
# ---------------------------------------------------------------------------

function Get-CtcEffectiveExecutionPolicy {
    try {
        return (Get-ExecutionPolicy).ToString()
    } catch {
        return 'Undefined'
    }
}

function Test-CtcExecutionPolicyOk {
    if ($env:CTC_SKIP_EXECPOLICY_CHECK -eq '1') { return $true }
    $effective = Get-CtcEffectiveExecutionPolicy
    if ($effective -in @('Restricted', 'AllSigned', 'Undefined')) {
        [Console]::Error.WriteLine("ctc: your PowerShell execution policy ($effective) blocks running local scripts.")
        [Console]::Error.WriteLine('Run this once, in your own (non-admin) PowerShell, then re-run this installer:')
        [Console]::Error.WriteLine('  Set-ExecutionPolicy -Scope CurrentUser RemoteSigned')
        return $false
    }
    return $true
}

# ---------------------------------------------------------------------------
# PATH patching — wrapped so Pester can Mock it and never touch the real
# per-user registry value during a test run.
# ---------------------------------------------------------------------------

function Add-CtcUserPath {
    param([string]$BinDir)
    # EnvironmentVariableTarget.User is Windows-only -- .NET throws
    # PlatformNotSupportedException for it on non-Windows. Guard on $env:OS
    # (not just try/catch) so the intent is clear, but keep the try/catch too
    # as a safety net for any other unexpected registry failure (e.g. a
    # locked-down HKCU hive) so a PATH-patch failure never aborts the install.
    if ($env:OS -eq 'Windows_NT') {
        try {
            $current = [Environment]::GetEnvironmentVariable('Path', 'User')
            $parts = @()
            if (-not [string]::IsNullOrEmpty($current)) { $parts = $current -split ';' }
            $already = $parts | Where-Object { $_.TrimEnd('\') -eq $BinDir.TrimEnd('\') }
            if (-not $already) {
                $new = if ([string]::IsNullOrEmpty($current)) { $BinDir } else { "$current;$BinDir" }
                [Environment]::SetEnvironmentVariable('Path', $new, 'User')
                [Console]::Out.WriteLine("Added $BinDir to your User PATH -- restart your shell, or run: `$env:Path = `"$BinDir;`$env:Path`"")
            }
        } catch {
            [Console]::Error.WriteLine("ctc: could not update your User PATH automatically. Add this folder to PATH yourself: $BinDir")
        }
    }
    # Also patch THIS session so a chained `ctc login` below can find ctc.cmd
    # without requiring a new shell.
    if (";$($env:Path);" -notlike "*;$BinDir;*") {
        $env:Path = "$BinDir;$env:Path"
    }
}

# ---------------------------------------------------------------------------
# Fetch ctc.ps1 — CTC_SRC env override: http(s) URL -> curl.exe, local path ->
# Copy-Item (mirrors install.sh). -k (insecure, skip cert check) is only
# meaningful for https; a plain http source has nothing to skip.
# ---------------------------------------------------------------------------

function Copy-CtcLauncherSource {
    param([string]$Src, [string]$Dest)
    if ($Src -match '^https://') {
        & curl.exe -fsSLk $Src -o $Dest
        return ($LASTEXITCODE -eq 0)
    } elseif ($Src -match '^http://') {
        & curl.exe -fsSL $Src -o $Dest
        return ($LASTEXITCODE -eq 0)
    } else {
        try {
            Copy-Item -LiteralPath $Src -Destination $Dest -Force
            return $true
        } catch {
            return $false
        }
    }
}

# ---------------------------------------------------------------------------
# Copilot CLI bootstrap — npm first, winget second. Wrapped per-step so tests
# can stub `npm`/`winget` on PATH exactly like the bash suite stubs them.
# ---------------------------------------------------------------------------

function Install-CtcCopilotCli {
    # Always `return`s bare (no value) and reports success/failure via
    # $script:CtcCopilotCliInstalled instead. Invoke-CtcInstallMain calls
    # this as a bare, unconsumed statement so `npm install`'s/`winget
    # install`'s own live stdout streams straight to the console -- any
    # `return <value>` here would surface as a stray printed line once
    # nothing captures it anymore (see the $script:CtcInstallExitCode
    # comment above for the full rationale). Pester tests should dot-source
    # and call this bare too, then assert on $script:CtcCopilotCliInstalled.
    if (Get-Command copilot -ErrorAction SilentlyContinue) {
        $path = (Get-Command copilot).Source
        [Console]::Out.WriteLine("Copilot CLI already installed ($path).")
        $script:CtcCopilotCliInstalled = $true
        return
    }
    [Console]::Out.WriteLine('GitHub Copilot CLI not found -- installing (npm install -g @github/copilot) ...')
    $installed = $false
    if (Get-Command npm -ErrorAction SilentlyContinue) {
        & npm install -g '@github/copilot'
        if ($LASTEXITCODE -eq 0) { $installed = $true } else { [Console]::Error.WriteLine('npm install -g @github/copilot failed.') }
    } elseif (Get-Command winget -ErrorAction SilentlyContinue) {
        [Console]::Out.WriteLine('npm not found -- trying winget install --id GitHub.Copilot -e ...')
        & winget install --id GitHub.Copilot -e
        if ($LASTEXITCODE -eq 0) { $installed = $true } else { [Console]::Error.WriteLine('winget install --id GitHub.Copilot -e failed.') }
    }
    if ($installed -and (Get-Command copilot -ErrorAction SilentlyContinue)) {
        [Console]::Out.WriteLine("Copilot CLI installed ($((Get-Command copilot).Source)).")
        $script:CtcCopilotCliInstalled = $true
        return
    }
    [Console]::Error.WriteLine('Could not install the GitHub Copilot CLI automatically.')
    [Console]::Error.WriteLine('Install Node (https://nodejs.org) then run: npm install -g @github/copilot')
    [Console]::Error.WriteLine('(or: winget install --id GitHub.Copilot -e)')
    [Console]::Error.WriteLine('ctc will not work until ''copilot'' is on your PATH.')
    $script:CtcCopilotCliInstalled = $false
    return
}

# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

function Invoke-CtcInstallMain {
    param([string]$Token)
    # NOTE: every branch below sets $script:CtcInstallExitCode and `return`s
    # bare (no value) -- this function is itself always invoked bare (by the
    # bottom dispatch guard) so that Install-CtcCopilotCli's nested native
    # `npm`/`winget` output streams live to the console; see the
    # $script:CtcInstallExitCode comment near the top of this file for why.

    if (-not (Assert-CtcInstallWindows)) { $script:CtcInstallExitCode = 1; return }
    if (-not (Test-CtcExecutionPolicyOk)) { $script:CtcInstallExitCode = 1; return }

    if (-not (Get-Command pwsh -ErrorAction SilentlyContinue)) {
        [Console]::Out.WriteLine('Note: pwsh (PowerShell 7) was not found. ctc works fine on Windows PowerShell 5.1,')
        [Console]::Out.WriteLine('  but installing pwsh is recommended for the fastest statusline rendering.')
    }

    $ctcHost = Get-CtcEnvOrDefault 'CTC_HOST' $CTC_HOST_DEFAULT
    $ctcScheme = Get-CtcEnvOrDefault 'CTC_SCHEME' $CTC_SCHEME_DEFAULT
    $src = Get-CtcEnvOrDefault 'CTC_SRC' "$ctcScheme`://$ctcHost/ctc.ps1"

    $localAppData = $env:LOCALAPPDATA
    if ([string]::IsNullOrEmpty($localAppData)) { $localAppData = Join-Path $env:USERPROFILE 'AppData\Local' }
    $root = Join-Path $localAppData 'Programs\ctc'
    $libDir = Join-Path $root 'lib'
    $binDir = Join-Path $root 'bin'
    New-Item -ItemType Directory -Path $libDir -Force | Out-Null
    New-Item -ItemType Directory -Path $binDir -Force | Out-Null

    $libPath = Join-Path $libDir 'ctc.ps1'
    [Console]::Out.WriteLine("Installing ctc to $libPath ...")
    if (-not (Copy-CtcLauncherSource -Src $src -Dest $libPath)) {
        [Console]::Error.WriteLine("ctc: failed to fetch ctc.ps1 from $src")
        $script:CtcInstallExitCode = 1
        return
    }

    $shimPath = Join-Path $binDir 'ctc.cmd'
    # @powershell (not pwsh) to keep the shim zero-dependency: Windows
    # PowerShell 5.1 ships on every supported Windows release. No policy
    # switch here at all -- the preflight above already confirmed the
    # effective CurrentUser execution policy allows local scripts to run.
    $shimContent = '@powershell -NoProfile -File "%~dp0..\lib\ctc.ps1" %*'
    Set-Content -LiteralPath $shimPath -Value $shimContent -Encoding ascii -NoNewline

    Add-CtcUserPath -BinDir $binDir
    [Console]::Out.WriteLine([char]0x2713 + ' Installed.')

    Install-CtcCopilotCli

    if (-not [string]::IsNullOrEmpty($Token)) {
        & $libPath login -Token $Token
        $script:CtcInstallExitCode = $LASTEXITCODE
        return
    } else {
        [Console]::Out.WriteLine('Next: ctc login')
    }
    $script:CtcInstallExitCode = 0
    return
}

if ($MyInvocation.InvocationName -ne '.') {
    # Bare call (no parens/assignment/pipe): see the $script:CtcInstallExitCode
    # comment near the top of this file for why -- this is the real entry
    # point for every actual install.ps1 invocation.
    Invoke-CtcInstallMain -Token $Token
    exit $script:CtcInstallExitCode
}
