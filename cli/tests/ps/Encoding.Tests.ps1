# Encoding/line-ending checks: ctc.ps1 and install.ps1 must ship as
# UTF-8-with-BOM, CRLF (per .gitattributes), and .gitattributes itself must
# declare that policy for *.ps1 so git never silently renormalizes it.

$filesToCheck = @(
    @{ Name = 'ctc.ps1' }
    @{ Name = 'install.ps1' }
)

Describe 'Encoding: UTF-8 BOM' {
    BeforeAll {
        $script:CtcLibDir = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
    }

    It '<Name> starts with EF BB BF' -ForEach $filesToCheck {
        $Path = Join-Path $CtcLibDir $Name
        $bytes = [IO.File]::ReadAllBytes($Path)
        $bytes.Length | Should -BeGreaterOrEqual 3
        $bytes[0] | Should -Be 0xEF
        $bytes[1] | Should -Be 0xBB
        $bytes[2] | Should -Be 0xBF
    }
}

Describe 'Encoding: .gitattributes' {
    BeforeAll {
        $script:CtcLibDir = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
        $script:CtcRepoRoot = Split-Path -Parent $CtcLibDir
        $script:GitAttributesPath = Join-Path $CtcRepoRoot '.gitattributes'
    }

    It 'exists at the repo root' {
        Test-Path -LiteralPath $script:GitAttributesPath | Should -BeTrue
    }

    It 'declares *.ps1 eol=crlf' {
        $content = Get-Content -Raw -LiteralPath $script:GitAttributesPath
        $content | Should -Match '(?m)^\*\.ps1\s+text\s+eol=crlf\s*$'
    }
}
