# Verifies Invoke-CtcMenu's interactive agent picker in cli/ctc.ps1: valid
# choices for each agent (numeric and word/letter aliases), invalid-input
# reprompting, and clean EOF handling. Ported from the menu-choice portions
# of cli/tests/test_menu.sh.
#
# Strategy: dot-source ctc.ps1 (see Dispatch.Tests.ps1's header comment for
# why this is safe) and Mock Invoke-CtcCopilot/Invoke-CtcClaude so no real
# child process is ever launched. Invoke-CtcMenu reads directly from
# [Console]::In.ReadLine() (not Read-Host) and writes its prompts to
# [Console]::Error, so both streams are redirected in-process via
# [Console]::SetIn/SetError and always restored afterwards so no state leaks
# into other test files sharing this pwsh process.
#
# NOTE on scoping: see Hygiene.Tests.ps1's header comment -- everything the
# It blocks need is set up inside BeforeAll, not at top level.

Describe 'Menu: Invoke-CtcMenu interactive agent picker' {
    BeforeAll {
        . (Join-Path $PSScriptRoot 'Common.ps1')
        $env:CTC_ALLOW_NON_WINDOWS = '1'
        $env:CTC_UPDATE_CHECK = '0'
        $env:CTC_LEDGER_POLL = '0'
        . $script:CtcScriptPath

        $script:OrigConsoleIn = [Console]::In
        $script:OrigConsoleError = [Console]::Error

        function Set-CtcMenuInput {
            # Joins each line with a trailing `n so ReadLine() returns them
            # one at a time, then a final $null once the reader is exhausted
            # (simulating EOF / Ctrl-Z / Ctrl-D with no trailing newline).
            param([string[]]$Lines)
            $text = if ($Lines.Count -eq 0) { '' } else { ($Lines -join "`n") + "`n" }
            [Console]::SetIn((New-Object IO.StringReader $text))
        }
    }

    BeforeEach {
        $script:CtcExitCode = 1
        Mock Invoke-CtcCopilot { $script:CtcExitCode = 0 }
        Mock Invoke-CtcClaude { $script:CtcExitCode = 0 }
        $script:MenuErrorWriter = New-Object IO.StringWriter
        [Console]::SetError($script:MenuErrorWriter)
    }

    AfterEach {
        [Console]::SetIn($script:OrigConsoleIn)
        [Console]::SetError($script:OrigConsoleError)
    }

    Context 'choosing Copilot' {
        It "'1' launches Copilot" {
            Set-CtcMenuInput -Lines @('1')
            Invoke-CtcMenu
            Should -Invoke Invoke-CtcCopilot -Times 1
            Should -Not -Invoke Invoke-CtcClaude
        }

        It "'copilot' launches Copilot" {
            Set-CtcMenuInput -Lines @('copilot')
            Invoke-CtcMenu
            Should -Invoke Invoke-CtcCopilot -Times 1
        }

        It "'c' launches Copilot" {
            Set-CtcMenuInput -Lines @('c')
            Invoke-CtcMenu
            Should -Invoke Invoke-CtcCopilot -Times 1
        }

        It 'trims surrounding whitespace before matching the choice' {
            Set-CtcMenuInput -Lines @('  1  ')
            Invoke-CtcMenu
            Should -Invoke Invoke-CtcCopilot -Times 1
        }
    }

    Context 'choosing Claude' {
        It "'2' launches Claude" {
            Set-CtcMenuInput -Lines @('2')
            Invoke-CtcMenu
            Should -Invoke Invoke-CtcClaude -Times 1
            Should -Not -Invoke Invoke-CtcCopilot
        }

        It "'claude' launches Claude" {
            Set-CtcMenuInput -Lines @('claude')
            Invoke-CtcMenu
            Should -Invoke Invoke-CtcClaude -Times 1
        }
    }

    Context 'invalid input' {
        It 'reprompts with a usage hint and proceeds once a valid choice follows' {
            Set-CtcMenuInput -Lines @('bogus', '2')
            Invoke-CtcMenu
            Should -Invoke Invoke-CtcClaude -Times 1
            $script:MenuErrorWriter.ToString() | Should -Match 'Please enter 1 or 2\.'
        }

        It 'reprompts repeatedly for multiple consecutive invalid choices' {
            Set-CtcMenuInput -Lines @('bogus', 'nope', '1')
            Invoke-CtcMenu
            Should -Invoke Invoke-CtcCopilot -Times 1
            $reprompts = ([regex]::Matches($script:MenuErrorWriter.ToString(), 'Please enter 1 or 2\.')).Count
            $reprompts | Should -Be 2
        }
    }

    Context 'EOF' {
        It 'exits cleanly (exit code 0) with neither agent invoked when input is immediately exhausted' {
            Set-CtcMenuInput -Lines @()
            Invoke-CtcMenu
            Should -Not -Invoke Invoke-CtcCopilot
            Should -Not -Invoke Invoke-CtcClaude
            $script:CtcExitCode | Should -Be 0
        }
    }
}
