# Verifies `ctc status` and `ctc logout` (Invoke-CtcStatus / Invoke-CtcLogout
# in cli/ctc.ps1): not-set-up messaging, masked token display, cert-trust
# messaging, and logout's config/home cleanup. Ported from
# cli/tests/test_status_logout.sh.
#
# Strategy: dot-source ctc.ps1 and run every test inside Common.ps1's sandbox
# (New-CtcTestSandbox / Initialize-CtcTestEnv), so CTC_CONFIG_DIR/HOME/etc.
# all point under a throwaway temp directory -- never the real user profile.
# Test-CtcCertTrusted is always Mocked (even when neither "trusted" value is
# under test) so this file can never fall through to a real
# Cert:\CurrentUser\Root / Cert:\LocalMachine\Root lookup. Invoke-CtcStatus/
# Invoke-CtcLogout write via [Console]::Out, not Write-Output (see the NOTE
# above Invoke-CtcStatus in ctc.ps1), so output is captured by redirecting
# [Console]::Out to an in-process StringWriter.
#
# NOTE on scoping: see Hygiene.Tests.ps1's header comment -- everything the
# It blocks need is set up inside BeforeAll/BeforeEach, not at top level.

Describe 'StatusLogout: ctc status / ctc logout' {
    BeforeAll {
        . (Join-Path $PSScriptRoot 'Common.ps1')
        . $script:CtcScriptPath   # dot-source only -- bottom guard skips Invoke-CtcMain

        $script:OrigConsoleOut = [Console]::Out
        $script:OrigSavedEnv = Save-CtcTestEnv

        function Invoke-CtcStatusCaptured {
            $sw = New-Object IO.StringWriter
            [Console]::SetOut($sw)
            try { $code = Invoke-CtcStatus } finally { [Console]::SetOut($script:OrigConsoleOut) }
            [PSCustomObject]@{ Code = $code; Text = $sw.ToString() }
        }

        function Invoke-CtcLogoutCaptured {
            $sw = New-Object IO.StringWriter
            [Console]::SetOut($sw)
            try { $code = Invoke-CtcLogout } finally { [Console]::SetOut($script:OrigConsoleOut) }
            [PSCustomObject]@{ Code = $code; Text = $sw.ToString() }
        }
    }

    AfterAll {
        Restore-CtcTestEnv -Saved $script:OrigSavedEnv
    }

    BeforeEach {
        $script:Sandbox = New-CtcTestSandbox
        Initialize-CtcTestEnv -Sandbox $script:Sandbox
        # A stand-in for "the real user's home", outside CTC's config dir, so
        # logout tests can assert it is never touched.
        $script:RealHomeSentinel = Join-Path $script:Sandbox.Home 'totally-unrelated-user-file.txt'
        Set-Content -LiteralPath $script:RealHomeSentinel -Value 'do not touch' -Encoding ascii
        Mock Test-CtcCertTrusted { return $false }
    }

    AfterEach {
        Remove-CtcTestSandbox -Sandbox $script:Sandbox
    }

    Context 'status when not logged in' {
        It "reports not set up and exits 0, without ever consulting the cert store" {
            $result = Invoke-CtcStatusCaptured
            $result.Code | Should -Be 0
            $result.Text | Should -Match "Not set up\. Run 'ctc login'\."
            Should -Not -Invoke Test-CtcCertTrusted
        }
    }

    Context 'status when logged in' {
        It 'shows set up, the proxy host (scheme stripped), and only the last 4 token characters' {
            Write-CtcLoginEnvJson -Sandbox $script:Sandbox -Token 'github_pat_SECRETVALUE9999' -Proxy 'http://ctc.local:8080' | Out-Null
            $result = Invoke-CtcStatusCaptured
            $result.Code | Should -Be 0
            $result.Text | Should -Match 'CTC: Set up'
            $result.Text | Should -Match 'proxy: ctc\.local:8080'
            $result.Text | Should -Match '9999'
            $result.Text | Should -Not -Match 'github_pat_SECRETVALUE9999' -Because 'the full token must never be printed'
        }

        It 'reports the cert as trusted when Test-CtcCertTrusted returns true and a cert file exists' {
            Mock Test-CtcCertTrusted { return $true }
            Write-CtcLoginEnvJson -Sandbox $script:Sandbox -WithFakeCert | Out-Null
            $result = Invoke-CtcStatusCaptured
            $result.Text | Should -Match 'cert:  trusted'
            Should -Invoke Test-CtcCertTrusted -Times 1
        }

        It 'reports the cert as NOT trusted when Test-CtcCertTrusted returns false' {
            Mock Test-CtcCertTrusted { return $false }
            Write-CtcLoginEnvJson -Sandbox $script:Sandbox -WithFakeCert | Out-Null
            $result = Invoke-CtcStatusCaptured
            $result.Text | Should -Match "cert:  NOT trusted -- re-run 'ctc login'"
        }

        It 'reports the cert as NOT trusted when no cert file exists at all, without calling Test-CtcCertTrusted' {
            Write-CtcLoginEnvJson -Sandbox $script:Sandbox | Out-Null   # no -WithFakeCert
            $result = Invoke-CtcStatusCaptured
            $result.Text | Should -Match "cert:  NOT trusted -- re-run 'ctc login'"
            Should -Not -Invoke Test-CtcCertTrusted
        }
    }

    Context 'logout' {
        It 'removes env.json and the isolated home dir, leaves guidance, exits 0, and never touches the cert store' {
            $paths = Write-CtcLoginEnvJson -Sandbox $script:Sandbox -WithFakeCert
            Test-Path -LiteralPath (Join-Path $paths.ConfigDir 'env.json') | Should -BeTrue
            Test-Path -LiteralPath $paths.IsoHome | Should -BeTrue

            $result = Invoke-CtcLogoutCaptured

            $result.Code | Should -Be 0
            Test-Path -LiteralPath (Join-Path $paths.ConfigDir 'env.json') | Should -BeFalse
            Test-Path -LiteralPath $paths.IsoHome | Should -BeFalse
            $result.Text | Should -Match "CTC config removed\. Your normal 'copilot' is unaffected\."
            $result.Text | Should -Match 'Cert:\\CurrentUser\\Root'
            Should -Not -Invoke Test-CtcCertTrusted
        }

        It 'never removes the CA cert file itself (only prints manual removal instructions)' {
            $paths = Write-CtcLoginEnvJson -Sandbox $script:Sandbox -WithFakeCert
            Invoke-CtcLogoutCaptured | Out-Null
            Test-Path -LiteralPath $paths.CertPath | Should -BeTrue -Because 'Invoke-CtcLogout only removes env.json/home, never the cert file'
        }

        It 'leaves the real-home sentinel file untouched' {
            Write-CtcLoginEnvJson -Sandbox $script:Sandbox -WithFakeCert | Out-Null
            Invoke-CtcLogoutCaptured | Out-Null
            Test-Path -LiteralPath $script:RealHomeSentinel | Should -BeTrue
            (Get-Content -Raw -LiteralPath $script:RealHomeSentinel) | Should -Match 'do not touch'
        }

        It 'is a no-op (still exits 0) when nothing was ever logged in' {
            $result = Invoke-CtcLogoutCaptured
            $result.Code | Should -Be 0
            $result.Text | Should -Match "CTC config removed\."
        }
    }
}
