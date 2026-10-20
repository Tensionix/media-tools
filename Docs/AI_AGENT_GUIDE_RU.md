# Audion Media Tools и ИИ-агент

[English](AI_AGENT_GUIDE_EN.md) · [Руководство](USER_GUIDE_RU.md) · [Консольная команда](CLI_RU.md) · [Операции](OPERATIONS_RU.md)

**Содержание**

- [Кто что делает](#кто-что-делает)
- [Консольная команда](#консольная-команда)
  - [Какая операция](#какая-операция)
- [Типовые задачи](#типовые-задачи)
- [Проверка результата](#проверка-результата)
- [Правила](#правила)

Руководство для ИИ-агента (Claude Code, Codex и подобных), которого пользователь попросил работать с программой. Для человека —
`USER_GUIDE_RU.md`; для командной строки — `CLI_RU.md`.

## Кто что делает

Программа делает работу с медиа через FFmpeg — одинаково при каждом запуске: кодирует для архива, монтажа, хранения и доставки;
переупаковывает в другой контейнер без перекодирования; извлекает и конвертирует звук; режет камерный файл без потерь; меняет
частоту кадров; накладывает LUT; скачивает по ссылке через yt-dlp; говорит, что за файлы, через ffprobe. Каждая кнопка её окна —
операция консольной команды `media_cli.cmd`, поэтому агенту доступно всё это.

Агент переводит слова пользователя в операцию и её пресет, запускает, читает итог и проверяет файл. Своих команд FFmpeg агент
не пишет там, где есть операция: операция уже знает подводные камни контейнеров, частот кадров и таймкода.

## Консольная команда

`media_cli.cmd` лежит в корне программы:

```
media_cli.cmd describe                                    операции, поля, варианты, пресеты (JSON)
media_cli.cmd run --operation ID --set ИМЯ=ЗНАЧЕНИЕ       запустить операцию; --dry-run — какие команды она запустила бы
media_cli.cmd run ... --source ФАЙЛ_ИЛИ_ПАПКА --target ПАПКА --result ИТОГ.json
```

Источник — `input\` программы, если `--source` не называет папку или один файл; Назначение — `output\`, если `--target` не
называет другое. Коды выхода: 0 готово, 1 сбой, 2 неверный вызов или запуск, отклонённый проверками (ничего не запускалось),
130 остановлено. Файл итога `--result`: `outcome`, `ok`, `message`, `parameters` — все значения, с которыми шёл прогон, —
и `data`: у медиа-операции `processed` (записано файлов), `skipped` (пропущено), `files`, `failed` там, где операция идёт
дальше упавшего файла; у скачивания `processed` и `downloaded` (пути записанного); всегда `log_file`. Все ключи —
`CLI_RU.md`. `--result` — файл `.json` вне Источника; давать полным путём или звать команду из папки программы:
относительный путь считается от папки, из которой вызвана команда. `failed` или `refused` больше 0 — итог `failed`.

### Какая операция

<!-- map:sections -->
| Раздел | Режим | Вызов |
|---|---|---|
| АУДИО | ИЗВЛЕЧЬ | `media_cli.cmd run --operation audio_run --set audio_workflow=extract` |
| АУДИО | ЗВУК В ВИДЕО | `media_cli.cmd run --operation audio_run --set audio_workflow=in_video` |
| АУДИО | КОНВЕРТИРОВАТЬ | `media_cli.cmd run --operation audio_run --set audio_workflow=audio_files` |
| КОДИРОВАНИЕ | АРХИВ | `media_cli.cmd run --operation archive_run` |
| КОДИРОВАНИЕ | МОНТАЖ | `media_cli.cmd run --operation editing_run` |
| КОДИРОВАНИЕ | ХРАНЕНИЕ | `media_cli.cmd run --operation storage_run` |
| КОДИРОВАНИЕ | ДОСТАВКА | `media_cli.cmd run --operation delivery_run` |
| КОДИРОВАНИЕ | RAW | `media_cli.cmd run --operation raw_develop_run` |
| УПАКОВКА | ВИДЕО | `media_cli.cmd run --operation remux_run --set remux_stream_mode=video` |
| УПАКОВКА | АУДИО | `media_cli.cmd run --operation remux_run --set remux_stream_mode=audio` |
| УПАКОВКА | ВИДЕО И АУДИО | `media_cli.cmd run --operation remux_run --set remux_stream_mode=video_audio` |
| УПАКОВКА | СУБТИТРЫ | `media_cli.cmd run --operation subtitles_extract` |
| НАРЕЗКА | ОСТАВИТЬ | `media_cli.cmd run --operation trim_run --set trim_action=keep` |
| НАРЕЗКА | ВЫРЕЗАТЬ | `media_cli.cmd run --operation trim_run --set trim_action=cut` |
| НАРЕЗКА | РАЗДЕЛИТЬ | `media_cli.cmd run --operation trim_run --set trim_action=split` |
| ЧАСТОТА | VARISPEED | `media_cli.cmd run --operation fps_run --set fps_mode=varispeed` |
| ЧАСТОТА | CONFORM | `media_cli.cmd run --operation fps_run --set fps_mode=conform` |
| ЦВЕТ | LUT | `media_cli.cmd run --operation grading_run` |
| СКАЧАТЬ | ЛУЧШЕЕ MP4 | `media_cli.cmd run --operation youtube_run --set youtube_profile=best_mp4` |
| СКАЧАТЬ | НАДЁЖНОЕ MP4 | `media_cli.cmd run --operation youtube_run --set youtube_profile=safe_mp4` |
| СКАЧАТЬ | СВОЁ ВИДЕО | `media_cli.cmd run --operation youtube_run --set youtube_profile=video_custom` |
| СКАЧАТЬ | ДЛЯ ЗАГРУЗКИ | `media_cli.cmd run --operation youtube_run --set youtube_profile=upload_ready` |
| СКАЧАТЬ | СВОЁ АУДИО | `media_cli.cmd run --operation youtube_run --set youtube_profile=audio_custom` |
| СКАЧАТЬ | СУБТИТРЫ | `media_cli.cmd run --operation youtube_run --set youtube_profile=subs_only` |
<!-- /map -->

СВЕДЕНИЯ, СЕРВИС и кнопки у полей:

<!-- map:service -->
| Операция | Что это |
|---|---|
| `probe_source` | Проверить источник: Один раз запустить ffprobe по Источнику, вывести таблицу и обновить строку параметров. |
| `source_info` | Инфо об источниках: Прогнать ffprobe по Источнику и вывести все аудиопотоки: codec, sample_fmt, sample rate, bits, channels, bitrate, language/title. |
| `inventory` | Инвентаризация: Посчитать файлы в Источнике, Назначении и LUTs. |
| `selftest` | Самопроверка: Проверить ffmpeg, ffprobe, yt-dlp и Deno. |
| `profile_doctor` | Проверка профилей: Проверить операции GUI, script wrappers и общий каталог пресетов. |
| `hardware_capabilities` | Возможности оборудования: Короткий FFmpeg smoke для CPU, QSV/NVENC/AMF H.264 и HEVC, SVT-AV1 и dav1d. |
| `preset_test_matrix` | Тест матрицы пресетов: Прогнать portable smoke на 1-секундных файлах по audio, remux, FPS, LUT, архиву, монтажу, хранению и публикации. |
| `install_7zip` | Установить 7-Zip: Установить или обновить portable 7-Zip; нужен для FFmpeg 7z payloads. |
| `install_ffmpeg` | Установить FFmpeg: Установить или обновить переносную FFmpeg от Gyan (GPL) в Tools\ffmpeg по драйверу NVIDIA: самая новая стабильная, не ниже 9.0.2, без карты NVIDIA и с LTS-драйвером 610.88 и новее; ниже него 8.0.1 (570-610.87) или 7.1, чтобы работал NVENC, и доступны не все операции. |
| `install_ytdlp` | Установить yt-dlp: Установить или обновить portable yt-dlp и Deno в Tools. |
| `install_mpv` | Установить mpv: Установить или обновить portable mpv в Tools/mpv: плеер нарезки. |
| `install_cineraw` | Установить проявку ProRes RAW: Собрать cineraw из libcraw в Tools/cineraw из исходников: переносной MSYS2 для сборки (около 185 МБ загрузки, 5 минут), удаляется после; cineraw проявляет ProRes RAW на видеокарте с Vulkan 1.4 (NVIDIA RTX). |
| `youtube_formats` | Форматы ссылки: Какие форматы есть у ссылки - разрешение, кодеки, размер - списком в журнале, ничего не скачивается. Взять один из них - профилем «Своё видео». |
| `youtube_cookies_import` | Взять под DPAPI: Файл поля «Файл cookies» запечатывается DPAPI для этой учётной записи Windows в config\cookies.dpapi: загрузки с Cookies - «Файл» берут эту копию, и открытый файл больше не нужен. |
<!-- /map -->

Каждое поле, вариант и пресет каждой операции — `OPERATIONS_RU.md`.

## Типовые задачи

1. **«Перекодируй файл для монтажа».** Сначала `probe_source` с `--source ФАЙЛ`: кодек, размер, частота кадров, звук
   (`source_info` подробно говорит о каждом звуковом потоке). Потом `editing_run`: по умолчанию
   `editing_profile=prores_422_mov`, полегче — `prores_lt_mov` или `prores_proxy_mov`, DNxHR — `dnxhr_hq_mov`, для Avid —
   пресет `*_mxf`. Файл ложится в папку операции и её настроек — `output\Editing\prores422\`, — а не в папку с именем
   пресета; точный путь печатает `--dry-run`.
2. **«Сожми для хранения» / «для загрузки».** `storage_run` (`x264_crf14`, `hevc10_crf14`, `svt_av1_crf14`, `x264_1080_crf14`
   — 4K вниз до 1080) или `delivery_run` (`review_h264`, `upload_h264`, `upload_hevc10`). На видеокарте — `--set
   encode_backend=cuda` (NVIDIA), `amd`, `qsv`; что умеет эта машина, говорит `hardware_capabilities`.
3. **«Переложи в MP4 / MOV / MKV» без перекодирования.** `remux_run` с `remux_target_format` и `remux_stream_mode=video_audio`.
   Контейнер, который не удержит поток, отклоняется до запуска, с причиной.
4. **Звук.** `audio_run`: `audio_workflow=extract` — достать из видео, `in_video` — перекодировать звук внутри видео, картинка
   копируется, `audio_files` — конвертировать звуковые файлы; `audio_profile` — `wav_24_48`, `flac_24_48`, `m4a384`, `mp3_v0`,
   `lufs14_m4a` (громкость −14 LUFS), `lufs_report` (только замер).
5. **Нарезка.** `trim_run --set trim_file=ИМЯ --set trim_action=keep --set trim_start=00:00:05,000 --set
   trim_end=00:01:00,000`. Видео копируется: начало встаёт на ближайший ключевой кадр, конец — на точный кадр; журнал говорит,
   где рез лёг на деле. `cut` вырезает кусок, `split` режет на части по точкам.
6. **Частота кадров в 23,976.** `fps_run`: `fps_mode=varispeed` замедляет каждый кадр и звук вместе с ними, тон
   идёт за скоростью; `conform` тоже сохраняет каждый кадр и растягивает звук, тон остаётся.
7. **LUT, HDR в SDR.** `grading_run --set lut_file=LUTs\ИМЯ.cube`; LUT лежат в `LUTs\`. `hdr_hable_x264` переводит HDR в SDR без
   LUT.
8. **Скачать по ссылке.** `youtube_formats --set youtube_url=ССЫЛКА` показывает, что предлагает ссылка, и ничего не скачивает;
   потом `youtube_run --set youtube_url=ССЫЛКА` (по умолчанию `youtube_profile=best_mp4`; `safe_mp4` — для ссылки, которая
   обрывается; `audio_custom` с `youtube_audio_format=m4a` — только звук). `best_mp4` берёт лучшую картинку, которая
   ложится в MP4, — это может быть AV1; H.264 с AAC — `upload_ready`. Файл называет `data.downloaded`:
   `output\Download\<автор>\<дата> - <название> [<id>].<ext>`. Весь плейлист — `--set youtube_source_mode=playlist`;
   список ссылок — `batch` с `input\urls.txt`.

## Проверка результата

- Прочитать файл итога: `outcome` — `done`, `data.processed` больше 0. При `failed` или `refused` журнал (`data.log_file`)
  говорит почему: его строки `[ERR]` и `[PREFLIGHT]`.
- Файл, который уже лежит в Назначении, без `--set overwrite=true` не перезаписывается: журнал пишет `[SKIP] ИМЯ already
  exists and Overwrite is off`, старый файл остаётся, а итог считает его в `skipped`, не в `processed`.
- Новый файл проверить `Tools\ffmpeg\bin\ffprobe.exe -v error -show_streams -show_format ФАЙЛ`: кодек, размер, частота кадров,
  длительность и звук против исходника; у нарезки — число кадров.

## Правила

- Не менять, не переносить и не удалять файлы пользователя в `input\` или там, куда указывает `--source`. Результаты — в
  Назначение.
- Файл cookies не читать и не печатать. По умолчанию файл cookies пользователя уходит со скачиванием, если он есть, — как
  в окне; публичной ссылке они не нужны — `--set cookies_source=none`; ссылке, которой нужен вход, —
  `--set cookies_source=chrome` (или `edge`, `firefox`, `brave`).
- Очистка папок удаляет насовсем и из команды не запускается: пользователь очищает их в окне, через Корзину.
- Видеокарту называть только после того, как `hardware_capabilities` сказал, что она работает на этой машине; процессор
  работает всегда.
- Перед долгим прогоном `--dry-run` показывает точные команды.
