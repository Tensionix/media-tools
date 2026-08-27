<#
.SYNOPSIS
  Audion Media Tools - bootstrap official 7-Zip portable CLIs.

.DESCRIPTION
  Dot-source this file to use Ensure-7zr / Ensure-7za / Expand-7zArchive.

  Idempotently installs 7-Zip standalone binaries into system_core\7zip.
  This mirrors the VapourSynth Engine Lite extractor helper used by its
  BtbN FFmpeg installer.
#>

function Get-Audion7zipDir {
    param([Parameter(Mandatory=$true)][string]$ProjectRoot)
    $d = Join-Path $ProjectRoot 'system_core\7zip'
    if (-not (Test-Path $d)) { New-Item -Path $d -ItemType Directory -Force | Out-Null }
    return $d
}

function Ensure-7zr {
    param([Parameter(Mandatory=$true)][string]$ProjectRoot)
    $dir = Get-Audion7zipDir -ProjectRoot $ProjectRoot
    $exe = Join-Path $dir '7zr.exe'
    if (-not (Test-Path $exe)) {
        $headers = @{ 'User-Agent' = 'Audion-Media-Tools' }
        $oldP = $ProgressPreference; $ProgressPreference = 'SilentlyContinue'
        try {
            Invoke-WebRequest -Headers $headers -Uri 'https://www.7-zip.org/a/7zr.exe' -OutFile $exe
        } finally { $ProgressPreference = $oldP }
        if (-not (Test-Path $exe)) { throw "Failed to download 7zr.exe to $exe" }
    }
    return $exe
}

function Ensure-7za {
    param(
        [Parameter(Mandatory=$true)][string]$ProjectRoot,
        [string]$ExtraVersion = '2501'
    )
    $dir = Get-Audion7zipDir -ProjectRoot $ProjectRoot
    $exe = Join-Path $dir '7za.exe'
    if (Test-Path $exe) { return $exe }

    $r = Ensure-7zr -ProjectRoot $ProjectRoot

    $headers = @{ 'User-Agent' = 'Audion-Media-Tools' }
    $extraName = "7z$ExtraVersion-extra.7z"
    $extraUrl = "https://www.7-zip.org/a/$extraName"
    $extraPath = Join-Path $dir $extraName

    if (-not (Test-Path $extraPath)) {
        $oldP = $ProgressPreference; $ProgressPreference = 'SilentlyContinue'
        try {
            Invoke-WebRequest -Headers $headers -Uri $extraUrl -OutFile $extraPath
        } finally { $ProgressPreference = $oldP }
    }

    & $r e $extraPath "-o$dir" '7za.exe' '7za.dll' -y -bso0 -bsp0 | Out-Null
    if (-not (Test-Path $exe)) {
        throw "7za.exe not found in $extraName after extraction. 7-Zip extras layout may have changed."
    }
    Remove-Item -Path $extraPath -Force -ErrorAction SilentlyContinue
    return $exe
}

function Expand-7zArchive {
    param(
        [Parameter(Mandatory=$true)][string]$Archive,
        [Parameter(Mandatory=$true)][string]$Destination,
        [Parameter(Mandatory=$true)][string]$ProjectRoot
    )
    if (-not (Test-Path $Archive)) { throw "Archive not found: $Archive" }
    if (-not (Test-Path $Destination)) { New-Item -Path $Destination -ItemType Directory -Force | Out-Null }

    if ($Archive -match '\.7z(\.\d+)?$') {
        $exe = Ensure-7zr -ProjectRoot $ProjectRoot
    } else {
        $exe = Ensure-7za -ProjectRoot $ProjectRoot
    }
    & $exe x "-o$Destination" $Archive -y -aoa -bso0 -bsp1 | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw ("{0} failed extracting {1} (exit {2})" -f [IO.Path]::GetFileName($exe), $Archive, $LASTEXITCODE)
    }
}
