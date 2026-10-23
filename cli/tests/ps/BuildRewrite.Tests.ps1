# Verifies the web/Dockerfile `sed` rewrites that bake deployment-specific
# defaults into cli/ctc.ps1 / cli/install.ps1 at image-build time (see
# files/ps-anchors.md in the session state for the agreed anchor contract).
#
# Mirrors cli/tests/test_launch.sh's
# test_no_proxy_build_time_rewrite_bakes_default, but for every PS anchor
# instead of just one, and additionally re-parses the baked file to make sure
# the substitution never corrupts PowerShell syntax.
#
# BSD sed (macOS, what this suite runs on) has no GNU-compatible `-i` without
# an explicit backup-extension argument, so instead of running the Dockerfile
# lines verbatim we extract just their `s/.../.../g` expression and apply it
# non-in-place (`sed -e "<expr>" <src> > <dst>`), which is byte-for-byte
# identical in effect and portable to both sed flavors -- only the in-place
# vs redirected-output mechanism differs, never the substitution semantics.
#
# NOTE on scoping (see Hygiene.Tests.ps1's header comment for the full
# rationale): plain top-level data -- the regex extraction of anchors below --
# runs during Pester's Discovery pass and is used to generate one It per
# anchor via -ForEach. Everything an It/BeforeAll body needs at Run time
# (Common.ps1's helpers, file copies, sed invocation) is (re)computed inside
# BeforeAll/It, since Run-pass scriptblocks don't close over top-level state.

$CtcLibDir = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)   # .../cli
$CtcScriptPath = Join-Path $CtcLibDir 'ctc.ps1'
$CtcInstallScriptPath = Join-Path $CtcLibDir 'install.ps1'
$CtcDockerfilePath = Join-Path (Split-Path -Parent $CtcLibDir) 'web/Dockerfile'

$CtcDockerfileText = [IO.File]::ReadAllText($CtcDockerfilePath)

# One entry per `sed -i "<expr>" <targets>;` line in web/Dockerfile whose
# targets include a .ps1 file. Each $expr still contains the literal,
# unexpanded shell variable (e.g. "$CTC_DOMAIN") exactly as Docker's
# `/bin/sh -c` would see it -- substituted for real only when we export that
# variable and hand the expression to `sh -c` below.
$script:CtcPsAnchors = @()
$sedLineMatches = [regex]::Matches($CtcDockerfileText, 'sed -i "([^"]+)" ([^;]+);')
foreach ($m in $sedLineMatches) {
    $expr = $m.Groups[1].Value
    $targets = $m.Groups[2].Value -split '\s+' | Where-Object { $_ -match '\.ps1$' } | ForEach-Object { Split-Path -Leaf $_ }
    if ($targets.Count -eq 0) { continue }
    # The anchor's own PS variable name appears escaped (\$NAME) on both
    # sides of the s/// expression (it is literal PowerShell source, not a
    # shell variable to expand) -- take the first occurrence.
    $psVarMatch = [regex]::Match($expr, '\\\$([A-Z_]+)')
    # The deployment value is a REAL (unescaped) shell variable reference.
    $envVarMatch = [regex]::Match($expr, '(?<!\\)\$([A-Z_]+)')
    if (-not $psVarMatch.Success -or -not $envVarMatch.Success) { continue }
    $script:CtcPsAnchors += @{
        PsVarName  = $psVarMatch.Groups[1].Value
        EnvVarName = $envVarMatch.Groups[1].Value
        Expr       = $expr
        Targets    = $targets
        TestValue  = "baked-$($psVarMatch.Groups[1].Value.ToLowerInvariant())-value"
    }
}

Describe 'BuildRewrite: web/Dockerfile sed anchors' {
    BeforeAll {
        . (Join-Path $PSScriptRoot 'Common.ps1')

        function Get-CtcAnchorSourcePath {
            param([string]$Target)
            if ($Target -eq 'ctc.ps1') { return $script:CtcScriptPath }
            if ($Target -eq 'install.ps1') { return $script:CtcInstallScriptPath }
            throw "unexpected target $Target"
        }

        $script:BashLike = (Get-Command sh -ErrorAction SilentlyContinue)
        if (-not $script:BashLike) { throw 'sh not found -- required to reproduce Dockerfile RUN semantics' }

        # Re-run the same extraction as the top-level Discovery-phase code
        # above (used there to drive the -ForEach below). Plain top-level
        # variables are NOT visible to It bodies at Run time (see this
        # file's header comment), so re-derive the count here instead of
        # relying on the top-level $script:CtcPsAnchors from Discovery.
        $dockerPath = Join-Path (Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))) 'web/Dockerfile'
        $dockerText = [IO.File]::ReadAllText($dockerPath)
        $script:RunPhasePsAnchorCount = ([regex]::Matches($dockerText, 'sed -i "([^"]+)" ([^;]+\.ps1[^;]*);')).Count
    }

    It 'found at least six PS anchor sed lines in web/Dockerfile' {
        $script:RunPhasePsAnchorCount | Should -BeGreaterOrEqual 6
    }

    Context 'anchor <PsVarName>' -ForEach $script:CtcPsAnchors {
        BeforeAll {
            $script:TempDir = Join-Path ([IO.Path]::GetTempPath()) ('ctc-buildrewrite-' + [guid]::NewGuid().ToString('N'))
            New-Item -ItemType Directory -Path $script:TempDir -Force | Out-Null
        }

        AfterAll {
            Remove-Item -LiteralPath $script:TempDir -Recurse -Force -ErrorAction SilentlyContinue
        }

        It 'appears exactly once in the shipped source, per target file' {
            foreach ($target in $Targets) {
                $srcPath = Get-CtcAnchorSourcePath -Target $target
                $text = [IO.File]::ReadAllText($srcPath)
                $anchorHits = [regex]::Matches($text, [regex]::Escape('$' + $PsVarName) + ' = ')
                $anchorHits.Count | Should -Be 1 -Because "`$$PsVarName should be a unique anchor in $target"
            }
        }

        It 'bakes the deployment value and still parses with zero errors after sed' {
            foreach ($target in $Targets) {
                $srcPath = Get-CtcAnchorSourcePath -Target $target
                $copyPath = Join-Path $script:TempDir $target
                Copy-Item -LiteralPath $srcPath -Destination $copyPath -Force
                $outPath = "$copyPath.out"

                # Run the REAL Dockerfile expression through `sh -c`, exactly as
                # Docker's RUN step would, so the deployment env var is expanded
                # by the shell -- not by us -- the same way it is in production.
                $sedExpr = $Expr
                $env:CTC_BUILD_REWRITE_TEST_VALUE = $TestValue
                $shCmd = "export $EnvVarName=`"`$CTC_BUILD_REWRITE_TEST_VALUE`"; sed -e `"$sedExpr`" '$copyPath' > '$outPath'"
                & $script:BashLike.Source '-c' $shCmd
                $LASTEXITCODE | Should -Be 0
                Remove-Item Env:\CTC_BUILD_REWRITE_TEST_VALUE -ErrorAction SilentlyContinue

                Test-Path -LiteralPath $outPath | Should -BeTrue
                $bakedText = [IO.File]::ReadAllText($outPath)

                $bakedHits = [regex]::Matches($bakedText, [regex]::Escape('$' + $PsVarName + " = '" + $TestValue + "'"))
                $bakedHits.Count | Should -Be 1 -Because "the baked value should appear exactly once in $target"

                # BOM + CRLF line endings must survive a byte-wise sed pass.
                $bakedBytes = [IO.File]::ReadAllBytes($outPath)
                $bakedBytes[0..2] | Should -Be @(0xEF, 0xBB, 0xBF) -Because 'sed must not strip the UTF-8 BOM'

                $tokens = $null
                $errors = $null
                [System.Management.Automation.Language.Parser]::ParseFile($outPath, [ref]$tokens, [ref]$errors) | Out-Null
                $errors.Count | Should -Be 0 -Because "the baked $target must still be valid PowerShell"
            }
        }
    }
}
