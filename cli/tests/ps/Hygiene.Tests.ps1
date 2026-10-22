# Static hygiene checks for ctc.ps1 / install.ps1: no obfuscation/elevation
# primitives, both files parse cleanly, and neither uses PS7-only syntax that
# would break on Windows PowerShell 5.1. Comments are stripped via the AST
# tokenizer before pattern matching so explanatory prose (e.g. "bypasses
# that pipeline capture") never false-positives.
#
# NOTE on scoping: Pester 5/6 runs Discovery and Run as separate passes.
# Scriptblocks captured for Run (It/BeforeAll/etc.) do NOT close over
# top-level `function`/dot-source statements in this file -- only code
# actually nested inside a Describe/Context/It/BeforeAll executes during Run.
# Conversely, Describe-body code OUTSIDE It (e.g. a `foreach` generating It
# blocks) runs during Discovery, in the same pass as top-level statements, so
# plain top-level data (like $CtcLibDir/$forbiddenPatterns below) IS visible
# there. Every *.Tests.ps1 file in this directory follows this split: data
# needed to generate test cases stays at top-level/Describe-body scope;
# anything an It/BeforeAll body needs (Common.ps1's helpers, derived state)
# is dot-sourced/computed inside a top-level BeforeAll.

$CtcLibDir = Split-Path -Parent $PSScriptRoot
$CtcScriptPath = Join-Path $CtcLibDir 'ctc.ps1'
$CtcInstallScriptPath = Join-Path $CtcLibDir 'install.ps1'

$forbiddenPatterns = @(
    'Invoke-Expression'
    '\biex\b'
    '\[scriptblock\]::Create'
    '-EncodedCommand'
    'FromBase64String'
    '\bBypass\b'
    'WindowStyle\s+Hidden'
    '-Verb\s+RunAs'
    '\bRunAs\b'
    'certutil'
    'Unblock-File'
    'ServerCertificateValidationCallback'
)

BeforeAll {
    . (Join-Path $PSScriptRoot 'Common.ps1')

    function Get-CtcSourceWithoutComments {
        # Returns the file's text with every Comment-token span blanked out
        # (replaced with same-length whitespace, newlines preserved) so
        # offsets/line numbers stay stable but comment CONTENT never matches
        # a pattern.
        param([string]$Path)
        $tokens = $null
        $errors = $null
        [System.Management.Automation.Language.Parser]::ParseFile($Path, [ref]$tokens, [ref]$errors) | Out-Null
        $text = [IO.File]::ReadAllText($Path)
        $chars = $text.ToCharArray()
        foreach ($t in $tokens) {
            if ($t.Kind -eq [System.Management.Automation.Language.TokenKind]::Comment) {
                $start = $t.Extent.StartOffset
                $end = $t.Extent.EndOffset
                for ($i = $start; $i -lt $end; $i++) {
                    if ($chars[$i] -ne "`n" -and $chars[$i] -ne "`r") { $chars[$i] = ' ' }
                }
            }
        }
        return (-join $chars)
    }
}

Describe 'Hygiene: ctc.ps1' {
    BeforeAll {
        $script:Source = Get-CtcSourceWithoutComments -Path $script:CtcScriptPath
    }

    It 'parses with zero errors' {
        $tokens = $null
        $errors = $null
        [System.Management.Automation.Language.Parser]::ParseFile($script:CtcScriptPath, [ref]$tokens, [ref]$errors) | Out-Null
        $errors.Count | Should -Be 0
    }

    It "does not contain forbidden pattern: <_>" -ForEach $forbiddenPatterns {
        $script:Source | Should -Not -Match $_
    }
}

Describe 'Hygiene: install.ps1' {
    BeforeAll {
        $script:Source = Get-CtcSourceWithoutComments -Path $script:CtcInstallScriptPath
    }

    It 'parses with zero errors' {
        $tokens = $null
        $errors = $null
        [System.Management.Automation.Language.Parser]::ParseFile($script:CtcInstallScriptPath, [ref]$tokens, [ref]$errors) | Out-Null
        $errors.Count | Should -Be 0
    }

    It "does not contain forbidden pattern: <_>" -ForEach $forbiddenPatterns {
        $script:Source | Should -Not -Match $_
    }

    It 'does not contain LocalMachine' {
        $script:Source | Should -Not -Match 'LocalMachine'
    }
}

Describe 'Hygiene: PowerShell 5.1 compatible syntax' {
    Context '<Name>' -ForEach @(
        @{ Name = 'ctc.ps1'; Path = $CtcScriptPath }
        @{ Name = 'install.ps1'; Path = $CtcInstallScriptPath }
    ) {
            BeforeAll {
                $tokens = $null
                $errors = $null
                [System.Management.Automation.Language.Parser]::ParseFile($Path, [ref]$tokens, [ref]$errors) | Out-Null
                $script:Tokens = $tokens
            }

            It 'contains no null-coalescing operator (??)' {
                ($script:Tokens | Where-Object { $_.Kind -eq [System.Management.Automation.Language.TokenKind]::QuestionQuestion }).Count | Should -Be 0
            }

            It 'contains no null-conditional member access (?.)' {
                ($script:Tokens | Where-Object { $_.Kind -eq [System.Management.Automation.Language.TokenKind]::QuestionDot }).Count | Should -Be 0
            }

            It 'contains no ternary operator (? :)' {
                ($script:Tokens | Where-Object { $_.Kind -eq [System.Management.Automation.Language.TokenKind]::Question }).Count | Should -Be 0
            }

            It 'contains no pipeline chain operators (&&, ||)' {
                ($script:Tokens | Where-Object {
                        $_.Kind -eq [System.Management.Automation.Language.TokenKind]::AndAnd -or
                        $_.Kind -eq [System.Management.Automation.Language.TokenKind]::OrOr
                    }).Count | Should -Be 0
            }

            It 'contains no ForEach-Object -Parallel' {
                ($script:Tokens | Where-Object {
                        $_.Kind -eq [System.Management.Automation.Language.TokenKind]::Parameter -and $_.ParameterName -eq 'Parallel'
                    }).Count | Should -Be 0
            }
    }
}
