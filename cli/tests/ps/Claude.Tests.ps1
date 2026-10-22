# Pester tests for `ctc claude`: Install-CtcClaudeStatusline (statusline.ps1 +
# never-clobber settings.json merge) exercised in-process via dot-sourcing, and
# the Invoke-CtcClaude launch path exercised as a real child process with a
# PATH-first stub `claude` (same pattern Launch.Tests.ps1 uses for copilot).
# Behavioral references: cli/tests/test_statusline.sh, cli/tests/test_menu.sh.
# Never touches the network or the real profile: GHE_DOMAIN points at a
# reserved .invalid name and a fresh prices.json is pre-seeded so the
# background price refresh short-circuits before any request.

Describe 'Install-CtcClaudeStatusline' {
    BeforeAll {
        . (Join-Path $PSScriptRoot 'Common.ps1')
        . $script:CtcScriptPath

        function Read-ClSettings {
            param([string]$IsoHome)
            return (Get-Content -Raw -LiteralPath (Join-Path (Join-Path $IsoHome '.claude') 'settings.json') | ConvertFrom-Json)
        }
        function Get-ClBytes {
            param([string]$Path)
            return [IO.File]::ReadAllBytes($Path)
        }
        function Test-ClBom {
            param([byte[]]$Bytes)
            return ($Bytes.Length -ge 3 -and $Bytes[0] -eq 0xEF -and $Bytes[1] -eq 0xBB -and $Bytes[2] -eq 0xBF)
        }
    }

    BeforeEach {
        $script:SavedEnv = Save-CtcTestEnv
        $script:Sandbox = New-CtcTestSandbox
        Initialize-CtcTestEnv -Sandbox $script:Sandbox
        $script:Iso = Join-Path $script:Sandbox.Root 'iso-home'
        $script:ClaudeDir = Join-Path $script:Iso '.claude'
        $script:SettingsPath = Join-Path $script:ClaudeDir 'settings.json'
        $script:SlPath = Join-Path $script:ClaudeDir 'statusline.ps1'
    }

    AfterEach {
        Remove-CtcTestSandbox -Sandbox $script:Sandbox
        Restore-CtcTestEnv -Saved $script:SavedEnv
    }

    It 'is a no-op for an empty IsoHome' {
        { Install-CtcClaudeStatusline -IsoHome '' } | Should -Not -Throw
        Test-Path -LiteralPath $script:ClaudeDir | Should -BeFalse
    }

    It 'creates .claude, statusline.ps1 and settings.json when absent' {
        Install-CtcClaudeStatusline -IsoHome $script:Iso

        Test-Path -LiteralPath $script:SlPath -PathType Leaf | Should -BeTrue
        Test-Path -LiteralPath $script:SettingsPath -PathType Leaf | Should -BeTrue
        $s = Read-ClSettings -IsoHome $script:Iso
        @($s.PSObject.Properties.Name) | Should -Be @('statusLine')
        $s.statusLine.type | Should -Be 'command'
        $s.statusLine.padding | Should -Be 0
        $s.statusLine.command | Should -Match ([regex]::Escape("-NoProfile -NonInteractive -File `"$script:SlPath`""))
    }

    It 'writes the embedded statusline source verbatim' {
        Install-CtcClaudeStatusline -IsoHome $script:Iso
        [IO.File]::ReadAllText($script:SlPath) | Should -BeExactly $script:CtcStatuslineSource
    }

    It 'merges into an existing settings.json, preserving every other key (incl. nested and non-ASCII)' {
        New-Item -ItemType Directory -Path $script:ClaudeDir -Force | Out-Null
        $existing = '{"model":"claude-sonnet-5","permissions":{"allow":["Bash(ls)"],"deny":[]},"env":{"FOO":"bär ✨"},"cleanupPeriodDays":30,"includeCoAuthoredBy":false,"statusLine":{"type":"command","command":"old","padding":4}}'
        [IO.File]::WriteAllText($script:SettingsPath, $existing, (New-Object System.Text.UTF8Encoding($false)))

        Install-CtcClaudeStatusline -IsoHome $script:Iso

        $s = Read-ClSettings -IsoHome $script:Iso
        $s.model | Should -Be 'claude-sonnet-5'
        @($s.permissions.allow) | Should -Be @('Bash(ls)')
        $s.permissions.PSObject.Properties.Name | Should -Contain 'deny'
        @($s.permissions.deny).Count | Should -Be 0
        $s.env.FOO | Should -BeExactly 'bär ✨'
        $s.cleanupPeriodDays | Should -Be 30
        $s.includeCoAuthoredBy | Should -BeFalse
        $s.statusLine.command | Should -Not -Be 'old'
        $s.statusLine.command | Should -Match 'statusline\.ps1'
        $s.statusLine.padding | Should -Be 0
        @($s.PSObject.Properties.Name | Where-Object { $_ -eq 'statusLine' }).Count | Should -Be 1
    }

    It 'keeps an empty JSON array an array (not null/scalar) after the merge' {
        New-Item -ItemType Directory -Path $script:ClaudeDir -Force | Out-Null
        [IO.File]::WriteAllText($script:SettingsPath, '{"a":[],"b":["x"],"c":{}}')
        Install-CtcClaudeStatusline -IsoHome $script:Iso
        $raw = Get-Content -Raw -LiteralPath $script:SettingsPath
        $raw | Should -Match '"a":\s*\[\s*\]'
        $raw | Should -Match '"b":\s*\[\s*"x"\s*\]'
        $raw | Should -Match '"c":\s*\{\s*\}'
    }

    It 'preserves deeply nested settings (python json.dumps has no depth limit)' {
        New-Item -ItemType Directory -Path $script:ClaudeDir -Force | Out-Null
        $deep = '{"l1":{"l2":{"l3":{"l4":{"l5":{"l6":{"l7":{"l8":{"l9":{"l10":{"l11":{"leaf":"v"}}}}}}}}}}}}'
        [IO.File]::WriteAllText($script:SettingsPath, $deep)
        Install-CtcClaudeStatusline -IsoHome $script:Iso 3>$null
        $s = Read-ClSettings -IsoHome $script:Iso
        $s.l1.l2.l3.l4.l5.l6.l7.l8.l9.l10.l11.leaf | Should -Be 'v'
    }

    It 'is idempotent: a second run yields byte-identical files' {
        New-Item -ItemType Directory -Path $script:ClaudeDir -Force | Out-Null
        [IO.File]::WriteAllText($script:SettingsPath, '{"model":"claude-opus-5","theme":"dark"}')
        Install-CtcClaudeStatusline -IsoHome $script:Iso
        $first = Get-ClBytes $script:SettingsPath
        $firstSl = Get-ClBytes $script:SlPath
        Install-CtcClaudeStatusline -IsoHome $script:Iso
        Install-CtcClaudeStatusline -IsoHome $script:Iso
        (Get-ClBytes $script:SettingsPath) | Should -Be $first
        (Get-ClBytes $script:SlPath) | Should -Be $firstSl
        (Read-ClSettings -IsoHome $script:Iso).theme | Should -Be 'dark'
    }

    It 'replaces a corrupt settings.json with a fresh object (mirrors bash: except -> d = {})' {
        New-Item -ItemType Directory -Path $script:ClaudeDir -Force | Out-Null
        [IO.File]::WriteAllText($script:SettingsPath, '{ this is : not json')
        Install-CtcClaudeStatusline -IsoHome $script:Iso
        $s = Read-ClSettings -IsoHome $script:Iso
        @($s.PSObject.Properties.Name) | Should -Be @('statusLine')
    }

    It 'replaces a non-object settings.json (JSON array) with a fresh object' {
        New-Item -ItemType Directory -Path $script:ClaudeDir -Force | Out-Null
        [IO.File]::WriteAllText($script:SettingsPath, '[1,2,3]')
        Install-CtcClaudeStatusline -IsoHome $script:Iso
        $s = Read-ClSettings -IsoHome $script:Iso
        $s | Should -BeOfType [System.Management.Automation.PSCustomObject]
        @($s.PSObject.Properties.Name) | Should -Be @('statusLine')
    }

    It 'reads an existing settings.json that starts with a UTF-8 BOM' {
        New-Item -ItemType Directory -Path $script:ClaudeDir -Force | Out-Null
        [IO.File]::WriteAllText($script:SettingsPath, '{"keepme":1}', (New-Object System.Text.UTF8Encoding($true)))
        Install-CtcClaudeStatusline -IsoHome $script:Iso
        (Read-ClSettings -IsoHome $script:Iso).keepme | Should -Be 1
    }

    It 'bakes pwsh into the command when pwsh is available' {
        Mock Get-Command -ParameterFilter { $Name -eq 'pwsh' } -MockWith { [PSCustomObject]@{ Name = 'pwsh'; Source = '/fake/pwsh' } }
        Install-CtcClaudeStatusline -IsoHome $script:Iso
        (Read-ClSettings -IsoHome $script:Iso).statusLine.command | Should -BeExactly ('pwsh -NoProfile -NonInteractive -File "{0}"' -f $script:SlPath)
    }

    It 'falls back to powershell when pwsh is not on PATH' {
        Mock Get-Command -ParameterFilter { $Name -eq 'pwsh' } -MockWith { $null }
        Install-CtcClaudeStatusline -IsoHome $script:Iso
        (Read-ClSettings -IsoHome $script:Iso).statusLine.command | Should -BeExactly ('powershell -NoProfile -NonInteractive -File "{0}"' -f $script:SlPath)
    }

    It 'writes statusline.ps1 as UTF-8 WITH BOM and settings.json as UTF-8 WITHOUT BOM, with a trailing newline on settings.json' {
        Install-CtcClaudeStatusline -IsoHome $script:Iso
        $sl = Get-ClBytes $script:SlPath
        $st = Get-ClBytes $script:SettingsPath
        Test-ClBom $sl | Should -BeTrue -Because 'PS 5.1 reads BOM-less .ps1 files as ANSI, mangling the non-ASCII glyphs'
        Test-ClBom $st | Should -BeFalse -Because "Node's JSON.parse rejects a leading BOM in settings.json"
        $st[$st.Length - 1] | Should -Be 10
        # Strictly valid UTF-8 (throws on invalid sequences).
        $strict = New-Object System.Text.UTF8Encoding($false, $true)
        { $strict.GetString($sl) } | Should -Not -Throw
        { $strict.GetString($st) } | Should -Not -Throw
        # The non-ASCII glyphs the statusline renders survive the round-trip.
        $strict.GetString($sl, 3, $sl.Length - 3) | Should -BeExactly $script:CtcStatuslineSource
    }

    It 'produces a command that actually renders the statusline' {
        Install-CtcClaudeStatusline -IsoHome $script:Iso
        $cmd = (Read-ClSettings -IsoHome $script:Iso).statusLine.command
        $m = [regex]::Match($cmd, '^(\S+) -NoProfile -NonInteractive -File "(.+)"$')
        $m.Success | Should -BeTrue
        $m.Groups[2].Value | Should -Be $script:SlPath
        $out = '{"model":{"display_name":"Sonnet 5"}}' | & $script:CtcPwshExe -NoProfile -NonInteractive -File $m.Groups[2].Value
        $LASTEXITCODE | Should -Be 0
        ($out -join '') | Should -Match 'CTC'
        ($out -join '') | Should -Match 'AIU'
    }
}

Describe 'Invoke-CtcClaude (ctc claude)' {
    BeforeAll {
        . (Join-Path $PSScriptRoot 'Common.ps1')

        # Logs in, pins GHE_DOMAIN to a reserved non-resolvable name, and seeds
        # a fresh prices.json at the exact path the price-refresh runspace
        # checks (it joins '.claude\prices.json' literally) so it returns
        # before issuing any request.
        function Initialize-ClLaunch {
            param($Sandbox, [hashtable]$ExtraEnv = @{})
            $login = Write-CtcLoginEnvJson -Sandbox $Sandbox -GhHost 'example.ghe.com' -Token 'github_pat_TESTTOKEN1234' -Proxy 'http://ctc.local:8080' -ExtraEnv $ExtraEnv
            [Environment]::SetEnvironmentVariable('GHE_DOMAIN', 'example.invalid')
            $now = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
            $payload = '{"fetched":' + $now + ',"prices":{"claude-sonnet-4.6":[330,1650,33,412]}}'
            foreach ($p in @((Join-Path $login.IsoHome '.claude\prices.json'), (Join-Path (Join-Path $login.IsoHome '.claude') 'prices.json'))) {
                New-Item -ItemType Directory -Path (Split-Path -Parent $p) -Force -ErrorAction SilentlyContinue | Out-Null
                [IO.File]::WriteAllText($p, $payload)
            }
            return $login
        }
    }

    BeforeEach {
        $script:SavedEnv = Save-CtcTestEnv
        $script:Sandbox = New-CtcTestSandbox
        Initialize-CtcTestEnv -Sandbox $script:Sandbox
    }

    AfterEach {
        Remove-CtcTestSandbox -Sandbox $script:Sandbox
        Restore-CtcTestEnv -Saved $script:SavedEnv
    }

    It 'exits 1 and tells the user to run ctc login when no env.json exists' {
        New-CtcStub -Sandbox $script:Sandbox -Name 'claude' -Body ':' | Out-Null
        $result = Invoke-CtcScript -ScriptArgs @('claude')
        $result.ExitCode | Should -Be 1
        $result.Combined | Should -Match 'ctc login'
        Get-CtcStubLog -Sandbox $script:Sandbox -Name 'claude' | Should -BeNullOrEmpty
    }

    It "exits 1 with an install hint when 'claude' is not on PATH" {
        Initialize-ClLaunch -Sandbox $script:Sandbox | Out-Null
        # PATH = the empty stubs dir only, so a real claude install can never be picked up.
        [Environment]::SetEnvironmentVariable('PATH', $script:Sandbox.Stubs)
        $result = Invoke-CtcScript -ScriptArgs @('claude')
        $result.ExitCode | Should -Be 1
        $result.Combined | Should -Match "'claude'.*not found"
    }

    It 'launches claude with the isolated env, Copilot backend vars and verbatim args' {
        $login = Initialize-ClLaunch -Sandbox $script:Sandbox
        New-CtcStub -Sandbox $script:Sandbox -Name 'claude' -Body (
            '{ echo "HOME=$HOME"; echo "USERPROFILE=$USERPROFILE"; echo "BASE=$ANTHROPIC_BASE_URL"; echo "AUTH=$ANTHROPIC_AUTH_TOKEN"; ' +
            'echo "MODEL=$ANTHROPIC_MODEL"; echo "SMALL=$ANTHROPIC_SMALL_FAST_MODEL"; echo "TOOLSEARCH=$ENABLE_TOOL_SEARCH"; ' +
            'echo "WORKFLOWS=$CLAUDE_CODE_DISABLE_WORKFLOWS"; echo "UNKWIN=$CLAUDE_CODE_DISABLE_UNKNOWN_MODEL_WINDOW_ENFORCEMENT"; ' +
            'echo "TAG=$CTC_RUN_TAG"; echo "HDR=$ANTHROPIC_CUSTOM_HEADERS"; echo "PROXY=$HTTPS_PROXY"; echo "ARGS=$*"; } > "$HOME/claude_out"'
        ) | Out-Null

        $result = Invoke-CtcScript -ScriptArgs @('claude', '-p', 'hello world', '--foo', '-xyz')

        $result.ExitCode | Should -Be 0 -Because $result.Combined
        $rec = Get-Content -Raw -LiteralPath (Join-Path $login.IsoHome 'claude_out')
        $rec | Should -Match ([regex]::Escape("HOME=$($login.IsoHome)"))
        $rec | Should -Match ([regex]::Escape("USERPROFILE=$($login.IsoHome)"))
        $rec | Should -Match ([regex]::Escape('BASE=https://copilot-api.example.invalid'))
        $rec | Should -Match ([regex]::Escape('AUTH=github_pat_TESTTOKEN1234'))
        $rec | Should -Match '(?m)^MODEL=claude-sonnet-5$'
        $rec | Should -Match '(?m)^SMALL=claude-haiku-4\.5$'
        $rec | Should -Match '(?m)^TOOLSEARCH=true$'
        $rec | Should -Match '(?m)^WORKFLOWS=1$'
        $rec | Should -Match '(?m)^UNKWIN=1$'
        $rec | Should -Match ([regex]::Escape('PROXY=http://ctc.local:8080'))
        $rec | Should -Match ([regex]::Escape('ARGS=-p hello world --foo -xyz'))
        $tag = [regex]::Match($rec, '(?m)^TAG=(run-[0-9a-f]{16})$').Groups[1].Value
        $tag | Should -Not -BeNullOrEmpty
        $rec | Should -Match ([regex]::Escape("HDR=X-CTC-Run-Tag: $tag"))
        # The token must reach claude only via env, never as an argument or in output.
        (Get-CtcStubLog -Sandbox $script:Sandbox -Name 'claude') | Should -Not -Match 'github_pat_TESTTOKEN1234'
        $result.Combined | Should -Not -Match 'github_pat_TESTTOKEN1234'
    }

    It 'gives every launch a fresh run tag' {
        $login = Initialize-ClLaunch -Sandbox $script:Sandbox
        New-CtcStub -Sandbox $script:Sandbox -Name 'claude' -Body 'echo "$CTC_RUN_TAG" >> "$HOME/tags"' | Out-Null
        Invoke-CtcScript -ScriptArgs @('claude') | Out-Null
        Invoke-CtcScript -ScriptArgs @('claude') | Out-Null
        $tags = @(Get-Content -LiteralPath (Join-Path $login.IsoHome 'tags') | Where-Object { $_ })
        $tags.Count | Should -Be 2
        $tags[0] | Should -Not -Be $tags[1]
    }

    It 'keeps caller-provided ANTHROPIC_MODEL / SMALL_FAST / ENABLE_TOOL_SEARCH and appends to existing custom headers' {
        $login = Initialize-ClLaunch -Sandbox $script:Sandbox
        [Environment]::SetEnvironmentVariable('ANTHROPIC_MODEL', 'claude-opus-5.5')
        [Environment]::SetEnvironmentVariable('ANTHROPIC_SMALL_FAST_MODEL', 'gpt-5-mini')
        [Environment]::SetEnvironmentVariable('ENABLE_TOOL_SEARCH', 'false')
        [Environment]::SetEnvironmentVariable('ANTHROPIC_CUSTOM_HEADERS', 'X-Existing: 1')
        New-CtcStub -Sandbox $script:Sandbox -Name 'claude' -Body (
            'printf "MODEL=%s\nSMALL=%s\nTS=%s\n" "$ANTHROPIC_MODEL" "$ANTHROPIC_SMALL_FAST_MODEL" "$ENABLE_TOOL_SEARCH" > "$HOME/claude_out"; printf "%s" "$ANTHROPIC_CUSTOM_HEADERS" > "$HOME/headers"'
        ) | Out-Null

        $result = Invoke-CtcScript -ScriptArgs @('claude')

        $result.ExitCode | Should -Be 0
        $rec = Get-Content -Raw -LiteralPath (Join-Path $login.IsoHome 'claude_out')
        $rec | Should -Match '(?m)^MODEL=claude-opus-5\.5$'
        $rec | Should -Match '(?m)^SMALL=gpt-5-mini$'
        $rec | Should -Match '(?m)^TS=false$'
        $hdr = [IO.File]::ReadAllText((Join-Path $login.IsoHome 'headers'))
        $hdr | Should -Match '^X-Existing: 1\nX-CTC-Run-Tag: run-[0-9a-f]{16}$'
    }

    It "propagates claude's exit code" {
        Initialize-ClLaunch -Sandbox $script:Sandbox | Out-Null
        New-CtcStub -Sandbox $script:Sandbox -Name 'claude' -Body 'exit 9' | Out-Null
        $result = Invoke-CtcScript -ScriptArgs @('claude')
        $result.ExitCode | Should -Be 9
    }

    It 'prints the CTC banner with the default model, --model X and --model=X' {
        Initialize-ClLaunch -Sandbox $script:Sandbox | Out-Null
        New-CtcStub -Sandbox $script:Sandbox -Name 'claude' -Body ':' | Out-Null
        $r1 = Invoke-CtcScript -ScriptArgs @('claude')
        $r1.Combined | Should -Match 'CTC mode'
        $r1.Combined | Should -Match 'model: claude-sonnet-5 '
        $r2 = Invoke-CtcScript -ScriptArgs @('claude', '-p', 'hi', '--model', 'claude-opus-5.5')
        $r2.Combined | Should -Match 'model: claude-opus-5\.5 '
        $r3 = Invoke-CtcScript -ScriptArgs @('claude', '--model=claude-haiku-4.5')
        $r3.Combined | Should -Match 'model: claude-haiku-4\.5 '
    }

    It 'installs the statusline into the isolated home only, never the real profile' {
        $login = Initialize-ClLaunch -Sandbox $script:Sandbox
        New-CtcStub -Sandbox $script:Sandbox -Name 'claude' -Body ':' | Out-Null

        Invoke-CtcScript -ScriptArgs @('claude') | Out-Null

        $isoClaude = Join-Path $login.IsoHome '.claude'
        Test-Path -LiteralPath (Join-Path $isoClaude 'statusline.ps1') -PathType Leaf | Should -BeTrue
        (Get-Content -Raw -LiteralPath (Join-Path $isoClaude 'settings.json')) | Should -Match 'statusLine'
        Test-Path -LiteralPath (Join-Path $script:Sandbox.Home '.claude') | Should -BeFalse
    }

    It 'merges into an existing isolated settings.json on launch' {
        $login = Initialize-ClLaunch -Sandbox $script:Sandbox
        $isoClaude = Join-Path $login.IsoHome '.claude'
        [IO.File]::WriteAllText((Join-Path $isoClaude 'settings.json'), '{"model":"claude-sonnet-5"}')
        New-CtcStub -Sandbox $script:Sandbox -Name 'claude' -Body ':' | Out-Null

        Invoke-CtcScript -ScriptArgs @('claude') | Out-Null

        $got = Get-Content -Raw -LiteralPath (Join-Path $isoClaude 'settings.json')
        $got | Should -Match 'claude-sonnet-5'
        $got | Should -Match 'statusline\.ps1'
    }

    It 'does not start the ledger poller when CTC_LEDGER_POLL=0' {
        $login = Initialize-ClLaunch -Sandbox $script:Sandbox
        New-CtcStub -Sandbox $script:Sandbox -Name 'claude' -Body ':' | Out-Null
        Invoke-CtcScript -ScriptArgs @('claude') | Out-Null
        Test-Path -LiteralPath (Join-Path (Join-Path $login.IsoHome '.claude') 'ledger') | Should -BeFalse
    }
}
