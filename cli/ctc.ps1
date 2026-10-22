#Requires -Version 5.1
<#
.SYNOPSIS
    CTC — launch GitHub Copilot CLI or Claude Code through the CTC credit proxy.

.DESCRIPTION
    Windows PowerShell 5.1-compatible port of cli/ctc (bash/macOS). Mirrors its
    behaviour exactly: same config layout (translated to Windows paths), same
    env-var names, same commands, same exit codes, same banner/usage text.

    Internal functions never call `exit` directly — they return an int exit
    code instead — so this file is safe to dot-source for unit testing (Pester
    can call Invoke-Ctc* functions directly without killing the test runner).
    `exit` is called exactly once, at the very bottom, guarded so it only fires
    when the file is run directly (not dot-sourced) — the PowerShell analogue
    of bash's `if [ "${BASH_SOURCE[0]:-$0}" = "${0}" ]; then main "$@"; fi`.
#>

# Force TLS 1.2 for Invoke-WebRequest/Invoke-RestMethod — Windows PowerShell
# 5.1's default SecurityProtocol can be SSL3/TLS1.0 depending on OS defaults.
try { [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12 } catch { }

# Capture this file's own path once, at script scope, so it is available to
# every function regardless of dot-source vs direct invocation, and so the
# update-check can compare the *served* launcher against *this exact file*.
$script:CtcSelfPath = $PSCommandPath

# Out-of-band exit-code channel for Invoke-CtcMain/Invoke-CtcMenu/the bottom
# dispatch guard -- see the long comment above those functions for why this
# exists: PowerShell's `exit (Foo)` / `return (Foo)` / `$x = Foo` all capture
# a function's ENTIRE success-stream output (every Write-Output call plus any
# native child-process stdout, not just its final `return` value) into one
# in-memory collection instead of letting it reach the real console. That
# silently swallows the live, interactive output of `& copilot`/`& claude` --
# the whole point of this launcher -- if any of those forms wrap a call chain
# that reaches them. The fix: Invoke-CtcMain/Invoke-CtcMenu/Invoke-CtcCopilot/
# Invoke-CtcClaude call each other as bare, unconsumed statements (so native
# passthrough streams live) and report their result through this variable
# instead of a captured return value; `return` in those functions is used
# only for flow control and never carries a value.
# SPIKE: this capture-vs-passthrough behavior was validated on pwsh 7 (PS
# Core, ConsoleHost) on macOS via stub executables and a pty harness. Re-run
# the equivalent smoke test on real Windows PowerShell 5.1 (powershell.exe's
# ConsoleHost) and pwsh 7 on Windows before shipping -- the pipeline-capture
# semantics are documented PowerShell language behavior (not host-specific),
# but the interactive-console plumbing for a native child process's
# stdout/stdin/stderr inheritance has historically had host-specific quirks
# (e.g. legacy console vs Windows Terminal, ConPTY availability).
$script:CtcExitCode = 0

# ---------------------------------------------------------------------------
# Build-time defaults. Each of the six lines below is a unique, single-line,
# sed-able anchor (web/Dockerfile rewrites them per deployment). Keep each one
# verbatim and occurring exactly once — see files/ps-anchors.md for the agreed
# sed substitutions. Env vars (CTC_HOST, CTC_SCHEME, ...) override at runtime.
# ---------------------------------------------------------------------------
$CTC_HOST_DEFAULT = 'ctc.local'
$CTC_SCHEME_DEFAULT = 'https'
$CTC_PROXY_HOST_DEFAULT = ''          # empty -> falls back to host
$CTC_PROXY_PORT_DEFAULT = '8080'
$GHE_DOMAIN_DEFAULT = 'example.ghe.com'
$CTC_NO_PROXY_DEFAULT = ''

# ---------------------------------------------------------------------------
# Settings resolution — recomputed on every call (never cached at script
# scope) because Pester dot-sources this file ONCE and calls functions
# repeatedly with different $env: values across tests, unlike bash which
# re-execs the whole script fresh on every invocation.
# ---------------------------------------------------------------------------

function Get-CtcEnvOrDefault {
    # Mirrors bash's "${VAR:-default}": empty-or-unset env value -> default.
    param([string]$Name, [string]$Default)
    $val = [Environment]::GetEnvironmentVariable($Name)
    if ([string]::IsNullOrEmpty($val)) { return $Default }
    return $val
}

function Get-CtcSettings {
    $ctcHost = Get-CtcEnvOrDefault 'CTC_HOST' $CTC_HOST_DEFAULT
    $ctcScheme = Get-CtcEnvOrDefault 'CTC_SCHEME' $CTC_SCHEME_DEFAULT
    $proxyHostDefault = if ([string]::IsNullOrEmpty($CTC_PROXY_HOST_DEFAULT)) { $ctcHost } else { $CTC_PROXY_HOST_DEFAULT }
    $proxyHostVal = Get-CtcEnvOrDefault 'CTC_PROXY_HOST' $proxyHostDefault
    $proxyPort = Get-CtcEnvOrDefault 'CTC_PROXY_PORT' $CTC_PROXY_PORT_DEFAULT
    $gheDomain = Get-CtcEnvOrDefault 'GHE_DOMAIN' $GHE_DOMAIN_DEFAULT
    $noProxy = Get-CtcEnvOrDefault 'CTC_NO_PROXY' $CTC_NO_PROXY_DEFAULT
    [PSCustomObject]@{
        CtcHost    = $ctcHost
        CtcScheme  = $ctcScheme
        ProxyHost  = $proxyHostVal
        ProxyPort  = $proxyPort
        GheDomain  = $gheDomain
        NoProxy    = $noProxy
    }
}

function Get-CtcConfigDir {
    # ${XDG_CONFIG_HOME:-$HOME/.config}/ctc in bash -> %APPDATA%\ctc on Windows.
    # CTC_CONFIG_DIR overrides for tests.
    if (-not [string]::IsNullOrEmpty($env:CTC_CONFIG_DIR)) { return $env:CTC_CONFIG_DIR }
    if (-not [string]::IsNullOrEmpty($env:XDG_CONFIG_HOME)) { return (Join-Path $env:XDG_CONFIG_HOME 'ctc') }
    if (-not [string]::IsNullOrEmpty($env:APPDATA)) { return (Join-Path $env:APPDATA 'ctc') }
    return (Join-Path $env:USERPROFILE '.config\ctc')
}

function Assert-CtcWindows {
    if ($env:CTC_ALLOW_NON_WINDOWS -eq '1') { return $true }
    if ($env:OS -eq 'Windows_NT') { return $true }
    [Console]::Error.WriteLine('ctc: Windows only for now. See TDD.md section 6.3 for the manual setup on other systems.')
    return $false
}

# Append CTC_NO_PROXY to any NO_PROXY the user already has. Done at launch, not
# baked into the login env, so a changed list applies without re-running login.
# Both spellings: curl and Go read no_proxy, others read NO_PROXY.
function Set-CtcNoProxyEnv {
    param([string]$CtcNoProxy)
    if ([string]::IsNullOrEmpty($CtcNoProxy)) { return }
    $cur = $env:NO_PROXY
    if ([string]::IsNullOrEmpty($cur)) { $cur = $env:no_proxy }
    $merged = if ([string]::IsNullOrEmpty($cur)) { $CtcNoProxy } else { "$cur,$CtcNoProxy" }
    $env:NO_PROXY = $merged
    $env:no_proxy = $merged
}

function Get-CtcNormalizedText {
    # Reads a file as UTF-8, strips a leading BOM, and normalizes CRLF -> LF,
    # so the update-check compares the served launcher against this file
    # content-for-content regardless of which line endings either carries.
    param([string]$Path)
    $bytes = [IO.File]::ReadAllBytes($Path)
    if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
        $bytes = $bytes[3..($bytes.Length - 1)]
    }
    $text = [Text.Encoding]::UTF8.GetString($bytes)
    return $text -replace "`r`n", "`n"
}

# ---------------------------------------------------------------------------
# Lightweight background-work helper: runs a scriptblock on a runspace INSIDE
# this process (no extra/hidden process). Threads die with the process; that
# is an accepted trade-off vs bash's truly-detached background job (see
# README notes in the final report) — real interactive sessions outlast the
# bounded fetch/poll intervals used here in the overwhelming common case.
# ---------------------------------------------------------------------------

function Start-CtcRunspace {
    param(
        [Parameter(Mandatory)][scriptblock]$ScriptBlock,
        [object[]]$ArgumentList = @()
    )
    $ps = [powershell]::Create()
    [void]$ps.AddScript($ScriptBlock)
    foreach ($a in $ArgumentList) { [void]$ps.AddArgument($a) }
    $handle = $ps.BeginInvoke()
    [PSCustomObject]@{ PS = $ps; Handle = $handle }
}

function Wait-CtcRunspace {
    param($Runspace, [int]$TimeoutMs = 3000)
    if (-not $Runspace) { return }
    try {
        $null = $Runspace.Handle.AsyncWaitHandle.WaitOne($TimeoutMs)
        if ($Runspace.Handle.IsCompleted) { $null = $Runspace.PS.EndInvoke($Runspace.Handle) }
    } catch {
    } finally {
        try { $Runspace.PS.Dispose() } catch { }
    }
}

function Stop-CtcRunspace {
    param($Runspace)
    if (-not $Runspace) { return }
    try { $Runspace.PS.Stop() } catch { }
    try { $Runspace.PS.Dispose() } catch { }
}

# ---------------------------------------------------------------------------
# Update check — warns when this launcher differs from the one the server
# ships. The compare runs in the BACKGROUND at most once a day and only
# records a verdict; the warning shown on THIS launch comes from the PREVIOUS
# verdict, so a launch never waits on the web host. Called before the login
# env is applied (uses the launcher's own resolved host/scheme, matching
# bash). CTC_UPDATE_CHECK=0 disables it.
# ---------------------------------------------------------------------------

function Invoke-CtcCheckLauncherUpdate {
    param($Settings, [string]$ConfigDir)
    if ($env:CTC_UPDATE_CHECK -eq '0') { return $null }
    $state = Join-Path $ConfigDir 'launcher-check'
    if (Test-Path -LiteralPath $state) {
        $lines = @(Get-Content -LiteralPath $state -ErrorAction SilentlyContinue)
        if ($lines.Count -ge 2 -and $lines[1] -eq 'stale') {
            [Console]::Error.WriteLine('ctc: this launcher is out of date (the server has a different one). Update with:')
            [Console]::Error.WriteLine("  curl.exe -fsSLko `"`$env:TEMP\ctc-install.ps1`" $($Settings.CtcScheme)://$($Settings.CtcHost)/install.ps1")
            [Console]::Error.WriteLine('  powershell -NoProfile -File "$env:TEMP\ctc-install.ps1"')
        }
    } else {
        $lines = @()
    }
    $last = 0
    if ($lines.Count -ge 1) { [void][int64]::TryParse($lines[0], [ref]$last) }
    $now = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    if (($now - $last) -lt 86400) { return $null }
    if (-not (Get-Command curl.exe -ErrorAction SilentlyContinue)) { return $null }

    $fetchScript = {
        param($Scheme, $HostName, $StatePath, $SelfPath)
        $tmp = $null
        try {
            $tmp = [IO.Path]::GetTempFileName()
            $url = "$Scheme`://$HostName/ctc.ps1"
            & curl.exe -fsSLk --max-time 10 $url -o $tmp 2>$null
            if ($LASTEXITCODE -ne 0) { return }
            if (-not (Test-Path -LiteralPath $tmp)) { return }
            if ((Get-Item -LiteralPath $tmp).Length -eq 0) { return }

            function Get-NormalizedText2 {
                param([string]$Path)
                $bytes = [IO.File]::ReadAllBytes($Path)
                if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
                    $bytes = $bytes[3..($bytes.Length - 1)]
                }
                ([Text.Encoding]::UTF8.GetString($bytes)) -replace "`r`n", "`n"
            }

            $fetched = Get-NormalizedText2 -Path $tmp
            $self = Get-NormalizedText2 -Path $SelfPath
            $verdict = if ($fetched -eq $self) { 'ok' } else { 'stale' }

            $dir = Split-Path -Parent $StatePath
            if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
            $nowEpoch = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
            $tmpState = "$StatePath.tmp"
            Set-Content -LiteralPath $tmpState -Value "$nowEpoch`n$verdict" -NoNewline -Encoding ascii
            Move-Item -LiteralPath $tmpState -Destination $StatePath -Force
        } catch {
        } finally {
            if ($tmp) { Remove-Item -LiteralPath $tmp -ErrorAction SilentlyContinue }
        }
    }
    Start-CtcRunspace -ScriptBlock $fetchScript -ArgumentList @($Settings.CtcScheme, $Settings.CtcHost, $state, $script:CtcSelfPath)
}

function Show-CtcUsage {
    param([System.IO.TextWriter]$Writer = [Console]::Out)
    $lines = @(
        'CTC - launch GitHub Copilot CLI through the CTC credit proxy.'
        ''
        'Usage:'
        '  ctc            Pick an agent (Copilot or Claude Code) via a menu, then launch it'
        '                 (in a non-interactive shell, launches Copilot directly)'
        '  ctc copilot    Launch Copilot through CTC directly (all flags pass through)'
        '  ctc claude     Launch native Claude Code on the Copilot backend through CTC'
        '  ctc login      Authenticate, trust the CA cert, cache config'
        '  ctc status     Show whether CTC is set up'
        '  ctc logout     Remove cached CTC config'
        '  ctc --help     Show this help'
    )
    foreach ($l in $lines) { $Writer.WriteLine($l) }
}

# ---------------------------------------------------------------------------
# Cert / trust helpers — each wrapped in its own small function so Pester can
# Mock it without ever touching the real Cert: provider (unavailable on
# non-Windows, and we never want tests to actually mutate a cert store).
# ---------------------------------------------------------------------------

function ConvertFrom-CtcSecureString {
    param([Security.SecureString]$Secure)
    if (-not $Secure) { return '' }
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
}

function Get-CtcCertFingerprint {
    param([string]$Path)
    try {
        $bytes = [IO.File]::ReadAllBytes($Path)
        $cert = New-Object Security.Cryptography.X509Certificates.X509Certificate2(,$bytes)
        $hash = $cert.GetCertHash([Security.Cryptography.HashAlgorithmName]::SHA256)
        return (($hash | ForEach-Object { $_.ToString('X2') }) -join ':')
    } catch {
        return $null
    }
}

function Get-CtcCertThumbprint {
    param([string]$Path)
    try {
        return (New-Object Security.Cryptography.X509Certificates.X509Certificate2($Path)).Thumbprint
    } catch {
        return $null
    }
}

function Test-CtcElevated {
    if ($env:CTC_TEST_ELEVATED -eq '1') { return $true }
    if ($env:CTC_TEST_ELEVATED -eq '0') { return $false }
    try {
        $id = [Security.Principal.WindowsIdentity]::GetCurrent()
        $p = New-Object Security.Principal.WindowsPrincipal($id)
        return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    } catch {
        return $false
    }
}

function Add-CtcCurrentUserTrust {
    # SPIKE: verify on real Windows that Copilot's bundled Node actually
    # consults CurrentUser\Root (not only LocalMachine\Root) for outbound TLS
    # to the CTC proxy. If it does not, `ctc login -Machine` from an elevated
    # shell is the only path that works.
    param([string]$Path)
    try {
        $cert = New-Object Security.Cryptography.X509Certificates.X509Certificate2($Path)
        $store = New-Object Security.Cryptography.X509Certificates.X509Store('Root', 'CurrentUser')
        $store.Open([Security.Cryptography.X509Certificates.OpenFlags]::ReadWrite)
        try { $store.Add($cert) } finally { $store.Close() }
        return $true
    } catch {
        return $false
    }
}

function Import-CtcMachineTrust {
    param([string]$Path)
    try {
        Import-Certificate -FilePath $Path -CertStoreLocation 'Cert:\LocalMachine\Root' | Out-Null
        return $true
    } catch {
        return $false
    }
}

function Test-CtcCertTrusted {
    param([string]$CertPath)
    try {
        $thumb = Get-CtcCertThumbprint -Path $CertPath
        if (-not $thumb) { return $false }
        foreach ($loc in 'Cert:\CurrentUser\Root', 'Cert:\LocalMachine\Root') {
            $hit = Get-ChildItem -Path $loc -ErrorAction SilentlyContinue | Where-Object { $_.Thumbprint -eq $thumb }
            if ($hit) { return $true }
        }
        return $false
    } catch {
        return $false
    }
}

function Protect-CtcFileAcl {
    # Best-effort ACL restriction to the current user, mirroring bash's
    # `umask 077`. Skipped on non-Windows (the Pester test sandbox).
    param([string]$Path)
    if ($env:OS -ne 'Windows_NT') { return }
    try {
        $acl = Get-Acl -LiteralPath $Path
        $acl.SetAccessRuleProtection($true, $false)
        $user = [Security.Principal.WindowsIdentity]::GetCurrent().User
        $rule = New-Object Security.AccessControl.FileSystemAccessRule($user, 'FullControl', 'Allow')
        $acl.AddAccessRule($rule)
        Set-Acl -LiteralPath $Path -AclObject $acl
    } catch {
    }
}

# ---------------------------------------------------------------------------
# ctc login
# ---------------------------------------------------------------------------

function Invoke-CtcLogin {
    param([string[]]$CtcArgs = @())
    if (-not (Assert-CtcWindows)) { return 1 }

    $token = $null
    $machine = $false
    for ($i = 0; $i -lt $CtcArgs.Count; $i++) {
        if ($CtcArgs[$i] -eq '-Token') {
            if ($i + 1 -lt $CtcArgs.Count) { $token = $CtcArgs[$i + 1]; $i++ } else { $token = '' }
        } elseif ($CtcArgs[$i] -eq '-Machine') {
            $machine = $true
        }
    }

    $settings = Get-CtcSettings
    $cfg = Get-CtcConfigDir
    $cert = Join-Path $cfg 'ca.pem'
    $envPath = Join-Path $cfg 'env.json'
    $iso = Join-Path $cfg 'home'

    if ($null -eq $token) {
        $secure = Read-Host -Prompt 'Paste your CTC token (from the dashboard "Set up CLI" panel)' -AsSecureString
        $token = ConvertFrom-CtcSecureString -Secure $secure
    }
    if ([string]::IsNullOrEmpty($token)) {
        [Console]::Error.WriteLine('ctc: No token entered -- aborting.')
        return 1
    }

    New-Item -ItemType Directory -Path $cfg -Force | Out-Null
    New-Item -ItemType Directory -Path $iso -Force | Out-Null

    $caUrl = "$($settings.CtcScheme)://$($settings.CtcHost)/ctc-ca.pem"
    [Console]::Error.WriteLine("Downloading CA cert from $caUrl ...")
    & curl.exe -fsSLk $caUrl -o $cert
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $cert)) {
        [Console]::Error.WriteLine("ctc: failed to download CA cert from $caUrl")
        return 1
    }

    $fp = Get-CtcCertFingerprint -Path $cert
    if ($fp) {
        [Console]::Error.WriteLine("CA fingerprint (SHA-256): $fp")
        [Console]::Error.WriteLine('Verify this matches the fingerprint on the dashboard before trusting.')
    }

    if ($machine) {
        if (-not (Test-CtcElevated)) {
            [Console]::Error.WriteLine('ctc: -Machine needs an elevated PowerShell. Open PowerShell as Administrator and run:')
            [Console]::Error.WriteLine("  Import-Certificate -FilePath `"$cert`" -CertStoreLocation Cert:\LocalMachine\Root")
            return 1
        }
        [Console]::Error.WriteLine('Trusting the CA cert in the Machine store (Cert:\LocalMachine\Root) ...')
        if (-not (Import-CtcMachineTrust -Path $cert)) {
            [Console]::Error.WriteLine('ctc: cert trust failed. To do it manually, run:')
            [Console]::Error.WriteLine("  Import-Certificate -FilePath `"$cert`" -CertStoreLocation Cert:\LocalMachine\Root")
            return 1
        }
    } else {
        # SPIKE: on real Windows, adding to CurrentUser\Root via X509Store.Add()
        # may trigger a native "Do you want to trust this certificate" dialog
        # that requires user interaction. Verify this is acceptable UX (bash's
        # `security add-trusted-cert` also prompts, via sudo, so this mirrors
        # the one-time-confirmation spirit of the macOS flow).
        [Console]::Error.WriteLine('Trusting the CA cert for your Windows user (Cert:\CurrentUser\Root). A confirmation dialog may appear.')
        if (-not (Add-CtcCurrentUserTrust -Path $cert)) {
            [Console]::Error.WriteLine('ctc: cert trust failed. To do it manually, run:')
            [Console]::Error.WriteLine("  Import-Certificate -FilePath `"$cert`" -CertStoreLocation Cert:\CurrentUser\Root")
            return 1
        }
    }

    $envObj = [ordered]@{
        HOME                 = $iso
        USERPROFILE          = $iso
        XDG_CONFIG_HOME      = (Join-Path $iso '.config')
        XDG_STATE_HOME       = (Join-Path $iso '.local\state')
        XDG_CACHE_HOME       = (Join-Path $iso '.cache')
        GH_HOST              = $settings.GheDomain
        GITHUB_API_URL       = "https://$($settings.GheDomain)/api/v3"
        COPILOT_GITHUB_TOKEN = $token
        HTTPS_PROXY          = "http://$($settings.ProxyHost):$($settings.ProxyPort)"
        NODE_EXTRA_CA_CERTS  = $cert
    }
    ($envObj | ConvertTo-Json) | Set-Content -LiteralPath $envPath -Encoding UTF8
    Protect-CtcFileAcl -Path $envPath

    [Console]::Error.WriteLine([char]0x2713 + ' CTC ready. Launch with: ctc')
    return 0
}

# ---------------------------------------------------------------------------
# ctc status / ctc logout
# ---------------------------------------------------------------------------

function Invoke-CtcStatus {
    # NOTE: uses [Console]::Out.WriteLine, not Write-Output -- this function's
    # result flows through `exit (Invoke-CtcMain ...)` at the bottom of this
    # file, and PowerShell's `exit (expr)` (like a plain variable assignment)
    # captures the ENTIRE success-stream output of `expr`, including every
    # Write-Output call made anywhere in the call chain, not just the final
    # `return` value. Write-Output here would be silently swallowed instead of
    # reaching the user's terminal. [Console]::Out writes straight to the OS
    # stdout handle, bypassing that pipeline capture entirely.
    $cfg = Get-CtcConfigDir
    $envPath = Join-Path $cfg 'env.json'
    if (-not (Test-Path -LiteralPath $envPath)) {
        [Console]::Out.WriteLine("CTC: Not set up. Run 'ctc login'.")
        return 0
    }
    $envData = Get-Content -Raw -LiteralPath $envPath | ConvertFrom-Json
    [Console]::Out.WriteLine('CTC: Set up ' + [char]0x2713)
    $proxy = [string]$envData.HTTPS_PROXY -replace '^https?://', ''
    [Console]::Out.WriteLine("  proxy: $proxy")
    $tok = [string]$envData.COPILOT_GITHUB_TOKEN
    $tail = if ($tok.Length -ge 4) { $tok.Substring($tok.Length - 4) } else { $tok }
    [Console]::Out.WriteLine('  token: ' + [char]0x2026 + $tail)
    $certPath = Join-Path $cfg 'ca.pem'
    if ((Test-Path -LiteralPath $certPath) -and (Test-CtcCertTrusted -CertPath $certPath)) {
        [Console]::Out.WriteLine('  cert:  trusted')
    } else {
        [Console]::Out.WriteLine("  cert:  NOT trusted -- re-run 'ctc login'")
    }
    return 0
}

function Invoke-CtcLogout {
    # See the NOTE in Invoke-CtcStatus above: [Console]::Out, not Write-Output.
    $cfg = Get-CtcConfigDir
    Remove-Item -LiteralPath (Join-Path $cfg 'env.json') -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath (Join-Path $cfg 'home') -Recurse -Force -ErrorAction SilentlyContinue
    [Console]::Out.WriteLine("CTC config removed. Your normal 'copilot' is unaffected.")
    [Console]::Out.WriteLine('To also untrust the CA cert, run (PowerShell, matching the store used at login):')
    [Console]::Out.WriteLine('  Get-ChildItem Cert:\CurrentUser\Root | Where-Object Subject -Match "copilot-proxy-ca" | Remove-Item')
    return 0
}

# ---------------------------------------------------------------------------
# /ide bridge — a directory junction from the isolated HOME's .copilot\ide to
# the real one, so Copilot's `/ide` command can see the running VS Code
# workspace registry without sharing the rest of .copilot (token, session,
# config stay isolated). Junction creation requires no admin rights on
# Windows. On non-Windows (test mode) falls back to a symlink, since the
# Junction item type does not exist outside Windows.
# ---------------------------------------------------------------------------

function New-CtcIdeBridge {
    param([string]$RealHome, [string]$IsoHome)
    if ([string]::IsNullOrEmpty($RealHome) -or [string]::IsNullOrEmpty($IsoHome)) { return }
    if ($RealHome -eq $IsoHome) { return }
    $disc = '.copilot\ide'
    $realIde = Join-Path $RealHome $disc
    if (-not (Test-Path -LiteralPath $realIde -PathType Container)) { return }

    $isoCopilot = Join-Path $IsoHome '.copilot'
    New-Item -ItemType Directory -Path $isoCopilot -Force | Out-Null
    $isoIde = Join-Path $IsoHome $disc

    $needsReplace = $true
    $existing = Get-Item -LiteralPath $isoIde -Force -ErrorAction SilentlyContinue
    if ($existing -and ($existing.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        # Already a link/junction — replace only if it points somewhere else
        # (covers a prior run's stale link as well as a stale EMPTY isolated
        # dir left behind by Copilot itself).
        try {
            $target = (Get-Item -LiteralPath $isoIde).Target
            if ($target -and ($target -join '') -like "*$([regex]::Escape($realIde))*") { $needsReplace = $false }
        } catch { }
    }
    if ($needsReplace) {
        if (Test-Path -LiteralPath $isoIde) {
            Remove-Item -LiteralPath $isoIde -Recurse -Force -ErrorAction SilentlyContinue
        }
        # SPIKE: verify on real Windows that a Directory Junction (no admin
        # required) is sufficient for Copilot's /ide discovery to resolve the
        # bridged path; some file watchers do not follow junctions the same
        # way they follow symlinks.
        if ($env:OS -eq 'Windows_NT') {
            New-Item -ItemType Junction -Path $isoIde -Target $realIde -ErrorAction SilentlyContinue | Out-Null
        } else {
            New-Item -ItemType SymbolicLink -Path $isoIde -Target $realIde -ErrorAction SilentlyContinue | Out-Null
        }
    }
}

# ---------------------------------------------------------------------------
# ctc copilot
# ---------------------------------------------------------------------------

function Set-CtcIsolationEnv {
    # Applies the cached login env (HOME/XDG_*/GH_HOST/token/proxy/CA path) to
    # THIS process's environment, which the child (copilot/claude) inherits.
    param([string]$EnvPath)
    $envData = Get-Content -Raw -LiteralPath $EnvPath | ConvertFrom-Json
    foreach ($p in $envData.PSObject.Properties) {
        Set-Item -Path "Env:$($p.Name)" -Value ([string]$p.Value)
    }
}

function Invoke-CtcCopilot {
    param([string[]]$CtcArgs = @())
    if (-not (Assert-CtcWindows)) { $script:CtcExitCode = 1; return }
    $cfg = Get-CtcConfigDir
    $envPath = Join-Path $cfg 'env.json'
    if (-not (Test-Path -LiteralPath $envPath)) {
        [Console]::Error.WriteLine("ctc: not set up yet. Run 'ctc login' first.")
        $script:CtcExitCode = 1
        return
    }
    $settings = Get-CtcSettings
    $updateJob = Invoke-CtcCheckLauncherUpdate -Settings $settings -ConfigDir $cfg

    $realHome = $env:USERPROFILE
    Set-CtcIsolationEnv -EnvPath $envPath
    Set-CtcNoProxyEnv -CtcNoProxy $settings.NoProxy
    New-CtcIdeBridge -RealHome $realHome -IsoHome $env:USERPROFILE

    if (-not (Get-Command copilot -ErrorAction SilentlyContinue)) {
        [Console]::Error.WriteLine("ctc: 'copilot' (GitHub Copilot CLI) not found on PATH.")
        [Console]::Error.WriteLine('  Install it with: npm install -g @github/copilot')
        [Console]::Error.WriteLine('  (or re-run the CTC installer)')
        Wait-CtcRunspace -Runspace $updateJob -TimeoutMs 1500
        $script:CtcExitCode = 1
        return
    }

    try { $Host.UI.RawUI.WindowTitle = 'CTC ' + [char]0x25C6 + ' copilot' } catch { }
    [Console]::Error.WriteLine([char]0x25C6 + " CTC mode -- credits via the donation pool (your normal 'copilot' is untouched)")
    & copilot @CtcArgs
    $code = $LASTEXITCODE
    Wait-CtcRunspace -Runspace $updateJob -TimeoutMs 1500
    $script:CtcExitCode = $code
    return
}

# ---------------------------------------------------------------------------
# Price refresh + ledger poll — background runspaces started by ctc claude.
# ---------------------------------------------------------------------------

function Start-CtcPriceRefreshRunspace {
    param([string]$IsoHome, [string]$GheDomain, [string]$Token, [string]$ProxyUrl)
    $script = {
        param($HomeDir, $GheDomain, $Token, $ProxyUrl)
        try {
            [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
            $out = Join-Path $HomeDir '.claude\prices.json'
            $ttl = 86400
            $fresh = $false
            if (Test-Path -LiteralPath $out) {
                try {
                    $existing = Get-Content -Raw -LiteralPath $out | ConvertFrom-Json
                    $fetchedAt = [double]($existing.fetched)
                    if (([DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - $fetchedAt) -lt $ttl) { $fresh = $true }
                } catch { }
            }
            if ($fresh) { return }

            $url = "https://copilot-api.$GheDomain/models"
            $headers = @{
                authorization          = "Bearer $Token"
                accept                 = 'application/json'
                'copilot-integration-id' = 'copilot-developer-cli'
                'editor-version'       = 'copilot/1.0.63'
                'user-agent'           = 'copilot/1.0.63 (win32 v10.0.0) term/vscode'
                'x-github-api-version' = '2026-06-01'
                'openai-intent'        = 'conversation-agent'
                'x-interaction-id'     = [guid]::NewGuid().ToString()
                'x-initiator'          = 'user'
            }
            $irmArgs = @{ Uri = $url; Headers = $headers; TimeoutSec = 20; ErrorAction = 'Stop' }
            if (-not [string]::IsNullOrEmpty($ProxyUrl)) { $irmArgs['Proxy'] = $ProxyUrl }
            $resp = Invoke-RestMethod @irmArgs

            $keys = @('input_price', 'output_price', 'cache_price', 'cache_write_price')
            $prices = @{}
            foreach ($m in @($resp.data)) {
                $tp = $null
                try { $tp = $m.billing.token_prices.default } catch { }
                if ($tp) {
                    $anyNonZero = $false
                    foreach ($k in $keys) { if ($tp.$k) { $anyNonZero = $true } }
                    if ($anyNonZero) {
                        $vals = @()
                        foreach ($k in $keys) { $v = 0; if ($tp.$k) { $v = [int]$tp.$k }; $vals += $v }
                        $prices[[string]$m.id] = $vals
                    }
                }
            }
            if ($prices.Count -eq 0) { return }   # never overwrite a good cache with nothing

            $dir = Split-Path -Parent $out
            if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
            $payload = @{ fetched = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds(); source = $url; prices = $prices } | ConvertTo-Json -Depth 5
            $tmp = "$out.tmp"
            Set-Content -LiteralPath $tmp -Value $payload -Encoding UTF8 -NoNewline
            Move-Item -LiteralPath $tmp -Destination $out -Force
        } catch {
        }
    }
    Start-CtcRunspace -ScriptBlock $script -ArgumentList @($IsoHome, $GheDomain, $Token, $ProxyUrl)
}

function Start-CtcLedgerPollRunspace {
    param([string]$IsoHome, $Settings, [string]$Tag, [string]$Token)
    $dir = Join-Path $IsoHome '.claude\ledger'
    New-Item -ItemType Directory -Path $dir -Force -ErrorAction SilentlyContinue | Out-Null
    $stop = [hashtable]::Synchronized(@{ Stop = $false })
    $script = {
        param($Scheme, $HostName, $Tag, $Token, $Out, $Stop)
        try {
            [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
            $url = "$Scheme`://$HostName/api/usage?tag=$Tag"
            # Real system/user proxy settings apply (WinINET defaults); we
            # deliberately do NOT pass -Proxy here, mirroring bash's
            # `--noproxy '*'` — the dashboard/control-plane host must be
            # reached directly, not through the CTC credit proxy.
            while (-not $Stop.Stop) {
                try {
                    $resp = Invoke-WebRequest -Uri $url -Headers @{ Authorization = "Bearer $Token" } -TimeoutSec 8 -UseBasicParsing -ErrorAction Stop
                    $tmp = "$Out.tmp"
                    Set-Content -LiteralPath $tmp -Value $resp.Content -Encoding UTF8 -NoNewline
                    Move-Item -LiteralPath $tmp -Destination $Out -Force
                } catch {
                }
                $waited = 0
                while ($waited -lt 10000 -and -not $Stop.Stop) {
                    Start-Sleep -Milliseconds 500
                    $waited += 500
                }
            }
        } catch {
        } finally {
            Remove-Item -LiteralPath $Out -Force -ErrorAction SilentlyContinue
            Remove-Item -LiteralPath "$Out.tmp" -Force -ErrorAction SilentlyContinue
        }
    }
    $out = Join-Path $dir "$Tag.json"
    $rs = Start-CtcRunspace -ScriptBlock $script -ArgumentList @($Settings.CtcScheme, $Settings.CtcHost, $Tag, $Token, $out, $stop)
    [PSCustomObject]@{ Runspace = $rs; Stop = $stop; OutPath = $out }
}

function Stop-CtcLedgerPoll {
    param($Poller)
    if (-not $Poller) { return }
    $Poller.Stop.Stop = $true
    Wait-CtcRunspace -Runspace $Poller.Runspace -TimeoutMs 2000
    Remove-Item -LiteralPath $Poller.OutPath -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath "$($Poller.OutPath).tmp" -Force -ErrorAction SilentlyContinue
}

# ---------------------------------------------------------------------------
# ctc claude
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# ctc claude -- statusline
# ---------------------------------------------------------------------------

# Faithful PowerShell port of the Python statusline embedded in cli/ctc
# (_install_claude_statusline / the PYEOF heredoc therein). Kept as a single
# source-of-truth string here; PriceParity.Tests.ps1 asserts the PRICES table
# below stays in sync with cli/ctc's embedded Python table.
$script:CtcStatuslineSource = @'
#requires -Version 5.1
# CTC statusline (Windows) - session cost in Copilot's own billing unit (AIU).
#
# Faithful PowerShell port of the Python statusline embedded in cli/ctc
# (_install_claude_statusline). Claude Code pipes its statusline JSON on
# stdin; we tally this session's token usage from the transcript and price it
# with Copilot's per-model billing.token_prices (nano-AIU per token) as
# returned by GET /models on copilot-api.<GHE_DOMAIN>.
#
# That tally is only a projection. The authoritative charge is what the proxy
# booked in its ledger (consumption_events.credits, nano-AIU). `ctc claude`
# tags every request with $env:CTC_RUN_TAG and a background runspace writes
# this run's ledger total to .claude\ledger\<tag>.json every ~10s. When that
# file is fresh it is shown as-is; when missing/stale the projection is shown,
# marked with a leading "~" (approx) glyph.
#
# Rewritten into the isolated Claude HOME on every `ctc claude` launch, and
# NEVER touches the user's real profile -- this file only ever runs with
# $env:USERPROFILE/$env:HOME pointed at the isolated home by Set-CtcIsolationEnv.
#
# PS 5.1 compatible. Must stay cheap: Claude Code re-invokes this on every
# keystroke, so avoid anything that blocks on the network (this file never
# touches the network -- it only reads local caches).

try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false) } catch { }

# ---------------------------------------------------------------------------
# Home / constants
# ---------------------------------------------------------------------------

$script:CtcSlHomeDir = $env:USERPROFILE
if ([string]::IsNullOrEmpty($script:CtcSlHomeDir)) { $script:CtcSlHomeDir = $env:HOME }
if ([string]::IsNullOrEmpty($script:CtcSlHomeDir)) { $script:CtcSlHomeDir = $HOME }
if ([string]::IsNullOrEmpty($script:CtcSlHomeDir)) { $script:CtcSlHomeDir = '.' }

# Copilot token prices, nano-AIU per token x1000 (default tier).
# order: input, output, cache_read, cache_write
# Keep in exact sync with the PRICES table in cli/ctc's embedded Python
# statusline -- PriceParity.Tests.ps1 asserts the two tables are identical.
$script:CtcSlPrices = New-Object 'System.Collections.Generic.Dictionary[string,int[]]'
$script:CtcSlPrices.Add('claude-haiku-4.5', [int[]]@(110, 550, 11, 137))
$script:CtcSlPrices.Add('claude-opus-4.5', [int[]]@(550, 2750, 55, 687))
$script:CtcSlPrices.Add('claude-opus-4.6', [int[]]@(550, 2750, 55, 687))
$script:CtcSlPrices.Add('claude-opus-4.7', [int[]]@(550, 2750, 55, 687))
$script:CtcSlPrices.Add('claude-opus-4.8', [int[]]@(550, 2750, 55, 687))
$script:CtcSlPrices.Add('claude-opus-5', [int[]]@(550, 2750, 55, 687))
$script:CtcSlPrices.Add('claude-opus-5.5', [int[]]@(440, 2200, 22, 550))
$script:CtcSlPrices.Add('claude-sonnet-4.5', [int[]]@(330, 1650, 33, 412))
$script:CtcSlPrices.Add('claude-sonnet-4.6', [int[]]@(330, 1650, 33, 412))
$script:CtcSlPrices.Add('claude-sonnet-5', [int[]]@(220, 1100, 22, 275))
$script:CtcSlPrices.Add('claude-sonnet-5.5', [int[]]@(220, 1100, 22, 275))
$script:CtcSlPrices.Add('gemini-3.5-flash', [int[]]@(165, 990, 16, 0))
$script:CtcSlPrices.Add('gpt-5-mini', [int[]]@(27, 220, 2, 0))
$script:CtcSlPrices.Add('gpt-5.3-codex', [int[]]@(192, 1540, 19, 0))
$script:CtcSlPrices.Add('gpt-5.4', [int[]]@(275, 1650, 27, 0))
$script:CtcSlPrices.Add('gpt-5.4-mini', [int[]]@(82, 495, 8, 0))
$script:CtcSlPrices.Add('gpt-5.5', [int[]]@(550, 3300, 55, 0))
$script:CtcSlPrices.Add('gpt-5.6-luna', [int[]]@(22, 132, 2, 27))
$script:CtcSlPrices.Add('gpt-5.6-sol', [int[]]@(550, 3300, 55, 687))
$script:CtcSlPrices.Add('gpt-5.6-terra', [int[]]@(220, 1320, 22, 275))
$script:CtcSlPrices.Add('mai-code-1-flash', [int[]]@(82, 495, 8, 0))
$script:CtcSlPrices.Add('<synthetic>', [int[]]@(0, 0, 0, 0))

# Priced from list, not from Copilot's catalog -- shown with a leading "~".
# Empty while every row above comes from Copilot's own catalog (forward-compat
# with the bash source, which also starts this set empty).
$script:CtcSlDerived = New-Object 'System.Collections.Generic.HashSet[string]'

# Live catalog, refreshed once a day by `ctc claude` (Start-CtcPriceRefreshRunspace).
# Anything it confirms overrides the baked-in table above and counts as exact.
# This script itself NEVER hits the network -- plain disk read with a TTL guard.
$script:CtcSlLiveTtlSeconds = 7 * 86400

function Get-CtcSlLivePrices {
    $liveDict = New-Object 'System.Collections.Generic.Dictionary[string,int[]]'
    try {
        $pricesPath = Join-Path (Join-Path $script:CtcSlHomeDir '.claude') 'prices.json'
        if (-not (Test-Path -LiteralPath $pricesPath -PathType Leaf)) { return $liveDict }
        $raw = Get-Content -Raw -LiteralPath $pricesPath -ErrorAction Stop
        $d = $raw | ConvertFrom-Json -ErrorAction Stop
        $fetched = 0.0
        if ($d.fetched) { $fetched = [double]$d.fetched }
        $nowEpoch = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
        if (($nowEpoch - $fetched) -gt $script:CtcSlLiveTtlSeconds) { return $liveDict }
        if ($d.prices) {
            foreach ($prop in $d.prices.PSObject.Properties) {
                $v = $prop.Value
                if ($null -eq $v) { continue }
                $arr = @($v)
                if ($arr.Count -ne 4) { continue }
                $ok = $true
                $ints = New-Object 'System.Collections.Generic.List[int]'
                foreach ($x in $arr) {
                    try { $ints.Add([int][double]$x) } catch { $ok = $false; break }
                }
                if ($ok) { $liveDict[[string]$prop.Name] = $ints.ToArray() }
            }
        }
    } catch {
    }
    return $liveDict
}

$script:CtcSlLive = Get-CtcSlLivePrices
foreach ($liveKey in $script:CtcSlLive.Keys) {
    $script:CtcSlPrices[$liveKey] = $script:CtcSlLive[$liveKey]
    [void]$script:CtcSlDerived.Remove($liveKey)
}

$script:CtcSlNanoPerAiu = 1000000000.0
# The poller rewrites the ledger cache every ~10s; past this it is stale (the
# runspace died, or the control plane is unreachable) and the projection wins.
$script:CtcSlLedgerTtlSeconds = 45
# 1 AIU lines up with published list prices at $1/110. Display only.
$script:CtcSlUsdPerAiu = 1.0 / 110.0
# Optional ceiling for the burn bar (a giver's entitlement, or a grant). Unset
# = no bar, since a consumer's grant is not knowable from the CLI.
$script:CtcSlCeiling = 0.0
if (-not [string]::IsNullOrEmpty($env:CTC_AIU_CEILING)) {
    try { $script:CtcSlCeiling = [double]::Parse($env:CTC_AIU_CEILING, [Globalization.CultureInfo]::InvariantCulture) } catch { $script:CtcSlCeiling = 0.0 }
}

# "gemini" CONTAINS "mini" -- keep it ahead of the mini entry below or an
# unlisted Gemini id would price as a GPT mini.
$script:CtcSlFamily = @(
    , @('opus', 'claude-opus-4.7')
    , @('sonnet', 'claude-sonnet-4.6')
    , @('haiku', 'claude-haiku-4.5')
    , @('codex', 'gpt-5.3-codex')
    , @('gemini', 'gemini-3.5-flash')
    , @('mini', 'gpt-5.4-mini')
    , @('gpt', 'gpt-5.5')
)

# ---------------------------------------------------------------------------
# Pricing
# ---------------------------------------------------------------------------

function Get-CtcSlPriceFor {
    # (prices, exact?) -- unlisted ids fall back to the nearest listed sibling.
    param([string]$ModelId)
    $mid = ''
    if ($ModelId) { $mid = $ModelId.Trim() }
    if ($script:CtcSlPrices.ContainsKey($mid)) {
        $exact = -not $script:CtcSlDerived.Contains($mid)
        return @{ Prices = $script:CtcSlPrices[$mid]; Exact = $exact }
    }
    $norm = $mid.Replace('claude-', '').Replace('-', '.').ToLowerInvariant()
    foreach ($pair in $script:CtcSlFamily) {
        if ($norm.Contains($pair[0])) {
            return @{ Prices = $script:CtcSlPrices[$pair[1]]; Exact = $false }
        }
    }
    return @{ Prices = $script:CtcSlPrices['claude-sonnet-4.6']; Exact = $false }
}

function Get-CtcSlCostNano {
    param($Usage, [int[]]$Prices)
    [int64]$i = 0; [int64]$outTok = 0; [int64]$cr = 0; [int64]$cw = 0; [int64]$h1 = 0
    if ($Usage.input_tokens) { $i = [int64]$Usage.input_tokens }
    if ($Usage.output_tokens) { $outTok = [int64]$Usage.output_tokens }
    if ($Usage.cache_read_input_tokens) { $cr = [int64]$Usage.cache_read_input_tokens }
    if ($Usage.cache_creation_input_tokens) { $cw = [int64]$Usage.cache_creation_input_tokens }
    if ($Usage.cache_creation -and $Usage.cache_creation.ephemeral_1h_input_tokens) {
        $h1 = [int64]$Usage.cache_creation.ephemeral_1h_input_tokens
    }
    $w5 = [Math]::Max($cw - $h1, 0)
    [int64]$p0 = $Prices[0]; [int64]$p1 = $Prices[1]; [int64]$p2 = $Prices[2]; [int64]$p3 = $Prices[3]
    $h1Price = 0L
    if ($p3 -ne 0) { $h1Price = $p0 * 2 }
    # [decimal], not [int64]: at extreme (if unrealistic) token counts the
    # nano-AIU total can exceed Int64.MaxValue (~9.2e18) and PowerShell's
    # auto-widened [double] intermediate would then overflow on the final
    # [int64] cast -- [decimal] keeps full integer precision well past where
    # [int64] would throw (its own ceiling is ~7.9e28).
    $nano = ([decimal]$i * $p0 + [decimal]$outTok * $p1 + [decimal]$cr * $p2 + [decimal]$w5 * $p3 + [decimal]$h1 * $h1Price) * 1000
    return [decimal]$nano
}

# ---------------------------------------------------------------------------
# Transcript discovery + incremental tally
# ---------------------------------------------------------------------------

function Get-CtcSlTranscripts {
    # Main transcript first, then every agent transcript below it (recursive:
    # subagents/agent-*.jsonl AND subagents/workflows/wf_*/agent-*.jsonl all
    # cost real credit).
    param($TranscriptFile, [string]$SessionId)
    $list = New-Object 'System.Collections.Generic.List[string]'
    $list.Add($TranscriptFile.FullName)
    $stem = $SessionId
    if ([string]::IsNullOrEmpty($stem)) { $stem = [IO.Path]::GetFileNameWithoutExtension($TranscriptFile.Name) }
    $subDir = Join-Path (Join-Path $TranscriptFile.DirectoryName $stem) 'subagents'
    if (Test-Path -LiteralPath $subDir -PathType Container) {
        try {
            $found = Get-ChildItem -LiteralPath $subDir -Filter '*.jsonl' -Recurse -File -ErrorAction SilentlyContinue |
                Sort-Object -Property FullName
            foreach ($item in $found) { $list.Add($item.FullName) }
        } catch {
        }
    }
    # The unary comma prevents PowerShell from flattening a 1-element array
    # return value into a bare scalar (a classic PS pitfall: `return $arr`
    # unrolls $arr onto the pipeline; callers indexing [0] would then index
    # into the first CHARACTER of the lone path string instead of the array).
    return , $list.ToArray()
}

function Read-CtcSlNewLines {
    # Reads every COMPLETE line (terminated by \n) at/after $Offset, decoded as
    # UTF-8 (invalid sequences replaced, mirroring Python's errors="replace").
    # A trailing partial line (no terminating \n -- a write in progress) is
    # left unconsumed: NewOffset does not advance past it, so it is re-read
    # whole on the next render. This hand-rolled byte scan exists because
    # .NET's StreamReader does not expose a reliable byte-accurate position
    # (internal buffering) the way Python's readline()/tell() does.
    param([string]$Path, [int64]$Offset)
    $linesOut = New-Object 'System.Collections.Generic.List[string]'
    $newOffset = $Offset
    $size = 0L
    $fs = $null
    try {
        $fs = [System.IO.File]::Open($Path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
        $size = $fs.Length
        if ($Offset -gt $size) { $Offset = 0 }
        if ($Offset -eq $size) {
            return [PSCustomObject]@{ Lines = $linesOut.ToArray(); NewOffset = $Offset; Size = $size }
        }
        $fs.Seek($Offset, [System.IO.SeekOrigin]::Begin) | Out-Null
        $toRead = [int]($size - $Offset)
        $buf = New-Object byte[] $toRead
        $readTotal = 0
        while ($readTotal -lt $toRead) {
            $n = $fs.Read($buf, $readTotal, $toRead - $readTotal)
            if ($n -le 0) { break }
            $readTotal += $n
        }
        $lineStart = 0
        $consumedUpTo = 0
        for ($idx = 0; $idx -lt $readTotal; $idx++) {
            if ($buf[$idx] -eq 10) {
                $lineEnd = $idx
                if ($lineEnd -gt $lineStart -and $buf[$lineEnd - 1] -eq 13) { $lineEnd = $lineEnd - 1 }
                $len = $lineEnd - $lineStart
                if ($len -gt 0) {
                    $lineBytes = New-Object byte[] $len
                    [Array]::Copy($buf, $lineStart, $lineBytes, 0, $len)
                    $linesOut.Add([System.Text.Encoding]::UTF8.GetString($lineBytes))
                } else {
                    $linesOut.Add('')
                }
                $lineStart = $idx + 1
                $consumedUpTo = $lineStart
            }
        }
        $newOffset = $Offset + $consumedUpTo
    } catch {
        # Unreadable or disappeared mid-scan -- treat as no new data this tick.
        $newOffset = $Offset
    } finally {
        if ($fs) { $fs.Dispose() }
    }
    return [PSCustomObject]@{ Lines = $linesOut.ToArray(); NewOffset = $newOffset; Size = $size }
}

function Get-CtcSlTally {
    # -> @{ Aiu; Sub; Last; Exact; Ctx }
    # Incremental: caches a per-file byte offset + running totals so long
    # transcripts are not re-parsed on every render.
    param([string]$TranscriptPath, [string]$SessionId)
    $zero = @{ Aiu = 0.0; Sub = 0.0; Last = 0.0; Exact = $true; Ctx = 0 }
    if ([string]::IsNullOrEmpty($TranscriptPath) -or -not (Test-Path -LiteralPath $TranscriptPath -PathType Leaf)) {
        return $zero
    }
    $p = Get-Item -LiteralPath $TranscriptPath
    $cdir = Join-Path (Join-Path $script:CtcSlHomeDir '.claude') 'statusline-cache'
    try {
        if (-not (Test-Path -LiteralPath $cdir)) { New-Item -ItemType Directory -Path $cdir -Force | Out-Null }
    } catch {
        return $zero
    }
    $stem = $SessionId
    if ([string]::IsNullOrEmpty($stem)) { $stem = [IO.Path]::GetFileNameWithoutExtension($p.Name) }
    $cf = Join-Path $cdir ($stem + '.json')

    $offs = New-Object 'System.Collections.Generic.Dictionary[string,int64]'
    # [decimal], not [int64]: nano-AIU totals can exceed Int64.MaxValue at
    # extreme token counts (see Get-CtcSlCostNano).
    $rids = New-Object 'System.Collections.Generic.Dictionary[string,decimal]'
    [decimal]$nano = 0; [decimal]$sub = 0; [decimal]$last = 0; [bool]$exact = $true; [int64]$ctx = 0

    if (Test-Path -LiteralPath $cf -PathType Leaf) {
        try {
            $cached = Get-Content -Raw -LiteralPath $cf -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
            if ($cached.offs) {
                foreach ($prop in $cached.offs.PSObject.Properties) { $offs[$prop.Name] = [int64]$prop.Value }
                if ($cached.rids) { foreach ($prop in $cached.rids.PSObject.Properties) { $rids[$prop.Name] = [decimal]$prop.Value } }
                if ($null -ne $cached.nano) { $nano = [decimal]$cached.nano }
                if ($null -ne $cached.sub) { $sub = [decimal]$cached.sub }
                if ($null -ne $cached.last) { $last = [decimal]$cached.last }
                if ($null -ne $cached.exact) { $exact = [bool]$cached.exact }
                if ($null -ne $cached.ctx) { $ctx = [int64]$cached.ctx }
            }
        } catch {
            # Corrupt cache -- start fresh rather than fail the render.
        }
    }

    $files = Get-CtcSlTranscripts -TranscriptFile $p -SessionId $SessionId
    for ($idx = 0; $idx -lt $files.Count; $idx++) {
        $f = $files[$idx]
        $key = $f
        $size = 0L
        try { $size = (Get-Item -LiteralPath $f).Length } catch { continue }
        $off = 0L
        if ($offs.ContainsKey($key)) { $off = $offs[$key] }
        if ($off -gt $size) { $off = 0L }
        if ($off -eq $size) { continue }
        $readResult = Read-CtcSlNewLines -Path $f -Offset $off
        foreach ($line in $readResult.Lines) {
            $o = $null
            try { $o = $line | ConvertFrom-Json -ErrorAction Stop } catch { continue }
            if ($null -eq $o) { continue }
            $msg = $o.message
            if (-not $msg) { continue }
            $u = $msg.usage
            if (-not $u) { continue }
            $prResult = Get-CtcSlPriceFor -ModelId ([string]$msg.model)
            $n = Get-CtcSlCostNano -Usage $u -Prices $prResult.Prices
            $rid = ''
            if ($o.requestId) { $rid = [string]$o.requestId } elseif ($o.uuid) { $rid = [string]$o.uuid }
            [decimal]$prev = 0
            if ($rids.ContainsKey($rid)) { $prev = $rids[$rid] }
            if ($n -le $prev) { continue }
            $rids[$rid] = $n
            $delta = $n - $prev
            $nano += $delta
            $exact = $exact -and $prResult.Exact
            if ($idx -gt 0) {
                $sub += $delta
            } else {
                $last = $n
                if (-not $o.isSidechain) {
                    [int64]$inTok = 0; [int64]$crTok = 0; [int64]$cwTok = 0
                    if ($u.input_tokens) { $inTok = [int64]$u.input_tokens }
                    if ($u.cache_read_input_tokens) { $crTok = [int64]$u.cache_read_input_tokens }
                    if ($u.cache_creation_input_tokens) { $cwTok = [int64]$u.cache_creation_input_tokens }
                    $ctx = $inTok + $crTok + $cwTok
                }
            }
        }
        $offs[$key] = $readResult.NewOffset
    }

    if ($rids.Count -gt 6000) {
        $keep = New-Object 'System.Collections.Generic.Dictionary[string,int64]'
        $allKeys = @($rids.Keys)
        $startIdx = $allKeys.Count - 4000
        for ($i = $startIdx; $i -lt $allKeys.Count; $i++) { $keep[$allKeys[$i]] = $rids[$allKeys[$i]] }
        $rids = $keep
    }

    $offsObj = [ordered]@{}
    foreach ($k in $offs.Keys) { $offsObj[$k] = $offs[$k] }
    $ridsObj = [ordered]@{}
    foreach ($k in $rids.Keys) { $ridsObj[$k] = $rids[$k] }
    $stateOut = [ordered]@{ offs = $offsObj; rids = $ridsObj; nano = $nano; sub = $sub; last = $last; exact = $exact; ctx = $ctx }
    try {
        $json = $stateOut | ConvertTo-Json -Depth 8 -Compress
        Set-Content -LiteralPath $cf -Value $json -Encoding UTF8 -NoNewline
    } catch {
    }

    return @{ Aiu = ($nano / $script:CtcSlNanoPerAiu); Sub = ($sub / $script:CtcSlNanoPerAiu); Last = ($last / $script:CtcSlNanoPerAiu); Exact = $exact; Ctx = $ctx }
}

# ---------------------------------------------------------------------------
# Ledger readout (authoritative, poller-written cache; disk read only)
# ---------------------------------------------------------------------------

function Get-CtcSlLedgerAiu {
    # This run's ledger charge in AIU, or $null when the cache is missing,
    # stale, unparseable, or for another tag.
    param([string]$Tag)
    if ([string]::IsNullOrEmpty($Tag)) { return $null }
    $f = Join-Path (Join-Path (Join-Path $script:CtcSlHomeDir '.claude') 'ledger') ($Tag + '.json')
    try {
        if (-not (Test-Path -LiteralPath $f -PathType Leaf)) { return $null }
        $mtimeUtc = (Get-Item -LiteralPath $f).LastWriteTimeUtc
        $ageSeconds = ([DateTime]::UtcNow - $mtimeUtc).TotalSeconds
        if ($ageSeconds -gt $script:CtcSlLedgerTtlSeconds) { return $null }
        $d = Get-Content -Raw -LiteralPath $f -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
        if ([string]$d.tag -ne $Tag) { return $null }
        if ([string]$d.unit -ne 'nano_aiu') { return $null }
        return ([int64]$d.nano_aiu_total) / $script:CtcSlNanoPerAiu
    } catch {
        return $null
    }
}

# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------

function Format-CtcSlColor {
    param([string]$Code, [string]$Text)
    return ([string][char]27) + '[' + $Code + 'm' + $Text + ([string][char]27) + '[0m'
}

$script:CtcSlDim = '2'
$script:CtcSlSeparator = Format-CtcSlColor $script:CtcSlDim (' ' + ([string][char]0x2595) + ' ')

function Get-CtcSlBar {
    param([double]$Frac, [int]$Width = 8)
    $filled = 0
    if ($Frac -gt 0) {
        $filled = [Math]::Min($Width, [int][Math]::Floor($Frac * $Width + 0.999))
    }
    $hue = '31'
    if ($Frac -lt 0.25) { $hue = '32' } elseif ($Frac -lt 0.6) { $hue = '33' }
    $filledGlyph = ([string][char]0x25B0) * $filled
    $emptyGlyph = ([string][char]0x25B1) * ($Width - $filled)
    return (Format-CtcSlColor $hue $filledGlyph) + (Format-CtcSlColor $script:CtcSlDim $emptyGlyph)
}

function Format-CtcSlRounded {
    # Round-half-to-even on the exact binary value of $N, then format with
    # $Decimals places -- matches Python's '%.Nf' / round() semantics. .NET's
    # ToString('0.00') first rounds to 15 significant digits and then rounds
    # half-away-from-zero, which disagrees with Python on values whose exact
    # double is just below a .xx5 boundary (3.135 is really
    # 3.13499999999999978...  -> Python prints 3.13, ToString('0.00') prints
    # 3.14) and on EXACT midpoints (0.125 -> Python's banker's rounding gives
    # 0.12, ToString('0.00') gives 0.13). Shared by Format-CtcSlFixed2, the
    # context-size 'M' formatting and the burn-bar percentage so all three
    # agree with the Python statusline bit-for-bit.
    param([double]$N, [int]$Decimals)
    $inv = [Globalization.CultureInfo]::InvariantCulture
    if ([double]::IsNaN($N) -or [double]::IsInfinity($N)) {
        return $N.ToString("F$Decimals", $inv)
    }
    $isNeg = $N -lt 0
    $abs = [Math]::Abs($N)
    try {
        # 'E16' renders 17 significant digits of the exact double value (enough
        # to disambiguate true vs. apparent decimal midpoints) as a string
        # [decimal]::Parse can read back without its own 15-digit pre-rounding.
        $d = [decimal]::Parse($abs.ToString('E16', $inv), [Globalization.NumberStyles]::Float, $inv)
        $rounded = [Math]::Round($d, $Decimals, [MidpointRounding]::ToEven)
    } catch [OverflowException] {
        # Too large for [decimal] (~7.9e28) -- fall back to double rounding;
        # at that magnitude fractional precision is moot anyway.
        $rounded = [Math]::Round($abs, $Decimals, [MidpointRounding]::ToEven)
    }
    if ($isNeg -and $rounded -ne 0) { $rounded = -$rounded }
    return $rounded.ToString("F$Decimals", $inv)
}

function Format-CtcSlHuman {
    param([double]$N)
    if ($N -ge 1000000) {
        return (Format-CtcSlRounded -N ($N / 1000000) -Decimals 1) + 'M'
    }
    if ($N -ge 1000) {
        $k = [Math]::Truncate($N / 1000)
        return ([int64]$k).ToString([Globalization.CultureInfo]::InvariantCulture) + 'k'
    }
    return ([int64]$N).ToString([Globalization.CultureInfo]::InvariantCulture)
}

function Format-CtcSlFixed2 {
    param([double]$N)
    return Format-CtcSlRounded -N $N -Decimals 2
}

function Get-CtcSlGitSegment {
    # Best-effort branch + dirty indicator. Never blocks the render for more
    # than 1s (matches the Python port's subprocess timeout=1):
    # StandardOutput/Error are drained asynchronously *before* WaitForExit so
    # a chatty `git status` cannot deadlock on a full OS pipe buffer while
    # this thread is blocked waiting for the process to exit.
    param([string]$Cwd)
    try {
        $dir = $Cwd
        if ([string]::IsNullOrEmpty($dir)) { $dir = '.' }
        if (-not (Get-Command git -ErrorAction SilentlyContinue)) { return '' }
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = 'git'
        $psi.Arguments = '-C "' + $dir.Replace('"', '""') + '" status --porcelain=v1 -b'
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError = $true
        $psi.UseShellExecute = $false
        $psi.CreateNoWindow = $true
        $proc = New-Object System.Diagnostics.Process
        $proc.StartInfo = $psi
        if (-not $proc.Start()) { return '' }
        $outTask = $proc.StandardOutput.ReadToEndAsync()
        $null = $proc.StandardError.ReadToEndAsync()
        if (-not $proc.WaitForExit(1000)) {
            try { $proc.Kill() } catch { }
            return ''
        }
        if ($proc.ExitCode -ne 0) { return '' }
        $stdout = $outTask.Result
        $allLines = [regex]::Split($stdout, "\r\n|\r|\n")
        if ($allLines.Count -gt 0 -and $allLines[$allLines.Count - 1] -eq '') {
            if ($allLines.Count -eq 1) { $allLines = @() } else { $allLines = $allLines[0..($allLines.Count - 2)] }
        }
        if ($allLines.Count -eq 0) { return '' }
        $branchLine = $allLines[0]
        $branchPart = ''
        if ($branchLine.Length -ge 3) { $branchPart = $branchLine.Substring(3) }
        $branch = $branchPart.Split([string[]]@('...'), [StringSplitOptions]::None)[0]
        $dirty = ''
        if ($allLines.Count -gt 1) { $dirty = Format-CtcSlColor '33' (' ' + ([string][char]0x270E)) }
        return (Format-CtcSlColor '38;5;114' (([string][char]0x2387) + ' ' + $branch)) + $dirty
    } catch {
        return ''
    }
}

function Get-CtcSlPathName {
    # Mirrors pathlib.Path(...).name: "." and ".." (and the root) have no name.
    param([string]$PathStr)
    if ([string]::IsNullOrEmpty($PathStr)) { return '' }
    $norm = $PathStr.Replace('\', '/').TrimEnd('/')
    if ([string]::IsNullOrEmpty($norm)) { return '' }
    $segments = $norm.Split('/')
    $leaf = $segments[$segments.Count - 1]
    if ($leaf -eq '.' -or $leaf -eq '..') { return '' }
    return $leaf
}

# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

function Invoke-CtcSlMain {
    $stdinText = ''
    try { $stdinText = [Console]::In.ReadToEnd() } catch { $stdinText = '' }
    $d = $null
    if (-not [string]::IsNullOrWhiteSpace($stdinText)) {
        try { $d = $stdinText | ConvertFrom-Json -ErrorAction Stop } catch { $d = $null }
    }
    if ($null -eq $d) { $d = [PSCustomObject]@{} }

    $model = '?'
    if ($d.model) {
        if ($d.model.display_name) { $model = [string]$d.model.display_name }
        elseif ($d.model.id) { $model = [string]$d.model.id }
    }
    $cwd = ''
    if ($d.workspace -and $d.workspace.current_dir) { $cwd = [string]$d.workspace.current_dir }
    elseif ($d.cwd) { $cwd = [string]$d.cwd }

    $projInput = ''
    if ($d.workspace -and $d.workspace.project_dir) { $projInput = [string]$d.workspace.project_dir }
    elseif (-not [string]::IsNullOrEmpty($cwd)) { $projInput = $cwd }
    else { $projInput = '.' }
    $proj = Get-CtcSlPathName $projInput

    $transcriptPath = ''
    if ($d.transcript_path) { $transcriptPath = [string]$d.transcript_path }
    $sessionId = ''
    if ($d.session_id) { $sessionId = [string]$d.session_id }

    $tallyResult = Get-CtcSlTally -TranscriptPath $transcriptPath -SessionId $sessionId
    $aiu = $tallyResult.Aiu
    $sub = $tallyResult.Sub
    $last = $tallyResult.Last
    $ctx = $tallyResult.Ctx

    $tag = $env:CTC_RUN_TAG
    $booked = Get-CtcSlLedgerAiu -Tag $tag
    $approx = [string][char]0x2248
    if ($null -ne $booked) { $aiu = $booked; $approx = '' }

    $hue = '32'
    if ($aiu -ge 50) { $hue = '31' } elseif ($aiu -ge 10) { $hue = '38;5;208' } elseif ($aiu -ge 1) { $hue = '33' }

    $parts = New-Object 'System.Collections.Generic.List[string]'
    $parts.Add((Format-CtcSlColor '1;38;5;213' (([string][char]0x25C6) + ' CTC')))
    $parts.Add((Format-CtcSlColor '38;5;110' ($model.Replace('Claude ', ''))))
    if (-not [string]::IsNullOrEmpty($proj) -and $proj.ToLowerInvariant() -ne 'ctc') {
        $parts.Add((Format-CtcSlColor '38;5;146' $proj))
    }
    $g = Get-CtcSlGitSegment -Cwd $cwd
    if (-not [string]::IsNullOrEmpty($g)) { $parts.Add($g) }

    $costAiuStr = Format-CtcSlFixed2 $aiu
    $usdStr = Format-CtcSlFixed2 ($aiu * $script:CtcSlUsdPerAiu)
    $cost = (Format-CtcSlColor $hue (([string][char]0x26A1) + ' ' + $approx + $costAiuStr + ' AIU')) +
            (Format-CtcSlColor $script:CtcSlDim (' ' + ([string][char]0xB7) + ' $' + $usdStr))
    if ($last -ne 0.0) {
        $cost += Format-CtcSlColor $script:CtcSlDim (' (+' + (Format-CtcSlFixed2 $last) + ')')
    }
    $parts.Add($cost)

    if ($sub -ne 0.0) {
        $parts.Add((Format-CtcSlColor '38;5;180' (([string][char]0x2442) + ' ' + (Format-CtcSlFixed2 $sub))) +
                    (Format-CtcSlColor $script:CtcSlDim ' agents'))
    }
    if ($script:CtcSlCeiling -gt 0) {
        $f = $aiu / $script:CtcSlCeiling
        $pctStr = Format-CtcSlRounded -N ($f * 100) -Decimals 1
        $ceilStr = $script:CtcSlCeiling.ToString('0', [Globalization.CultureInfo]::InvariantCulture)
        $parts.Add((Get-CtcSlBar -Frac $f) + (Format-CtcSlColor $script:CtcSlDim (' ' + $pctStr + '% of ' + $ceilStr)))
    }
    if ($ctx -ne 0) {
        $parts.Add((Format-CtcSlColor $script:CtcSlDim (([string][char]0x2301) + ' ' + (Format-CtcSlHuman $ctx))))
    }

    [Console]::Out.Write(($parts -join $script:CtcSlSeparator))
}

# Run Main only when this file is executed directly, not when dot-sourced --
# lets Pester dot-source it to unit-test the internal Get-CtcSl*/Format-CtcSl*
# functions in isolation.
if ($MyInvocation.InvocationName -ne '.') {
    Invoke-CtcSlMain
}

'@

function Install-CtcClaudeStatusline {
    # Writes statusline.ps1 into the isolated Claude HOME on every launch and
    # wires it up via settings.json -- a never-clobber merge that only ever
    # touches the "statusLine" key, leaving every other user setting alone
    # (mirrors bash's _install_claude_statusline: d["statusLine"] = {...};
    # write d back; see also its bash-side -- it bakes `python3 "<path>"` as
    # the command there, we bake a PowerShell invocation here instead).
    param([string]$IsoHome)
    if ([string]::IsNullOrEmpty($IsoHome)) { return }
    $claudeDir = Join-Path $IsoHome '.claude'
    try {
        if (-not (Test-Path -LiteralPath $claudeDir)) { New-Item -ItemType Directory -Path $claudeDir -Force | Out-Null }
    } catch {
        return
    }

    $slPath = Join-Path $claudeDir 'statusline.ps1'
    try {
        $utf8Bom = New-Object System.Text.UTF8Encoding($true)
        [System.IO.File]::WriteAllText($slPath, $script:CtcStatuslineSource, $utf8Bom)
    } catch {
        return
    }

    # Prefer pwsh (PowerShell 7+) when present -- faster cold start and the
    # same engine ctc.ps1 itself was validated against -- but PS 5.1's
    # "powershell" ships on every supported Windows box, so it is always a
    # safe fallback.
    $slShell = 'powershell'
    if (Get-Command pwsh -ErrorAction SilentlyContinue) { $slShell = 'pwsh' }
    $slCommand = '{0} -NoProfile -NonInteractive -File "{1}"' -f $slShell, $slPath

    $settingsPath = Join-Path $claudeDir 'settings.json'
    $settingsObj = $null
    if (Test-Path -LiteralPath $settingsPath -PathType Leaf) {
        try {
            $raw = Get-Content -Raw -LiteralPath $settingsPath -ErrorAction Stop
            $parsed = $raw | ConvertFrom-Json -ErrorAction Stop
            if ($parsed -is [System.Management.Automation.PSCustomObject]) { $settingsObj = $parsed }
        } catch {
            # Corrupt/non-object settings.json -- fall through to a fresh {}.
        }
    }
    if ($null -eq $settingsObj) { $settingsObj = [PSCustomObject]@{} }

    $statusLineValue = [PSCustomObject]@{ type = 'command'; command = $slCommand; padding = 0 }
    if ($settingsObj.PSObject.Properties.Match('statusLine').Count -gt 0) {
        $settingsObj.statusLine = $statusLineValue
    } else {
        $settingsObj | Add-Member -NotePropertyName 'statusLine' -NotePropertyValue $statusLineValue -Force
    }

    try {
        $settingsJson = $settingsObj | ConvertTo-Json -Depth 100
        # No BOM: unlike statusline.ps1 (a PS 5.1 script that needs the BOM so
        # its non-ASCII glyphs aren't misread as ANSI), settings.json is JSON
        # consumed by Node/Claude -- and Node's JSON.parse rejects a leading
        # BOM. Get-Content -Raw above already auto-detects/tolerates a BOM on
        # an existing file, so round-tripping an old BOM-written file is safe.
        $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
        [System.IO.File]::WriteAllText($settingsPath, $settingsJson + "`n", $utf8NoBom)
    } catch {
        # Best-effort: a failed settings merge should not block `ctc claude`.
    }
}


function Get-CtcRunTag {
    return ('run-' + ([guid]::NewGuid().ToString('N').Substring(0, 16)))
}

function Invoke-CtcClaude {
    param([string[]]$CtcArgs = @())
    if (-not (Assert-CtcWindows)) { $script:CtcExitCode = 1; return }
    $cfg = Get-CtcConfigDir
    $envPath = Join-Path $cfg 'env.json'
    if (-not (Test-Path -LiteralPath $envPath)) {
        [Console]::Error.WriteLine("ctc: not set up yet. Run 'ctc login' first.")
        $script:CtcExitCode = 1
        return
    }
    $settings = Get-CtcSettings
    $updateJob = Invoke-CtcCheckLauncherUpdate -Settings $settings -ConfigDir $cfg

    Set-CtcIsolationEnv -EnvPath $envPath
    Set-CtcNoProxyEnv -CtcNoProxy $settings.NoProxy

    $env:ANTHROPIC_BASE_URL = "https://copilot-api.$($settings.GheDomain)"
    $env:ANTHROPIC_AUTH_TOKEN = $env:COPILOT_GITHUB_TOKEN
    if ([string]::IsNullOrEmpty($env:ANTHROPIC_MODEL)) { $env:ANTHROPIC_MODEL = 'claude-sonnet-5' }
    if ([string]::IsNullOrEmpty($env:ANTHROPIC_SMALL_FAST_MODEL)) { $env:ANTHROPIC_SMALL_FAST_MODEL = 'claude-haiku-4.5' }
    if ([string]::IsNullOrEmpty($env:ENABLE_TOOL_SEARCH)) { $env:ENABLE_TOOL_SEARCH = 'true' }
    if ([string]::IsNullOrEmpty($env:CLAUDE_CODE_DISABLE_WORKFLOWS)) { $env:CLAUDE_CODE_DISABLE_WORKFLOWS = '1' }
    $env:CLAUDE_CODE_DISABLE_UNKNOWN_MODEL_WINDOW_ENFORCEMENT = '1'

    if (-not (Get-Command claude -ErrorAction SilentlyContinue)) {
        [Console]::Error.WriteLine("ctc: 'claude' (Anthropic Claude Code CLI) not found on PATH.")
        [Console]::Error.WriteLine('  Install it from https://docs.claude.com/claude-code')
        Wait-CtcRunspace -Runspace $updateJob -TimeoutMs 1500
        $script:CtcExitCode = 1
        return
    }

    $tag = Get-CtcRunTag
    $env:CTC_RUN_TAG = $tag
    $headerLine = "X-CTC-Run-Tag: $tag"
    $env:ANTHROPIC_CUSTOM_HEADERS = if ([string]::IsNullOrEmpty($env:ANTHROPIC_CUSTOM_HEADERS)) {
        $headerLine
    } else {
        "$($env:ANTHROPIC_CUSTOM_HEADERS)`n$headerLine"
    }

    Install-CtcClaudeStatusline -IsoHome $env:USERPROFILE
    # Price refresh always runs (best-effort, background); the ledger poll is
    # the only one gated by CTC_LEDGER_POLL=0 (statusline then always shows
    # the ≈ projection instead of the authoritative ledger total) -- mirrors
    # bash's _start_ledger_poll, which is always CALLED but checks the env var
    # internally and returns immediately when disabled.
    $priceJob = Start-CtcPriceRefreshRunspace -IsoHome $env:USERPROFILE -GheDomain $settings.GheDomain -Token $env:COPILOT_GITHUB_TOKEN -ProxyUrl $env:HTTPS_PROXY
    $ledgerPoll = $null
    if ($env:CTC_LEDGER_POLL -ne '0') {
        $ledgerPoll = Start-CtcLedgerPollRunspace -IsoHome $env:USERPROFILE -Settings $settings -Tag $tag -Token $env:COPILOT_GITHUB_TOKEN
    }

    # A --model flag beats ANTHROPIC_MODEL inside Claude Code, so show that one.
    $model = $env:ANTHROPIC_MODEL
    $prev = ''
    foreach ($a in $CtcArgs) {
        if ($a -like '--model=*') { $model = $a.Substring(8) }
        if ($prev -eq '--model') { $model = $a }
        $prev = $a
    }

    try { $Host.UI.RawUI.WindowTitle = 'CTC ' + [char]0x25C6 + ' claude' } catch { }
    [Console]::Error.WriteLine([char]0x25C6 + ' CTC mode -- Claude Code on the Copilot backend (credits via the donation pool)')
    [Console]::Error.WriteLine("  model: $model  (small/fast: $($env:ANTHROPIC_SMALL_FAST_MODEL))")

    & claude @CtcArgs
    $code = $LASTEXITCODE

    if ($ledgerPoll) { Stop-CtcLedgerPoll -Poller $ledgerPoll }
    Wait-CtcRunspace -Runspace $priceJob -TimeoutMs 1500
    Wait-CtcRunspace -Runspace $updateJob -TimeoutMs 1500
    $script:CtcExitCode = $code
    return
}

# ---------------------------------------------------------------------------
# ctc menu (bare `ctc` on an interactive console)
# ---------------------------------------------------------------------------

function Test-CtcInteractiveConsole {
    try {
        return (-not [Console]::IsInputRedirected) -and (-not [Console]::IsOutputRedirected)
    } catch {
        return $false
    }
}

function Invoke-CtcMenu {
    # NOTE: Invoke-CtcCopilot/Invoke-CtcClaude are invoked as bare statements
    # (never wrapped in parens/assignment) so the live, interactive stdout of
    # the native `copilot`/`claude` child process streams straight through to
    # the console. Wrapping either call -- even just to capture its exit code
    # -- would route that native output through PowerShell's success pipeline
    # instead, where it is silently collected and never printed. The exit
    # code is instead read back from $script:CtcExitCode, which both
    # functions set as their last act. `return` here is for flow control only
    # and never carries a value (see the $script:CtcExitCode comment above
    # its declaration for the full rationale).
    while ($true) {
        [Console]::Error.WriteLine([char]0x25C6 + ' CTC -- choose your agent')
        [Console]::Error.WriteLine('  1) GitHub Copilot CLI')
        [Console]::Error.WriteLine('  2) Claude Code')
        [Console]::Error.Write('Choice: ')
        $choice = [Console]::In.ReadLine()
        if ($null -eq $choice) {
            [Console]::Error.WriteLine('')
            $script:CtcExitCode = 0
            return
        }
        switch ($choice.Trim()) {
            { $_ -in '1', 'copilot', 'c' } { Invoke-CtcCopilot -CtcArgs @(); return }
            { $_ -in '2', 'claude' } { Invoke-CtcClaude -CtcArgs @(); return }
            default { [Console]::Error.WriteLine('  Please enter 1 or 2.') }
        }
    }
}

# ---------------------------------------------------------------------------
# main dispatch
# ---------------------------------------------------------------------------

function Invoke-CtcMain {
    param([string[]]$CtcArgs = @())
    # NOTE: see the $script:CtcExitCode declaration above for why every
    # branch below assigns to it (never relies on this function's own
    # `return <value>`) and why Invoke-CtcMenu/Invoke-CtcCopilot/
    # Invoke-CtcClaude are always invoked as bare statements. This function
    # is itself always invoked bare too (by the bottom dispatch guard), so
    # any value it returned directly would otherwise print as stray,
    # unconsumed console output.

    if ($CtcArgs.Count -eq 0) {
        if (Test-CtcInteractiveConsole) { Invoke-CtcMenu; return }
        Invoke-CtcCopilot -CtcArgs @()
        return
    }

    $cmd = $CtcArgs[0]
    $rest = @()
    if ($CtcArgs.Count -gt 1) { $rest = $CtcArgs[1..($CtcArgs.Count - 1)] }

    switch ($cmd) {
        'login' { $script:CtcExitCode = (Invoke-CtcLogin -CtcArgs $rest); return }
        'status' { $script:CtcExitCode = (Invoke-CtcStatus); return }
        'logout' { $script:CtcExitCode = (Invoke-CtcLogout); return }
        'claude' { Invoke-CtcClaude -CtcArgs $rest; return }
        'copilot' { Invoke-CtcCopilot -CtcArgs $rest; return }
        '-h' { Show-CtcUsage; $script:CtcExitCode = 0; return }
        '--help' { Show-CtcUsage; $script:CtcExitCode = 0; return }
        'help' { Show-CtcUsage; $script:CtcExitCode = 0; return }
        default {
            if ($cmd.StartsWith('-')) { Invoke-CtcCopilot -CtcArgs $CtcArgs; return }
            [Console]::Error.WriteLine("ctc: unknown command '$cmd'")
            [Console]::Error.WriteLine('')
            Show-CtcUsage -Writer ([Console]::Error)
            $script:CtcExitCode = 2
            return
        }
    }
}

# Run Main only when this file is executed directly, not when dot-sourced —
# lets Pester dot-source it to call the internal Invoke-Ctc* functions (and
# Mock things like Read-Host / Add-CtcCurrentUserTrust) in isolation.
if ($MyInvocation.InvocationName -ne '.') {
    # Bare call (no parens/assignment/pipe): see the $script:CtcExitCode
    # comment above for why -- this is the one call site that matters most,
    # since it is the real entry point for every actual `ctc ...` invocation.
    Invoke-CtcMain -CtcArgs $args
    exit $script:CtcExitCode
}
