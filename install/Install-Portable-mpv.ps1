# Audion Media Tools - portable mpv installer.
#
# mpv is the player the trim section uses to find a cut: exact seeks, one-frame
# steps both ways, backwards playback, and an A/B loop that is the cut itself.
# It runs as its own program and is spoken to over a pipe, exactly as ffmpeg.exe
# is used here.
#
# The release is found without the GitHub API, which rate-limits unauthenticated
# callers within a few calls: the /releases/latest page redirects to the current
# tag, and the expanded_assets page for that tag lists the archives.
#
# Licence: mpv is GPLv2-or-later. The shinchiro archive ships no licence text at
# all, so this script fetches it from the mpv repository and stores it beside the
# binary. This project is GPL-3.0-or-later and calls mpv as a separate program,
# so nothing is linked and the two remain cleanly separated.

[CmdletBinding()]
param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [switch]$KeepArchive
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

function Write-Step {
    param([string]$Text)
    Write-Host $Text
}

function Get-LatestMpvAsset {
    <#
        Returns the download URL of the plain 64-bit build.

        Not the -dev archive (import libraries for linking, which is neither
        needed nor wanted here) and not the -v3 build, which requires AVX2 and
        would refuse to start on an older machine.
    #>
    $headers = @{ 'User-Agent' = 'Audion-Media-Tools' }
    $latest = Invoke-WebRequest -Headers $headers -Uri 'https://github.com/shinchiro/mpv-winbuild-cmake/releases/latest' -MaximumRedirection 5
    $tag = ($latest.BaseResponse.RequestMessage.RequestUri.AbsoluteUri -split '/')[-1]
    if (-not $tag) { throw 'Could not determine the latest mpv release tag.' }

    $assets = Invoke-WebRequest -Headers $headers -Uri "https://github.com/shinchiro/mpv-winbuild-cmake/releases/expanded_assets/$tag"
    $matches = [regex]::Matches($assets.Content, '/shinchiro/mpv-winbuild-cmake/releases/download/[^"]+\.7z') |
        ForEach-Object { $_.Value } |
        Sort-Object -Unique |
        Where-Object { $_ -match '/mpv-x86_64-\d' }
    if (-not $matches) { throw "No plain x86_64 mpv archive in release $tag." }

    [pscustomobject]@{
        Tag = $tag
        Url = 'https://github.com' + ($matches | Select-Object -First 1)
    }
}

function Get-SevenZip {
    param([string]$Root)
    $candidates = @(
        (Join-Path $Root 'system_core\7zip\7za.exe'),
        (Join-Path $Root 'Tools\7zip\bin\7za.exe')
    )
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) { return $candidate }
    }
    foreach ($name in @('7za.exe', '7z.exe')) {
        $found = Get-Command $name -ErrorAction SilentlyContinue
        if ($found) { return $found.Source }
    }
    $ensure = Join-Path $PSScriptRoot 'Ensure-7zip.ps1'
    if (Test-Path $ensure) {
        Write-Step '[BOOTSTRAP] Ensuring portable 7-Zip before mpv...'
        . $ensure
        $null = Ensure-7za -ProjectRoot $Root
        $bootstrapped = Join-Path $Root 'system_core\7zip\7za.exe'
        if (Test-Path $bootstrapped) { return $bootstrapped }
    }
    throw '7-Zip was not found and could not be bootstrapped.'
}

$downloadDir = Join-Path $ProjectRoot 'install\download'
$toolsDir = Join-Path $ProjectRoot 'Tools'
$targetDir = Join-Path $toolsDir 'mpv'
$binDir = Join-Path $targetDir 'bin'

Write-Step '======================================================================'
Write-Step '  AUDION MEDIA TOOLS - INSTALL PORTABLE MPV'
Write-Step '======================================================================'
Write-Step "Root:    $ProjectRoot"
Write-Step "Target:  $binDir"

New-Item -ItemType Directory -Force -Path $downloadDir | Out-Null

Write-Step '[1/6] Finding the latest release...'
$asset = Get-LatestMpvAsset
$archive = Join-Path $downloadDir (Split-Path -Leaf $asset.Url)
Write-Step "[URL] $($asset.Url)"

Write-Step '[2/6] Downloading...'
Invoke-WebRequest -Headers @{ 'User-Agent' = 'Audion-Media-Tools' } -Uri $asset.Url -OutFile $archive
Write-Step ('[OK] Downloaded: {0:N1} MB' -f ((Get-Item $archive).Length / 1MB))

Write-Step '[3/6] Unpacking...'
$sevenZip = Get-SevenZip -Root $ProjectRoot
if (Test-Path $binDir) { Remove-Item -Recurse -Force $binDir }
New-Item -ItemType Directory -Force -Path $binDir | Out-Null
& $sevenZip x $archive "-o$binDir" -y | Out-Null
$player = Join-Path $binDir 'mpv.exe'
if (-not (Test-Path $player)) { throw "mpv.exe is not in the archive: $archive" }

# The archive carries scripts that install mpv into Windows - file associations,
# registry entries - and an updater that would replace the binary behind this
# program's back. A portable build has no business writing to the system, so
# they go.
foreach ($unwanted in @('installer', 'mpv-register.bat', 'mpv-unregister.bat', 'updater.bat')) {
    $path = Join-Path $binDir $unwanted
    if (Test-Path $path) { Remove-Item -Recurse -Force $path }
}

Write-Step '[4/6] Fetching the licence text (the archive ships none)...'
try {
    $licence = Invoke-WebRequest -Headers @{ 'User-Agent' = 'Audion-Media-Tools' } -Uri 'https://raw.githubusercontent.com/mpv-player/mpv/master/LICENSE.GPL'
    [IO.File]::WriteAllText((Join-Path $targetDir 'LICENSE.GPL'), $licence.Content, (New-Object Text.UTF8Encoding $false))
    $copyright = Invoke-WebRequest -Headers @{ 'User-Agent' = 'Audion-Media-Tools' } -Uri 'https://raw.githubusercontent.com/mpv-player/mpv/master/Copyright'
    [IO.File]::WriteAllText((Join-Path $targetDir 'COPYRIGHT'), $copyright.Content, (New-Object Text.UTF8Encoding $false))
    Write-Step '[OK] LICENSE.GPL and COPYRIGHT stored next to the binary.'
} catch {
    Write-Warning "The licence text could not be fetched: $($_.Exception.Message)"
    Write-Warning 'Add it manually before publishing a build that bundles mpv.'
}

Write-Step '[5/6] Verifying...'
$banner = & (Join-Path $binDir 'mpv.com') --version 2>&1
$version = ($banner | Select-Object -First 1)
Write-Step "[OK] $version"

Write-Step '[6/6] Fetching the matching sources (GPL: the binary travels with them)...'
# The commits come out of the binary rather than being pinned here, so the
# archives always match the build that was just installed. mpv prints
# "mpv v0.41.0-923-g7b8915bc1" and "FFmpeg version: N-126125-g1d7b14f61".
$bannerText = ($banner -join "`n")
$mpvCommit = ([regex]::Match($bannerText, 'mpv v[\d.]+-\d+-g([0-9a-f]{7,})')).Groups[1].Value
$ffCommit = ([regex]::Match($bannerText, 'FFmpeg version: N-\d+-g([0-9a-f]{7,})')).Groups[1].Value

$sources = @()
if ($mpvCommit) {
    $sources += @{ name = "mpv-$mpvCommit-source.tar.gz"; url = "https://codeload.github.com/mpv-player/mpv/tar.gz/$mpvCommit" }
}
if ($ffCommit) {
    # Not the same FFmpeg the rest of the program carries: this one is compiled
    # into mpv, and its own source is what the licence asks for.
    $sources += @{ name = "mpv-ffmpeg-$ffCommit-source.tar.gz"; url = "https://codeload.github.com/FFmpeg/FFmpeg/tar.gz/$ffCommit" }
}
$sources += @{ name = "mpv-winbuild-$($asset.Tag)-source.tar.gz"; url = "https://codeload.github.com/shinchiro/mpv-winbuild-cmake/tar.gz/refs/tags/$($asset.Tag)" }

$stored = @()
foreach ($source in $sources) {
    $path = Join-Path $toolsDir $source.name
    try {
        Invoke-WebRequest -Headers @{ 'User-Agent' = 'Audion-Media-Tools' } -Uri $source.url -OutFile $path
        Write-Step ('[OK] {0} ({1:N1} MB)' -f $source.name, ((Get-Item $path).Length / 1MB))
        $stored += $source.name
    } catch {
        Write-Warning "$($source.name) could not be fetched: $($_.Exception.Message)"
        Write-Warning 'Fetch it before publishing a build that bundles mpv.'
    }
}

# What was taken and from where, so the pack can be checked years later without
# having to work out which commit this binary came from.
# Just the version, not the whole banner: the copyright sign in it comes back
# through the console code page as mojibake, and the record is a file.
$versionOnly = ([regex]::Match($bannerText, '^(mpv v\S+)')).Groups[1].Value
if (-not $versionOnly) { $versionOnly = 'unknown' }

$record = @(
    'Sources for the mpv build installed here.',
    '',
    "Binary:        $versionOnly",
    "Release tag:   $($asset.Tag)  (shinchiro/mpv-winbuild-cmake)",
    "mpv commit:    $mpvCommit",
    "FFmpeg commit: $ffCommit",
    '',
    'Stored in Tools\:'
) + ($stored | ForEach-Object { "  $_" }) + @(
    '',
    'mpv is GPLv2-or-later, and the FFmpeg compiled into it carries GPL',
    'components. Both are run as a separate program here, not linked into this',
    'project. The build-scripts archive names the version and origin of every',
    'other library the build pulls in.'
)
[IO.File]::WriteAllText((Join-Path $targetDir 'SOURCES.txt'), ($record -join "`r`n"), (New-Object Text.UTF8Encoding $false))

# The same facts again, machine-readable. SOURCES.txt is for a person;
# Audion Build Licenses reads a sidecar next to the binary and takes
# version, licence and the path of the bundled source archive from it.
# Without this file the scanner sees three unmapped archives and three
# unmapped binaries, reports UNKNOWN_RISKY_FILE, and fails the project -
# measured 27 August 2026, six findings while the sources sat right there.
# The archive names carry commit hashes, so they cannot be pinned in the
# catalogue: only the installer knows what it just fetched.
$sidecar = [ordered]@{
    component = 'mpv'
    version = $versionOnly
    license = 'GPL v2 or later'
    upstream_commit = $mpvCommit
    upstream_url = "https://github.com/mpv-player/mpv/commit/$mpvCommit"
    source_archive = "Tools\$("mpv-$mpvCommit-source.tar.gz")"
    source_url = "https://codeload.github.com/mpv-player/mpv/tar.gz/$mpvCommit"
    release_tag = $asset.Tag
    provider = 'shinchiro/mpv-winbuild-cmake'
    bundled_ffmpeg_commit = $ffCommit
    bundled_ffmpeg_source_archive = "Tools\$("mpv-ffmpeg-$ffCommit-source.tar.gz")"
    buildscripts_source_archive = "Tools\$("mpv-winbuild-$($asset.Tag)-source.tar.gz")"
    stored_archives = @($stored)
    recorded_at = (Get-Date).ToString('o')
}
[IO.File]::WriteAllText((Join-Path $targetDir 'mpv-source.json'), (($sidecar | ConvertTo-Json -Depth 5) + "`r`n"), (New-Object Text.UTF8Encoding $false))
Write-Step '[OK] Licence record for the collector: Tools\mpv\mpv-source.json'

if (-not $KeepArchive) { Remove-Item -Force $archive -ErrorAction SilentlyContinue }

Write-Step ''
Write-Step "[SUCCESS] mpv installed: $player"
Write-Step "[NOTE] Release $($asset.Tag). Settings live in config\mpv."
exit 0
