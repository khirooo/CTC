# Pester port of cli/tests/test_login.sh's bash cmd_login coverage, for the
# Windows Invoke-CtcLogin port (cli/ctc.ps1). Unlike Launch.Tests.ps1/
# Install.Tests.ps1 (which run ctc.ps1/install.ps1 as a REAL child process),
# this file dot-sources ctc.ps1 directly and calls Invoke-CtcLogin in-process
# so Pester can Mock the cert-trust/elevation functions
# (Add-CtcCurrentUserTrust / Import-CtcMachineTrust / Test-CtcElevated) and
# Read-Host -- exactly the use case called out by the comment above the
# bottom dot-source guard in ctc.ps1 ("lets Pester dot-source it to call the
# internal Invoke-Ctc* functions (and Mock things like Read-Host /
# Add-CtcCurrentUserTrust) in isolation."). This file NEVER touches a real
# X509 cert store and NEVER prompts for real input: every cert-trust function
# and Read-Host call is Mocked in BeforeEach.
#
# curl.exe itself is NOT mocked via Pester (it's a native exe, not a
# dot-sourced PS function) -- it is shadowed on PATH with a real stub script,
# the same New-CtcStub/Initialize-CtcTestEnv mechanism Launch.Tests.ps1 and
# Install.Tests.ps1 already use, so `& curl.exe` in Invoke-CtcLogin resolves
# to the stub even though the function runs in-process.

BeforeAll {
    . (Join-Path $PSScriptRoot 'Common.ps1')
    # Dot-source the launcher itself into this scope (not a child process) so
    # Invoke-CtcLogin and its helpers (Add-CtcCurrentUserTrust, etc.) become
    # plain functions here that Mock can shadow. The bottom dispatch guard in
    # ctc.ps1 only runs Invoke-CtcMain/exit when NOT dot-sourced, so this is
    # safe -- see the comment at the bottom of ctc.ps1.
    . $script:CtcScriptPath

    $script:FakeCertPem = '-----BEGIN CERTIFICATE-----FAKE-----END CERTIFICATE-----'

    function Invoke-CtcLoginCaptured {
        # Calls Invoke-CtcLogin in-process while capturing its
        # [Console]::Out/Error writes (which, unlike Invoke-CtcScript's real
        # child process, would otherwise go to the Pester host's own
        # console) into strings so assertions can inspect them.
        param([string[]]$CtcArgs = @())
        $origOut = [Console]::Out
        $origErr = [Console]::Error
        $swOut = New-Object IO.StringWriter
        $swErr = New-Object IO.StringWriter
        [Console]::SetOut($swOut)
        [Console]::SetError($swErr)
        try {
            $code = Invoke-CtcLogin -CtcArgs $CtcArgs
        } finally {
            [Console]::SetOut($origOut)
            [Console]::SetError($origErr)
        }
        [PSCustomObject]@{
            ExitCode = $code
            StdOut   = $swOut.ToString()
            StdErr   = $swErr.ToString()
        }
    }

    function New-CtcLoginCurlStub {
        # Shadows curl.exe on PATH (a real stub file, not a Pester Mock --
        # see the file header) so the hard-coded
        # `& curl.exe -fsSLk $caUrl -o $cert` in Invoke-CtcLogin "downloads"
        # a canned CA cert instead of hitting the network. Mirrors
        # Install.Tests.ps1's curl.exe stub shape.
        param($Sandbox, [int]$ExitCode = 0, [switch]$NoFile, [string]$CertBody = $script:FakeCertPem)
        $writeLoop = if ($NoFile) {
            ''
        } else {
            # Single-quoted here-string so $@/$a are left for the stub's own
            # shell to expand (not PowerShell); the cert body is substituted
            # afterwards via a literal (non-regex) -replace.
            (@'
prev=""
for a in "$@"; do
  if [ "$prev" = "-o" ]; then printf '%s' 'CERTBODY_PLACEHOLDER' > "$a"; fi
  prev="$a"
done
'@).Replace('CERTBODY_PLACEHOLDER', $CertBody)
        }
        $body = "$writeLoop`nexit $ExitCode`n"
        New-CtcStub -Sandbox $Sandbox -Name 'curl.exe' -Body $body | Out-Null
    }

    function ConvertTo-CtcSecureStringForTest {
        param([string]$PlainText)
        $ss = New-Object Security.SecureString
        foreach ($ch in $PlainText.ToCharArray()) { $ss.AppendChar($ch) }
        $ss.MakeReadOnly()
        return $ss
    }

    function Get-CtcLoginEnvJsonObj {
        param($Sandbox)
        $cfg = Get-CtcTestConfigDir
        $path = Join-Path $cfg 'env.json'
        if (-not (Test-Path -LiteralPath $path)) { return $null }
        return (Get-Content -Raw -LiteralPath $path | ConvertFrom-Json)
    }

    function Get-CtcLoginCertPath {
        $cfg = Get-CtcTestConfigDir
        return (Join-Path $cfg 'ca.pem')
    }
}

Describe 'Invoke-CtcLogin' {
    BeforeEach {
        $script:SavedEnv = Save-CtcTestEnv
        $script:Sandbox = New-CtcTestSandbox
        Initialize-CtcTestEnv -Sandbox $script:Sandbox

        # Default happy-path mocks for every cert-trust / elevation function
        # Invoke-CtcLogin can call -- tests override individual mocks as
        # needed. None of these ever touch a real X509 store.
        Mock Add-CtcCurrentUserTrust { $true }
        Mock Import-CtcMachineTrust { $true }
        Mock Test-CtcElevated { $true }
        # Safety net: Invoke-CtcLogin must NEVER elevate (no RunAs prompt is
        # part of the Windows design -- -Machine just requires an
        # already-elevated shell). If any code path tried to self-elevate
        # via Start-Process, fail loudly instead of silently launching it.
        Mock Start-Process { throw 'Invoke-CtcLogin must never call Start-Process (no self-elevation).' }
    }

    AfterEach {
        Remove-CtcTestSandbox -Sandbox $script:Sandbox
        Restore-CtcTestEnv -Saved $script:SavedEnv
    }

    Context 'token source' {
        It 'uses the -Token argument verbatim and never prompts' {
            Mock Read-Host { throw 'Read-Host must not be called when -Token is supplied' }
            New-CtcLoginCurlStub -Sandbox $script:Sandbox

            $result = Invoke-CtcLoginCaptured -CtcArgs @('-Token', 'github_pat_FROMFLAG')

            $result.ExitCode | Should -Be 0
            (Get-CtcLoginEnvJsonObj -Sandbox $script:Sandbox).COPILOT_GITHUB_TOKEN | Should -Be 'github_pat_FROMFLAG'
        }

        It 'prompts with Read-Host -AsSecureString when -Token is omitted' {
            Mock Read-Host {
                param($Prompt, [switch]$AsSecureString)
                ConvertTo-CtcSecureStringForTest -PlainText 'github_pat_FROMPROMPT'
            }
            New-CtcLoginCurlStub -Sandbox $script:Sandbox

            $result = Invoke-CtcLoginCaptured -CtcArgs @()

            $result.ExitCode | Should -Be 0
            (Get-CtcLoginEnvJsonObj -Sandbox $script:Sandbox).COPILOT_GITHUB_TOKEN | Should -Be 'github_pat_FROMPROMPT'
            Should -Invoke Read-Host -Times 1 -Exactly -ParameterFilter { $AsSecureString }
        }

        It 'aborts with exit 1 and no token entered when -Token is an empty string' {
            Mock Read-Host { throw 'Read-Host must not be called when -Token is explicitly supplied (even empty)' }
            New-CtcLoginCurlStub -Sandbox $script:Sandbox

            $result = Invoke-CtcLoginCaptured -CtcArgs @('-Token', '')

            $result.ExitCode | Should -Be 1
            $result.StdErr | Should -Match 'No token entered'
            Get-CtcLoginEnvJsonObj -Sandbox $script:Sandbox | Should -BeNullOrEmpty
        }

        It 'aborts with exit 1 when the prompted token is empty' {
            Mock Read-Host { ConvertTo-CtcSecureStringForTest -PlainText '' }
            New-CtcLoginCurlStub -Sandbox $script:Sandbox

            $result = Invoke-CtcLoginCaptured -CtcArgs @()

            $result.ExitCode | Should -Be 1
            $result.StdErr | Should -Match 'No token entered'
            Should -Invoke Add-CtcCurrentUserTrust -Times 0
        }
    }

    Context 'http vs https scheme' {
        It 'builds an https CA URL and still downloads via curl.exe -fsSLk' {
            [Environment]::SetEnvironmentVariable('CTC_SCHEME', 'https')
            [Environment]::SetEnvironmentVariable('CTC_HOST', 'ctc.example.com')
            New-CtcLoginCurlStub -Sandbox $script:Sandbox

            $result = Invoke-CtcLoginCaptured -CtcArgs @('-Token', 'tok')

            $result.ExitCode | Should -Be 0
            $log = Get-CtcStubLog -Sandbox $script:Sandbox -Name 'curl.exe'
            $log | Should -Match ([regex]::Escape('https://ctc.example.com/ctc-ca.pem'))
            $log | Should -Match '-fsSLk'
        }

        It 'builds an http CA URL and still passes -k (matches bash cmd_login, which is unconditional for the CA download)' {
            [Environment]::SetEnvironmentVariable('CTC_SCHEME', 'http')
            [Environment]::SetEnvironmentVariable('CTC_HOST', 'ctc.example.com')
            New-CtcLoginCurlStub -Sandbox $script:Sandbox

            $result = Invoke-CtcLoginCaptured -CtcArgs @('-Token', 'tok')

            $result.ExitCode | Should -Be 0
            $log = Get-CtcStubLog -Sandbox $script:Sandbox -Name 'curl.exe'
            $log | Should -Match ([regex]::Escape('http://ctc.example.com/ctc-ca.pem'))
            $log | Should -Match '-fsSLk'
        }
    }

    Context 'server / download error handling' {
        It 'returns exit 1 and reports the failed URL when curl.exe exits non-zero' {
            [Environment]::SetEnvironmentVariable('CTC_SCHEME', 'https')
            [Environment]::SetEnvironmentVariable('CTC_HOST', 'ctc.example.com')
            New-CtcLoginCurlStub -Sandbox $script:Sandbox -ExitCode 7 -NoFile

            $result = Invoke-CtcLoginCaptured -CtcArgs @('-Token', 'tok')

            $result.ExitCode | Should -Be 1
            $result.StdErr | Should -Match 'failed to download CA cert'
            $result.StdErr | Should -Match ([regex]::Escape('https://ctc.example.com/ctc-ca.pem'))
            Get-CtcLoginEnvJsonObj -Sandbox $script:Sandbox | Should -BeNullOrEmpty
            Should -Invoke Add-CtcCurrentUserTrust -Times 0
        }

        It 'returns exit 1 when curl.exe exits 0 but never writes the cert file' {
            New-CtcLoginCurlStub -Sandbox $script:Sandbox -ExitCode 0 -NoFile

            $result = Invoke-CtcLoginCaptured -CtcArgs @('-Token', 'tok')

            $result.ExitCode | Should -Be 1
            $result.StdErr | Should -Match 'failed to download CA cert'
        }
    }

    Context 'env.json contents' {
        It 'writes HOME/USERPROFILE/XDG_* under an isolated home, plus GH_HOST/GITHUB_API_URL/token/proxy/CA path' {
            [Environment]::SetEnvironmentVariable('GHE_DOMAIN', 'my.ghe.example')
            [Environment]::SetEnvironmentVariable('CTC_PROXY_HOST', 'proxy.example.com')
            [Environment]::SetEnvironmentVariable('CTC_PROXY_PORT', '9090')
            New-CtcLoginCurlStub -Sandbox $script:Sandbox

            $result = Invoke-CtcLoginCaptured -CtcArgs @('-Token', 'github_pat_ENVTEST')

            $result.ExitCode | Should -Be 0
            $cfg = Get-CtcTestConfigDir
            $iso = Join-Path $cfg 'home'
            $envObj = Get-CtcLoginEnvJsonObj -Sandbox $script:Sandbox

            $envObj.HOME | Should -Be $iso
            $envObj.USERPROFILE | Should -Be $iso
            $envObj.XDG_CONFIG_HOME | Should -Be (Join-Path $iso '.config')
            $envObj.XDG_STATE_HOME | Should -Be (Join-Path $iso '.local\state')
            $envObj.XDG_CACHE_HOME | Should -Be (Join-Path $iso '.cache')
            $envObj.GH_HOST | Should -Be 'my.ghe.example'
            $envObj.GITHUB_API_URL | Should -Be 'https://my.ghe.example/api/v3'
            $envObj.COPILOT_GITHUB_TOKEN | Should -Be 'github_pat_ENVTEST'
            $envObj.HTTPS_PROXY | Should -Be 'http://proxy.example.com:9090'
            $envObj.NODE_EXTRA_CA_CERTS | Should -Be (Get-CtcLoginCertPath)
        }

        It 'creates the isolated home directory on disk' {
            New-CtcLoginCurlStub -Sandbox $script:Sandbox
            Invoke-CtcLoginCaptured -CtcArgs @('-Token', 'tok') | Out-Null

            $cfg = Get-CtcTestConfigDir
            Test-Path -LiteralPath (Join-Path $cfg 'home') -PathType Container | Should -BeTrue
        }
    }

    Context 'CA file' {
        It 'writes the downloaded CA cert bytes to ca.pem under the config dir' {
            New-CtcLoginCurlStub -Sandbox $script:Sandbox -CertBody $script:FakeCertPem

            $result = Invoke-CtcLoginCaptured -CtcArgs @('-Token', 'tok')

            $result.ExitCode | Should -Be 0
            $certPath = Get-CtcLoginCertPath
            Test-Path -LiteralPath $certPath | Should -BeTrue
            (Get-Content -Raw -LiteralPath $certPath).Trim() | Should -Be $script:FakeCertPem
        }
    }

    Context 'cert store trust (mocked -- never touches the real store)' {
        It 'calls Add-CtcCurrentUserTrust with the downloaded cert path when -Machine is not given' {
            New-CtcLoginCurlStub -Sandbox $script:Sandbox

            $result = Invoke-CtcLoginCaptured -CtcArgs @('-Token', 'tok')

            $result.ExitCode | Should -Be 0
            $certPath = Get-CtcLoginCertPath
            Should -Invoke Add-CtcCurrentUserTrust -Times 1 -Exactly -ParameterFilter { $Path -eq $certPath }
            Should -Invoke Import-CtcMachineTrust -Times 0
        }

        It 'returns exit 1 and never writes env.json when Add-CtcCurrentUserTrust fails' {
            Mock Add-CtcCurrentUserTrust { $false }
            New-CtcLoginCurlStub -Sandbox $script:Sandbox

            $result = Invoke-CtcLoginCaptured -CtcArgs @('-Token', 'tok')

            $result.ExitCode | Should -Be 1
            $result.StdErr | Should -Match 'cert trust failed'
            Get-CtcLoginEnvJsonObj -Sandbox $script:Sandbox | Should -BeNullOrEmpty
        }
    }

    Context '-Machine flag' {
        It 'calls Import-CtcMachineTrust (not Add-CtcCurrentUserTrust) when -Machine is given and the shell is elevated' {
            Mock Test-CtcElevated { $true }
            New-CtcLoginCurlStub -Sandbox $script:Sandbox

            $result = Invoke-CtcLoginCaptured -CtcArgs @('-Token', 'tok', '-Machine')

            $result.ExitCode | Should -Be 0
            $certPath = Get-CtcLoginCertPath
            Should -Invoke Import-CtcMachineTrust -Times 1 -Exactly -ParameterFilter { $Path -eq $certPath }
            Should -Invoke Add-CtcCurrentUserTrust -Times 0
        }

        It 'refuses with exit 1 and manual-import instructions when -Machine is given but not elevated, without attempting elevation' {
            Mock Test-CtcElevated { $false }
            New-CtcLoginCurlStub -Sandbox $script:Sandbox

            $result = Invoke-CtcLoginCaptured -CtcArgs @('-Token', 'tok', '-Machine')

            $result.ExitCode | Should -Be 1
            $result.StdErr | Should -Match 'needs an elevated PowerShell'
            $result.StdErr | Should -Match 'Cert:\\LocalMachine\\Root'
            Should -Invoke Import-CtcMachineTrust -Times 0
            Should -Invoke Start-Process -Times 0
            Get-CtcLoginEnvJsonObj -Sandbox $script:Sandbox | Should -BeNullOrEmpty
        }

        It 'returns exit 1 and never writes env.json when Import-CtcMachineTrust fails even though elevated' {
            Mock Test-CtcElevated { $true }
            Mock Import-CtcMachineTrust { $false }
            New-CtcLoginCurlStub -Sandbox $script:Sandbox

            $result = Invoke-CtcLoginCaptured -CtcArgs @('-Token', 'tok', '-Machine')

            $result.ExitCode | Should -Be 1
            $result.StdErr | Should -Match 'cert trust failed'
            Get-CtcLoginEnvJsonObj -Sandbox $script:Sandbox | Should -BeNullOrEmpty
        }
    }

    Context 'proxy defaults' {
        It 'defaults HTTPS_PROXY to the CTC host on port 8080 when CTC_PROXY_HOST/PORT are unset' {
            [Environment]::SetEnvironmentVariable('CTC_HOST', 'ctc.local')
            New-CtcLoginCurlStub -Sandbox $script:Sandbox

            $result = Invoke-CtcLoginCaptured -CtcArgs @('-Token', 'tok')

            $result.ExitCode | Should -Be 0
            (Get-CtcLoginEnvJsonObj -Sandbox $script:Sandbox).HTTPS_PROXY | Should -Be 'http://ctc.local:8080'
        }

        It 'honors CTC_PROXY_HOST and CTC_PROXY_PORT overrides' {
            [Environment]::SetEnvironmentVariable('CTC_HOST', 'ctc.local')
            [Environment]::SetEnvironmentVariable('CTC_PROXY_HOST', 'other-proxy.local')
            [Environment]::SetEnvironmentVariable('CTC_PROXY_PORT', '4444')
            New-CtcLoginCurlStub -Sandbox $script:Sandbox

            $result = Invoke-CtcLoginCaptured -CtcArgs @('-Token', 'tok')

            $result.ExitCode | Should -Be 0
            (Get-CtcLoginEnvJsonObj -Sandbox $script:Sandbox).HTTPS_PROXY | Should -Be 'http://other-proxy.local:4444'
        }
    }

    Context 'no elevation' {
        It 'never calls Start-Process in the default (CurrentUser) trust path' {
            New-CtcLoginCurlStub -Sandbox $script:Sandbox

            Invoke-CtcLoginCaptured -CtcArgs @('-Token', 'tok') | Out-Null

            Should -Invoke Start-Process -Times 0
        }

        It 'never calls Start-Process even when -Machine is requested while unelevated' {
            Mock Test-CtcElevated { $false }
            New-CtcLoginCurlStub -Sandbox $script:Sandbox

            Invoke-CtcLoginCaptured -CtcArgs @('-Token', 'tok', '-Machine') | Out-Null

            Should -Invoke Start-Process -Times 0
        }
    }
}
