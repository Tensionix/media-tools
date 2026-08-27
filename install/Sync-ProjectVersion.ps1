# UTF-8 without BOM
<#
.SYNOPSIS
    Copy the project version from config\version.json into the YAML configs.

.DESCRIPTION
    There is one version of this project and it lives in `config\version.json`
    - that file is what the build stack reads and what names every archive.
    `config\project.yaml` and `config\tool_manifest.yaml` used to carry their
    own value, and a second copy of a number is a copy that goes stale: on
    27 August 2026 they still said "2.1.0-gui" while the release was 2.5.1.

    So the YAML keeps the field - anything reading the manifest still finds a
    version there - but stops being the place where it is decided. The builder
    runs this before showing its menu, so the two can no longer drift apart.

    Nothing else in the YAML is touched: the value is replaced in place, with
    the file's own line endings and encoding, rather than through a YAML
    round-trip that would reflow quoting and comments.
#>
[CmdletBinding()]
param(
    [string]$ProjectRoot = '',
    [switch]$CheckOnly
)

$ErrorActionPreference = 'Stop'

if (-not $ProjectRoot) {
    $ProjectRoot = Split-Path -Parent $PSScriptRoot
}
$root = [System.IO.Path]::GetFullPath($ProjectRoot)

$versionFile = Join-Path $root 'config\version.json'
if (-not (Test-Path -LiteralPath $versionFile -PathType Leaf)) {
    throw "Version file not found: $versionFile"
}

$version = ([string]((Get-Content -LiteralPath $versionFile -Raw | ConvertFrom-Json).version)).Trim()
if (-not $version) { throw "Empty version in $versionFile" }

$targets = @(
    @{ Path = Join-Path $root 'config\project.yaml'; Pattern = '^(?<indent>\s*)version:\s*".*"\s*$' },
    @{ Path = Join-Path $root 'config\tool_manifest.yaml'; Pattern = '^(?<indent>\s*)version:\s*".*"\s*$' }
)

$changed = 0
foreach ($target in $targets) {
    if (-not (Test-Path -LiteralPath $target.Path -PathType Leaf)) { continue }

    $raw = [System.IO.File]::ReadAllText($target.Path)
    $eol = if ($raw -match "`r`n") { "`r`n" } else { "`n" }
    $lines = $raw -split "`r`n|`n"

    $done = $false
    for ($i = 0; $i -lt $lines.Count; $i++) {
        # Only the first version: line, which belongs to the top-level block.
        # Operation definitions further down must not be rewritten.
        if (-not $done -and $lines[$i] -match $target.Pattern) {
            $replacement = '{0}version: "{1}"' -f $Matches['indent'], $version
            if ($lines[$i] -ne $replacement) {
                if (-not $CheckOnly) { $lines[$i] = $replacement }
                Write-Host ("[SYNC] {0}: {1} -> {2}" -f (Split-Path -Leaf $target.Path), $lines[$i].Trim(), $version) -ForegroundColor DarkGray
                $changed++
            }
            $done = $true
        }
    }

    if (-not $done) {
        Write-Warning ("No top-level version field in {0}" -f (Split-Path -Leaf $target.Path))
        continue
    }

    if (-not $CheckOnly) {
        $text = ($lines -join $eol)
        [System.IO.File]::WriteAllText($target.Path, $text, (New-Object Text.UTF8Encoding $false))
    }
}

if ($changed -eq 0) {
    Write-Host "[OK] YAML configs already carry version $version." -ForegroundColor DarkGray
} elseif ($CheckOnly) {
    Write-Host "[CHECK] $changed file(s) would be updated to $version." -ForegroundColor Yellow
} else {
    Write-Host "[OK] Version $version written into $changed YAML file(s)." -ForegroundColor Green
}

exit 0
