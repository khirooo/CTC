# Verifies Invoke-CtcMain's command dispatch in cli/ctc.ps1: help/usage,
# unknown-command handling, login/status/logout routing, claude/copilot
# routing (including dash-prefixed passthrough), and the bare-invocation
# menu-vs-direct-copilot branch. Ported from cli/tests/test_dispatch.sh and
# cli/tests/test_menu.sh (dispatch portion only; see Menu.Tests.ps1 for the
# interactive menu's own prompt/reprompt/EOF behavior).
#
# NOTE: there is no `ctc version` subcommand in either the bash (cli/ctc) or
# PS (cli/ctc.ps1) launcher -- confirmed by inspection/grep -- so "version"
# routing is intentionally not covered here.
#
# Strategy: dot-source ctc.ps1 (its own bottom guard skips running
# Invoke-CtcMain when dot-sourced -- see the comment directly above that
# guard in ctc.ps1) and Mock its internal Invoke-Ctc*/Show-CtcUsage/
# Test-CtcInteractiveConsole functions so no real process is ever launched,
# no real cert store/PATH/home is touched, and no network call is made.
#
# NOTE on scoping: see Hygiene.Tests.ps1's header comment -- everything the
# It blocks need is set up inside BeforeAll, not at top level.

Describe 'Dispatch: Invoke-CtcMain command routing' {
    BeforeAll {
        . (Join-Path $PSScriptRoot 'Common.ps1')
        $env:CTC_ALLOW_NON_WINDOWS = '1'
        $env:CTC_UPDATE_CHECK = '0'
        $env:CTC_LEDGER_POLL = '0'
        . $script:CtcScriptPath
    }

    BeforeEach {
        $script:CtcExitCode = 1
        Mock Invoke-CtcCopilot { $script:CtcExitCode = 0 }
        Mock Invoke-CtcClaude { $script:CtcExitCode = 0 }
        Mock Invoke-CtcLogin { return 0 }
        Mock Invoke-CtcStatus { return 0 }
        Mock Invoke-CtcLogout { return 0 }
        Mock Invoke-CtcMenu { }
        Mock Show-CtcUsage { }
        Mock Test-CtcInteractiveConsole { return $false }
    }

    Context 'help / usage' {
        It '-h shows usage and exits 0' {
            Invoke-CtcMain -CtcArgs @('-h')
            Should -Invoke Show-CtcUsage -Times 1
            $script:CtcExitCode | Should -Be 0
        }

        It '--help shows usage and exits 0' {
            Invoke-CtcMain -CtcArgs @('--help')
            Should -Invoke Show-CtcUsage -Times 1
            $script:CtcExitCode | Should -Be 0
        }

        It "'help' shows usage and exits 0" {
            Invoke-CtcMain -CtcArgs @('help')
            Should -Invoke Show-CtcUsage -Times 1
            $script:CtcExitCode | Should -Be 0
        }
    }

    Context 'unknown command' {
        It 'prints an unknown-command message to stderr, shows usage there, and exits 2' {
            $origErr = [Console]::Error
            $sw = New-Object IO.StringWriter
            [Console]::SetError($sw)
            try {
                Invoke-CtcMain -CtcArgs @('bogus')
            } finally {
                [Console]::SetError($origErr)
            }
            $sw.ToString() | Should -Match "unknown command 'bogus'"
            Should -Invoke Show-CtcUsage -Times 1 -ParameterFilter { $Writer -ne $null }
            $script:CtcExitCode | Should -Be 2
        }

        It 'treats a dash-prefixed unknown argument as a Copilot flag passthrough, not an unknown command' {
            Invoke-CtcMain -CtcArgs @('-p', 'foo')
            Should -Invoke Invoke-CtcCopilot -Times 1 -ParameterFilter { ($CtcArgs -join ',') -eq '-p,foo' }
        }
    }

    Context 'login / status / logout routing' {
        It "routes 'login' to Invoke-CtcLogin with the remaining args and propagates its exit code" {
            Mock Invoke-CtcLogin { return 7 }
            Invoke-CtcMain -CtcArgs @('login', '--force')
            Should -Invoke Invoke-CtcLogin -Times 1 -ParameterFilter { ($CtcArgs -join ',') -eq '--force' }
            $script:CtcExitCode | Should -Be 7
        }

        It "routes 'status' to Invoke-CtcStatus and propagates its exit code" {
            Mock Invoke-CtcStatus { return 3 }
            Invoke-CtcMain -CtcArgs @('status')
            Should -Invoke Invoke-CtcStatus -Times 1
            $script:CtcExitCode | Should -Be 3
        }

        It "routes 'logout' to Invoke-CtcLogout and propagates its exit code" {
            Mock Invoke-CtcLogout { return 4 }
            Invoke-CtcMain -CtcArgs @('logout')
            Should -Invoke Invoke-CtcLogout -Times 1
            $script:CtcExitCode | Should -Be 4
        }
    }

    Context 'claude / copilot routing' {
        It "routes 'claude' to Invoke-CtcClaude with the remaining args" {
            Invoke-CtcMain -CtcArgs @('claude', '--model', 'foo')
            Should -Invoke Invoke-CtcClaude -Times 1 -ParameterFilter { ($CtcArgs -join ',') -eq '--model,foo' }
        }

        It "routes 'copilot' to Invoke-CtcCopilot with the remaining args" {
            Invoke-CtcMain -CtcArgs @('copilot', '--resume')
            Should -Invoke Invoke-CtcCopilot -Times 1 -ParameterFilter { ($CtcArgs -join ',') -eq '--resume' }
        }
    }

    Context 'bare invocation (no args)' {
        It 'launches the interactive menu when the console is interactive' {
            Mock Test-CtcInteractiveConsole { return $true }
            Invoke-CtcMain -CtcArgs @()
            Should -Invoke Invoke-CtcMenu -Times 1
            Should -Not -Invoke Invoke-CtcCopilot
        }

        It 'launches Copilot directly with no args when the console is not interactive' {
            Mock Test-CtcInteractiveConsole { return $false }
            Invoke-CtcMain -CtcArgs @()
            Should -Invoke Invoke-CtcCopilot -Times 1 -ParameterFilter { $CtcArgs.Count -eq 0 }
            Should -Not -Invoke Invoke-CtcMenu
        }
    }
}
