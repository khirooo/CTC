# Pester 5 suite for cli/install.ps1. Every test launches install.ps1 as a
# REAL child `pwsh -File` process (never dot-sourced) so the bottom
# `Invoke-CtcInstallMain; exit $script:CtcInstallExitCode` dispatch guard,
# real exit codes and [Console]::Out/Error streams are exercised exactly as
# a real `iwr ... | .\install.ps1` invocation would.
BeforeAll {
    . (Join-Path $PSScriptRoot 'Common.ps1')

    # -----------------------------------------------------------------------
    # Local helpers (this file only -- Common.ps1 is read-only for this
    # task). Defined inside this top-level BeforeAll (rather than at script
    # scope) so they are visible during Pester's Run phase, not just
    # Discovery.
    # -----------------------------------------------------------------------

    function New-CtcInstallFixtureSource {
        # A minimal, self-contained stand-in for the real ctc.ps1 that
        # install.ps1 copies into place. Used wherever a test only cares about
        # install.ps1's OWN behaviour (fetch/shim/PATH/copilot bootstrap) and
        # must not depend on -- or accidentally exercise -- the real launcher's
        # own cert-trust / network code.
        param($Sandbox)
        $path = Join-Path $Sandbox.Root 'fixture-ctc.ps1'
        Set-Content -LiteralPath $path -Value '# fixture ctc.ps1 placeholder' -Encoding ascii
        return $path
    }

    function New-CtcInstallLoginStubSource {
        # A fake ctc.ps1 whose ONLY job is to understand `login -Token <t>` well
        # enough to write env.json exactly like the real Invoke-CtcLogin does,
        # without touching curl.exe or any cert store. This is the "stub/mocked
        # trust" stand-in the task calls for: install.ps1's own `-Token` handling
        # (building the right args, propagating the exit code) is real; the
        # login/cert-trust internals it shells out to are faked.
        param($Sandbox)
        $path = Join-Path $Sandbox.Root 'fixture-login-ctc.ps1'
        $body = @'
param()
if ($args.Count -ge 1 -and $args[0] -eq 'login') {
    $tokenIdx = [Array]::IndexOf($args, '-Token')
    $token = if ($tokenIdx -ge 0 -and $tokenIdx + 1 -lt $args.Count) { $args[$tokenIdx + 1] } else { $null }
    if ([string]::IsNullOrEmpty($token)) { [Console]::Error.WriteLine('ctc: No token entered -- aborting.'); exit 1 }
    $cfg = if ($env:CTC_CONFIG_DIR) { $env:CTC_CONFIG_DIR } elseif ($env:APPDATA) { Join-Path $env:APPDATA 'ctc' } else { Join-Path $env:USERPROFILE '.config\ctc' }
    New-Item -ItemType Directory -Path $cfg -Force | Out-Null
    $envObj = [ordered]@{ COPILOT_GITHUB_TOKEN = $token }
    ($envObj | ConvertTo-Json) | Set-Content -LiteralPath (Join-Path $cfg 'env.json') -Encoding UTF8
    exit 0
}
exit 1
'@
        Set-Content -LiteralPath $path -Value $body -Encoding ascii
        return $path
    }

    function Invoke-CtcInstallChild {
        # Like Common's Invoke-CtcScript, but invoked via `-Command` so a test
        # can inject a function (e.g. a fake `Get-ExecutionPolicy`) into the
        # SAME top-level scope install.ps1 runs in, via PowerShell's normal
        # function-shadowing rules -- the one thing `-File` can't do. The script
        # itself still runs as the real top-level script (not dot-sourced), so
        # its own `exit $script:CtcInstallExitCode` still terminates the whole
        # process and $LASTEXITCODE/process exit code still line up.
        param(
            [string[]]$ScriptArgs = @(),
            [string]$Preamble = '',
            [hashtable]$EnvOverrides = @{},
            [int]$TimeoutSec = 20
        )
        $quotedArgs = ($ScriptArgs | ForEach-Object { "'" + ($_ -replace "'", "''") + "'" }) -join ' '
        $quotedPath = "'" + ($script:CtcInstallScriptPath -replace "'", "''") + "'"
        $command = "$Preamble`n& $quotedPath $quotedArgs`nexit `$LASTEXITCODE"

        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = $script:CtcPwshExe
        foreach ($a in @('-NoProfile', '-NonInteractive', '-Command', $command)) { $psi.ArgumentList.Add($a) | Out-Null }
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError = $true
        $psi.RedirectStandardInput = $true
        $psi.UseShellExecute = $false
        foreach ($k in $EnvOverrides.Keys) { $psi.EnvironmentVariables[$k] = $EnvOverrides[$k] }
        $proc = New-Object System.Diagnostics.Process
        $proc.StartInfo = $psi
        [void]$proc.Start()
        $proc.StandardInput.Close()
        $stdout = $proc.StandardOutput.ReadToEnd()
        $stderr = $proc.StandardError.ReadToEnd()
        if (-not $proc.WaitForExit($TimeoutSec * 1000)) {
            try { $proc.Kill() } catch { }
            throw "Invoke-CtcInstallChild: timed out after ${TimeoutSec}s"
        }
        [PSCustomObject]@{ ExitCode = $proc.ExitCode; StdOut = $stdout; StdErr = $stderr; Combined = $stdout + $stderr }
    }

    function Get-CtcInstallRoot {
        param($Sandbox)
        Join-Path $Sandbox.LocalAppData 'Programs\ctc'
    }
}

Describe 'install.ps1' {
    BeforeEach {
        $script:CtcSavedEnv = Save-CtcTestEnv
        $script:Sandbox = New-CtcTestSandbox
        Initialize-CtcTestEnv -Sandbox $script:Sandbox
        # Every happy-path test bypasses the ExecutionPolicy preflight via its
        # documented override; the preflight itself gets its own Context below.
        [Environment]::SetEnvironmentVariable('CTC_SKIP_EXECPOLICY_CHECK', '1')
    }

    AfterEach {
        Restore-CtcTestEnv -Saved $script:CtcSavedEnv
        Remove-CtcTestSandbox -Sandbox $script:Sandbox
    }

    Context 'basic install layout' {
        It 'installs lib\ctc.ps1 and bin\ctc.cmd under LOCALAPPDATA\Programs\ctc' {
            $src = New-CtcInstallFixtureSource -Sandbox $script:Sandbox
            [Environment]::SetEnvironmentVariable('CTC_SRC', $src)
            New-CtcStub -Sandbox $script:Sandbox -Name 'copilot' | Out-Null

            $result = Invoke-CtcScript -ScriptPath $script:CtcInstallScriptPath -ScriptArgs @()

            $result.ExitCode | Should -Be 0
            $root = Get-CtcInstallRoot -Sandbox $script:Sandbox
            Join-Path $root 'lib\ctc.ps1' | Should -Exist
            Join-Path $root 'bin\ctc.cmd' | Should -Exist
        }

        It 'writes a shim that points at ..\lib\ctc.ps1 via "powershell -NoProfile -File" (no Bypass)' {
            $src = New-CtcInstallFixtureSource -Sandbox $script:Sandbox
            [Environment]::SetEnvironmentVariable('CTC_SRC', $src)
            New-CtcStub -Sandbox $script:Sandbox -Name 'copilot' | Out-Null

            $result = Invoke-CtcScript -ScriptPath $script:CtcInstallScriptPath -ScriptArgs @()
            $result.ExitCode | Should -Be 0

            $shimPath = Join-Path (Get-CtcInstallRoot -Sandbox $script:Sandbox) 'bin\ctc.cmd'
            $shimContent = Get-Content -Raw -LiteralPath $shimPath
            $shimContent | Should -Match 'powershell -NoProfile -File'
            $shimContent | Should -Match '\.\.\\lib\\ctc\.ps1'
            $shimContent | Should -Not -Match 'Bypass'
        }

        It 'records the User PATH update (prints the Added-to-PATH message)' {
            $src = New-CtcInstallFixtureSource -Sandbox $script:Sandbox
            [Environment]::SetEnvironmentVariable('CTC_SRC', $src)
            New-CtcStub -Sandbox $script:Sandbox -Name 'copilot' | Out-Null
            # Add-CtcUserPath's registry-backed branch is gated on
            # $env:OS -eq 'Windows_NT'; simulate Windows so the PATH-update
            # codepath (and its console message) actually runs on macOS too.
            # [Environment]::SetEnvironmentVariable('Path', ..., 'User') is a
            # silent no-op on non-Windows .NET (no exception, no real
            # persistence), so this is safe to run in the sandbox.
            [Environment]::SetEnvironmentVariable('OS', 'Windows_NT')

            $result = Invoke-CtcScript -ScriptPath $script:CtcInstallScriptPath -ScriptArgs @()

            $result.ExitCode | Should -Be 0
            $binDir = Join-Path (Get-CtcInstallRoot -Sandbox $script:Sandbox) 'bin'
            $result.Combined | Should -Match ([regex]::Escape("Added $binDir to your User PATH"))
        }
    }

    Context 'CTC_SRC fetch modes' {
        It 'copies a local-path CTC_SRC verbatim (file copy, no curl)' {
            $src = Join-Path $script:Sandbox.Root 'local-ctc.ps1'
            $marker = '# marker-' + [guid]::NewGuid().ToString('N')
            Set-Content -LiteralPath $src -Value $marker -Encoding ascii
            [Environment]::SetEnvironmentVariable('CTC_SRC', $src)
            New-CtcStub -Sandbox $script:Sandbox -Name 'copilot' | Out-Null

            $result = Invoke-CtcScript -ScriptPath $script:CtcInstallScriptPath -ScriptArgs @()

            $result.ExitCode | Should -Be 0
            $libPath = Join-Path (Get-CtcInstallRoot -Sandbox $script:Sandbox) 'lib\ctc.ps1'
            Get-Content -Raw -LiteralPath $libPath | Should -Match ([regex]::Escape($marker))
            Get-CtcStubLog -Sandbox $script:Sandbox -Name 'curl.exe' | Should -Be ''
        }

        It 'fetches an https:// CTC_SRC via curl.exe with -fsSLk (insecure allowed)' {
            New-CtcStub -Sandbox $script:Sandbox -Name 'curl.exe' -Body @'
prev=""
for a in "$@"; do
  if [ "$prev" = "-o" ]; then printf "# from-https" > "$a"; fi
  prev="$a"
done
'@ | Out-Null
            [Environment]::SetEnvironmentVariable('CTC_SRC', 'https://ctc.local/ctc.ps1')
            New-CtcStub -Sandbox $script:Sandbox -Name 'copilot' | Out-Null

            $result = Invoke-CtcScript -ScriptPath $script:CtcInstallScriptPath -ScriptArgs @()

            $result.ExitCode | Should -Be 0
            Get-CtcStubLog -Sandbox $script:Sandbox -Name 'curl.exe' | Should -Match '-fsSLk'
            $libPath = Join-Path (Get-CtcInstallRoot -Sandbox $script:Sandbox) 'lib\ctc.ps1'
            Get-Content -Raw -LiteralPath $libPath | Should -Match 'from-https'
        }

        It 'fetches a plain http:// CTC_SRC via curl.exe WITHOUT -k' {
            New-CtcStub -Sandbox $script:Sandbox -Name 'curl.exe' -Body @'
prev=""
for a in "$@"; do
  if [ "$prev" = "-o" ]; then printf "# from-http" > "$a"; fi
  prev="$a"
done
'@ | Out-Null
            [Environment]::SetEnvironmentVariable('CTC_SRC', 'http://ctc.local/ctc.ps1')
            New-CtcStub -Sandbox $script:Sandbox -Name 'copilot' | Out-Null

            $result = Invoke-CtcScript -ScriptPath $script:CtcInstallScriptPath -ScriptArgs @()

            $result.ExitCode | Should -Be 0
            $log = Get-CtcStubLog -Sandbox $script:Sandbox -Name 'curl.exe'
            $log | Should -Match '-fsSL'
            $log | Should -Not -Match '-fsSLk'
            $log | Should -Not -Match '(?<!fsS)-k(?!\S)'
        }
    }

    Context 'Copilot CLI bootstrap' {
        It 'does not reinstall when copilot is already on PATH' {
            $src = New-CtcInstallFixtureSource -Sandbox $script:Sandbox
            [Environment]::SetEnvironmentVariable('CTC_SRC', $src)
            New-CtcStub -Sandbox $script:Sandbox -Name 'copilot' | Out-Null
            New-CtcStub -Sandbox $script:Sandbox -Name 'npm' | Out-Null

            $result = Invoke-CtcScript -ScriptPath $script:CtcInstallScriptPath -ScriptArgs @()

            $result.ExitCode | Should -Be 0
            $result.Combined | Should -Match 'Copilot CLI already installed'
            Get-CtcStubLog -Sandbox $script:Sandbox -Name 'npm' | Should -Be ''
        }

        It 'tries npm install -g @github/copilot when copilot is missing and npm is present' {
            $src = New-CtcInstallFixtureSource -Sandbox $script:Sandbox
            [Environment]::SetEnvironmentVariable('CTC_SRC', $src)
            # npm "succeeds" and drops a working copilot stub, like a real
            # `npm install -g` would end up putting `copilot` on PATH.
            $copilotStub = Join-Path $script:Sandbox.Stubs 'copilot'
            New-CtcStub -Sandbox $script:Sandbox -Name 'npm' -Body "printf '#!/bin/sh\nexit 0\n' > `"$copilotStub`"`nchmod +x `"$copilotStub`"" | Out-Null
            # Restrict PATH to the sandbox stub dir plus just enough of the
            # real system bin dirs for the stub scripts themselves (sh,
            # printf, chmod) to run -- Initialize-CtcTestEnv merely prepends
            # the stub dir to the real PATH, so a machine with a real
            # `copilot`/`npm` already installed (e.g. this dev box) would
            # otherwise find them and short-circuit the npm bootstrap.
            [Environment]::SetEnvironmentVariable('PATH', "$($script:Sandbox.Stubs)$([IO.Path]::PathSeparator)/bin$([IO.Path]::PathSeparator)/usr/bin")

            $result = Invoke-CtcScript -ScriptPath $script:CtcInstallScriptPath -ScriptArgs @()

            $result.ExitCode | Should -Be 0
            Get-CtcStubLog -Sandbox $script:Sandbox -Name 'npm' | Should -Match 'install -g @github/copilot'
            $result.Combined | Should -Match 'Copilot CLI installed'
        }

        It 'falls back to winget when npm is absent' {
            $src = New-CtcInstallFixtureSource -Sandbox $script:Sandbox
            [Environment]::SetEnvironmentVariable('CTC_SRC', $src)
            $copilotStub = Join-Path $script:Sandbox.Stubs 'copilot'
            New-CtcStub -Sandbox $script:Sandbox -Name 'winget' -Body "printf '#!/bin/sh\nexit 0\n' > `"$copilotStub`"`nchmod +x `"$copilotStub`"" | Out-Null
            # See the npm test above for why PATH must be restricted to the
            # sandbox stub dir only.
            [Environment]::SetEnvironmentVariable('PATH', "$($script:Sandbox.Stubs)$([IO.Path]::PathSeparator)/bin$([IO.Path]::PathSeparator)/usr/bin")

            $result = Invoke-CtcScript -ScriptPath $script:CtcInstallScriptPath -ScriptArgs @()

            $result.ExitCode | Should -Be 0
            Get-CtcStubLog -Sandbox $script:Sandbox -Name 'winget' | Should -Match 'install --id GitHub\.Copilot'
            $result.Combined | Should -Match 'npm not found -- trying winget'
            $result.Combined | Should -Match 'Copilot CLI installed'
        }

        It 'reports failure when neither npm nor winget can produce a working copilot' {
            $src = New-CtcInstallFixtureSource -Sandbox $script:Sandbox
            [Environment]::SetEnvironmentVariable('CTC_SRC', $src)
            New-CtcStub -Sandbox $script:Sandbox -Name 'npm' -Body 'exit 1' | Out-Null
            # See the npm/winget tests above for why PATH must be restricted
            # to the sandbox stub dir only.
            [Environment]::SetEnvironmentVariable('PATH', "$($script:Sandbox.Stubs)$([IO.Path]::PathSeparator)/bin$([IO.Path]::PathSeparator)/usr/bin")

            $result = Invoke-CtcScript -ScriptPath $script:CtcInstallScriptPath -ScriptArgs @()

            # install.ps1 itself still exits 0 here: a failed copilot bootstrap
            # is a warning, not a fatal install error (mirrors install.sh).
            $result.ExitCode | Should -Be 0
            $result.Combined | Should -Match 'Could not install the GitHub Copilot CLI automatically'
        }
    }

    It 'warns (but continues) when pwsh is not found' {
        $src = New-CtcInstallFixtureSource -Sandbox $script:Sandbox
        [Environment]::SetEnvironmentVariable('CTC_SRC', $src)
        New-CtcStub -Sandbox $script:Sandbox -Name 'copilot' | Out-Null

        # Build a PATH containing ONLY the sandbox stub dir, so `Get-Command
        # pwsh` fails inside the child -- while still launching that child
        # via pwsh's own absolute path (which never consults PATH).
        $envOverrides = @{ PATH = $script:Sandbox.Stubs }
        foreach ($n in $script:CtcEnvNames) {
            $v = [Environment]::GetEnvironmentVariable($n)
            if ($null -ne $v -and $n -ne 'PATH') { $envOverrides[$n] = $v }
        }
        # A restricted PATH alone isn't enough here: this pwsh (at least the
        # Homebrew build used on macOS) silently re-adds its own install
        # directory to $env:PATH on startup, so `Get-Command pwsh` would
        # still resolve itself even with PATH pointed only at the sandbox
        # stub dir. Shadow Get-Command in the child's top-level scope so it
        # reports 'pwsh' as absent while still delegating every other name
        # (copilot/npm/winget/etc.) to the real cmdlet.
        $preamble = @'
function Get-Command {
    param($Name, $ErrorAction = 'Continue')
    if ($Name -eq 'pwsh') {
        if ($ErrorAction -eq 'Stop') { throw "The term 'pwsh' is not recognized." }
        return $null
    }
    Microsoft.PowerShell.Core\Get-Command -Name $Name -ErrorAction $ErrorAction
}
'@
        $result = Invoke-CtcInstallChild -ScriptArgs @() -EnvOverrides $envOverrides -Preamble $preamble

        $result.ExitCode | Should -Be 0
        $result.Combined | Should -Match 'pwsh \(PowerShell 7\) was not found'
    }

    Context 'ExecutionPolicy preflight' {
        It 'blocks the install and prints the RemoteSigned hint when the effective policy is Restricted' {
            [Environment]::SetEnvironmentVariable('CTC_SKIP_EXECPOLICY_CHECK', $null)
            $src = New-CtcInstallFixtureSource -Sandbox $script:Sandbox
            [Environment]::SetEnvironmentVariable('CTC_SRC', $src)

            # Shadow the built-in Get-ExecutionPolicy cmdlet for the duration
            # of this one child process: install.ps1 is invoked (not
            # dot-sourced) via the call operator, so PowerShell's normal
            # function-over-cmdlet precedence makes this override apply
            # inside it without touching the real (non-Windows) policy.
            $preamble = "function Get-ExecutionPolicy { 'Restricted' }"
            $result = Invoke-CtcInstallChild -Preamble $preamble

            $result.ExitCode | Should -Not -Be 0
            $result.Combined | Should -Match 'Set-ExecutionPolicy -Scope CurrentUser RemoteSigned'
            $root = Get-CtcInstallRoot -Sandbox $script:Sandbox
            Test-Path -LiteralPath $root | Should -BeFalse
        }
    }

    Context '-Token auto-login' {
        It 'runs ctc login -Token non-interactively and writes env.json with the token' {
            $src = New-CtcInstallLoginStubSource -Sandbox $script:Sandbox
            [Environment]::SetEnvironmentVariable('CTC_SRC', $src)
            New-CtcStub -Sandbox $script:Sandbox -Name 'copilot' | Out-Null

            $result = Invoke-CtcScript -ScriptPath $script:CtcInstallScriptPath -ScriptArgs @('-Token', 'github_pat_INSTALLTOK99') -StdIn ''

            $result.ExitCode | Should -Be 0
            $envPath = Join-Path (Get-CtcTestConfigDir) 'env.json'
            $envPath | Should -Exist
            (Get-Content -Raw -LiteralPath $envPath) | Should -Match 'github_pat_INSTALLTOK99'
        }

        It 'does not auto-login when -Token is omitted' {
            $src = New-CtcInstallLoginStubSource -Sandbox $script:Sandbox
            [Environment]::SetEnvironmentVariable('CTC_SRC', $src)
            New-CtcStub -Sandbox $script:Sandbox -Name 'copilot' | Out-Null

            $result = Invoke-CtcScript -ScriptPath $script:CtcInstallScriptPath -ScriptArgs @()

            $result.ExitCode | Should -Be 0
            $result.Combined | Should -Match 'Next: ctc login'
            $envPath = Join-Path (Get-CtcTestConfigDir) 'env.json'
            $envPath | Should -Not -Exist
        }
    }

    Context 'non-Windows guard' {
        It 'refuses to run on non-Windows without CTC_ALLOW_NON_WINDOWS' {
            [Environment]::SetEnvironmentVariable('CTC_ALLOW_NON_WINDOWS', $null)
            [Environment]::SetEnvironmentVariable('OS', $null)
            $src = New-CtcInstallFixtureSource -Sandbox $script:Sandbox
            [Environment]::SetEnvironmentVariable('CTC_SRC', $src)

            $result = Invoke-CtcScript -ScriptPath $script:CtcInstallScriptPath -ScriptArgs @()

            $result.ExitCode | Should -Not -Be 0
            $result.Combined | Should -Match 'Windows only for now'
            Test-Path -LiteralPath (Get-CtcInstallRoot -Sandbox $script:Sandbox) | Should -BeFalse
        }
    }
}
