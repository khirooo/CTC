# Differential parity tests: the PowerShell statusline embedded in ctc.ps1
# ($script:CtcStatuslineSource) vs. the Python statusline embedded in cli/ctc
# (the `cat > "$dir/statusline.py" <<'PYEOF'` heredoc). Both are extracted to
# temp files, fed the same Claude Code statusline JSON on stdin (and the same
# transcript JSONL on disk), and must print byte-identical output. Each
# interpreter gets its OWN throwaway HOME so their statusline-cache files
# (different on-disk shapes) never cross-contaminate. No network, no real
# profile.

Describe 'Claude statusline: PowerShell port vs Python original (differential parity)' {
    BeforeAll {
        . (Join-Path $PSScriptRoot 'Common.ps1')

        $script:SlPython = (Get-Command python3 -ErrorAction SilentlyContinue).Source
        if (-not $script:SlPython) { $script:SlPython = (Get-Command python -ErrorAction SilentlyContinue).Source }

        $script:SlRoot = Join-Path ([IO.Path]::GetTempPath()) ('ctc-sl-parity-' + [guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Path $script:SlRoot -Force | Out-Null

        # --- extract the Python statusline from the bash launcher -------------
        $bashLines = [IO.File]::ReadAllLines((Join-Path $script:CtcLibDir 'ctc'))
        $start = -1
        for ($i = 0; $i -lt $bashLines.Count; $i++) {
            if ($bashLines[$i] -match 'statusline\.py" <<''PYEOF''') { $start = $i + 1; break }
        }
        if ($start -lt 0) { throw 'could not locate the embedded Python statusline in cli/ctc' }
        $end = $start
        while ($end -lt $bashLines.Count -and $bashLines[$end] -ne 'PYEOF') { $end++ }
        $script:SlPyPath = Join-Path $script:SlRoot 'statusline.py'
        [IO.File]::WriteAllText($script:SlPyPath, (($bashLines[$start..($end - 1)]) -join "`n") + "`n", (New-Object System.Text.UTF8Encoding($false)))

        # --- extract the PowerShell statusline from ctc.ps1 (dot-source is safe:
        #     its Main only runs when invoked directly) ------------------------
        . $script:CtcScriptPath
        if ([string]::IsNullOrEmpty($script:CtcStatuslineSource)) { throw 'CtcStatuslineSource is empty' }
        $script:SlPsPath = Join-Path $script:SlRoot 'statusline.ps1'
        [IO.File]::WriteAllText($script:SlPsPath, $script:CtcStatuslineSource, (New-Object System.Text.UTF8Encoding($true)))

        function Invoke-SlProcess {
            param([string]$Exe, [string[]]$ArgList, [string]$StdIn, [string]$HomeDir, [hashtable]$ExtraEnv)
            $psi = New-Object System.Diagnostics.ProcessStartInfo
            $psi.FileName = $Exe
            foreach ($a in $ArgList) { $psi.ArgumentList.Add($a) | Out-Null }
            $psi.RedirectStandardInput = $true
            $psi.RedirectStandardOutput = $true
            $psi.RedirectStandardError = $true
            $psi.UseShellExecute = $false
            $psi.StandardOutputEncoding = New-Object System.Text.UTF8Encoding($false)
            $psi.StandardErrorEncoding = New-Object System.Text.UTF8Encoding($false)
            foreach ($n in @('CTC_RUN_TAG', 'CTC_AIU_CEILING')) { [void]$psi.Environment.Remove($n) }
            $psi.Environment['HOME'] = $HomeDir
            $psi.Environment['USERPROFILE'] = $HomeDir
            $psi.Environment['PYTHONIOENCODING'] = 'utf-8'
            $psi.Environment['PYTHONDONTWRITEBYTECODE'] = '1'
            foreach ($k in $ExtraEnv.Keys) { $psi.Environment[$k] = [string]$ExtraEnv[$k] }
            $sw = [Diagnostics.Stopwatch]::StartNew()
            $proc = [System.Diagnostics.Process]::Start($psi)
            $bytes = (New-Object System.Text.UTF8Encoding($false)).GetBytes([string]$StdIn)
            $proc.StandardInput.BaseStream.Write($bytes, 0, $bytes.Length)
            $proc.StandardInput.Close()
            $errTask = $proc.StandardError.ReadToEndAsync()
            $out = $proc.StandardOutput.ReadToEnd()
            if (-not $proc.WaitForExit(30000)) { try { $proc.Kill() } catch { }; throw "$Exe timed out" }
            $sw.Stop()
            [PSCustomObject]@{ ExitCode = $proc.ExitCode; StdOut = $out; StdErr = $errTask.Result; Ms = $sw.ElapsedMilliseconds }
        }

        # Runs both statuslines on one case. Placeholders in $StdIn:
        #   __T__  -> path of the transcript written from $Lines
        #   __D__  -> a fresh (non-git) workspace dir named $ProjName
        # $Raw lines are written verbatim (no added newline) for partial-line cases.
        function Invoke-SlPair {
            param(
                [string]$StdIn,
                [string[]]$Lines = $null,
                [string]$RawTranscript = $null,
                [hashtable]$SubAgents = @{},
                [string]$SessionId = 's1',
                [string]$ProjName = 'proj-x',
                [hashtable]$ExtraEnv = @{},
                [hashtable]$Ledger = $null
            )
            $case = Join-Path $script:SlRoot ([guid]::NewGuid().ToString('N'))
            $ws = Join-Path $case $ProjName
            $proj = Join-Path $case 'projects'
            New-Item -ItemType Directory -Path $ws, $proj -Force | Out-Null
            $t = Join-Path $proj "$SessionId.jsonl"
            $utf8 = New-Object System.Text.UTF8Encoding($false)
            if ($null -ne $Lines) { [IO.File]::WriteAllText($t, (($Lines | ForEach-Object { $_ + "`n" }) -join ''), $utf8) }
            if ($null -ne $RawTranscript -and $RawTranscript -ne '') { [IO.File]::WriteAllText($t, $RawTranscript, $utf8) }
            foreach ($rel in $SubAgents.Keys) {
                $sp = Join-Path (Join-Path (Join-Path $proj $SessionId) 'subagents') $rel
                New-Item -ItemType Directory -Path (Split-Path -Parent $sp) -Force | Out-Null
                [IO.File]::WriteAllText($sp, ((@($SubAgents[$rel]) | ForEach-Object { $_ + "`n" }) -join ''), $utf8)
            }
            $esc = { param($s) $s.Replace('\', '\\').Replace('"', '\"') }
            $in = $StdIn.Replace('__T__', (& $esc $t)).Replace('__D__', (& $esc $ws))

            $res = @{}
            foreach ($kind in 'py', 'ps') {
                $h = Join-Path $case "home-$kind"
                New-Item -ItemType Directory -Path $h -Force | Out-Null
                if ($Ledger) {
                    $ld = Join-Path (Join-Path $h '.claude') 'ledger'
                    New-Item -ItemType Directory -Path $ld -Force | Out-Null
                    [IO.File]::WriteAllText((Join-Path $ld "$($Ledger.tag).json"), ($Ledger | ConvertTo-Json -Compress), $utf8)
                }
                if ($kind -eq 'py') {
                    $res.py = Invoke-SlProcess -Exe $script:SlPython -ArgList @($script:SlPyPath) -StdIn $in -HomeDir $h -ExtraEnv $ExtraEnv
                } else {
                    $res.ps = Invoke-SlProcess -Exe $script:CtcPwshExe -ArgList @('-NoProfile', '-NonInteractive', '-File', $script:SlPsPath) -StdIn $in -HomeDir $h -ExtraEnv $ExtraEnv
                }
            }
            [PSCustomObject]@{ Py = $res.py; Ps = $res.ps; Transcript = $t; Case = $case }
        }

        function Remove-SlAnsi { param([string]$s) return ([regex]::Replace($s, "\x1b\[[0-9;]*m", '')) }

        function Assert-SlParity {
            param([hashtable]$Case)
            $r = Invoke-SlPair @Case
            $r.Py.ExitCode | Should -Be 0 -Because "python stderr: $($r.Py.StdErr)"
            $r.Ps.ExitCode | Should -Be 0 -Because "pwsh stderr: $($r.Ps.StdErr)"
            $r.Ps.StdErr | Should -BeNullOrEmpty
            (Remove-SlAnsi $r.Ps.StdOut) | Should -BeExactly (Remove-SlAnsi $r.Py.StdOut)
            $r.Ps.StdOut | Should -BeExactly $r.Py.StdOut
            return $r
        }

        function New-SlTurn {
            param([string]$Model, [hashtable]$Usage, [string]$Rid = 'r1', [switch]$Sidechain, [string]$Uuid)
            $o = [ordered]@{ type = 'assistant' }
            if ($Rid) { $o.requestId = $Rid }
            if ($Uuid) { $o.uuid = $Uuid }
            if ($Sidechain) { $o.isSidechain = $true }
            $msg = [ordered]@{}
            if ($null -ne $Model) { $msg.model = $Model }
            if ($null -ne $Usage) { $msg.usage = $Usage }
            $o.message = $msg
            return ($o | ConvertTo-Json -Depth 6 -Compress)
        }

        $script:SlStd = '{"model":{"display_name":"Sonnet 5","id":"claude-sonnet-5"},"workspace":{"current_dir":"__D__","project_dir":"__D__"},"session_id":"s1","transcript_path":"__T__"}'
    }

    AfterAll {
        if ($script:SlRoot -and (Test-Path -LiteralPath $script:SlRoot)) {
            Remove-Item -LiteralPath $script:SlRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
    }

    It 'has python3 and both extracted scripts available' {
        $script:SlPython | Should -Not -BeNullOrEmpty
        (Get-Content -Raw -LiteralPath $script:SlPyPath) | Should -Match 'def main\(\):'
        (Get-Content -Raw -LiteralPath $script:SlPsPath) | Should -Match 'function Invoke-CtcSlMain'
    }

    # --- known-value anchors --------------------------------------------------
    It 'prices 1M sonnet input tokens identically (330.00 AIU, 3.00 USD)' {
        $r = Assert-SlParity @{ StdIn = $script:SlStd; Lines = @(New-SlTurn 'claude-sonnet-4.6' @{ input_tokens = 1000000 }) }
        (Remove-SlAnsi $r.Ps.StdOut) | Should -Match ([regex]::Escape("$([char]0x2248)330.00 AIU $([char]0xB7) `$3.00"))
    }

    It 'matches the bash suite example (sonnet-4.6 mixed tokens, 5m cache writes)' {
        $u = @{ input_tokens = 1000; output_tokens = 500; cache_read_input_tokens = 2000; cache_creation_input_tokens = 100; cache_creation = @{ ephemeral_5m_input_tokens = 100; ephemeral_1h_input_tokens = 0 } }
        $r = Assert-SlParity @{ StdIn = $script:SlStd; Lines = @(New-SlTurn 'claude-sonnet-4.6' $u) }
        (Remove-SlAnsi $r.Ps.StdOut) | Should -Match '1\.26 AIU'
    }

    # --- model matrix -------------------------------------------------------------
    It 'agrees on opus with cache read, 5m and 1h cache writes' {
        $u = @{ input_tokens = 12345; output_tokens = 6789; cache_read_input_tokens = 500000; cache_creation_input_tokens = 40000; cache_creation = @{ ephemeral_1h_input_tokens = 15000 } }
        Assert-SlParity @{ StdIn = $script:SlStd.Replace('Sonnet 5', 'Claude Opus 4.7'); Lines = @(New-SlTurn 'claude-opus-4.7' $u) } | Out-Null
    }

    It 'agrees on haiku with 1h writes larger than the total cache write (w5 clamps to 0)' {
        $u = @{ input_tokens = 100; output_tokens = 200000; cache_creation_input_tokens = 10; cache_creation = @{ ephemeral_1h_input_tokens = 999 } }
        Assert-SlParity @{ StdIn = $script:SlStd; Lines = @(New-SlTurn 'claude-haiku-4.5' $u) } | Out-Null
    }

    It 'agrees on a zero-cache-write-price model (1h writes bill at 0)' {
        $u = @{ input_tokens = 70000; output_tokens = 9000; cache_creation_input_tokens = 50000; cache_creation = @{ ephemeral_1h_input_tokens = 50000 } }
        Assert-SlParity @{ StdIn = $script:SlStd; Lines = @(New-SlTurn 'gpt-5.5' $u) } | Out-Null
    }

    It 'agrees on an unknown model id (falls back to sonnet-4.6 pricing)' {
        Assert-SlParity @{ StdIn = $script:SlStd; Lines = @(New-SlTurn 'mystery-model-x' @{ input_tokens = 333333; output_tokens = 4444 }) } | Out-Null
    }

    It 'agrees on family fallbacks (opus/gemini/mini/codex/gpt unlisted ids)' {
        $lines = @(
            (New-SlTurn 'claude-opus-9' @{ input_tokens = 1000 } -Rid 'a'),
            (New-SlTurn 'gemini-9-mini' @{ input_tokens = 2000 } -Rid 'b'),
            (New-SlTurn 'gpt-9-mini' @{ input_tokens = 3000 } -Rid 'c'),
            (New-SlTurn 'gpt-9-codex' @{ input_tokens = 4000 } -Rid 'd'),
            (New-SlTurn ' gpt-9 ' @{ input_tokens = 5000 } -Rid 'e'),
            (New-SlTurn 'Claude-Sonnet-9' @{ output_tokens = 6000 } -Rid 'f')
        )
        Assert-SlParity @{ StdIn = $script:SlStd; Lines = $lines } | Out-Null
    }

    It 'agrees on a synthetic (never billed) message' {
        Assert-SlParity @{ StdIn = $script:SlStd; Lines = @(New-SlTurn '<synthetic>' @{ input_tokens = 999999 }) } | Out-Null
    }

    # --- token edge cases -----------------------------------------------------
    It 'agrees on an all-zero usage record' {
        Assert-SlParity @{ StdIn = $script:SlStd; Lines = @(New-SlTurn 'claude-sonnet-4.6' @{ input_tokens = 0; output_tokens = 0; cache_read_input_tokens = 0; cache_creation_input_tokens = 0 }) } | Out-Null
    }

    It 'agrees on huge (but int64-safe) token counts' {
        Assert-SlParity @{ StdIn = $script:SlStd; Lines = @(New-SlTurn 'claude-opus-4.7' @{ input_tokens = 1000000000000; output_tokens = 2000000000; cache_read_input_tokens = 30000000000 }) } | Out-Null
    }

    It 'agrees on token counts whose nano-AIU cost overflows int64' {
        Assert-SlParity @{ StdIn = $script:SlStd; Lines = @(New-SlTurn 'claude-opus-4.7' @{ input_tokens = 10000000000000000 }) } | Out-Null
    }

    It 'agrees on missing and null usage fields' {
        $lines = @(
            (New-SlTurn 'claude-sonnet-4.6' @{} -Rid 'a'),
            (New-SlTurn 'claude-sonnet-4.6' @{ output_tokens = 777; input_tokens = $null; cache_creation = $null } -Rid 'b'),
            (New-SlTurn $null @{ input_tokens = 1234 } -Rid 'c'),
            (New-SlTurn 'claude-sonnet-4.6' $null -Rid 'd'),
            '{"type":"user","message":{"content":"hi"}}',
            '{"type":"assistant","message":{"model":"claude-sonnet-4.6","usage":"not-a-dict"}}',
            '{"type":"assistant","message":null}',
            '{"no_message":true}'
        )
        Assert-SlParity @{ StdIn = $script:SlStd; Lines = $lines } | Out-Null
    }

    It 'agrees on records with no requestId (uuid fallback and empty key)' {
        $lines = @(
            (New-SlTurn 'claude-sonnet-4.6' @{ input_tokens = 1000 } -Rid '' -Uuid 'u1'),
            (New-SlTurn 'claude-sonnet-4.6' @{ input_tokens = 3000 } -Rid ''),
            (New-SlTurn 'claude-sonnet-4.6' @{ input_tokens = 2000 } -Rid '')
        )
        Assert-SlParity @{ StdIn = $script:SlStd; Lines = $lines } | Out-Null
    }

    It 'agrees on streaming repeats of one requestId (only the growing delta counts)' {
        $lines = @(
            (New-SlTurn 'claude-sonnet-4.6' @{ input_tokens = 4000; output_tokens = 10 }),
            (New-SlTurn 'claude-sonnet-4.6' @{ input_tokens = 4000; output_tokens = 1000 }),
            (New-SlTurn 'claude-sonnet-4.6' @{ input_tokens = 4000; output_tokens = 1000 }),
            (New-SlTurn 'claude-sonnet-4.6' @{ input_tokens = 4000; output_tokens = 50 })
        )
        Assert-SlParity @{ StdIn = $script:SlStd; Lines = $lines } | Out-Null
    }

    It 'agrees on subagent transcripts (nested, recursive) and sidechain context' {
        $sub = @{
            'agent-a.jsonl'                    = @(New-SlTurn 'claude-haiku-4.5' @{ input_tokens = 40000; output_tokens = 3000 } -Rid 'sa')
            'workflows/wf_1/agent-b.jsonl'     = @(New-SlTurn 'claude-opus-4.7' @{ input_tokens = 10000 } -Rid 'sb')
        }
        $lines = @(
            (New-SlTurn 'claude-sonnet-4.6' @{ input_tokens = 1500; cache_read_input_tokens = 120000 } -Rid 'm1'),
            (New-SlTurn 'claude-sonnet-4.6' @{ input_tokens = 9; output_tokens = 1 } -Rid 'm2' -Sidechain)
        )
        $r = Assert-SlParity @{ StdIn = $script:SlStd; Lines = $lines; SubAgents = $sub }
        (Remove-SlAnsi $r.Ps.StdOut) | Should -Match 'agents'
    }

    It 'agrees on CRLF lines, junk lines and a trailing partial line' {
        $raw = (New-SlTurn 'claude-sonnet-4.6' @{ input_tokens = 2222 } -Rid 'a') + "`r`n" +
               "this is not json`n`n{broken`n" +
               (New-SlTurn 'claude-sonnet-4.6' @{ output_tokens = 3333 } -Rid 'b') + "`n" +
               (New-SlTurn 'claude-sonnet-4.6' @{ output_tokens = 99999 } -Rid 'c')
        Assert-SlParity @{ StdIn = $script:SlStd; RawTranscript = $raw } | Out-Null
    }

    It 'agrees on context-size formatting (k and M)' {
        Assert-SlParity @{ StdIn = $script:SlStd; Lines = @(New-SlTurn 'claude-sonnet-4.6' @{ input_tokens = 999; cache_read_input_tokens = 2410000 }) } | Out-Null
        Assert-SlParity @{ StdIn = $script:SlStd; Lines = @(New-SlTurn 'claude-sonnet-4.6' @{ input_tokens = 1999 }) } | Out-Null
    }

    # Python's %.2f / %.1f round the EXACT binary value (half-to-even on true
    # midpoints). .NET custom formats ('0.00'/'0.0') first round to 15
    # significant digits, then half-away-from-zero -- so 3.135 (really
    # 3.13499999...) prints 3.14, and the exact midpoint 0.125 prints 0.13.
    It 'agrees on a non-midpoint value just below .xx5 (3.135 AIU)' {
        Assert-SlParity @{ StdIn = $script:SlStd; Lines = @(New-SlTurn 'claude-sonnet-4.6' @{ input_tokens = 5000; output_tokens = 900 }) } | Out-Null
    }

    It 'agrees on an exact 0.125 AIU midpoint (two-decimal rounding)' {
        Assert-SlParity @{ StdIn = $script:SlStd; Lines = @(New-SlTurn 'gpt-5.6-luna' @{ cache_read_input_tokens = 62500 }) } | Out-Null
    }

    It 'agrees on an exact 1.25M context midpoint (one-decimal rounding)' {
        Assert-SlParity @{ StdIn = $script:SlStd; Lines = @(New-SlTurn 'claude-sonnet-4.6' @{ input_tokens = 1250000 }) } | Out-Null
    }

    # --- stdin / workspace variants ------------------------------------------
    It 'agrees when the transcript path is missing or does not exist' {
        Assert-SlParity @{ StdIn = '{"model":{"display_name":"Opus"},"workspace":{"current_dir":"__D__"}}' } | Out-Null
        Assert-SlParity @{ StdIn = '{"model":{"id":"claude-opus-5"},"cwd":"__D__","transcript_path":"/nonexistent/x.jsonl"}' } | Out-Null
    }

    It 'agrees on model display_name/id fallbacks and the Claude prefix strip' {
        Assert-SlParity @{ StdIn = '{"model":{"display_name":"Claude Opus 4.7"},"cwd":"__D__"}' } | Out-Null
        Assert-SlParity @{ StdIn = '{"model":{"id":"claude-haiku-4.5"},"cwd":"__D__"}' } | Out-Null
        Assert-SlParity @{ StdIn = '{"model":{},"cwd":"__D__"}' } | Out-Null
        Assert-SlParity @{ StdIn = '{"cwd":"__D__"}' } | Out-Null
        Assert-SlParity @{ StdIn = '{"model":{"display_name":"Sönnet ✨ 5"},"cwd":"__D__"}' } | Out-Null
    }

    It 'agrees on hiding a project dir named ctc (any case)' {
        Assert-SlParity @{ StdIn = '{"model":{"display_name":"X"},"workspace":{"current_dir":"__D__","project_dir":"__D__"}}'; ProjName = 'CTC' } | Out-Null
    }

    It 'agrees on empty stdin' {
        Assert-SlParity @{ StdIn = '' } | Out-Null
    }

    It 'agrees on junk stdin' {
        Assert-SlParity @{ StdIn = 'definitely { not json' } | Out-Null
        Assert-SlParity @{ StdIn = "   `n`t " } | Out-Null
        Assert-SlParity @{ StdIn = '{}' } | Out-Null
    }

    It 'renders the burn bar identically with CTC_AIU_CEILING' {
        Assert-SlParity @{ StdIn = $script:SlStd; Lines = @(New-SlTurn 'claude-sonnet-4.6' @{ input_tokens = 100000 }); ExtraEnv = @{ CTC_AIU_CEILING = '100' } } | Out-Null
        Assert-SlParity @{ StdIn = $script:SlStd; Lines = @(New-SlTurn 'claude-opus-4.7' @{ input_tokens = 1000000 }); ExtraEnv = @{ CTC_AIU_CEILING = '200' } } | Out-Null
    }

    It 'shows a fresh ledger total identically (no approx glyph)' {
        $led = @{ tag = 'run-abc'; unit = 'nano_aiu'; nano_aiu_total = 12340000000 }
        $r = Assert-SlParity @{ StdIn = $script:SlStd; Lines = @(New-SlTurn 'claude-sonnet-4.6' @{ input_tokens = 1000 }); ExtraEnv = @{ CTC_RUN_TAG = 'run-abc' }; Ledger = $led }
        (Remove-SlAnsi $r.Ps.StdOut) | Should -Match '12\.34 AIU'
        $wrongUnit = @{ tag = 'run-abc'; unit = 'aiu'; nano_aiu_total = 5 }
        Assert-SlParity @{ StdIn = $script:SlStd; ExtraEnv = @{ CTC_RUN_TAG = 'run-abc' }; Ledger = $wrongUnit } | Out-Null
    }

    It 'is incremental: a second render after appending matches too' {
        $r = Assert-SlParity @{ StdIn = $script:SlStd; Lines = @(New-SlTurn 'claude-sonnet-4.6' @{ input_tokens = 1000 } -Rid 'a') }
        # Re-run both against their own (now warm) caches after appending a turn.
        Add-Content -LiteralPath $r.Transcript -Value (New-SlTurn 'claude-sonnet-4.6' @{ input_tokens = 7000 } -Rid 'b') -NoNewline
        Add-Content -LiteralPath $r.Transcript -Value "`n" -NoNewline
        $in = $script:SlStd.Replace('__T__', $r.Transcript).Replace('__D__', (Join-Path $r.Case 'proj-x'))
        $py = Invoke-SlProcess -Exe $script:SlPython -ArgList @($script:SlPyPath) -StdIn $in -HomeDir (Join-Path $r.Case 'home-py') -ExtraEnv @{}
        $ps = Invoke-SlProcess -Exe $script:CtcPwshExe -ArgList @('-NoProfile', '-NonInteractive', '-File', $script:SlPsPath) -StdIn $in -HomeDir (Join-Path $r.Case 'home-ps') -ExtraEnv @{}
        $ps.StdOut | Should -BeExactly $py.StdOut
        (Remove-SlAnsi $ps.StdOut) | Should -Match '2\.64 AIU'
    }

    # --- robustness -------------------------------------------------------------
    It 'exits 0 without errors on junk stdin, including JSON non-objects' {
        foreach ($junk in @('', 'garbage', '[1,2,3]', 'null', '42', '"str"', '{"model":"not-an-object","workspace":7}', ([string][char]0xFEFF + '{}'))) {
            $r = Invoke-SlPair -StdIn $junk
            $r.Ps.ExitCode | Should -Be 0 -Because "input [$junk] stderr: $($r.Ps.StdErr)"
            $r.Ps.StdErr | Should -BeNullOrEmpty -Because "input [$junk]"
            (Remove-SlAnsi $r.Ps.StdOut) | Should -Match 'CTC'
        }
    }

    It 'renders within a reasonable time' {
        $lines = 1..300 | ForEach-Object { New-SlTurn 'claude-sonnet-4.6' @{ input_tokens = $_ * 10; output_tokens = $_ } -Rid "r$_" }
        $r = Assert-SlParity @{ StdIn = $script:SlStd; Lines = $lines }
        $r.Ps.Ms | Should -BeLessThan 10000
    }
}
