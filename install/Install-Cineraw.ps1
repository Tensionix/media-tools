# Audion Media Tools - cineraw: ProRes RAW developed on the video card.
#
# cineraw is the tool of libcraw (https://github.com/cyanreg/libcraw, BSD-2-Clause, by Lynne): it decodes a ProRes RAW
# clip with FFmpeg and develops every frame on a Vulkan device - the white balance and the colour matrix of the camera,
# as shot - into 16-bit pictures. libcraw publishes no builds, only its sources, so this script builds it here:
#
#   1. a portable MSYS2 in a folder of its own (nothing goes into Windows), the compiler and the build tools;
#   2. FFmpeg 9.0.2 cut down to what cineraw takes - the MOV demuxer, the ProRes RAW decoder, the TIFF and PPM
#      encoders: LGPL, three DLLs of 2 MB instead of the 97 DLLs and 134 MB of the FFmpeg of MSYS2;
#   3. libcraw at the commit checked on a machine with NVIDIA RTX (MEMORY.md);
#   4. Tools\cineraw: cineraw.exe, libcraw.dll, the FFmpeg DLLs, libwinpthread-1.dll, the licences, the sources and
#      cineraw-source.json - what was built from what.
#
# MSYS2 and the configure of FFmpeg do not take a path with spaces, so the build tree stands in a folder of the user
# without them and is removed at the end; the downloads stay in install\download\cineraw until its cleanup.

[CmdletBinding()]
param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [switch]$KeepBuildTree
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

# What is built. libcraw changes almost every day: move the commit after a check on an RTX machine.
$LibcrawCommit = '0d44e6d66c2ff8e0d84071612c09cd3062dd6098'
$FfmpegVersion = '9.0.2'
# The commit of n9.0.2 - the same as the FFmpeg of Gyan 9.0.2 in Tools\ffmpeg.
$FfmpegCommit = '946fcce07b6dcd0331c8cc609192aeff5e1924f8'
# The base of MSYS2, 27.09.2026, and its SHA-256 as the release on GitHub gives it (msys2/msys2-installer).
$MsysTag = '2026-09-27'
$MsysArchive = 'msys2-base-x86_64-20260927.tar.xz'
$MsysSha256 = 'ea2f31a0b6ade63914ce441ffb022f0f6aa96982bfefa2326460a26d5fb01322'
$MsysUrl = "https://github.com/msys2/msys2-installer/releases/download/$MsysTag/$MsysArchive"
# The packages of MSYS2 the build needs, and what they come to (measured on a clean base, 20.10.2026).
$Packages = @(
    'make', 'diffutils',
    'mingw-w64-ucrt-x86_64-gcc', 'mingw-w64-ucrt-x86_64-nasm', 'mingw-w64-ucrt-x86_64-pkgconf',
    'mingw-w64-ucrt-x86_64-meson', 'mingw-w64-ucrt-x86_64-ninja',
    'mingw-w64-ucrt-x86_64-vulkan-headers', 'mingw-w64-ucrt-x86_64-vulkan-loader', 'mingw-w64-ucrt-x86_64-glslang',
    'mingw-w64-ucrt-x86_64-python', 'mingw-w64-ucrt-x86_64-python-jinja', 'mingw-w64-ucrt-x86_64-python-markupsafe'
)
$PackagesBytes = '133000000'
$FfmpegConfigure = @(
    '--disable-everything', '--disable-programs', '--disable-doc', '--disable-network', '--disable-autodetect',
    '--disable-avdevice', '--disable-avfilter', '--disable-swscale', '--disable-swresample',
    '--enable-shared', '--disable-static', '--enable-w32threads', '--disable-debug',
    '--enable-protocol=file', '--enable-demuxer=mov', '--enable-decoder=prores_raw', '--enable-encoder=tiff,ppm'
)

$Tools = Join-Path $ProjectRoot 'Tools'
$Target = Join-Path $Tools 'cineraw'
$Download = Join-Path $ProjectRoot 'install\download\cineraw'
$LibcrawUrl = "https://codeload.github.com/cyanreg/libcraw/tar.gz/$LibcrawCommit"
$FfmpegUrl = "https://codeload.github.com/FFmpeg/FFmpeg/tar.gz/$FfmpegCommit"
# The sources the FFmpeg installer keeps for Tools\ffmpeg are of the same commit: taken from there when they are at hand.
$FfmpegAtHand = Join-Path $Tools "ffmpeg-$FfmpegVersion-source.tar.gz"
$LibcrawArchive = Join-Path $Download ("libcraw-{0}.tar.gz" -f $LibcrawCommit.Substring(0, 7))
$FfmpegArchive = Join-Path $Download "ffmpeg-$FfmpegVersion.tar.gz"
$MsysCached = Join-Path $Download $MsysArchive

function Write-Step([string]$Text) { Write-Host $Text }

function Get-File([string]$Url, [string]$Path) {
    Invoke-WebRequest -Headers @{ 'User-Agent' = 'Audion-Media-Tools' } -Uri $Url -OutFile $Path -UseBasicParsing
}

# A folder without spaces for the build tree: the local application data of the user, else the system drive.
function Get-BuildRoot {
    foreach ($base in @($env:LOCALAPPDATA, $env:TEMP, "$env:SystemDrive\")) {
        if ($base -and ($base -notmatch '\s')) { return (Join-Path $base 'AudionBuild\cineraw') }
    }
    throw 'No folder without spaces for the build of cineraw: LOCALAPPDATA, TEMP and the system drive all have them.'
}

function ConvertTo-MsysPath([string]$Path) {
    $full = [IO.Path]::GetFullPath($Path)
    return '/' + $full.Substring(0, 1).ToLowerInvariant() + ($full.Substring(2) -replace '\\', '/')
}

if ($env:AUDION_INSTALL_PLAN -eq '1') {
    # Say what would be downloaded (install\Plan-Download.ps1) and stop.
    $plan = Join-Path $PSScriptRoot 'Plan-Download.ps1'
    if (Test-Path -LiteralPath $MsysCached) { Write-Host "[PLAN] MSYS2|$MsysArchive|cache|$((Get-Item $MsysCached).Length)" }
    else { & $plan -Url $MsysUrl -What 'MSYS2' }
    Write-Host "[PLAN] MSYS2|$($Packages.Count) packages: the compiler, meson, Vulkan, Python|https://repo.msys2.org/|$PackagesBytes"
    if (Test-Path -LiteralPath $FfmpegArchive) { Write-Host "[PLAN] FFmpeg source|$(Split-Path -Leaf $FfmpegArchive)|cache|$((Get-Item $FfmpegArchive).Length)" }
    elseif (-not (Test-Path -LiteralPath $FfmpegAtHand)) { & $plan -Url $FfmpegUrl -Name "ffmpeg-$FfmpegVersion.tar.gz" -What 'FFmpeg source' -Size '17320345' }
    # codeload says no size: the archive of the commit is 16 579 840 bytes.
    if (Test-Path -LiteralPath $LibcrawArchive) { Write-Host "[PLAN] libcraw source|$(Split-Path -Leaf $LibcrawArchive)|cache|$((Get-Item $LibcrawArchive).Length)" }
    else { & $plan -Url $LibcrawUrl -Name (Split-Path -Leaf $LibcrawArchive) -What 'libcraw source' -Size '16579840' }
    exit 0
}

$started = Get-Date
$BuildRoot = Get-BuildRoot
$Msys = Join-Path $BuildRoot 'msys64'
New-Item -ItemType Directory -Force -Path $Download, $BuildRoot | Out-Null
Write-Host "Target:     $Target"
Write-Host "Build tree: $BuildRoot (removed at the end)"
Write-Host "libcraw:    $LibcrawCommit"
Write-Host "FFmpeg:     $FfmpegVersion (LGPL, MOV + ProRes RAW + TIFF/PPM)"

Write-Step '[1/6] MSYS2 base...'
if (Test-Path -LiteralPath $MsysCached) {
    $hash = (Get-FileHash -LiteralPath $MsysCached -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($hash -ne $MsysSha256) { Remove-Item -LiteralPath $MsysCached -Force }
}
if (-not (Test-Path -LiteralPath $MsysCached)) {
    Get-File $MsysUrl $MsysCached
    $hash = (Get-FileHash -LiteralPath $MsysCached -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($hash -ne $MsysSha256) { throw "SHA-256 of $MsysArchive is $hash, the release gives $MsysSha256." }
}
Write-Step ('[OK] {0}: {1:N1} MB, SHA-256 checked' -f $MsysArchive, ((Get-Item $MsysCached).Length / 1MB))
if (Test-Path -LiteralPath $Msys) { Remove-Item -LiteralPath $Msys -Recurse -Force }
& "$env:SystemRoot\System32\tar.exe" -xf $MsysCached -C $BuildRoot
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath (Join-Path $Msys 'usr\bin\bash.exe'))) { throw "$MsysArchive did not unpack." }

$env:MSYSTEM = 'UCRT64'
$env:CHERE_INVOKING = '1'
$bash = Join-Path $Msys 'usr\bin\bash.exe'

# A step of the build as a script of bash in the build tree: no quoting of bash through PowerShell.
function Invoke-Msys([string]$Name, [string]$Body, [switch]$MayEnd) {
    $file = Join-Path $BuildRoot "$Name.sh"
    [IO.File]::WriteAllText($file, ("set -e`n" + $Body + "`n").Replace("`r`n", "`n"), (New-Object Text.UTF8Encoding $false))
    $log = Join-Path $BuildRoot "$Name.log"
    # Windows PowerShell 5.1 turns every line a program writes to stderr into an error: it is the log, not a failure.
    $ErrorActionPreference = 'Continue'
    & $bash -l (ConvertTo-MsysPath $file) *> $log
    $code = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    if ($code -ne 0 -and -not $MayEnd) {
        Get-Content -LiteralPath $log -Tail 25 | ForEach-Object { Write-Host "    $_" }
        throw "$Name failed with exit code $code (log: $log)."
    }
}

Write-Step '[2/6] MSYS2: first start, update, packages...'
Invoke-Msys 'msys-init' 'true'
# The first update renews the core of MSYS2 and ends every process of it, this one too: its exit says nothing.
Invoke-Msys 'msys-update-1' 'pacman -Syuu --noconfirm' -MayEnd
Invoke-Msys 'msys-update-2' 'pacman -Syuu --noconfirm'
$cache = Join-Path $Msys 'var\cache\pacman\pkg'
$before = (Get-ChildItem -LiteralPath $cache -File -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum
Invoke-Msys 'msys-packages' ("pacman -S --noconfirm --needed " + ($Packages -join ' '))
$after = (Get-ChildItem -LiteralPath $cache -File -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum
Write-Step ('[OK] MSYS2 ready; packages downloaded: {0:N0} MB' -f (($after - $before) / 1MB))

Write-Step '[3/6] Sources...'
if (-not (Test-Path -LiteralPath $FfmpegArchive)) {
    if (Test-Path -LiteralPath $FfmpegAtHand) { Copy-Item -LiteralPath $FfmpegAtHand -Destination $FfmpegArchive }
    else { Get-File $FfmpegUrl $FfmpegArchive }
}
if (-not (Test-Path -LiteralPath $LibcrawArchive)) { Get-File $LibcrawUrl $LibcrawArchive }
Write-Step ('[OK] FFmpeg {0}: {1:N1} MB, libcraw {2}: {3:N1} MB' -f $FfmpegVersion, ((Get-Item $FfmpegArchive).Length / 1MB),
    $LibcrawCommit.Substring(0, 7), ((Get-Item $LibcrawArchive).Length / 1MB))

$jobs = [Math]::Max(2, [Environment]::ProcessorCount)
$b = ConvertTo-MsysPath $BuildRoot
Write-Step '[4/6] FFmpeg, cut down...'
Invoke-Msys 'ffmpeg' @"
export PATH=/ucrt64/bin:/usr/bin:`$PATH
cd '$b'
rm -rf ffmpeg-src ffmin
mkdir ffmpeg-src
tar -xzf '$(ConvertTo-MsysPath $FfmpegArchive)' -C ffmpeg-src --strip-components=1
cd ffmpeg-src
./configure --prefix='$b/ffmin' $($FfmpegConfigure -join ' ')
make -j$jobs
make install
"@
Write-Step '[OK] avcodec, avformat, avutil'

Write-Step '[5/6] libcraw and cineraw...'
Invoke-Msys 'libcraw' @"
export PATH=/ucrt64/bin:/usr/bin:`$PATH
export PKG_CONFIG_PATH='$b/ffmin/lib/pkgconfig'
cd '$b'
rm -rf libcraw-src
mkdir libcraw-src
tar -xzf '$(ConvertTo-MsysPath $LibcrawArchive)' -C libcraw-src --strip-components=1
cd libcraw-src
meson setup build --buildtype=release -Dtests=disabled -Dtools=enabled -Dffmpeg=enabled -Dc_args=-D_POSIX_THREAD_SAFE_FUNCTIONS -Dc_link_args=-static -Dcpp_link_args=-static
ninja -C build tools/cineraw.exe
"@

Write-Step '[6/6] Tools\cineraw...'
if (Test-Path -LiteralPath $Target) { Remove-Item -LiteralPath $Target -Recurse -Force }
$sourceDir = Join-Path $Target 'source'
New-Item -ItemType Directory -Force -Path $Target, $sourceDir | Out-Null
$craw = Join-Path $BuildRoot 'libcraw-src'
Copy-Item -LiteralPath (Join-Path $craw 'build\tools\cineraw.exe'), (Join-Path $craw 'build\lib\libcraw.dll') -Destination $Target
Copy-Item -Path (Join-Path $BuildRoot 'ffmin\bin\*.dll') -Destination $Target
Copy-Item -LiteralPath (Join-Path $Msys 'ucrt64\bin\libwinpthread-1.dll') -Destination $Target
Copy-Item -LiteralPath (Join-Path $craw 'LICENSE.md') -Destination (Join-Path $Target 'LICENSE-libcraw.md')
Copy-Item -LiteralPath (Join-Path $BuildRoot 'ffmpeg-src\COPYING.LGPLv2.1') -Destination (Join-Path $Target 'LICENSE-FFmpeg-LGPLv2.1.txt')
Copy-Item -LiteralPath (Join-Path $Msys 'ucrt64\share\licenses\winpthreads\COPYING') -Destination (Join-Path $Target 'LICENSE-winpthreads.txt')
Copy-Item -LiteralPath $FfmpegArchive, $LibcrawArchive -Destination $sourceDir

# The check: it starts outside MSYS2, with the DLLs beside it, and says what it is.
$saved = $env:PATH
$env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
try { $help = & (Join-Path $Target 'cineraw.exe') --help 2>&1 | Out-String; $code = $LASTEXITCODE } finally { $env:PATH = $saved }
if ($help -notmatch 'usage: cineraw') { throw "cineraw.exe does not start outside MSYS2 (exit $code): $help" }

$record = [ordered]@{
    component = 'cineraw'
    version = 'libcraw-' + $LibcrawCommit.Substring(0, 7)
    license = 'BSD-2-Clause (libcraw); LGPL-2.1-or-later (FFmpeg, no GPL parts); ZPL-2.1 and MIT (winpthreads)'
    upstream_commit = $LibcrawCommit
    upstream_url = "https://github.com/cyanreg/libcraw/commit/$LibcrawCommit"
    ffmpeg_version = $FfmpegVersion
    ffmpeg_configuration = ($FfmpegConfigure -join ' ')
    source_archives = @("Tools\cineraw\source\$(Split-Path -Leaf $FfmpegArchive)", "Tools\cineraw\source\$(Split-Path -Leaf $LibcrawArchive)")
    source_urls = @($FfmpegUrl, $LibcrawUrl)
    msys2_base = $MsysArchive
    built_at = (Get-Date).ToString('s')
}
$record | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $Target 'cineraw-source.json') -Encoding UTF8

if (-not $KeepBuildTree) {
    Set-Location -LiteralPath $ProjectRoot
    Remove-Item -LiteralPath $BuildRoot -Recurse -Force -ErrorAction SilentlyContinue
}
$size = (Get-ChildItem -LiteralPath $Target -Recurse -File | Measure-Object Length -Sum).Sum
Write-Step ('[OK] cineraw {0} in {1}: {2:N1} MB, {3:N1} min' -f $record.version, $Target, ($size / 1MB), ((Get-Date) - $started).TotalMinutes)
Write-Step '[SUCCESS] cineraw installed.'
