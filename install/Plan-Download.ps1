# What an installer of install\ would download - said, not done.
#
# Every Install-Portable-* script runs its own logic to the point of its download (the release, the NVIDIA driver
# policy, the mirror) and, when AUDION_INSTALL_PLAN is 1, calls this instead of downloading: one line per file,
#
#     [PLAN] <component>|<file>|<url>|<bytes>
#
# the size read from the answer to HEAD ("" when the server does not say it). The window of the program reads these
# lines (media_cli.cmd plan) and names the file, its source and its size before anything is downloaded.
param(
    [Parameter(Mandatory = $true)][string]$Url,
    [string]$Name = '',
    [string]$What = '',
    [string]$Size = ''
)

$ProgressPreference = 'SilentlyContinue'
$headers = @{ 'User-Agent' = 'Audion-Media-Tools' }
if ($env:GITHUB_TOKEN) { $headers['Authorization'] = 'Bearer ' + $env:GITHUB_TOKEN }
if (-not $Name) { $Name = [IO.Path]::GetFileName(([Uri]$Url).AbsolutePath) }
if (-not $Size) {
    try {
        $answer = Invoke-WebRequest -Uri $Url -Method Head -Headers $headers -MaximumRedirection 10 -TimeoutSec 20 -UseBasicParsing
        $length = @($answer.Headers['Content-Length'])[0]
        if ($length) { $Size = [string]$length }
    } catch {
        Write-Host "[WARN] The size of $Name was not told: $($_.Exception.Message)"
    }
}
Write-Host "[PLAN] $What|$Name|$Url|$Size"
