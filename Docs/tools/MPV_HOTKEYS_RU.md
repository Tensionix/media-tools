# Горячие клавиши mpv

Клавиши работают в **окне плеера**, а не в панели программы: mpv — отдельная
программа, панель ему только отдаёт команды и забирает у него позиции.

Список снят с самого плеера — это ответ `input-bindings` сборки от 14 августа
2026 года с конфигурацией из `config\mpv`, а не переписанная страница из
интернета. То, что здесь написано, — то, на что плеер отвечает в этой сборке.

## Чем режут

Дюжина клавиш, которыми делается вся работа. Остальное — по желанию.

| Клавиша | Что делает |
|---|---|
| `Пробел` | играть / пауза |
| `,` `.` | шаг ровно в один кадр назад и вперёд |
| `←` `→` | перемотка на 5 секунд |
| `Shift+←` `Shift+→` | **точно** на секунду назад и вперёд |
| `Shift+↓` `Shift+↑` | **точно** на пять секунд |
| `↓` `↑` | на минуту назад и вперёд |
| `Home` | в начало файла |
| `l` | поставить точку **A**; второе нажатие — точку **B**; кусок между ними играет по кругу |
| `Ctrl+l` | снять точки A и B |
| `b` | играть **назад** |
| `n` | вернуться к воспроизведению вперёд |
| `[` `]` | медленнее / быстрее на 10 % — на скорости 0,25 слышно каждый слог |
| `Backspace` | вернуть обычную скорость |
| `s` | снимок кадра рядом с исходным файлом (`ИмяФайла-shot-1.png`) |

`l` — это и есть рез: поставили A и B, послушали петлю, и если точка неверна —
подвинули её `,` и `.`, нажали `l` снова. Дальше в панели `Взять A и B`
переносит обе точки в поля.

Разница между `←` и `Shift+←` важна: обычная перемотка прыгает на 5 секунд и
показывает ближайший кадр, а `Shift` — точная, ровно на секунду, и попадает в
кадр. Для поиска точки реза нужна вторая.

`b` и `n` добавлены этой сборкой. В обычном mpv на `b` висит подавление полос
(`deband`) — здесь оно переопределено.

## Всё остальное

Ниже — все 197 привязок этой сборки, по разделам. Где команда говорит
сама за себя, стоит перевод; где нет — команда mpv как есть, её можно ввести
в консоли плеера (`` ` ``).

### Перемотка и время

| Клавиша | Что делает | Команда mpv |
|---|---|---|
| `!` | к соседней главе | `add chapter -1` |
| `,` | на кадр назад | `frame-back-step` |
| `.` | на кадр вперёд | `frame-step` |
| `@` | к соседней главе | `add chapter 1` |
| `Ctrl+←` | к соседней реплике субтитров | `no-osd sub-seek -1` |
| `Ctrl+→` | к соседней реплике субтитров | `no-osd sub-seek 1` |
| `↓` | на минуту назад | `seek -60` |
| `Вперёд (мультимедийная)` | на минуту вперёд | `seek 60` |
| `g-c` | выбрать из списка | `script-binding select/select-chapter` |
| `Home` | в начало файла | `seek 0 absolute` |
| `←` | на 5 с назад | `seek -5` |
| `Page Down` | к соседней главе | `add chapter -1` |
| `Page Up` | к соседней главе | `add chapter 1` |
| `Назад (мультимедийная)` | на минуту назад | `seek -60` |
| `→` | на 5 с вперёд | `seek 5` |
| `Shift+Backspace` | вернуться туда, где были до перемотки | `revert-seek` |
| `Shift+Ctrl+Backspace` | запомнить место, куда возвращаться | `revert-seek mark` |
| `Shift+↓` | точно на 5 с назад | `no-osd seek -5 exact` |
| `Shift+←` | точно на 1 с назад | `no-osd seek -1 exact` |
| `Shift+Page Down` | на 10 мин назад | `seek -600` |
| `Shift+Page Up` | на 10 мин вперёд | `seek 600` |
| `Shift+→` | точно на 1 с вперёд | `no-osd seek 1 exact` |
| `Shift+↑` | точно на 5 с вперёд | `no-osd seek 5 exact` |
| `↑` | на минуту вперёд | `seek 60` |
| `Колесо влево` | на 10 с назад | `seek -10` |
| `Колесо вправо` | на 10 с вперёд | `seek 10` |

### Воспроизведение и скорость

| Клавиша | Что делает | Команда mpv |
|---|---|---|
| `[` | скорость × 1/1.1 | `multiply speed 1/1.1` |
| `]` | скорость × 1.1 | `multiply speed 1.1` |
| `b` | играть назад | `set play-direction backward ; set pause no` |
| `Backspace` | обычная скорость | `set speed 1` |
| `Закрытие окна` | выйти | `quit` |
| `Ctrl+c` | выйти | `quit 4` |
| `Ctrl+l` | снять точки A и B | `set ab-loop-a no ; set ab-loop-b no` |
| `Ctrl+w` | выйти | `quit` |
| `L` | повторять файл по кругу | `cycle-values loop-file inf no` |
| `l` | поставить точку A, затем B — петля между ними | `ab-loop` |
| `n` | играть вперёд | `set play-direction forward ; set pause no` |
| `p` | играть / пауза | `cycle pause` |
| `Pause (мультимедийная)` | играть / пауза | `cycle pause` |
| `Pause (мультимедийная)` | пауза | `set pause yes` |
| `Play (мультимедийная)` | играть / пауза | `cycle pause` |
| `Play (мультимедийная)` | играть | `set pause no` |
| `Play/Pause (мультимедийная)` | играть / пауза | `cycle pause` |
| `Power (мультимедийная)` | выйти | `quit` |
| `Q` | выйти, запомнив место | `quit-watch-later` |
| `q` | выйти | `quit` |
| `Пробел` | играть / пауза | `cycle pause` |
| `Stop (мультимедийная)` | выйти | `quit` |
| `{` | скорость × 0.5 | `multiply speed 0.5` |
| `}` | скорость × 2.0 | `multiply speed 2.0` |

### Звук

| Клавиша | Что делает | Команда mpv |
|---|---|---|
| `*` | громкость 2 | `add volume 2` |
| `/` | громкость -2 | `add volume -2` |
| `0` | громкость 2 | `add volume 2` |
| `9` | громкость -2 | `add volume -2` |
| `Ctrl++` | сдвиг звука на 0.1 с | `add audio-delay 0.1` |
| `Ctrl+-` | сдвиг звука на -0.1 с | `add audio-delay -0.1` |
| `Ctrl+Плюс на цифровом блоке` | сдвиг звука на 0.1 с | `add audio-delay 0.1` |
| `Ctrl+Минус на цифровом блоке` | сдвиг звука на -0.1 с | `add audio-delay -0.1` |
| `g-a` | выбрать из списка | `script-binding select/select-aid` |
| `g-d` | — | `script-binding select/select-audio-device` |
| `Дробь на цифровом блоке` | громкость -2 | `add volume -2` |
| `Звёздочка на цифровом блоке` | громкость 2 | `add volume 2` |
| `m` | звук вкл/выкл | `cycle mute` |
| `Mute (мультимедийная)` | звук вкл/выкл | `cycle mute` |
| `#` | следующая звуковая дорожка | `cycle audio` |
| `Тише (мультимедийная)` | громкость -2 | `add volume -2` |
| `Громче (мультимедийная)` | громкость 2 | `add volume 2` |

### Субтитры

| Клавиша | Что делает | Команда mpv |
|---|---|---|
| `Alt+v` | — | `cycle secondary-sub-visibility` |
| `F` | размер субтитров -0.1 | `add sub-scale -0.1` |
| `G` | размер субтитров 0.1 | `add sub-scale 0.1` |
| `g-L` | — | `script-binding select/select-secondary-subtitle-line` |
| `g-l` | — | `script-binding select/select-subtitle-line` |
| `g-S` | — | `script-binding select/select-secondary-sid` |
| `g-s` | выбрать из списка | `script-binding select/select-sid` |
| `J` | — | `cycle sub down` |
| `j` | следующие субтитры | `cycle sub` |
| `R` | — | `add sub-pos +1` |
| `r` | субтитры выше/ниже | `add sub-pos -1` |
| `Shift+Ctrl+←` | — | `sub-step -1` |
| `Shift+Ctrl+→` | — | `sub-step 1` |
| `t` | — | `add sub-pos +1` |
| `u` | переключить sub-ass-override | `cycle-values sub-ass-override "force" "scale"` |
| `V` | — | `cycle sub-ass-use-video-data` |
| `v` | показать/скрыть субтитры | `cycle sub-visibility` |
| `x` | сдвиг субтитров на 0.1 с | `add sub-delay 0.1` |
| `Z` | сдвиг субтитров на 0.1 с | `add sub-delay 0.1` |
| `z` | сдвиг субтитров на -0.1 с | `add sub-delay -0.1` |

### Картинка

| Клавиша | Что делает | Команда mpv |
|---|---|---|
| `1` | контраст -1 | `add contrast -1` |
| `2` | контраст 1 | `add contrast 1` |
| `3` | яркость -1 | `add brightness -1` |
| `4` | яркость 1 | `add brightness 1` |
| `5` | гамма -1 | `add gamma -1` |
| `6` | гамма 1 | `add gamma 1` |
| `7` | насыщенность -1 | `add saturation -1` |
| `8` | насыщенность 1 | `add saturation 1` |
| `_` | следующая видеодорожка | `cycle video` |
| `A` | переключить video-aspect-override | `cycle-values video-aspect-override "16:9" "4:3" "2.35:1" "no"` |
| `Alt++` | приблизить / отдалить | `add video-zoom 0.1` |
| `Alt+-` | приблизить / отдалить | `add video-zoom -0.1` |
| `Alt+Backspace` | вернуть масштаб и положение | `set video-zoom 0; no-osd set panscan 0; no-osd set video-pan-x 0; no-osd set video-pan-y 0; no-osd set video-align-x 0; no-osd set video-align-y 0` |
| `Alt+↓` | сдвинуть картинку по вертикали | `add video-pan-y -0.1` |
| `Alt+KP1` | — | `repeatable add video-rotate -1` |
| `Alt+KP3` | — | `repeatable add video-rotate 1` |
| `Alt+KP5` | video-rotate = 0 | `set video-rotate 0` |
| `Alt+Плюс на цифровом блоке` | приблизить / отдалить | `add video-zoom 0.1` |
| `Alt+Минус на цифровом блоке` | приблизить / отдалить | `add video-zoom -0.1` |
| `Alt+←` | сдвинуть картинку по горизонтали | `add video-pan-x 0.1` |
| `Alt+→` | сдвинуть картинку по горизонтали | `add video-pan-x -0.1` |
| `Alt+↑` | сдвинуть картинку по вертикали | `add video-pan-y 0.1` |
| `Ctrl+h` | переключить hwdec | `cycle-values hwdec no auto` |
| `Ctrl+KP1` | — | `add video-pan-x -0.01; add video-pan-y 0.01` |
| `Ctrl+KP2` | сдвинуть картинку по вертикали | `add video-pan-y 0.01` |
| `Ctrl+KP3` | — | `add video-pan-x 0.01; add video-pan-y 0.01` |
| `Ctrl+KP4` | сдвинуть картинку по горизонтали | `add video-pan-x -0.01` |
| `Ctrl+KP5` | — | `set video-pan-x 0.00; set video-pan-y 0.00` |
| `Ctrl+KP6` | сдвинуть картинку по горизонтали | `add video-pan-x 0.01` |
| `Ctrl+KP7` | — | `add video-pan-x -0.01; add video-pan-y -0.01` |
| `Ctrl+KP8` | сдвинуть картинку по вертикали | `add video-pan-y -0.01` |
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
| `d` | устранение чересстрочности | `cycle deinterlace` |
| `e` | — | `add panscan +0.1` |
| `g-v` | выбрать из списка | `script-binding select/select-vid` |
| `KP1` | приблизить / отдалить | `add video-zoom -0.01` |
| `KP2` | video-scale-y: -0.01 | `add video-scale-y -0.01` |
| `KP4` | video-scale-x: -0.01 | `add video-scale-x -0.01` |
| `KP5` | — | `set video-scale-x 1.00; set video-scale-y 1; set video-zoom 0` |
| `KP6` | video-scale-x: 0.01 | `add video-scale-x 0.01` |
| `KP8` | video-scale-y: 0.01 | `add video-scale-y 0.01` |
| `KP9` | приблизить / отдалить | `add video-zoom 0.01` |
| `S` | снимок чистого кадра, без субтитров | `screenshot video` |
| `W` | — | `add panscan +0.1` |
| `w` | обрезать поля по краям | `add panscan -0.1` |
| `ZOOMIN` | приблизить / отдалить | `add video-zoom 0.1` |
| `ZOOMOUT` | приблизить / отдалить | `add video-zoom -0.1` |

### Окно, экран и снимки

| Клавиша | Что делает | Команда mpv |
|---|---|---|
| `Alt+0` | window-scale = 0.5 | `set window-scale 0.5` |
| `Alt+1` | window-scale = 1 | `set window-scale 1` |
| `Alt+2` | window-scale = 2 | `set window-scale 2` |
| `Alt+s` | — | `screenshot each-frame` |
| `Ctrl+r` | — | `set file-local-options/start ${=time-pos}; playlist-play-index current yes; show-text "Reloading current file..."` |
| `Ctrl+s` | снимок окна как оно есть | `screenshot window` |
| `Ctrl+v` | — | `update-clipboard text; loadfile ${clipboard/text} append-play; show-text '+ ${clipboard/text}'` |
| `Esc` | fullscreen = no | `set fullscreen no` |
| `f` | полный экран | `cycle fullscreen` |
| `F8` | — | `show-text ${playlist}` |
| `F9` | — | `show-text ${track-list}` |
| `Двойной щелчок` | полный экран | `cycle fullscreen` |
| `O` | — | `no-osd cycle-values osd-level 3 1` |
| `o` | показать полосу времени | `show-progress` |
| `P` | показать полосу времени | `show-progress` |
| `s` | снимок кадра с субтитрами | `screenshot` |
| `Shift+End` | — | `no-osd set playlist-pos-1 ${playlist-count}` |
| `Shift+Home` | — | `no-osd set playlist-pos 0` |
| `T` | поверх других окон | `cycle ontop` |

### Файлы и список

| Клавиша | Что делает | Команда mpv |
|---|---|---|
| `<` | предыдущий файл в списке | `playlist-prev` |
| `>` | следующий файл в списке | `playlist-next` |
| `Enter` | следующий файл в списке | `playlist-next` |
| `g-p` | выбрать из списка | `script-binding select/select-playlist` |
| `Кнопка «назад»` | предыдущий файл в списке | `playlist-prev` |
| `Кнопка «вперёд»` | следующий файл в списке | `playlist-next` |
| `Следующий (мультимедийная)` | следующий файл в списке | `playlist-next` |
| `Предыдущий (мультимедийная)` | предыдущий файл в списке | `playlist-prev` |

### Меню, сведения, прочее

| Клавиша | Что делает | Команда mpv |
|---|---|---|
| `?` | — | `script-binding stats/display-page-4-toggle` |
| ``` | — | `script-binding commands/open` |
| `Ctrl+Левая кнопка` | перетаскивание картинки мышью | `script-binding positioning/drag-to-pan` |
| `Ctrl+p` | меню | `script-binding select/menu` |
| `Ctrl+Колесо вниз` | — | `script-binding positioning/cursor-centric-zoom -0.1` |
| `Ctrl+Колесо вверх` | — | `script-binding positioning/cursor-centric-zoom 0.1` |
| `Delete` | экранный пульт | `script-binding osc/visibility` |
| `E` | — | `cycle edition` |
| `g-b` | выбрать из списка | `script-binding select/select-binding` |
| `g-e` | выбрать из списка | `script-binding select/select-edition` |
| `g-h` | — | `script-binding select/select-watch-history` |
| `g-m` | меню | `script-binding select/menu` |
| `g-r` | — | `script-binding select/show-properties` |
| `g-t` | выбрать из списка | `script-binding select/select-track` |
| `g-w` | — | `script-binding select/select-watch-later` |
| `I` | сведения о файле и воспроизведении | `script-binding stats/display-stats-toggle` |
| `i` | сведения о файле и воспроизведении | `script-binding stats/display-stats` |
| `Левая кнопка` | экранный пульт | `script-binding osc/__keybinding11` |
| `Средняя кнопка` | экранный пульт | `script-binding osc/__keybinding6` |
| `Правая кнопка` | экранный пульт | `script-binding osc/__keybinding7` |
| `MENU` | — | `script-binding select/context-menu` |
| `MOUSE_LEAVE` | экранный пульт | `script-binding osc/__keybinding4` |
| `MOUSE_MOVE` | экранный пульт | `script-binding osc/__keybinding3` |
| `Shift+F10` | — | `script-binding select/context-menu` |
| `Shift+Левая кнопка` | экранный пульт | `script-binding osc/__keybinding8` |
| `Колесо вниз` | экранный пульт | `script-binding osc/__keybinding10` |
| `Колесо вверх` | экранный пульт | `script-binding osc/__keybinding9` |

## Если клавиша не сработала

- Окно плеера должно быть активным: щелчок по нему возвращает фокус.
- Пока стоит петля A/B, воспроизведение не выходит за точку B — снимите её `Ctrl+l`.
- Полный справочник самого mpv лежит рядом с плеером:
  `Tools\mpv\bin\doc\manual.pdf`, его кладёт установщик.
