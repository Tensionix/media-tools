using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text.Json;
using System.Threading.Tasks;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Shapes;
using Avalonia.Layout;
using Avalonia.Media;
using AudionMediaTools.Core;
using AudionMediaTools.Views;

namespace AudionMediaTools;

/// <summary>
/// The versions in the middle of the header (the plan, 6.5; the owner, 15.10.2026: yt-dlp, FFmpeg, the NVIDIA driver, mpv -
/// "нужно обновить или иметь в виду"): a badge each, a dot of freshness - Burn Orange when a newer release is out, a bright
/// forest green when it is the newest - the mark of the brand in its colour and the version. The driver of the GPU is the
/// user's: green always, the version shown. FFmpeg is compared with the newest Gyan stable; under an NVIDIA driver below
/// the LTS 610.88 its dot is amber: the older branch keeps NVENC working, not every operation is possible. deno is
/// there too: without it yt-dlp gets no formats of YouTube, and it is released often. The console command answers
/// (media_cli.cmd components), off the window's thread, once the window is up; GitHub at most once a day.
/// </summary>
public partial class MainWindow
{
    JsonElement? _components;

    async Task LoadComponents(bool refresh = false)
    {
        var told = await Door.Components(refresh);
        if (told is null) return;
        _components = told;
        ShowComponents();
        if (_sheet == "settings") FillSheet();
    }

    /// <summary>What updates a component: an operation of SERVICE (yt-dlp brings deno with it).</summary>
    static readonly Dictionary<string, string> Installers = new()
    {
        ["yt-dlp"] = "install_ytdlp", ["deno"] = "install_ytdlp", ["mpv"] = "install_mpv", ["ffmpeg"] = "install_ffmpeg", ["7zip"] = "install_7zip", ["cineraw"] = "install_cineraw",
    };

    IEnumerable<JsonElement> ComponentList() =>
        _components is { } told && told.TryGetProperty("components", out var list) ? list.EnumerateArray() : Enumerable.Empty<JsonElement>();

    /// <summary>The mark a component is drawn with: yt-dlp has none in any set and takes the one of YouTube (the owner, 15.10.2026);
    /// a GPU, the one of its maker.</summary>
    static string MarkOf(string id, string brand = "") => id switch { "yt-dlp" => "youtube", "gpu" => brand, _ => id };

    static string Text(JsonElement component, string name) =>
        component.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String ? value.GetString() ?? "" : "";

    /// <summary>
    /// SETTINGS, COMPONENTS (the plan, 6.6): every component with its version, the newest release, its state in the colour
    /// of the header, and the operation of SERVICE that installs or updates it - its run goes to the journal as any other.
    /// </summary>
    void ComponentsCard(Panel column)
    {
        Open(column, "КОМПОНЕНТЫ");
        if (_components is null) { Note("Версии ещё читаются…"); return; }
        foreach (var component in ComponentList())
        {
            var id = Text(component, "id");
            if (id == "gpu") continue;
            string version = Text(component, "version"), latest = Text(component, "latest"), state = Text(component, "state");
            var row = new Grid { ColumnDefinitions = new ColumnDefinitions("22,84,130,*,Auto"), Margin = new Thickness(0, 1) };
            void Put(Control control, int at) { Grid.SetColumn(control, at); control.VerticalAlignment = VerticalAlignment.Center; row.Children.Add(control); }
            if (Icons.Mark(MarkOf(id), 13) is { } mark) Put(mark, 0);
            Put(new TextBlock { Text = Text(component, "name") }, 1);
            Put(new SelectableTextBlock { Text = version.Length > 0 ? version : Lang.T("нет") }, 2);
            var dot = new Ellipse { Classes = { "dot" }, Margin = new Thickness(0, 0, 6, 0) };
            dot.Classes.Set("ok", state == "fresh");
            dot.Classes.Set("warn", state == "limited");
            dot.Classes.Set("bad", state is "old" or "missing");
            var said = state switch
            {
                // FFmpeg under an NVIDIA driver below the LTS 610.88: the older branch that keeps NVENC working.
                "limited" => Lang.F("драйвер NVIDIA {0} ниже 610.88: доступны не все операции", Text(component, "driver")),
                "fresh" => Lang.T("свежая"), "old" => Lang.F("есть новее: {0}", latest),
                "missing" => Lang.T("не установлен"), "own" => Lang.T("собран здесь из исходников"), _ => Lang.T("не проверено"),
            };
            var stateText = new TextBlock { Classes = { "caption" }, Text = said, TextTrimming = TextTrimming.CharacterEllipsis };
            ToolTip.SetTip(stateText, said);
            Put(new DockPanel { Children = { dot, stateText } }, 3);
            if (Installers.TryGetValue(id, out var op) && _told?.Find(op) is { } node)
            {
                var update = new Button { Classes = { "small" }, Content = Lang.T(version.Length > 0 ? "ОБНОВИТЬ" : "УСТАНОВИТЬ"), Margin = new Thickness(6, 0, 0, 0) };
                Avalonia.Automation.AutomationProperties.SetAutomationId(update, "update_" + id);
                var tip = TipOf(node);
                if (id == "ffmpeg")
                    tip += "\n\n" + Lang.T("Версию FFmpeg выбирает драйвер NVIDIA: самая новая стабильная, не ниже 9.0.2, - без карты NVIDIA и с драйвером 610.88 и новее; ниже 610.88 - 8.0.1 или 7.1, при которых работает NVENC, и доступны не все операции. Перед скачиванием окно покажет выбранный файл, его размер и причину выбора.");
                ToolTip.SetTip(update, tip);
                update.IsEnabled = !_runner.Running && !_asking && !_clearing;
                update.Click += (_, _) => Press(node, null);
                Put(update, 4);
            }
            Add(row);
        }
        var checkedAt = _components is { } told && told.TryGetProperty("checked", out var when) && DateTime.TryParse(when.GetString(), CultureInfo.InvariantCulture, DateTimeStyles.None, out var at)
            ? at.ToString("dd.MM.yyyy HH:mm", CultureInfo.InvariantCulture) : "";
        var again = new Button { Classes = { "small" }, Content = Lang.T("ПРОВЕРИТЬ СЕЙЧАС"), HorizontalAlignment = HorizontalAlignment.Left, Margin = new Thickness(0, 6, 0, 0) };
        Avalonia.Automation.AutomationProperties.SetAutomationId(again, "components_refresh");
        ToolTip.SetTip(again, Lang.T("Спросить GitHub о свежих выпусках yt-dlp, deno, mpv, FFmpeg и 7-Zip сейчас. Сам он спрашивается не чаще раза в сутки."));
        again.Click += async (_, _) =>
        {
            again.IsEnabled = false;
            SetStatus("Спрашиваю GitHub о свежих выпусках…");
            await LoadComponents(refresh: true);
            SetStatus("Версии компонентов прочитаны.");
        };
        Add(new StackPanel { Orientation = Orientation.Horizontal, Spacing = 10, Children = { again } });
        Note(checkedAt.Length > 0 ? Lang.F("GitHub спрошен {0}.", checkedAt) : Lang.T("GitHub ещё не спрашивался."));
    }

    /// <summary>
    /// SETTINGS, SYSTEM (the owner, 15.10.2026: "всю раскладку - версии системы, процессор, GPU, RAM, видеодрайвер и прочее
    /// сделать в бейдже ... просто в SETTINGS"): what the machine is, and the coders FFmpeg found working on it; copied as
    /// text for a report of a trouble.
    /// </summary>
    void SystemCard(Panel column)
    {
        Open(column, "СИСТЕМА");
        var lines = new List<(string Key, string Value)>();
        string Read(string key, string name)
        {
            try { return Microsoft.Win32.Registry.GetValue(key, name, null)?.ToString() ?? ""; }
            catch { return ""; }
        }
        const string Nt = @"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Windows NT\CurrentVersion";
        var build = Read(Nt, "CurrentBuild");
        var ubr = Read(Nt, "UBR");
        var windows = int.TryParse(build, out var number) && number >= 22000 ? "Windows 11" : "Windows 10";
        lines.Add(("Windows", $"{windows} {Read(Nt, "EditionID")} {Read(Nt, "DisplayVersion")}".Trim() + (build.Length > 0 ? Lang.F(", сборка {0}", build + (ubr.Length > 0 ? "." + ubr : "")) : "")));
        var cpu = Read(@"HKEY_LOCAL_MACHINE\HARDWARE\DESCRIPTION\System\CentralProcessor\0", "ProcessorNameString").Trim();
        lines.Add((Lang.T("Процессор"), (cpu.Length > 0 ? cpu + ", " : "") + Lang.F("потоков: {0}", Environment.ProcessorCount)));
        foreach (var gpu in ComponentList().Where(component => Text(component, "id") == "gpu"))
            lines.Add((Lang.T("Видеокарта"), $"{Text(gpu, "name")}" + (Text(gpu, "version").Length > 0 ? Lang.F(", драйвер {0}", Text(gpu, "version")) : "")));
        var memory = GC.GetGCMemoryInfo().TotalAvailableMemoryBytes;
        if (memory > 0) lines.Add((Lang.T("Память"), Lang.F("{0} ГБ", (memory / 1024.0 / 1024 / 1024).ToString("0.#", CultureInfo.InvariantCulture))));
        lines.Add((Lang.T("Кодеры FFmpeg"), Coders()));
        try
        {
            var drive = new System.IO.DriveInfo(System.IO.Path.GetPathRoot(Paths.Root) ?? Paths.Root);
            lines.Add((Lang.T("Диск программы"), Lang.F("{0}: свободно {1} ГБ из {2} ГБ", drive.Name.TrimEnd('\\', ':'),
                (drive.AvailableFreeSpace / 1073741824.0).ToString("0", CultureInfo.InvariantCulture), (drive.TotalSize / 1073741824.0).ToString("0", CultureInfo.InvariantCulture))));
        }
        catch { }
        foreach (var (key, value) in lines) Pair(key, value);
        var copy = new Button { Classes = { "small" }, Content = Lang.T("СКОПИРОВАТЬ"), HorizontalAlignment = HorizontalAlignment.Left, Margin = new Thickness(0, 6, 0, 0) };
        Avalonia.Automation.AutomationProperties.SetAutomationId(copy, "system_copy");
        ToolTip.SetTip(copy, Lang.T("Скопировать сведения о машине текстом - для сообщения об ошибке."));
        copy.Click += async (_, _) =>
        {
            var text = "Audion Media Tools " + (Paths.Version ?? "") + Environment.NewLine + string.Join(Environment.NewLine, lines.Select(line => line.Key + ": " + line.Value));
            if (Clipboard is { } clipboard) await Avalonia.Input.Platform.ClipboardExtensions.SetTextAsync(clipboard, text);
            SetStatus("Сведения о машине скопированы.");
        };
        Add(copy);
    }

    /// <summary>
    /// Before an installer runs: what it would download - every file with its size and its source, a verified archive at
    /// hand said as no download, the policy that picked the release - asked of its script with nothing fetched (Door.Plan)
    /// and put to the person. True - the download may go.
    /// </summary>
    async Task<bool> AskDownload(Node node)
    {
        SetStatus("Спрашиваю, что будет скачано…");
        var plan = await Door.Plan(node.Id);
        var text = new System.Text.StringBuilder();
        var culture = Lang.Code == "ru" ? new CultureInfo("ru-RU") : CultureInfo.InvariantCulture;
        string Megabytes(long bytes) => Lang.F("{0} МБ", (bytes / 1048576.0).ToString("0.0", culture));
        if (plan is { } told && told.TryGetProperty("ok", out var ok) && ok.ValueKind == JsonValueKind.True)
        {
            long total = 0;
            bool unsized = false;
            text.Append(Lang.T("Будет скачано:")).Append('\n');
            foreach (var file in told.GetProperty("files").EnumerateArray())
            {
                var name = Text(file, "name");
                if (file.TryGetProperty("cached", out var cached) && cached.ValueKind == JsonValueKind.True)
                {
                    text.Append("  ").Append(name).Append(" - ").Append(Lang.T("уже лежит в кэше и проверен: скачивать не нужно")).Append('\n');
                    continue;
                }
                long? size = file.TryGetProperty("size", out var bytes) && bytes.ValueKind == JsonValueKind.Number ? bytes.GetInt64() : null;
                text.Append("  ").Append(name).Append(" - ").Append(size is { } known ? Megabytes(known) : Lang.T("размер не сообщён")).Append('\n');
                text.Append("    ").Append(Text(file, "url")).Append('\n');
                total += size ?? 0;
                unsized |= size is null;
            }
            if (total > 0) text.Append(Lang.F("Всего: {0}", Megabytes(total))).Append(unsized ? Lang.T(" и файлы без размера") : "").Append('\n');
            foreach (var note in told.GetProperty("notes").EnumerateArray())
                text.Append('\n').Append(Lang.T("Почему эта версия:")).Append(' ').Append(note.GetString()).Append('\n');
        }
        else
        {
            var why = plan is { } refused && Text(refused, "error") is { Length: > 0 } error ? error : Lang.T("консольная команда не ответила");
            text.Append(Lang.F("Заранее узнать, что будет скачано, не удалось: {0}", why)).Append('\n')
                .Append(Lang.T("Установка назовёт файлы сама, в журнале."));
        }
        SetStatus("Готово.");
        return await AskDialog.YesNo(this, Lang.F("Скачать для «{0}»?", node.Name), text.ToString().TrimEnd());
    }

    /// <summary>What the program carries, its licence, and where its source lies (the plan, 6.7: ABOUT, COMPOSITION).</summary>
    static readonly (string Id, string Name, string Licence, string Source)[] Composition =
    {
        ("ffmpeg", "FFmpeg", "GPL v3 (сборка gyan.dev full)", "ffmpeg-*-source.tar.gz"),
        ("mpv", "mpv", "GPL v2 или новее", "mpv-*-source.tar.gz"),
        ("yt-dlp", "yt-dlp", "Unlicense", "https://github.com/yt-dlp/yt-dlp"),
        ("deno", "deno", "MIT", "https://github.com/denoland/deno"),
        ("7zip", "7-Zip", "LGPL 2.1, BSD-3; unRAR - со своим ограничением", @"7zip\bin\License.txt"),
    };

    void CompositionCard(Panel column)
    {
        Open(column, "СОСТАВ");
        var tools = System.IO.Path.Combine(Paths.Root, "Tools");
        foreach (var (id, name, licence, source) in Composition)
        {
            var version = ComponentList().Where(component => Text(component, "id") == id).Select(component => Text(component, "version")).FirstOrDefault() ?? "";
            // The sources the GPL asks to give beside the build: the archives in Tools\, by their names.
            var where = source.StartsWith("https://", StringComparison.Ordinal) ? source
                : source.Contains('*') && System.IO.Directory.Exists(tools)
                    ? string.Join(", ", System.IO.Directory.GetFiles(tools, source).Select(path => @"Tools\" + System.IO.Path.GetFileName(path)))
                    : @"Tools\" + source;
            var row = new Grid { ColumnDefinitions = new ColumnDefinitions("22,84,170,250,*"), Margin = new Thickness(0, 1) };
            void Put(Control control, int at) { Grid.SetColumn(control, at); control.VerticalAlignment = VerticalAlignment.Center; row.Children.Add(control); }
            if (Icons.Mark(MarkOf(id), 13) is { } mark) Put(mark, 0);
            Put(new TextBlock { Text = name }, 1);
            Put(new SelectableTextBlock { Text = version.Length > 0 ? version : "—" }, 2);
            Put(new TextBlock { Classes = { "caption" }, Text = Lang.T(licence), TextWrapping = TextWrapping.Wrap }, 3);
            Put(new SelectableTextBlock { Classes = { "caption" }, Text = where.Length > 0 ? where : "—", TextWrapping = TextWrapping.Wrap }, 4);
            Add(row);
        }
        Note("Компоненты - отдельные программы со своими лицензиями: программа зовёт их, а не встраивает. Исходники GPL-сборок лежат рядом с ними в Tools.");
    }

    /// <summary>The coders FFmpeg was found to work with on this machine (config\hardware_capabilities_cache.json).</summary>
    string Coders()
    {
        try
        {
            var file = System.IO.Path.Combine(Paths.Config, "hardware_capabilities_cache.json");
            if (!System.IO.File.Exists(file)) return Lang.T("не проверялись: СЕРВИС → Возможности оборудования");
            using var told = JsonDocument.Parse(System.IO.File.ReadAllText(file));
            var ok = told.RootElement.GetProperty("statuses").EnumerateArray()
                .Where(status => status.GetProperty("status").GetString() == "OK").Select(status => status.GetProperty("label").GetString() ?? "").ToList();
            return ok.Count > 0 ? string.Join(", ", ok) : Lang.T("ни один не прошёл проверку");
        }
        catch { return Lang.T("кэш проверки не читается"); }
    }

    void ShowComponents()
    {
        ComponentRow.Children.Clear();
        if (_components is not { } told || !told.TryGetProperty("components", out var list)) return;
        var checkedAt = told.TryGetProperty("checked", out var when) && DateTime.TryParse(when.GetString(), CultureInfo.InvariantCulture, DateTimeStyles.None, out var at)
            ? at.ToString("dd.MM.yyyy HH:mm", CultureInfo.InvariantCulture) : "";
        foreach (var component in list.EnumerateArray())
        {
            string Text(string name) => component.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String ? value.GetString() ?? "" : "";
            var id = Text("id");
            // 7-Zip is a tool of the builder, not of a run: it stands in SETTINGS alone.
            if (id == "7zip") continue;
            ComponentRow.Children.Add(Badge(id, Text("name"), Text("version"), Text("detail"), Text("latest"), Text("state"), Text("source"), Text("brand"), Text("driver"), checkedAt));
        }
    }

    static Control Badge(string id, string name, string version, string detail, string latest, string state, string source, string brand, string driver, string checkedAt)
    {
        var dot = new Ellipse { Classes = { "dot" } };
        dot.Classes.Set("ok", state is "fresh" or "own");
        dot.Classes.Set("warn", state == "limited");
        dot.Classes.Set("bad", state is "old" or "missing");
        var row = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 6, VerticalAlignment = VerticalAlignment.Center, Children = { dot } };
        var mark = Icons.Mark(MarkOf(id, brand));
        if (mark is not null) row.Children.Add(mark);
        // A mark says whose it is; yt-dlp has none in any set, and a GPU without a known maker has its name.
        else row.Children.Add(new TextBlock { Classes = { "caption" }, Text = id == "gpu" ? Lang.T("GPU") : name });
        row.Children.Add(new TextBlock { Classes = { "caption", "version" }, Text = version.Length > 0 ? version : Lang.T("нет") });

        var tip = new System.Text.StringBuilder(name + (version.Length > 0 ? " " + version : ""));
        if (detail.Length > 0 && detail != version) tip.Append('\n').Append(detail);
        tip.Append('\n').Append(state switch
        {
            "fresh" => Lang.T("Это свежий выпуск."),
            "old" => Lang.F("Вышел более новый выпуск: {0}. Обновить - в SETTINGS.", latest),
            "limited" => Lang.F("Драйвер NVIDIA {0} ниже 610.88 - LTS-драйвера, под который собраны программы: стоит FFmpeg {1}, при которой работает NVENC, и доступны не все операции.", driver, version),
            "own" when id == "cineraw" => Lang.T("Собран из исходников libcraw при сборке программы; СЕРВИС - Установить проявку ProRes RAW собирает его заново. Версия - коммит libcraw, свежесть не сравнивается."),
            "own" => Lang.T("Драйвер видеокарты ставите вы: программа его не сравнивает, только показывает. От него зависит сборка FFmpeg с NVENC."),
            "missing" => Lang.T("Не установлен: установить - в меню СЕРВИС или в SETTINGS."),
            _ => Lang.T("Свежесть не проверена: GitHub не ответил."),
        });
        if (source.Length > 0) tip.Append('\n').Append(Lang.F("Свежий выпуск смотрится в {0}", source));
        if (source.Length > 0 && checkedAt.Length > 0) tip.Append('\n').Append(Lang.F("Проверено: {0}", checkedAt));
        var badge = new Border { Classes = { "verbadge" }, Child = row };
        ToolTip.SetTip(badge, tip.ToString());
        Avalonia.Automation.AutomationProperties.SetAutomationId(badge, "component_" + (id == "gpu" ? "gpu_" + brand : id));
        return badge;
    }
}
