# mpv hotkeys

[Русский](MPV_HOTKEYS_RU.md)

The keys work in the **player window**, not in the panel of the program: mpv is a separate
program; the panel only sends it commands and takes positions from it.

The list is taken from the player itself: it is the `input-bindings` answer of the build of
14 August 2026 with the configuration from `config\mpv`, not a page copied from the
internet. What is written here is what the player answers to in this build.

## What you cut with

A dozen keys that do all the work. The rest is optional.

| Key | What it does |
|---|---|
| `Space` | play / pause |
| `,` `.` | step exactly one frame back and forward |
| `←` `→` | seek 5 seconds |
| `Shift+←` `Shift+→` | **exactly** one second back and forward |
| `Shift+↓` `Shift+↑` | **exactly** five seconds |
| `↓` `↑` | one minute back and forward |
| `Home` | to the start of the file |
| `l` | set point **A**; a second press sets point **B**; the piece between them plays in a loop |
| `Ctrl+l` | clear points A and B |
| `b` | play **backwards** |
| `n` | return to forward playback |
| `[` `]` | slower / faster by 10 %; at speed 0.25 every syllable is heard |
| `Backspace` | back to normal speed |
| `s` | screenshot of the frame next to the source file (`FileName-shot-1.png`) |

`l` is the cut itself: set A and B, listen to the loop, and if a point is wrong,
move it with `,` and `.` and press `l` again. Then in the panel `Take A and B`
moves both points into the last row of fields, and `+` clears A and B for the
next piece. In `SPLIT` the point is moved by `Take A`, and only if it lies past
the previous ones.

The difference between `←` and `Shift+←` matters: the plain seek jumps 5 seconds and
shows the nearest frame, while `Shift` is exact, one second precisely, and lands on the
frame. To find a cut point you need the second one.

`b` and `n` are added by this build. In a plain mpv, `b` turns debanding on and off
(`deband`); here it is redefined.

## Everything else

Below are all 197 bindings of this build, by section. Where a command speaks
for itself, there is a description; where it does not, there is the mpv command as it is,
and it can be typed in the player console (`` ` ``).

### Seeking and time

| Key | What it does | mpv command |
|---|---|---|
| `!` | to the neighboring chapter | `add chapter -1` |
| `,` | one frame back | `frame-back-step` |
| `.` | one frame forward | `frame-step` |
| `@` | to the neighboring chapter | `add chapter 1` |
| `Ctrl+←` | to the neighboring subtitle line | `no-osd sub-seek -1` |
| `Ctrl+→` | to the neighboring subtitle line | `no-osd sub-seek 1` |
| `↓` | one minute back | `seek -60` |
| `Forward (media key)` | one minute forward | `seek 60` |
| `g-c` | choose from a list | `script-binding select/select-chapter` |
| `Home` | to the start of the file | `seek 0 absolute` |
| `←` | 5 s back | `seek -5` |
| `Page Down` | to the neighboring chapter | `add chapter -1` |
| `Page Up` | to the neighboring chapter | `add chapter 1` |
| `Rewind (media key)` | one minute back | `seek -60` |
| `→` | 5 s forward | `seek 5` |
| `Shift+Backspace` | return to where you were before the seek | `revert-seek` |
| `Shift+Ctrl+Backspace` | remember the place to return to | `revert-seek mark` |
| `Shift+↓` | exactly 5 s back | `no-osd seek -5 exact` |
| `Shift+←` | exactly 1 s back | `no-osd seek -1 exact` |
| `Shift+Page Down` | 10 min back | `seek -600` |
| `Shift+Page Up` | 10 min forward | `seek 600` |
| `Shift+→` | exactly 1 s forward | `no-osd seek 1 exact` |
| `Shift+↑` | exactly 5 s forward | `no-osd seek 5 exact` |
| `↑` | one minute forward | `seek 60` |
| `Wheel left` | 10 s back | `seek -10` |
| `Wheel right` | 10 s forward | `seek 10` |

### Playback and speed

| Key | What it does | mpv command |
|---|---|---|
| `[` | speed × 1/1.1 | `multiply speed 1/1.1` |
| `]` | speed × 1.1 | `multiply speed 1.1` |
| `b` | play backwards | `set play-direction backward ; set pause no` |
| `Backspace` | normal speed | `set speed 1` |
| `Window close` | quit | `quit` |
| `Ctrl+c` | quit | `quit 4` |
| `Ctrl+l` | clear points A and B | `set ab-loop-a no ; set ab-loop-b no` |
| `Ctrl+w` | quit | `quit` |
| `L` | loop the file | `cycle-values loop-file inf no` |
| `l` | set point A, then B: a loop between them | `ab-loop` |
| `n` | play forward | `set play-direction forward ; set pause no` |
| `p` | play / pause | `cycle pause` |
| `Pause (media key)` | play / pause | `cycle pause` |
| `Pause (media key)` | pause | `set pause yes` |
| `Play (media key)` | play / pause | `cycle pause` |
| `Play (media key)` | play | `set pause no` |
| `Play/Pause (media key)` | play / pause | `cycle pause` |
| `Power (media key)` | quit | `quit` |
| `Q` | quit and remember the place | `quit-watch-later` |
| `q` | quit | `quit` |
| `Space` | play / pause | `cycle pause` |
| `Stop (media key)` | quit | `quit` |
| `{` | speed × 0.5 | `multiply speed 0.5` |
| `}` | speed × 2.0 | `multiply speed 2.0` |

### Sound

| Key | What it does | mpv command |
|---|---|---|
| `*` | volume 2 | `add volume 2` |
| `/` | volume -2 | `add volume -2` |
| `0` | volume 2 | `add volume 2` |
| `9` | volume -2 | `add volume -2` |
| `Ctrl++` | shift the sound by 0.1 s | `add audio-delay 0.1` |
| `Ctrl+-` | shift the sound by -0.1 s | `add audio-delay -0.1` |
| `Ctrl+Numpad plus` | shift the sound by 0.1 s | `add audio-delay 0.1` |
| `Ctrl+Numpad minus` | shift the sound by -0.1 s | `add audio-delay -0.1` |
| `g-a` | choose from a list | `script-binding select/select-aid` |
| `g-d` | — | `script-binding select/select-audio-device` |
| `Numpad slash` | volume -2 | `add volume -2` |
| `Numpad asterisk` | volume 2 | `add volume 2` |
| `m` | sound on/off | `cycle mute` |
| `Mute (media key)` | sound on/off | `cycle mute` |
| `#` | next audio track | `cycle audio` |
| `Volume down (media key)` | volume -2 | `add volume -2` |
| `Volume up (media key)` | volume 2 | `add volume 2` |

### Subtitles

| Key | What it does | mpv command |
|---|---|---|
| `Alt+v` | — | `cycle secondary-sub-visibility` |
| `F` | subtitle size -0.1 | `add sub-scale -0.1` |
| `G` | subtitle size 0.1 | `add sub-scale 0.1` |
| `g-L` | — | `script-binding select/select-secondary-subtitle-line` |
| `g-l` | — | `script-binding select/select-subtitle-line` |
| `g-S` | — | `script-binding select/select-secondary-sid` |
| `g-s` | choose from a list | `script-binding select/select-sid` |
| `J` | — | `cycle sub down` |
| `j` | next subtitles | `cycle sub` |
| `R` | — | `add sub-pos +1` |
| `r` | subtitles up/down | `add sub-pos -1` |
| `Shift+Ctrl+←` | — | `sub-step -1` |
| `Shift+Ctrl+→` | — | `sub-step 1` |
| `t` | — | `add sub-pos +1` |
| `u` | toggle sub-ass-override | `cycle-values sub-ass-override "force" "scale"` |
| `V` | — | `cycle sub-ass-use-video-data` |
| `v` | show/hide subtitles | `cycle sub-visibility` |
| `x` | shift the subtitles by 0.1 s | `add sub-delay 0.1` |
| `Z` | shift the subtitles by 0.1 s | `add sub-delay 0.1` |
| `z` | shift the subtitles by -0.1 s | `add sub-delay -0.1` |

### Picture

| Key | What it does | mpv command |
|---|---|---|
| `1` | contrast -1 | `add contrast -1` |
| `2` | contrast 1 | `add contrast 1` |
| `3` | brightness -1 | `add brightness -1` |
| `4` | brightness 1 | `add brightness 1` |
| `5` | gamma -1 | `add gamma -1` |
| `6` | gamma 1 | `add gamma 1` |
| `7` | saturation -1 | `add saturation -1` |
| `8` | saturation 1 | `add saturation 1` |
| `_` | next video track | `cycle video` |
| `A` | toggle video-aspect-override | `cycle-values video-aspect-override "16:9" "4:3" "2.35:1" "no"` |
| `Alt++` | zoom in / out | `add video-zoom 0.1` |
| `Alt+-` | zoom in / out | `add video-zoom -0.1` |
| `Alt+Backspace` | reset the zoom and the position | `set video-zoom 0; no-osd set panscan 0; no-osd set video-pan-x 0; no-osd set video-pan-y 0; no-osd set video-align-x 0; no-osd set video-align-y 0` |
| `Alt+↓` | move the picture vertically | `add video-pan-y -0.1` |
| `Alt+KP1` | — | `repeatable add video-rotate -1` |
| `Alt+KP3` | — | `repeatable add video-rotate 1` |
| `Alt+KP5` | video-rotate = 0 | `set video-rotate 0` |
| `Alt+Numpad plus` | zoom in / out | `add video-zoom 0.1` |
| `Alt+Numpad minus` | zoom in / out | `add video-zoom -0.1` |
| `Alt+←` | move the picture horizontally | `add video-pan-x 0.1` |
| `Alt+→` | move the picture horizontally | `add video-pan-x -0.1` |
| `Alt+↑` | move the picture vertically | `add video-pan-y 0.1` |
| `Ctrl+h` | toggle hwdec | `cycle-values hwdec no auto` |
| `Ctrl+KP1` | — | `add video-pan-x -0.01; add video-pan-y 0.01` |
| `Ctrl+KP2` | move the picture vertically | `add video-pan-y 0.01` |
| `Ctrl+KP3` | — | `add video-pan-x 0.01; add video-pan-y 0.01` |
| `Ctrl+KP4` | move the picture horizontally | `add video-pan-x -0.01` |
| `Ctrl+KP5` | — | `set video-pan-x 0.00; set video-pan-y 0.00` |
| `Ctrl+KP6` | move the picture horizontally | `add video-pan-x 0.01` |
| `Ctrl+KP7` | — | `add video-pan-x -0.01; add video-pan-y -0.01` |
| `Ctrl+KP8` | move the picture vertically | `add video-pan-y -0.01` |
| `Ctrl+KP9` | — | `add video-pan-x 0.01; add video-pan-y -0.01` |
| `Ctrl+KP_BEGIN` | — | `set video-align-x 0.00; set video-align-y 0.00` |
| `Ctrl+KP_DOWN` | video-align-y: 0.01 | `add video-align-y 0.01` |
| `Ctrl+KP_END` | — | `add video-align-x -0.01; add video-align-y 0.01` |
| `Ctrl+KP_HOME` | — | `add video-align-x -0.01; add video-align-y -0.01` |
| `Ctrl+KP_LEFT` | video-align-x: -0.01 | `add video-align-x -0.01` |
| `Ctrl+KP_PGDWN` | — | `add video-align-x 0.01; add video-align-y 0.01` |
| `Ctrl+KP_PGUP` | — | `add video-align-x 0.01; add video-align-y -0.01` |
| `Ctrl+KP_RIGHT` | video-align-x: 0.01 | `add video-align-x 0.01` |
| `Ctrl+KP_UP` | video-align-y: -0.01 | `add video-align-y -0.01` |
| `d` | deinterlacing | `cycle deinterlace` |
| `e` | — | `add panscan +0.1` |
| `g-v` | choose from a list | `script-binding select/select-vid` |
| `KP1` | zoom in / out | `add video-zoom -0.01` |
| `KP2` | video-scale-y: -0.01 | `add video-scale-y -0.01` |
| `KP4` | video-scale-x: -0.01 | `add video-scale-x -0.01` |
| `KP5` | — | `set video-scale-x 1.00; set video-scale-y 1; set video-zoom 0` |
| `KP6` | video-scale-x: 0.01 | `add video-scale-x 0.01` |
| `KP8` | video-scale-y: 0.01 | `add video-scale-y 0.01` |
| `KP9` | zoom in / out | `add video-zoom 0.01` |
| `S` | screenshot of the clean frame, without subtitles | `screenshot video` |
| `W` | — | `add panscan +0.1` |
| `w` | crop the margins at the edges | `add panscan -0.1` |
| `ZOOMIN` | zoom in / out | `add video-zoom 0.1` |
| `ZOOMOUT` | zoom in / out | `add video-zoom -0.1` |

### Window, screen and screenshots

| Key | What it does | mpv command |
|---|---|---|
| `Alt+0` | window-scale = 0.5 | `set window-scale 0.5` |
| `Alt+1` | window-scale = 1 | `set window-scale 1` |
| `Alt+2` | window-scale = 2 | `set window-scale 2` |
| `Alt+s` | — | `screenshot each-frame` |
| `Ctrl+r` | — | `set file-local-options/start ${=time-pos}; playlist-play-index current yes; show-text "Reloading current file..."` |
| `Ctrl+s` | screenshot of the window as it is | `screenshot window` |
| `Ctrl+v` | — | `update-clipboard text; loadfile ${clipboard/text} append-play; show-text '+ ${clipboard/text}'` |
| `Esc` | fullscreen = no | `set fullscreen no` |
| `f` | fullscreen | `cycle fullscreen` |
| `F8` | — | `show-text ${playlist}` |
| `F9` | — | `show-text ${track-list}` |
| `Double click` | fullscreen | `cycle fullscreen` |
| `O` | — | `no-osd cycle-values osd-level 3 1` |
| `o` | show the time bar | `show-progress` |
| `P` | show the time bar | `show-progress` |
| `s` | screenshot of the frame with subtitles | `screenshot` |
| `Shift+End` | — | `no-osd set playlist-pos-1 ${playlist-count}` |
| `Shift+Home` | — | `no-osd set playlist-pos 0` |
| `T` | on top of other windows | `cycle ontop` |

### Files and the list

| Key | What it does | mpv command |
|---|---|---|
| `<` | previous file in the list | `playlist-prev` |
| `>` | next file in the list | `playlist-next` |
| `Enter` | next file in the list | `playlist-next` |
| `g-p` | choose from a list | `script-binding select/select-playlist` |
| `Mouse back button` | previous file in the list | `playlist-prev` |
| `Mouse forward button` | next file in the list | `playlist-next` |
| `Next (media key)` | next file in the list | `playlist-next` |
| `Previous (media key)` | previous file in the list | `playlist-prev` |

### Menu, information, other

| Key | What it does | mpv command |
|---|---|---|
| `?` | — | `script-binding stats/display-page-4-toggle` |
| ``` | — | `script-binding commands/open` |
| `Ctrl+Left button` | drag the picture with the mouse | `script-binding positioning/drag-to-pan` |
| `Ctrl+p` | menu | `script-binding select/menu` |
| `Ctrl+Wheel down` | — | `script-binding positioning/cursor-centric-zoom -0.1` |
| `Ctrl+Wheel up` | — | `script-binding positioning/cursor-centric-zoom 0.1` |
| `Delete` | on-screen controller | `script-binding osc/visibility` |
| `E` | — | `cycle edition` |
| `g-b` | choose from a list | `script-binding select/select-binding` |
| `g-e` | choose from a list | `script-binding select/select-edition` |
| `g-h` | — | `script-binding select/select-watch-history` |
| `g-m` | menu | `script-binding select/menu` |
| `g-r` | — | `script-binding select/show-properties` |
| `g-t` | choose from a list | `script-binding select/select-track` |
| `g-w` | — | `script-binding select/select-watch-later` |
| `I` | information about the file and playback | `script-binding stats/display-stats-toggle` |
| `i` | information about the file and playback | `script-binding stats/display-stats` |
| `Left button` | on-screen controller | `script-binding osc/__keybinding11` |
| `Middle button` | on-screen controller | `script-binding osc/__keybinding6` |
| `Right button` | on-screen controller | `script-binding osc/__keybinding7` |
| `MENU` | — | `script-binding select/context-menu` |
| `MOUSE_LEAVE` | on-screen controller | `script-binding osc/__keybinding4` |
| `MOUSE_MOVE` | on-screen controller | `script-binding osc/__keybinding3` |
| `Shift+F10` | — | `script-binding select/context-menu` |
| `Shift+Left button` | on-screen controller | `script-binding osc/__keybinding8` |
| `Wheel down` | on-screen controller | `script-binding osc/__keybinding10` |
| `Wheel up` | on-screen controller | `script-binding osc/__keybinding9` |

## If a key does not work

- The player window must be active: a click on it returns the focus.
- While the A/B loop is set, playback does not go past point B; clear it with `Ctrl+l`.
- The full reference of mpv itself lies next to the player:
  `Tools\mpv\bin\doc\manual.pdf`; the installer puts it there.
