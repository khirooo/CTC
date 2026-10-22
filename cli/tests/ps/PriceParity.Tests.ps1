# Verifies the Copilot per-model token-price table embedded in the PS
# statusline source ($script:CtcStatuslineSource inside cli/ctc.ps1) stays in
# exact sync with the PRICES table embedded in cli/ctc's Python statusline.
# Both are deliberately hand-maintained, independent copies of the same
# source-of-truth data (see the comment directly above each table), so
# nothing at runtime enforces parity -- this test is the only thing that
# does. order per row: (input, output, cache_read, cache_write), nano-AIU
# per token x1000.
#
# NOTE on scoping: see Hygiene.Tests.ps1's header comment -- plain top-level
# functions/variables are not visible to It bodies at Run time, so the
# extraction helpers below live inside BeforeAll.

Describe 'PriceParity: ctc.ps1 statusline prices vs cli/ctc (bash) PRICES' {
    BeforeAll {
        . (Join-Path $PSScriptRoot 'Common.ps1')

        function Get-CtcBashPrices {
            # Parses cli/ctc's `PRICES = { "id": (a, b, c, d), ... }` Python
            # dict literal out of the bash source. Tolerant of the trailing
            # comma and inline "# comment" on each row.
            param([string]$BashPath)
            $text = [IO.File]::ReadAllText($BashPath)
            $tableMatch = [regex]::Match($text, '(?s)PRICES\s*=\s*\{(.*?)\n\}')
            if (-not $tableMatch.Success) { throw "could not find PRICES = { ... } in $BashPath" }
            $body = $tableMatch.Groups[1].Value
            $prices = [ordered]@{}
            foreach ($m in [regex]::Matches($body, '"([^"]+)"\s*:\s*\(\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*\)')) {
                $prices[$m.Groups[1].Value] = @([int]$m.Groups[2].Value, [int]$m.Groups[3].Value, [int]$m.Groups[4].Value, [int]$m.Groups[5].Value)
            }
            return $prices
        }

        function Get-CtcPsPrices {
            # Parses the `$script:CtcSlPrices.Add('id', [int[]]@(a, b, c, d))`
            # calls out of the embedded here-string statusline source in
            # cli/ctc.ps1 (NOT out of a running instance of the dictionary --
            # the here-string is inert text at the point ctc.ps1 itself
            # executes; it is only ever materialized when
            # Install-CtcClaudeStatusline writes it out and Claude Code later
            # runs it as its own process).
            param([string]$PsPath)
            $text = [IO.File]::ReadAllText($PsPath)
            $hereStringMatch = [regex]::Match($text, "(?s)CtcStatuslineSource = @'\r?\n(.*?)\r?\n'@")
            if (-not $hereStringMatch.Success) { throw "could not find the `$script:CtcStatuslineSource here-string in $PsPath" }
            $body = $hereStringMatch.Groups[1].Value
            $prices = [ordered]@{}
            foreach ($m in [regex]::Matches($body, "CtcSlPrices\.Add\('([^']+)',\s*\[int\[\]\]@\(\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*\)\)")) {
                $prices[$m.Groups[1].Value] = @([int]$m.Groups[2].Value, [int]$m.Groups[3].Value, [int]$m.Groups[4].Value, [int]$m.Groups[5].Value)
            }
            return $prices
        }

        $script:BashPath = Join-Path $script:CtcLibDir 'ctc'
        $script:PsPath = $script:CtcScriptPath
        $script:BashPrices = Get-CtcBashPrices -BashPath $script:BashPath
        $script:PsPrices = Get-CtcPsPrices -PsPath $script:PsPath
    }

    It 'extracted a non-trivial number of rows from both sources' {
        $script:BashPrices.Count | Should -BeGreaterOrEqual 15
        $script:PsPrices.Count | Should -BeGreaterOrEqual 15
    }

    It 'has the exact same set of model ids in both tables' {
        $bashIds = [string[]]$script:BashPrices.Keys | Sort-Object
        $psIds = [string[]]$script:PsPrices.Keys | Sort-Object
        Compare-Object -ReferenceObject $bashIds -DifferenceObject $psIds | Should -BeNullOrEmpty
    }

    It 'has identical (input, output, cache_read, cache_write) values for every model id' {
        $mismatches = @()
        foreach ($id in $script:BashPrices.Keys) {
            if (-not $script:PsPrices.Contains($id)) { continue }   # covered by the id-set test above
            $bashVals = $script:BashPrices[$id]
            $psVals = $script:PsPrices[$id]
            if (($bashVals -join ',') -ne ($psVals -join ',')) {
                $mismatches += "$id`: bash=($($bashVals -join ', ')) ps=($($psVals -join ', '))"
            }
        }
        $mismatches | Should -BeNullOrEmpty -Because ('every model id should price identically in both launchers: ' + ($mismatches -join '; '))
    }

    It 'includes the synthetic (local/error) zero-priced sentinel row in both tables' {
        $script:BashPrices.Contains('<synthetic>') | Should -BeTrue
        $script:PsPrices.Contains('<synthetic>') | Should -BeTrue
        ($script:BashPrices['<synthetic>'] -join ',') | Should -Be '0,0,0,0'
        ($script:PsPrices['<synthetic>'] -join ',') | Should -Be '0,0,0,0'
    }
}
