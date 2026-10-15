# The built program walked through without a mouse: its own buttons are pressed by UI Automation.
#
#   Source\Tools\release-walk.ps1 -Stand C:\Temp\media_stand
#
# A release build has no steps of a check inside, so the stand is a copy of the program: App\, the
# console command, the engine, the Python of the project, FFmpeg and FFprobe of Tools\ffmpeg\bin, the
# player of Tools\mpv and config\ without the files of the owner (the history of paths, the forms and the look of the window,
# the sealed cookies). Its input, output, logs and report are its own - nothing of the owner's is read
# or written. The window is started with AUDION_WALK=1: it and its questions stand off every screen
# and take no focus. It is found by the id of its process, never by its name or title; the pointer is
# not moved.
#
# What is pressed: a section and a mode, a choice of the form, COMMAND (the commands said, nothing
# written), RUN of the form, SOURCE INFO of the work zone, the pin of the Source, TO SOURCE with its
# question, CLEAR with its menu and its question (the files of the stand go to the Recycle Bin), RUN on
# an empty Source (refused before it began), the player of CUT opened and closed (it stays minimised
# and takes no focus), a preset of STORAGE, STOP while a long encode goes (no half-written file is
# left), and the window closed while one goes. Exit code 0 - every check held; 1 - one did not, and the
# line says which.
#
# Needs a PowerShell with the WindowsDesktop assemblies (an installed PowerShell 7).
# -Keep leaves the stand in place for a look; otherwise it is removed at the end.
param(
    [Parameter(Mandatory)][string]$Stand,
    # The built window to walk: App\ of the program, or another build of it.
    [string]$App = '',
    [switch]$Keep
)
$ErrorActionPreference = 'Stop'
$source = Split-Path -Parent $PSScriptRoot
$project = Split-Path -Parent $source
$window = 'AudionMediaTools.exe'
if (-not $App) { $App = Join-Path $project 'App' }

if (Test-Path -LiteralPath $Stand) { "the stand must not exist yet: $Stand"; exit 2 }
if (-not (Test-Path -LiteralPath (Join-Path $App $window))) { "no built window in $App`: install\Build-App.cmd"; exit 2 }
[void](New-Item -ItemType Directory -Force -Path $Stand)
$Stand = (Resolve-Path -LiteralPath $Stand).Path
$copies = @(
    @($App, 'App', @(), @()),
    @((Join-Path $project 'system_core'), 'system_core', @('__pycache__', 'powershell'), @()),
    @((Join-Path $project 'runtime'), 'runtime', @('__pycache__'), @()),
    @((Join-Path $project 'config'), 'config', @(), @('window_settings.json*', 'path_history.json*', 'cookies.dpapi*')),
    @((Join-Path $project 'Tools\ffmpeg\bin'), 'Tools\ffmpeg\bin', @(), @('ffplay.exe')),
    @((Join-Path $project 'Tools\mpv'), 'Tools\mpv', @(), @())
)
foreach ($copy in $copies) {
    $skip = @()
    if ($copy[2].Count -gt 0) { $skip += @('/XD') + $copy[2] }
    if ($copy[3].Count -gt 0) { $skip += @('/XF') + $copy[3] }
    $null = robocopy $copy[0] (Join-Path $Stand $copy[1]) /E @skip /NFL /NDL /NJH /NJS /NP
    if ($LASTEXITCODE -ge 8) { "the copy of $($copy[1]) failed"; exit 2 }
}
Copy-Item -LiteralPath (Join-Path $project 'media_cli.cmd') -Destination $Stand
$in = Join-Path $Stand 'input'; $out = Join-Path $Stand 'output'
foreach ($name in 'input', 'output', 'logs', 'report') { [void](New-Item -ItemType Directory -Force -Path (Join-Path $Stand $name)) }
$exe = Join-Path $Stand "App\$window"
$ffmpeg = Join-Path $Stand 'Tools\ffmpeg\bin\ffmpeg.exe'

# Clips of the stand, made by its own FFmpeg: a test picture with a tone under it.
function MakeClip([string]$name, [int]$seconds, [string]$size) {
    & $ffmpeg -hide_banner -loglevel error -f lavfi -i "testsrc2=size=$size`:rate=25:duration=$seconds" -f lavfi -i "sine=frequency=440:duration=$seconds" `
        -c:v libx264 -preset ultrafast -pix_fmt yuv420p -c:a aac -shortest (Join-Path $in $name)
    if ($LASTEXITCODE -ne 0) { throw "the clip $name of the stand was not made" }
}
function FilesIn([string]$folder) { @(Get-ChildItem -LiteralPath $folder -Recurse -File -Force -ErrorAction SilentlyContinue) }

Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
$auto = [System.Windows.Automation.AutomationElement]
$failed = 0
function Say([bool]$ok, [string]$what) {
    '{0} {1}' -f $(if ($ok) { '[OK]  ' } else { '[FAIL]' }), $what
    if (-not $ok) { $script:failed++ }
}
function Find($root, [string]$id, [int]$seconds = 20) {
    $condition = [System.Windows.Automation.PropertyCondition]::new($auto::AutomationIdProperty, $id)
    $until = (Get-Date).AddSeconds($seconds)
    do {
        # The tree may be rebuilt under the search - a section was just pressed - and the search
        # then breaks instead of finding nothing: asked again like any other "not yet".
        $found = $null
        try { $found = $root.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $condition) } catch { }
        if ($found) { return $found }
        Start-Sleep -Milliseconds 300
    } while ((Get-Date) -lt $until)
    return $null
}
function Press($element) {
    if ($null -eq $element) { throw 'nothing to press' }
    $pattern = $null
    if ($element.TryGetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern, [ref]$pattern)) { $pattern.Invoke(); return }
    if ($element.TryGetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern, [ref]$pattern)) { $pattern.Toggle(); return }
    throw 'the element can be neither invoked nor toggled'
}
function IsOn($element) {
    $pattern = $null
    if (-not $element.TryGetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern, [ref]$pattern)) { return $false }
    return $pattern.Current.ToggleState -eq [System.Windows.Automation.ToggleState]::On
}
function TextOf($root, [string]$id) {
    $found = Find $root $id 5
    if (-not $found) { return '' }
    $value = $null
    if ($found.TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern, [ref]$value)) { return $value.Current.Value }
    return $found.Current.Name
}
function Shown($root, [string]$id) {
    # One look, no waiting: a control that is hidden is not in the tree at all.
    try { return $null -ne $root.FindFirst([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.PropertyCondition]::new($auto::AutomationIdProperty, $id)) }
    catch { return $false }
}
function Outcome($root) {
    # How a run ended is read from the status line, in either language, and a run that goes - from STOP,
    # which is in sight only then.
    $line = TextOf $root 'StatusText'
    if ($line -match '^(Готово|Done): ') { return 'done' }
    if ($line -match '^(Остановлено|Stopped): ') { return 'stopped' }
    if ($line -match ': (отказ до начала|refused before it began)') { return 'refused' }
    if ($line -match ': (ошибка|failed) - ') { return 'failed' }
    if (Shown $root 'StopButton') { return 'running' }
    return ''
}
function WaitOutcome($root, [string]$wanted, [int]$seconds, [string]$before = '') {
    # $before: the status line before the press - an outcome of the run before is not this run's.
    $until = (Get-Date).AddSeconds($seconds)
    do {
        $now = Outcome $root
        if ($now -eq $wanted -and ($wanted -eq 'running' -or (TextOf $root 'StatusText') -ne $before)) { return $now }
        Start-Sleep -Milliseconds 300
    } while ((Get-Date) -lt $until)
    return "$(Outcome $root) <$(TextOf $root 'StatusText')>"
}
function FindInProcess([int]$id, [string]$name, [int]$seconds = 15) {
    # A question and a menu are windows of their own: looked for among the windows of the process, not inside the main one.
    $mine = [System.Windows.Automation.PropertyCondition]::new($auto::ProcessIdProperty, $id)
    $named = [System.Windows.Automation.PropertyCondition]::new($auto::AutomationIdProperty, $name)
    $until = (Get-Date).AddSeconds($seconds)
    do {
        try {
            foreach ($top in $auto::RootElement.FindAll([System.Windows.Automation.TreeScope]::Children, $mine)) {
                $found = $top.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $named)
                if ($found) { return $found }
            }
        }
        catch { }
        Start-Sleep -Milliseconds 300
    } while ((Get-Date) -lt $until)
    return $null
}
function AnswerYes([int]$id, [int]$seconds = 30) {
    # "Yes" of a question that cannot be taken back comes alive a moment after it opens.
    $yes = FindInProcess $id 'AskYes' $seconds
    if (-not $yes) { return $false }
    $until = (Get-Date).AddSeconds(5)
    while (-not $yes.Current.IsEnabled -and (Get-Date) -lt $until) { Start-Sleep -Milliseconds 100 }
    Press $yes
    Start-Sleep -Milliseconds 500
    return $true
}
function WaitFile([string]$path, [string]$pattern, [bool]$present, [int]$seconds = 15) {
    $until = (Get-Date).AddSeconds($seconds)
    do {
        $text = if (Test-Path -LiteralPath $path) { Get-Content -LiteralPath $path -Raw -ErrorAction SilentlyContinue } else { '' }
        if (($text -match $pattern) -eq $present) { return $true }
        Start-Sleep -Milliseconds 300
    } while ((Get-Date) -lt $until)
    return $false
}
function LastJournal([string]$like) {
    # The journal of the last run of an operation, as the engine wrote it into the logs of the stand.
    $file = Get-ChildItem -LiteralPath (Join-Path $Stand 'logs') -Recurse -File -ErrorAction SilentlyContinue | Where-Object { $_.Name -like $like } |
        Sort-Object LastWriteTime | Select-Object -Last 1
    if ($file) { return Get-Content -LiteralPath $file.FullName -Raw } else { return '' }
}
function StartWindow {
    $env:AUDION_WALK = '1'
    try { $process = Start-Process -FilePath $exe -PassThru }
    finally { Remove-Item Env:\AUDION_WALK -ErrorAction SilentlyContinue }
    # A window with no button on the taskbar is no "main window" to .NET: it is looked for among the
    # windows of the desktop by the id of its process.
    $mine = [System.Windows.Automation.PropertyCondition]::new($auto::ProcessIdProperty, $process.Id)
    $until = (Get-Date).AddSeconds(40)
    do {
        $found = $null
        try { $found = $auto::RootElement.FindFirst([System.Windows.Automation.TreeScope]::Children, $mine) } catch { }
        if ($found) { $script:root = $found; return $process }
        Start-Sleep -Milliseconds 300
    } while (-not $process.HasExited -and (Get-Date) -lt $until)
    throw $(if ($process.HasExited) { "the window ended at its start, exit code $($process.ExitCode)" } else { 'the window did not open' })
}
function CloseWindow($root) {
    $close = $null
    [void]$root.TryGetCurrentPattern([System.Windows.Automation.WindowPattern]::Pattern, [ref]$close)
    $close.Close()
}

try {
    foreach ($n in 1..3) { MakeClip "clip_$n.mp4" 2 '640x360' }
    $process = StartWindow
    $bounds = $root.Current.BoundingRectangle
    Say ($bounds.Right -le 0 -or $bounds.Bottom -le 0) ("the window of the walk stands off the screen: {0},{1}" -f $bounds.Left, $bounds.Top)

    $tab = Find $root 'section_package' 40
    Say ($null -ne $tab) 'the layout is read: the section PACKAGE is in the window'

    # A mode of the section and a choice of its form.
    Press $tab
    $mode = Find $root 'page_package_video_audio' 15
    if ($mode) { Press $mode; Start-Sleep -Milliseconds 600 }
    $mkv = Find $root 'field_remux_target_format_mkv' 15
    if ($mkv) { Press $mkv; Start-Sleep -Milliseconds 600 }
    # The choice goes to the form server and comes back: the switch is looked for again.
    $mkv = Find $root 'field_remux_target_format_mkv' 5
    Say ($null -ne $mkv -and (IsOn $mkv)) 'PACKAGE -> VIDEO AND AUDIO: MKV pressed and on'

    # COMMAND: the commands of the run are said in the journal, nothing is written.
    $before = TextOf $root 'StatusText'
    Press (Find $root 'preview_remux_run' 10)
    $state = WaitOutcome $root 'done' 60 $before
    $said = LastJournal '*remux_run.log'
    Say ($state -eq 'done' -and (FilesIn $out).Count -eq 0 -and $said -match '\[DRY RUN\]') "COMMAND: $state, the journal says the commands, files in output: $((FilesIn $out).Count)"

    # RUN of the form: every clip into MKV, each file whole under its own name.
    $before = TextOf $root 'StatusText'
    Press (Find $root 'run_remux_run' 10)
    $state = WaitOutcome $root 'done' 90 $before
    $made = FilesIn $out
    $mkvs = @($made | Where-Object { $_.Extension -eq '.mkv' -and $_.Name -notlike '*.writing-*' })
    Say ($state -eq 'done' -and $mkvs.Count -eq 3 -and $made.Count -eq 3) "RUN of the form: $state, MKV in output: $($mkvs.Count) of 3 ($($made.Count) files)"
    $log = @(Get-ChildItem -LiteralPath (Join-Path $Stand 'logs') -Recurse -File -ErrorAction SilentlyContinue | Where-Object { $_.Name -like '*remux_run*' })
    Say ($log.Count -ge 2) "the runs went through the console command: their journals lie in the logs of the stand ($($log.Count))"

    # SOURCE INFO of the work zone: its menu, the ffprobe table of the Source in the journal.
    # The button comes alive a moment after the run before ends; a press that found it asleep opens nothing and is made again.
    $details = Find $root 'route_details' 10
    $info = $null
    foreach ($attempt in 1..2) {
        $until = (Get-Date).AddSeconds(5)
        while (-not $details.Current.IsEnabled -and (Get-Date) -lt $until) { Start-Sleep -Milliseconds 100 }
        Press $details
        $info = Find $root 'run_probe_source' 3
        if (-not $info) { $info = FindInProcess $process.Id 'run_probe_source' 5 }
        if ($info) { break }
    }
    Say ($null -ne $info) 'the button SOURCE INFO opens its menu: "probe_source" is in it'
    if ($info) {
        $before = TextOf $root 'StatusText'
        Press $info
        $state = WaitOutcome $root 'done' 60 $before
        $said = LastJournal '*probe_source.log'
        Say ($state -eq 'done' -and $said -match '3 file\(s\), uniform \| V: H264 640x360 25p') "SOURCE INFO: $state, the folder said as uniform H264 640x360 25p"
    }

    # The pin of the Source: kept in the history of the stand, and taken off again.
    $history = Join-Path $Stand 'config\path_history.json'
    Press (Find $root 'route_pin_source' 15)
    Say (WaitFile $history '"pinned":\s*true' $true) 'the pin of the Source: config\path_history.json holds a pinned path'
    Press (Find $root 'route_pin_source' 15)
    Say (WaitFile $history '"pinned":\s*true' $false) 'pressed again: no path is pinned'

    # TO SOURCE: the Source is cleared, the result moves into it, the Target is left empty.
    $results = (FilesIn $out).Count
    Press (Find $root 'route_to_source' 15)
    Say (AnswerYes $process.Id) 'TO SOURCE asks first'
    $until = (Get-Date).AddSeconds(20)
    while ((FilesIn $out).Count -gt 0 -and (Get-Date) -lt $until) { Start-Sleep -Milliseconds 300 }
    Start-Sleep -Milliseconds 500
    Say ((FilesIn $out).Count -eq 0 -and (FilesIn $in).Count -eq $results) "TO SOURCE: output is empty, input holds the $results results ($((FilesIn $in).Count))"

    # CLEAR: its menu, the question, the contents gone and the folders left - to the Recycle Bin.
    Set-Content -LiteralPath (Join-Path $out 'release-walk-probe.txt') -Value 'a probe of release-walk.ps1' -Encoding utf8
    Press (Find $root 'route_clear' 15)
    $both = Find $root 'clear_both' 5
    if (-not $both) { $both = FindInProcess $process.Id 'clear_both' 10 }
    Say ($null -ne $both) 'the button CLEAR opens its menu: "both" is in it'
    if ($both) {
        Press $both
        Say (AnswerYes $process.Id) 'CLEAR asks first'
        # A folder outside the program is asked about once more; the stand's are its own.
        [void](AnswerYes $process.Id 2)
        $until = (Get-Date).AddSeconds(20)
        do { Start-Sleep -Milliseconds 300; $left = (FilesIn $in).Count + (FilesIn $out).Count } while ($left -gt 0 -and (Get-Date) -lt $until)
        Say ($left -eq 0 -and (Test-Path -LiteralPath $in) -and (Test-Path -LiteralPath $out)) "CLEAR: the contents of input and output are gone, the folders stay ($left left)"
    }

    # RUN on an empty Source: refused before it began, the reason in the terminal, nothing written.
    Start-Sleep -Milliseconds 600
    $before = TextOf $root 'StatusText'
    Press (Find $root 'run_remux_run' 10)
    $state = WaitOutcome $root 'refused' 30 $before
    $said = LastJournal '*remux_run.log'
    Say ($state -eq 'refused' -and (FilesIn $out).Count -eq 0 -and $said -match '\[REFUSED\]' -and $said -notmatch 'Traceback') "RUN on an empty Source: $state, one line [REFUSED], no trace"

    # The player of CUT: OPEN starts mpv of the stand with the file of the take, CLOSE ends it.
    MakeClip 'long.mp4' 60 '1920x1080'
    $mpv = Join-Path $Stand 'Tools\mpv\bin\mpv.exe'
    function Players { @(Get-CimInstance Win32_Process -Filter "Name = 'mpv.exe'" | Where-Object { $_.ExecutablePath -eq $mpv }) }
    Press (Find $root 'section_cut' 10)
    $page = Find $root 'page_cut_keep' 10
    if ($page) { Press $page; Start-Sleep -Milliseconds 600 }
    Press (Find $root 'player_open' 10)
    $until = (Get-Date).AddSeconds(20)
    while ((Players).Count -eq 0 -and (Get-Date) -lt $until) { Start-Sleep -Milliseconds 300 }
    $taken = @(Players | Where-Object { $_.CommandLine -like '*long.mp4*' })
    Say ((Players).Count -eq 1 -and $taken.Count -eq 1) 'CUT -> KEEP: OPEN starts the player of the stand with the file of the take, long.mp4'
    Start-Sleep -Seconds 1
    Press (Find $root 'player_close' 10)
    $until = (Get-Date).AddSeconds(15)
    while ((Players).Count -gt 0 -and (Get-Date) -lt $until) { Start-Sleep -Milliseconds 300 }
    Say ((Players).Count -eq 0) 'CLOSE ends the player'

    # A preset of STORAGE: its button on, and the form takes its codec.
    Press (Find $root 'section_encode' 10)
    $page = Find $root 'page_encode_storage_run' 10
    if ($page) { Press $page; Start-Sleep -Milliseconds 600 }
    Press (Find $root 'preset_storage_profile_hevc10_crf14' 10)
    Start-Sleep -Milliseconds 800
    $preset = Find $root 'preset_storage_profile_hevc10_crf14' 5
    $hevc = Find $root 'field_target_codecs_hevc_x265' 5
    Say ($null -ne $preset -and (IsOn $preset) -and $null -ne $hevc -and (IsOn $hevc)) 'ENCODE -> STORAGE: the preset HEVC 10-bit CRF 14 is on, and so is its codec'

    # STOP while a long encode goes: HEVC 10-bit, slow, of a minute of 1080p.
    $run = Find $root 'run_storage_run' 10
    Say ($null -ne $run -and $run.Current.IsEnabled) 'ENCODE -> STORAGE: RUN is there and can be pressed'
    Press $run
    $state = WaitOutcome $root 'running' 15
    Say ($state -eq 'running') "a minute of 1080p into HEVC 10-bit: the operation goes ($state)"
    $until = (Get-Date).AddSeconds(30)
    while (-not (FilesIn $out | Where-Object { $_.Length -gt 0 }) -and (Get-Date) -lt $until) { Start-Sleep -Milliseconds 300 }
    $writing = @(FilesIn $out | Where-Object { $_.Name -like '*.writing-*' })
    Say ($writing.Count -eq 1) "FFmpeg writes under a name of its own while it goes: $(($writing | ForEach-Object Name) -join ', ')"
    $stop = Find $root 'StopButton' 5
    Say ($null -ne $stop -and $stop.Current.IsEnabled) 'STOP is in sight and can be pressed while the operation goes'
    $clock = [System.Diagnostics.Stopwatch]::StartNew()
    Press $stop
    $state = WaitOutcome $root 'stopped' 70
    $took = [Math]::Round($clock.Elapsed.TotalSeconds, 1)
    Say ($state -eq 'stopped' -and $took -lt 30) "STOP pressed: $state in $took s"
    Start-Sleep -Milliseconds 800
    $left = FilesIn $out
    Say ($left.Count -eq 0) "no half-written file is left in output: $(($left | ForEach-Object Name) -join ', ')"
    $said = LastJournal '*storage_run.log'
    Say ($said -match '\[STOPPED\]' -and $said -notmatch 'Traceback') 'the journal says [STOPPED] in one line, no trace'
    Start-Sleep -Milliseconds 600
    Say ($run.Current.IsEnabled) 'after the stop RUN can be pressed again'

    # The window closed while the encode goes: it asks, stops the operation and then closes.
    Press $run
    $null = WaitOutcome $root 'running' 15
    Start-Sleep -Seconds 3
    CloseWindow $root
    $asked = AnswerYes $process.Id 15
    Say $asked 'closing during an operation asks first'
    Say ($process.WaitForExit(90000)) 'answered: the operation stopped and the window closed'
    Start-Sleep -Seconds 1
    $left = FilesIn $out
    Say ($left.Count -eq 0) "closed in the middle: no half-written file in output ($(($left | ForEach-Object Name) -join ', '))"

    Start-Sleep -Seconds 2
    $alive = @(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($Stand, [StringComparison]::OrdinalIgnoreCase) })
    Say ($alive.Count -eq 0) ("no process of the stand is left: {0}" -f $alive.Count)
    $crash = @(Get-ChildItem -LiteralPath (Join-Path $Stand 'logs') -Recurse -File -ErrorAction SilentlyContinue | Where-Object { $_.Name -like 'gui-crash-*' -or ($_.Name -eq 'gui-event-errors.log' -and $_.Length -gt 0) })
    Say ($crash.Count -eq 0) ("the window wrote no report of its own errors: {0}" -f (($crash | ForEach-Object Name) -join ', '))
}
catch {
    Say $false ("the walk broke: " + $_.Exception.Message)
}
finally {
    Get-Process | Where-Object { $_.Path -and $_.Path.StartsWith($Stand, [StringComparison]::OrdinalIgnoreCase) } | ForEach-Object { try { $_.Kill($true) } catch { } }
    if ($Keep) { "the stand is kept: $Stand" }
    else {
        Start-Sleep -Milliseconds 800
        # The stand is a plain copy - no link of it leads into the program - so it goes whole.
        [System.IO.Directory]::Delete($Stand, $true)
        'the stand is removed'
    }
}
"failed checks: $failed"
exit $(if ($failed) { 1 } else { 0 })
