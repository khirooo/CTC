# Pester port of cli/tests/test_launch.sh — exercises `ctc copilot` (and the
# bare/default dispatch into it) as a real child process via Invoke-CtcScript,
# with stub `copilot`/`curl.exe` executables shadowing PATH. Mirrors the bash
# suite's scenarios one-for-one; see the comment above each Describe block for
# the corresponding bash test function.

BeforeAll {
    . (Join-Path $PSScriptRoot 'Common.ps1')

    # Bounded poll for a file written by the background update-check runspace —
    # mirrors bash's _wait_for_verdict (20 x 0.25s = 5s ceiling).
    function Wait-CtcTestFile {
        param([string]$Path, [int]$TimeoutMs = 5000, [int]$StepMs = 250)
        $elapsed = 0
        while ($elapsed -lt $TimeoutMs) {
            if (Test-Path -LiteralPath $Path) { return $true }
            Start-Sleep -Milliseconds $StepMs
            $elapsed += $StepMs
        }
        return (Test-Path -LiteralPath $Path)
    }

    # True on Windows (real PS 5.1/7) where NO_PROXY and no_proxy are the SAME
    # environment variable (case-insensitive names) -- unlike POSIX/macOS where
    # they are distinct. Tests that set both to different values must branch on
    # this; see test_launch.sh's test_launch_leaves_no_proxy_alone_when_unset.
    $script:CtcIsWindowsEnv = ($env:OS -eq 'Windows_NT')
}

Describe 'Invoke-CtcCopilot (ctc copilot / ctc passthrough args)' {
    BeforeEach {
        $script:SavedEnv = Save-CtcTestEnv
        $script:Sandbox = New-CtcTestSandbox
        Initialize-CtcTestEnv -Sandbox $script:Sandbox
    }

    AfterEach {
        Remove-CtcTestSandbox -Sandbox $script:Sandbox
        Restore-CtcTestEnv -Saved $script:SavedEnv
    }

    # test_launch_without_config_prompts_login
    It 'exits 1 and tells the user to run ctc login when no env.json exists' {
        $result = Invoke-CtcScript -ScriptArgs @('copilot')
        $result.ExitCode | Should -Be 1
        $result.Combined | Should -Match 'ctc login'
    }

    # test_launch_execs_copilot_with_isolated_env
    It 'launches copilot with the isolated env and passes args through verbatim, incl. args starting with -' {
        $login = Write-CtcLoginEnvJson -Sandbox $script:Sandbox -GhHost 'example.ghe.com' `
            -Token 'github_pat_TESTTOKEN1234' -Proxy 'http://ctc.local:8080'
        New-CtcStub -Sandbox $script:Sandbox -Name 'copilot' -Body (
            'echo "HOME=$HOME USERPROFILE=$USERPROFILE GH=$GH_HOST PROXY=$HTTPS_PROXY ARGS=$*" > "$HOME/copilot_out"'
        ) | Out-Null

        $result = Invoke-CtcScript -ScriptArgs @('copilot', '-p', 'hello world', '--foo', '-xyz')

        $result.ExitCode | Should -Be 0
        $rec = Get-Content -Raw -LiteralPath (Join-Path $login.IsoHome 'copilot_out')
        $rec | Should -Match ([regex]::Escape("HOME=$($login.IsoHome)"))
        $rec | Should -Match ([regex]::Escape("USERPROFILE=$($login.IsoHome)"))
        $rec | Should -Match 'GH=example\.ghe\.com'
        $rec | Should -Match ([regex]::Escape('PROXY=http://ctc.local:8080'))
        $rec | Should -Match ([regex]::Escape('ARGS=-p hello world --foo -xyz'))
        # The token must never show up as a command-line argument the child
        # received -- only as the COPILOT_GITHUB_TOKEN env var it inherited.
        $rec | Should -Not -Match 'github_pat_TESTTOKEN1234'
        $result.Combined | Should -Not -Match 'github_pat_TESTTOKEN1234'
    }

    # args starting with '-' also reach copilot via the bare/default dispatch
    # (no explicit 'copilot' subcommand) -- Invoke-CtcMain's `$cmd.StartsWith('-')` branch.
    It 'passes dash-prefixed args through verbatim via the bare default dispatch too' {
        $login = Write-CtcLoginEnvJson -Sandbox $script:Sandbox
        New-CtcStub -Sandbox $script:Sandbox -Name 'copilot' -Body (
            'echo "ARGS=$*" > "$HOME/copilot_out"'
        ) | Out-Null

        $result = Invoke-CtcScript -ScriptArgs @('-p', 'hello')

        $result.ExitCode | Should -Be 0
        $rec = Get-Content -Raw -LiteralPath (Join-Path $login.IsoHome 'copilot_out')
        $rec | Should -Match ([regex]::Escape('ARGS=-p hello'))
    }

    # Exercises COPILOT_GITHUB_TOKEN/NODE_EXTRA_CA_CERTS reaching the child too
    # (test_launch_execs_copilot_with_isolated_env checks GH_HOST/HOME/PROXY;
    # the plan additionally calls out COPILOT_GITHUB_TOKEN and NODE_EXTRA_CA_CERTS).
    It 'exposes COPILOT_GITHUB_TOKEN and NODE_EXTRA_CA_CERTS to the child env' {
        $login = Write-CtcLoginEnvJson -Sandbox $script:Sandbox -Token 'github_pat_TESTTOKEN1234'
        New-CtcStub -Sandbox $script:Sandbox -Name 'copilot' -Body (
            'echo "TOK=$COPILOT_GITHUB_TOKEN CA=$NODE_EXTRA_CA_CERTS" > "$HOME/copilot_out"'
        ) | Out-Null

        $result = Invoke-CtcScript -ScriptArgs @('copilot')

        $result.ExitCode | Should -Be 0
        $rec = Get-Content -Raw -LiteralPath (Join-Path $login.IsoHome 'copilot_out')
        $rec | Should -Match ([regex]::Escape('TOK=github_pat_TESTTOKEN1234'))
        $rec | Should -Match ([regex]::Escape("CA=$($login.CertPath)"))
    }

    # test_launch -- the child's exit code must propagate as ctc's own.
    It "propagates the child copilot process's exit code" {
        Write-CtcLoginEnvJson -Sandbox $script:Sandbox | Out-Null
        New-CtcStub -Sandbox $script:Sandbox -Name 'copilot' -Body 'exit 7' | Out-Null

        $result = Invoke-CtcScript -ScriptArgs @('copilot')

        $result.ExitCode | Should -Be 7
    }

    # test_launch_prints_banner
    It 'prints the CTC banner' {
        Write-CtcLoginEnvJson -Sandbox $script:Sandbox | Out-Null
        New-CtcStub -Sandbox $script:Sandbox -Name 'copilot' -Body ':' | Out-Null

        $result = Invoke-CtcScript -ScriptArgs @('copilot')

        $result.Combined | Should -Match 'CTC mode'
    }

    # test_launch_without_discovery_dir_still_runs -- no ~/.copilot/ide at all.
    It 'still launches and prints the banner when there is no ~/.copilot/ide discovery dir' {
        Write-CtcLoginEnvJson -Sandbox $script:Sandbox | Out-Null
        New-CtcStub -Sandbox $script:Sandbox -Name 'copilot' -Body ':' | Out-Null

        $result = Invoke-CtcScript -ScriptArgs @('copilot')

        $result.ExitCode | Should -Be 0
        $result.Combined | Should -Match 'CTC mode'
    }

    # Missing `copilot` on PATH -> install hint, exit 1.
    It "exits 1 with an install hint when 'copilot' is not on PATH" {
        Write-CtcLoginEnvJson -Sandbox $script:Sandbox | Out-Null
        # No copilot stub created. Restrict PATH to the (now-empty) stubs
        # dir plus the system dirs ctc.ps1/the child process itself need
        # (sh/etc.) -- Initialize-CtcTestEnv merely prepends the stub dir to
        # the real PATH, so a machine with a real `copilot` already
        # installed (e.g. this dev box) would otherwise be found instead of
        # exercising the "not found" codepath.
        [Environment]::SetEnvironmentVariable('PATH', "$($script:Sandbox.Stubs)$([IO.Path]::PathSeparator)/bin$([IO.Path]::PathSeparator)/usr/bin")

        $result = Invoke-CtcScript -ScriptArgs @('copilot')

        $result.ExitCode | Should -Be 1
        $result.Combined | Should -Match 'not found on PATH'
        $result.Combined | Should -Match 'npm install -g @github/copilot'
    }
}

Describe 'Invoke-CtcCopilot /ide bridge' {
    BeforeEach {
        $script:SavedEnv = Save-CtcTestEnv
        $script:Sandbox = New-CtcTestSandbox
        Initialize-CtcTestEnv -Sandbox $script:Sandbox
        New-CtcStub -Sandbox $script:Sandbox -Name 'copilot' -Body ':' | Out-Null
    }

    AfterEach {
        Remove-CtcTestSandbox -Sandbox $script:Sandbox
        Restore-CtcTestEnv -Saved $script:SavedEnv
    }

    # test_launch_bridges_ide_discovery_path_into_isolated_home
    It "links the real ~/.copilot/ide into the isolated home (symlink in test mode; assert the link target)" {
        # $Sandbox.Home is the *real* USERPROFILE/HOME before isolation kicks
        # in (Set-CtcIsolationEnv overwrites it with the isolated home).
        $realIde = Join-Path $script:Sandbox.Home '.copilot\ide'
        New-Item -ItemType Directory -Path $realIde -Force | Out-Null
        'workspace-marker' | Set-Content -LiteralPath (Join-Path $realIde 'registry.json')

        $login = Write-CtcLoginEnvJson -Sandbox $script:Sandbox

        $result = Invoke-CtcScript -ScriptArgs @('copilot')
        $result.ExitCode | Should -Be 0

        $isoIde = Join-Path $login.IsoHome '.copilot\ide'
        $linkItem = Get-Item -LiteralPath $isoIde -Force
        $linkItem.Attributes -band [IO.FileAttributes]::ReparsePoint | Should -Not -Be 0
        # On real Windows this is a Junction; in test mode (non-Windows) ctc.ps1
        # falls back to a SymbolicLink -- either way .Target must resolve to the
        # real ide dir.
        ($linkItem.Target -join '') | Should -Match ([regex]::Escape($realIde))

        $bridged = Join-Path $isoIde 'registry.json'
        Get-Content -Raw -LiteralPath $bridged | Should -Match 'workspace-marker'
    }

    # test_launch_bridges_even_when_stale_empty_ide_dir_exists
    It 'replaces a stale empty isolated ide dir left behind by a previous run' {
        $realIde = Join-Path $script:Sandbox.Home '.copilot\ide'
        New-Item -ItemType Directory -Path $realIde -Force | Out-Null
        'live-lock' | Set-Content -LiteralPath (Join-Path $realIde 'conn.lock')

        $login = Write-CtcLoginEnvJson -Sandbox $script:Sandbox
        # Stale, empty isolated ide dir from an earlier run -- NOT a link.
        $staleIde = Join-Path $login.IsoHome '.copilot\ide'
        New-Item -ItemType Directory -Path $staleIde -Force | Out-Null

        $result = Invoke-CtcScript -ScriptArgs @('copilot')
        $result.ExitCode | Should -Be 0

        $bridged = Join-Path $staleIde 'conn.lock'
        Get-Content -Raw -LiteralPath $bridged | Should -Match 'live-lock'
    }

    # test_launch_does_not_share_rest_of_copilot_dir
    It 'does not share the rest of .copilot (only .copilot/ide is bridged)' {
        $realCopilot = Join-Path $script:Sandbox.Home '.copilot'
        New-Item -ItemType Directory -Path (Join-Path $realCopilot 'ide') -Force | Out-Null
        'real-token' | Set-Content -LiteralPath (Join-Path $realCopilot 'config.json')

        $login = Write-CtcLoginEnvJson -Sandbox $script:Sandbox

        $result = Invoke-CtcScript -ScriptArgs @('copilot')
        $result.ExitCode | Should -Be 0

        Test-Path -LiteralPath (Join-Path $login.IsoHome '.copilot\config.json') | Should -BeFalse
    }

    # test_launch_without_discovery_dir_still_runs (ide-bridge angle: the real
    # ide dir is simply missing -- bridge is a silent no-op, launch still works).
    It 'still launches when the real ide discovery dir is missing' {
        Write-CtcLoginEnvJson -Sandbox $script:Sandbox | Out-Null
        # No .copilot/ide under $Sandbox.Home at all.

        $result = Invoke-CtcScript -ScriptArgs @('copilot')

        $result.ExitCode | Should -Be 0
        $result.Combined | Should -Match 'CTC mode'
    }
}

Describe 'Set-CtcNoProxyEnv (NO_PROXY/no_proxy merge at launch)' {
    BeforeEach {
        $script:SavedEnv = Save-CtcTestEnv
        $script:Sandbox = New-CtcTestSandbox
        Initialize-CtcTestEnv -Sandbox $script:Sandbox
        $script:Login = Write-CtcLoginEnvJson -Sandbox $script:Sandbox -Proxy 'http://ctc.local:8080'
        New-CtcStub -Sandbox $script:Sandbox -Name 'copilot' -Body (
            'echo "NP=${NO_PROXY:-} np=${no_proxy:-}" > "$HOME/copilot_out"'
        ) | Out-Null
    }

    AfterEach {
        Remove-CtcTestSandbox -Sandbox $script:Sandbox
        Restore-CtcTestEnv -Saved $script:SavedEnv
    }

    # test_launch_exports_ctc_no_proxy_hosts
    It 'appends CTC_NO_PROXY to NO_PROXY and mirrors it into no_proxy when both are unset' {
        $env:CTC_NO_PROXY = 'jira.corp.example,corp.example'
        $env:NO_PROXY = ''
        $env:no_proxy = ''

        $result = Invoke-CtcScript -ScriptArgs @('copilot')
        $result.ExitCode | Should -Be 0

        $rec = Get-Content -Raw -LiteralPath (Join-Path $script:Login.IsoHome 'copilot_out')
        $rec | Should -Match ([regex]::Escape('NP=jira.corp.example,corp.example'))
        $rec | Should -Match ([regex]::Escape('np=jira.corp.example,corp.example'))
    }

    # test_launch_keeps_users_existing_no_proxy
    It 'keeps and extends an existing NO_PROXY rather than replacing it' {
        $env:CTC_NO_PROXY = 'jira.corp.example'
        $env:NO_PROXY = 'localhost,127.0.0.1'

        $result = Invoke-CtcScript -ScriptArgs @('copilot')
        $result.ExitCode | Should -Be 0

        $rec = Get-Content -Raw -LiteralPath (Join-Path $script:Login.IsoHome 'copilot_out')
        $rec | Should -Match ([regex]::Escape('NP=localhost,127.0.0.1,jira.corp.example'))
        $rec | Should -Match ([regex]::Escape('np=localhost,127.0.0.1,jira.corp.example'))
    }

    # test_launch_leaves_no_proxy_alone_when_unset
    It 'leaves NO_PROXY/no_proxy untouched when CTC_NO_PROXY is empty' {
        $env:CTC_NO_PROXY = ''
        $env:NO_PROXY = 'localhost'
        if (-not $script:CtcIsWindowsEnv) {
            # On POSIX, NO_PROXY and no_proxy are genuinely distinct vars --
            # the bash test explicitly sets no_proxy='' to prove ctc doesn't
            # invent/mirror a value when there's nothing to append. On
            # Windows this is the SAME variable as NO_PROXY, so setting it
            # separately here would just stomp the value above; skip it.
            $env:no_proxy = ''
        }

        $result = Invoke-CtcScript -ScriptArgs @('copilot')
        $result.ExitCode | Should -Be 0

        $rec = Get-Content -Raw -LiteralPath (Join-Path $script:Login.IsoHome 'copilot_out')
        if ($script:CtcIsWindowsEnv) {
            # Same variable under the hood -- both reads see 'localhost'.
            $rec | Should -Match ([regex]::Escape('NP=localhost np=localhost'))
        } else {
            $rec | Should -Match ([regex]::Escape('NP=localhost np='))
        }
    }
}

Describe 'Invoke-CtcCheckLauncherUpdate (background update check)' {
    BeforeAll {
        # Writes a curl.exe stub that "serves" $ServedPath as the body of the
        # -o target, mirroring the bash suite's _update_fixture. Defined here
        # (rather than at script scope) so it is visible during Pester's Run
        # phase, not just Discovery.
        function New-CtcCurlServeStub {
            param($Sandbox, [string]$ServedPath)
            $body = @"
prev=""
for a in "`$@"; do
  if [ "`$prev" = "-o" ]; then cp "$ServedPath" "`$a"; fi
  prev="`$a"
done
"@
            New-CtcStub -Sandbox $Sandbox -Name 'curl.exe' -Body $body | Out-Null
        }
    }

    BeforeEach {
        $script:SavedEnv = Save-CtcTestEnv
        $script:Sandbox = New-CtcTestSandbox
        Initialize-CtcTestEnv -Sandbox $script:Sandbox
        $script:Login = Write-CtcLoginEnvJson -Sandbox $script:Sandbox
        $script:StatePath = Join-Path $script:Login.ConfigDir 'launcher-check'
        New-CtcStub -Sandbox $script:Sandbox -Name 'copilot' -Body ':' | Out-Null
    }

    AfterEach {
        Remove-CtcTestSandbox -Sandbox $script:Sandbox
        Restore-CtcTestEnv -Saved $script:SavedEnv
    }

    # test_update_check_quiet_when_launcher_matches_server
    It 'records "ok" and does not warn on the next launch when the served launcher is identical' {
        $served = Join-Path $script:Sandbox.Root 'served.ps1'
        Copy-Item -LiteralPath $script:CtcScriptPath -Destination $served
        New-CtcCurlServeStub -Sandbox $script:Sandbox -ServedPath $served
        $env:CTC_UPDATE_CHECK = '1'

        Invoke-CtcScript -ScriptArgs @('copilot') | Out-Null
        Wait-CtcTestFile -Path $script:StatePath | Should -BeTrue
        (Get-Content -LiteralPath $script:StatePath)[1] | Should -Be 'ok'

        $result = Invoke-CtcScript -ScriptArgs @('copilot')
        $result.Combined | Should -Not -Match 'out of date'
    }

    # test_update_check_warns_on_next_launch_when_server_differs
    It 'records "stale" and warns on the NEXT launch (with the PowerShell update command) when the server differs' {
        $served = Join-Path $script:Sandbox.Root 'served.ps1'
        Copy-Item -LiteralPath $script:CtcScriptPath -Destination $served
        Add-Content -LiteralPath $served -Value '# newer'
        New-CtcCurlServeStub -Sandbox $script:Sandbox -ServedPath $served
        $env:CTC_UPDATE_CHECK = '1'

        Invoke-CtcScript -ScriptArgs @('copilot') | Out-Null
        Wait-CtcTestFile -Path $script:StatePath | Should -BeTrue
        (Get-Content -LiteralPath $script:StatePath)[1] | Should -Be 'stale'

        $result = Invoke-CtcScript -ScriptArgs @('copilot')
        $result.Combined | Should -Match 'out of date'
        $result.Combined | Should -Match 'powershell -NoProfile -File'
    }

    # test_update_check_warns_on_next_launch_when_server_differs (CRLF/BOM clause)
    It 'treats a served copy differing only by CRLF/BOM as identical' {
        $bytes = [IO.File]::ReadAllBytes($script:CtcScriptPath)
        $text = ([Text.Encoding]::UTF8.GetString($bytes) -replace "`r`n", "`n") -replace "`n", "`r`n"
        $withBom = [byte[]](0xEF, 0xBB, 0xBF) + [Text.Encoding]::UTF8.GetBytes($text)
        $served = Join-Path $script:Sandbox.Root 'served-crlf-bom.ps1'
        [IO.File]::WriteAllBytes($served, $withBom)
        New-CtcCurlServeStub -Sandbox $script:Sandbox -ServedPath $served
        $env:CTC_UPDATE_CHECK = '1'

        Invoke-CtcScript -ScriptArgs @('copilot') | Out-Null
        Wait-CtcTestFile -Path $script:StatePath | Should -BeTrue
        (Get-Content -LiteralPath $script:StatePath)[1] | Should -Be 'ok'
    }

    # test_update_check_fetches_at_most_once_a_day
    It 'does not re-fetch when the recorded verdict is less than a day old' {
        $callLog = Join-Path $script:Sandbox.Root 'curl-calls.log'
        New-CtcStub -Sandbox $script:Sandbox -Name 'curl.exe' -Body "echo called >> `"$callLog`"" | Out-Null
        $now = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
        New-Item -ItemType Directory -Path $script:Login.ConfigDir -Force | Out-Null
        Set-Content -LiteralPath $script:StatePath -Value "$now`nok" -NoNewline
        $env:CTC_UPDATE_CHECK = '1'

        $result = Invoke-CtcScript -ScriptArgs @('copilot')
        Start-Sleep -Milliseconds 500

        $result.ExitCode | Should -Be 0
        Test-Path -LiteralPath $callLog | Should -BeFalse
    }

    # test_update_check_failed_fetch_records_nothing
    It 'records nothing and still succeeds when the fetch fails' {
        New-CtcStub -Sandbox $script:Sandbox -Name 'curl.exe' -Body 'exit 7' | Out-Null
        $env:CTC_UPDATE_CHECK = '1'

        $result = Invoke-CtcScript -ScriptArgs @('copilot')
        Start-Sleep -Milliseconds 500

        $result.ExitCode | Should -Be 0
        Test-Path -LiteralPath $script:StatePath | Should -BeFalse
    }
}
