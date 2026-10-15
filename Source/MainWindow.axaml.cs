using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Documents;
using Avalonia.Controls.Primitives;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Threading;
using AudionMediaTools.Core;
using AudionMediaTools.Views;
using Page = AudionMediaTools.Core.Page;

namespace AudionMediaTools;

/// <summary>
/// The window of Audion Media Tools. It encodes, cuts and downloads nothing itself: every button runs an operation of
/// the manifest through the console door (media_cli.cmd) and shows what the operation says. Which sections there are,
/// which modes they have and which fields an operation has, the door tells; what a form holds and allows, the form
/// server of the door decides (media_cli.cmd form) - the window knows none of them by name.
/// </summary>
public partial class MainWindow : Window
{
    readonly Settings _settings;
    readonly Runner _runner = new();
    /// <summary>The forms of the pages, held by the engine while the window is open (Core\FormServer.cs).</summary>
    readonly FormServer _forms = new();
    Described? _told;
    Section? _section;
    Page? _page;
    /// <summary>The page each section was left at.</summary>
    readonly Dictionary<string, string> _lastPage = new();

    public MainWindow()
    {
        // The theme is the application's: set before the markup is read, so the window comes up in it.
        _settings = Settings.Load();
        Lang.Set(_settings.LanguageInUse);
        if (Application.Current is { } app) app.RequestedThemeVariant = App.Variant(_settings.Look);
        InitializeComponent();
        if (_settings.Width >= MinWidth && _settings.Height >= MinHeight)
        {
            Width = _settings.Width;
            Height = _settings.Height;
        }
        // The journal as wide as the divider was left, the cards keeping their least width beside it.
        if (_settings.JournalWidth >= RightZone.MinWidth)
            Zones.ColumnDefinitions[2].Width = new GridLength(Math.Min(_settings.JournalWidth, Math.Max(RightZone.MinWidth, Width - LeftZone.MinWidth - 60)));
        Classes.Set("vault", _settings.Look == "vault");
        App.SetFonts(_settings.UiFont, _settings.LogFont);
        App.SetSizes(_settings.UiShift, _settings.LogSize);
        // Words and signs on whole pixels of this screen, whatever its scale.
        PixelGrid.Apply(RenderScaling);
        ScalingChanged += (_, _) => PixelGrid.Apply(RenderScaling);

        var version = Paths.Version;
        Title = version is null ? "Audion Media Tools" : "Audion Media Tools v" + version;
        VersionText.Text = (version is null ? "version unknown" : "v" + version) + " • " + DateTime.Now.Year;

        _runner.Output += OnOutput;
        _runner.Finished += OnFinished;
        Guard.Told = message =>
        {
            AppendLines(new[] { "[GUI ERROR] " + message });
            SetStatus("Ошибка окна записана в logs.");
        };

        Wire();
        WireIo();
        WireCommand();
        // The form server was started anew - it fell, or went silent: every page opened is opened again with what it held.
        _forms.Restarted += () => _reopen = true;
        // The right part of the state row - the bar of a run, its clock and STOP - stands under the journal and is as
        // wide as it, whatever the splitter or the wide journal make of the column.
        RightZone.SizeChanged += (_, e) => StateRight.Width = Math.Max(0, e.NewSize.Width);
        // A pass of a check (-Shot of a Debug build) and a walk of the built window (AUDION_WALK=1) are
        // not for a person: the window stands off every screen, takes no focus and has no button on
        // the taskbar (the owner of Audion Get Tools: "I cannot make out by your millisecond switches
        // what belongs to what"). Its pictures are drawn from the window itself, not from a screen.
        bool offScreen = Program.Walk;
#if DEBUG
        // AUDION_SHOT_ON_SCREEN=1 puts a pass in sight.
        offScreen |= Program.ShotFolder.Length > 0 && Environment.GetEnvironmentVariable("AUDION_SHOT_ON_SCREEN") != "1";
#endif
        if (offScreen)
        {
            ShowInTaskbar = false;
            ShowActivated = false;
            WindowStartupLocation = WindowStartupLocation.Manual;
            Position = OffScreen;
        }
        MarkTheme();
        MarkLanguage();
        // What the markup holds is written in Russian: walked once, into the language in use.
        Lang.Walk(this);
        Closing += OnClosing;
        Opened += async (_, _) =>
        {
            // A place set before the window is shown is not kept: it came up at the corner of the
            // screen (measured 14.10.2026, -32000 and Manual alike). Set again once it is open.
            if (offScreen) Position = OffScreen;
            await StartUp();
#if DEBUG
            // AUDION_SHOT_HEIGHT: a pass may ask for a taller window - a long page in one picture. Off the screen it may be any height.
            if (Program.ShotFolder.Length > 0 && double.TryParse(Environment.GetEnvironmentVariable("AUDION_SHOT_HEIGHT"), out var tall) && tall > 400) Height = tall;
            if (Program.ShotFolder.Length > 0) await TakeShots(Program.ShotFolder);
#endif
        };
    }

    /// <summary>Where a window of a check stands: off every screen. Not -32000 - Windows reads that as "minimised".</summary>
    static readonly PixelPoint OffScreen = new(-30000, -30000);

    // ------------------------------------------------------------ the look

    void Wire()
    {
        LangRu.Click += (_, _) => SetLanguage("ru");
        LangEn.Click += (_, _) => SetLanguage("en");
        ThemeVault.Click += (_, _) => SetTheme("vault");
        ThemeDark.Click += (_, _) => SetTheme("dark");
        ThemeCode.Click += (_, _) => SetTheme("codedark");
        ThemeLight.Click += (_, _) => SetTheme("light");
        StopButton.Click += (_, _) => StopRun();
        CopyLogButton.Click += (_, _) => CopyLog();
        ClearLogButton.Click += (_, _) => ClearLog();
        WideLogButton.Click += (_, _) => ToggleWide();
        ActionReset.Click += (_, _) => { if (_view is { } view) ResetPage(view); };
        LogsButton.Click += (_, _) => OpenFolder(Paths.ProgramLogs);
        ReportButton.Click += (_, _) => OpenFolder(_told?.Paths.Report is { Length: > 0 } report ? report : Path.Combine(Paths.Root, "report"));
        ConfigButton.Click += (_, _) => OpenFolder(Paths.Config);
        _clock.Tick += (_, _) => ShowClock();
        SheetSettings.Click += (_, _) => ToggleSheet("settings");
        SheetAbout.Click += (_, _) => ToggleSheet("about");
        SheetClose.Click += (_, _) => ToggleSheet(_sheet);
        KeyDown += (_, e) =>
        {
            if (e.Key != Avalonia.Input.Key.Escape || _sheet.Length == 0) return;
            ToggleSheet(_sheet);
            e.Handled = true;
        };
    }

    void MarkLanguage()
    {
        LangRu.IsChecked = Lang.Code == "ru";
        LangEn.IsChecked = Lang.Code != "ru";
    }

    void SetLanguage(string code)
    {
        if (Lang.Code != code)
        {
            Lang.Set(code);
            _settings.Lang = code;
            _settings.Save();
            // What code wrote is written again in the new language; what the markup holds is walked.
            ForgetPages();
            BuildService();
            BuildSections();
            ShowComponents();
            Lang.Walk(this);
            FillSheet();
        }
        MarkLanguage();
    }

    void SetTheme(string look)
    {
        _settings.Look = look;
        _settings.Save();
        if (Application.Current is { } app) app.RequestedThemeVariant = App.Variant(look);
        Classes.Set("vault", look == "vault");
        MarkTheme();
        // The lines of the terminal took their brushes from the old theme; so did the cards of ticks.
        Dispatcher.UIThread.Post(Recolour, DispatcherPriority.Background);
        OutdateAll();
        // A brand too dark for the new ground takes the ink of the text, and back.
        ShowComponents();
        // SETTINGS marks the theme chosen; ABOUT shows the mark made for it.
        FillSheet();
    }

    void MarkTheme()
    {
        ThemeVault.IsChecked = _settings.Look == "vault";
        ThemeDark.IsChecked = _settings.Look == "dark";
        ThemeCode.IsChecked = _settings.Look == "codedark";
        ThemeLight.IsChecked = _settings.Look == "light";
        ThemeButton.IsChecked = false;
    }

    static string Upper(string text) => text.ToUpper(CultureInfo.CurrentCulture);

    /// <summary>The status line: written in Russian by whoever speaks, shown in the language of the window.</summary>
    void SetStatus(string text) => StatusText.Text = Lang.T(text);

    // ------------------------------------------------------------ the start

    async Task StartUp()
    {
        if (!Door.Ready)
        {
            ShowNote(Door.Trouble);
            SetStatus("Движок программы недоступен.");
            return;
        }
        SetStatus("Читаю состав программы…");
        var (told, trouble) = await Door.Describe();
        if (told is null)
        {
            ShowNote(Lang.F("Консольная команда программы не ответила: {0}", trouble));
            SetStatus("Состав программы не прочитан.");
            return;
        }
        _told = told;
        StartIo();
        BuildService();
        BuildSections();
        SetStatus("Готово.");
        // The versions come when the console command has asked the components - and GitHub, once a day; the window does not wait.
        _ = LoadComponents();
    }

    void ShowNote(string text)
    {
        CardsNote.Text = text;
        CardsNote.IsVisible = true;
    }

    // ------------------------------------------------------------ the header: the service of the program

    /// <summary>
    /// SERVICE of the header: one button, and the checks and installers of the program in its menu (`service` of the
    /// layout) - the sections of the window are for the material, this is for the program itself.
    /// </summary>
    void BuildService()
    {
        ServiceRow.Children.Clear();
        if (_told is null) return;
        var menu = new MenuFlyout { Placement = PlacementMode.BottomEdgeAlignedRight };
        foreach (var node in _told.Layout.Service.Select(_told.Find).OfType<Node>())
        {
            var item = new MenuItem { Header = node.Name };
            Avalonia.Automation.AutomationProperties.SetAutomationId(item, "run_" + node.Id);
            ToolTip.SetTip(item, TipOf(node));
            item.Click += (_, _) => Press(node, null);
            menu.Items.Add(item);
        }
        var face = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 6, Children = { Icons.Sign("wrench"), new TextBlock { Text = Lang.T("СЕРВИС") } } };
        var button = new Button { Classes = { "small" }, Content = face, Flyout = menu, Margin = new Thickness(0, 0, 4, 0) };
        Avalonia.Automation.AutomationProperties.SetAutomationId(button, "service");
        ToolTip.SetTip(button, Lang.T("Проверки и установка инструментов программы: опись папок, самопроверка, проверка пресетов, железо, установка 7-Zip, FFmpeg и yt-dlp."));
        ServiceRow.Children.Add(button);
        BuildDetails();
        ApplyBusy();
    }

    /// <summary>DETAILS of the work zone: the operations of window_layout.yaml, details - ffprobe of the Source, into the journal.</summary>
    void BuildDetails()
    {
        if (_told is null) return;
        var menu = new MenuFlyout { Placement = PlacementMode.BottomEdgeAlignedLeft };
        foreach (var node in _told.Layout.Details.Select(_told.Find).OfType<Node>())
        {
            var item = new MenuItem { Header = node.Name };
            Avalonia.Automation.AutomationProperties.SetAutomationId(item, "run_" + node.Id);
            ToolTip.SetTip(item, TipOf(node));
            item.Click += (_, _) => Press(node, null);
            menu.Items.Add(item);
        }
        DetailsButton.Flyout = menu;
        DetailsButton.IsVisible = menu.Items.Count > 0;
    }

    /// <summary>The name of an operation and what it does: the tooltip of its button.</summary>
    static string TipOf(Node node) => node.About.Length > 0 ? node.Name + "\n" + node.About : node.Name;

    // ------------------------------------------------------------ the sections and their pages

    void BuildSections()
    {
        SectionRow.Children.Clear();
        SectionRow.ColumnDefinitions.Clear();
        if (_told is null) return;
        foreach (var section in _told.Layout.Sections)
        {
            var head = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 7, HorizontalAlignment = HorizontalAlignment.Center };
            if (Icons.Glyph(section.Icon) is not null) head.Children.Add(Icons.Sign(section.Icon));
            head.Children.Add(new TextBlock { Classes = { "sectionname" }, Text = Upper(section.Name) });
            var face = new StackPanel { VerticalAlignment = VerticalAlignment.Center, Children = { head } };
            // A line that does not fit - a larger font of SETTINGS, a narrow window - ends in an ellipsis, not at the rim.
            if (section.Line.Length > 0) face.Children.Add(new TextBlock { Classes = { "hint" }, Text = section.Line, TextTrimming = TextTrimming.CharacterEllipsis });
            var tab = new ToggleButton { Classes = { "switch", "section" }, Tag = section.Id, Content = face, HorizontalAlignment = HorizontalAlignment.Stretch, MinHeight = 46 };
            Avalonia.Automation.AutomationProperties.SetAutomationId(tab, "section_" + section.Id);
            ToolTip.SetTip(tab, section.Name + "\n" + section.Line);
            tab.Click += (_, _) => SelectSection(section);
            // The sections share the width of the window equally, with a gap between them.
            if (SectionRow.ColumnDefinitions.Count > 0) SectionRow.ColumnDefinitions.Add(new ColumnDefinition(new GridLength(6)));
            SectionRow.ColumnDefinitions.Add(new ColumnDefinition(GridLength.Star));
            Grid.SetColumn(tab, SectionRow.ColumnDefinitions.Count - 1);
            SectionRow.Children.Add(tab);
        }
        var open = _told.Layout.Sections.FirstOrDefault(section => section.Id == _section?.Id) ?? _told.Layout.Sections.FirstOrDefault();
        if (open is not null) SelectSection(open);
    }

    void SelectSection(Section section)
    {
        _section = section;
        foreach (var child in SectionRow.Children)
            if (child is ToggleButton tab) tab.IsChecked = (string?)tab.Tag == section.Id;
        // The pages of the section: a band of switches as large as the sections over it, sharing
        // the width of the left side equally - a sign and a name, no line under them. A name that
        // does not fit an equal share takes its own width (Views\EvenRow.cs).
        PageRow.Children.Clear();
        PageRow.Break = -1;
        foreach (var page in section.Pages)
        {
            var face = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 7, HorizontalAlignment = HorizontalAlignment.Center };
            if (Icons.Glyph(page.Icon) is not null) face.Children.Add(Icons.Sign(page.Icon));
            face.Children.Add(new TextBlock { Classes = { "sectionname" }, Text = Upper(page.Name), TextTrimming = TextTrimming.CharacterEllipsis });
            var tab = new ToggleButton { Classes = { "switch", "section" }, Tag = page.Id, Content = face, HorizontalAlignment = HorizontalAlignment.Stretch };
            Avalonia.Automation.AutomationProperties.SetAutomationId(tab, $"page_{section.Id}_{page.Id}");
            // What the mode does: the mode is an operation of its own - its description; a choice of a field - the operation's.
            var about = page.ModeField.Length > 0 && page.Node.Field(page.ModeField)?.OptionOf(FieldKinds.Text(page.ModeValue)) is { Tip.Length: > 0 } option
                ? option.Tip : page.Node.About;
            ToolTip.SetTip(tab, about.Length > 0 ? page.Name + "\n" + about : page.Name);
            tab.Click += (_, _) => SelectPage(page);
            PageRow.Children.Add(tab);
        }
        // A section of one page has nothing to switch.
        PageRow.IsVisible = section.Pages.Count > 1;
        var open = section.Pages.FirstOrDefault(page => _lastPage.TryGetValue(section.Id, out var last) && last == page.Id) ?? section.Pages.FirstOrDefault();
        if (open is not null) SelectPage(open);
    }

    void OpenFolder(string folder)
    {
        try
        {
            Directory.CreateDirectory(folder);
            Process.Start(new ProcessStartInfo("explorer.exe") { ArgumentList = { folder }, UseShellExecute = false });
        }
        catch (Exception ex) { SetStatus(Lang.F("Папка не открылась: {0}", ex.Message)); }
    }

    // ------------------------------------------------------------ the terminal

    /// <summary>The text of the terminal since it was last cleared: the copy button gives all of it, up to a limit.</summary>
    readonly StringBuilder _logAll = new();
    const int LogAllLimit = 16_000_000;

    /// <summary>
    /// The panel keeps the last lines of a run and not all of them. It is pages of text one under
    /// another: a text is laid out whole at every line added to it, so new lines go into the last
    /// page while it has room, a full page is never touched again, and the oldest pages leave whole.
    /// </summary>
    const int LogLimit = 5000;
    const int PageLines = 100;
    readonly List<int> _pageLines = new();
    readonly List<int> _pageRuns = new();
    readonly List<(Run Run, Hue Hue)> _logRuns = new();
    int _logShown;
    bool _scrollPosted;
    /// <summary>The colours of the operation that runs: what a line opened is in force on the next.</summary>
    readonly Ansi _ansi = new();

    /// <summary>
    /// Lines into the terminal. A line an operation told is written in the colours its writer gave
    /// it and in no other (Core\Ansi.cs); a line of the window itself - what was run, how it
    /// ended, what the window could not do - in the tone of what it says (Core\LogTones.cs).
    /// </summary>
    void AppendLines(IReadOnlyList<string> lines, bool told = false)
    {
        if (lines.Count == 0) return;
        // The panel follows the new lines while its reader is at the end, and stays where it is
        // when he has gone up to read: asked before the lines are added.
        bool follow = _scrollPosted || LogScroll.Offset.Y + LogScroll.Viewport.Height >= LogScroll.Extent.Height - 40;

        var read = new List<(string Text, Hue Hue)>[lines.Count];
        for (int i = 0; i < lines.Count; i++)
        {
            string plain = lines[i];
            if (told) read[i] = _ansi.Read(lines[i], out plain);
            else
            {
                read[i] = new List<(string, Hue)>();
                // The bounds of a run - its title and its verdict, "===== ..." - stand out in bold.
                if (plain.Length > 0) read[i].Add((plain, new Hue(LogTones.Key(LogTones.Of(plain)), null, plain.StartsWith("===== ", StringComparison.Ordinal), false)));
            }
            _logAll.Append(plain).Append("\r\n");
        }
        // What the window says itself - a run started, how it ended, a command typed, what could not be done - goes to the
        // file of the day too, with its time (as Audion Browsers Portable keeps it). What an operation says is not written
        // again: every operation keeps its own journal in logs\.
        if (!told) KeepLines(lines);
        if (_logAll.Length > LogAllLimit)
        {
            int cut = LogAllLimit / 4;
            while (cut < _logAll.Length && _logAll[cut - 1] != '\n') cut++;
            _logAll.Remove(0, cut);
        }

        int at = Math.Max(0, lines.Count - LogLimit);
        _logShown += lines.Count - at;
        var pages = LogPages.Children;
        while (at < lines.Count)
        {
            if (_pageLines.Count == 0 || _pageLines[^1] >= PageLines)
            {
                pages.Add(new Controls.LogPage { TextWrapping = TextWrapping.Wrap });
                _pageLines.Add(0);
                _pageRuns.Add(0);
            }
            int held = _pageLines[^1], take = Math.Min(PageLines - held, lines.Count - at);
            // Pieces that stand together and are written the same way are one run.
            var added = new List<Inline>();
            var piece = new StringBuilder();
            var kind = new Hue("LogPlain", null, false, false);
            void Close()
            {
                if (piece.Length == 0) return;
                var run = new Run(piece.ToString()) { Foreground = Ansi.Brush(kind) };
                if (kind.Bold) run.FontWeight = FontWeight.Bold;
                if (kind.Underline) run.TextDecorations = TextDecorations.Underline;
                added.Add(run);
                _logRuns.Add((run, kind));
                piece.Clear();
            }
            for (int i = 0; i < take; i++)
            {
                if (held + i > 0) piece.Append('\n');
                foreach (var (text, hue) in read[at + i])
                {
                    if (hue != kind) Close();
                    kind = hue;
                    piece.Append(text);
                }
            }
            Close();
            var page = (Controls.LogPage)pages[^1];
            (page.Inlines ??= new InlineCollection()).AddRange(added);
            _pageLines[^1] = held + take;
            _pageRuns[^1] += added.Count;
            at += take;
        }

        int gone = 0, lost = 0;
        while (gone < _pageLines.Count - 1 && _logShown - _pageLines[gone] >= LogLimit)
        {
            _logShown -= _pageLines[gone];
            lost += _pageRuns[gone++];
        }
        if (gone > 0)
        {
            pages.RemoveRange(0, gone);
            _pageLines.RemoveRange(0, gone);
            _pageRuns.RemoveRange(0, gone);
            _logRuns.RemoveRange(0, lost);
        }

        if (!follow || _scrollPosted) return;
        _scrollPosted = true;
        Dispatcher.UIThread.Post(() =>
        {
            _scrollPosted = false;
            LogScroll.ScrollToEnd();
        }, DispatcherPriority.Background);
    }

    /// <summary>The file of the day of the window: logs\gui-DATE.log.</summary>
    static string DayLog => Path.Combine(Paths.Logs, $"gui-{DateTime.Now:yyyyMMdd}.log");

    static void KeepLines(IReadOnlyList<string> lines)
    {
        var stamp = DateTime.Now.ToString("HH:mm:ss");
        var text = new StringBuilder();
        // A command of several lines is several lines of the file, each with its time.
        foreach (var line in lines.SelectMany(line => line.Split('\n')).Select(line => line.TrimEnd('\r')))
            if (line.Length > 0) text.Append(stamp).Append("  ").Append(line).Append("\r\n");
        if (text.Length == 0) return;
        try
        {
            Directory.CreateDirectory(Paths.Logs);
            File.AppendAllText(DayLog, text.ToString(), new UTF8Encoding(false));
        }
        catch { }
    }

    void ClearLog()
    {
        LogPages.Children.Clear();
        _pageLines.Clear();
        _pageRuns.Clear();
        _logRuns.Clear();
        _logAll.Clear();
        _logShown = 0;
        if (!_runner.Running) _ansi.Reset();
    }

    /// <summary>After a change of the theme the lines already written keep their meaning and take the new colours.</summary>
    void Recolour()
    {
        // A colour a line was given by its writer is the same in every theme.
        foreach (var (run, hue) in _logRuns)
            if (hue.Own is null) run.Foreground = App.Ink(hue.Key);
        if (ActivityRow.IsVisible) ShowActivity(_activity, true);
    }

    async void CopyLog()
    {
        if (_logAll.Length == 0 || Clipboard is not { } clipboard) return;
        try
        {
            await Avalonia.Input.Platform.ClipboardExtensions.SetTextAsync(clipboard, _logAll.ToString());
            Toast.Show(this, Lang.T("Терминал скопирован."));
        }
        catch (Exception ex) { SetStatus(Lang.F("Буфер обмена не принял текст: {0}", ex.Message)); }
    }

    bool _wide;
    /// <summary>The width of the journal beside the cards, kept while the journal stands over the whole window.</summary>
    double _journalWidth = 560;

    /// <summary>The terminal over the whole window - the cards step aside - and back to the width it had.</summary>
    void ToggleWide()
    {
        if (!_wide) _journalWidth = RightZone.Bounds.Width;
        _wide = !_wide;
        LeftZone.IsVisible = !_wide;
        Zones.ColumnDefinitions[0].Width = _wide ? new GridLength(0) : GridLength.Star;
        Zones.ColumnDefinitions[2].Width = _wide ? GridLength.Star : new GridLength(_journalWidth);
        if (WideLogButton.Content is Avalonia.Controls.Shapes.Path sign) sign.Data = Icons.Glyph(_wide ? "minimize-2" : "maximize-2");
    }

    // ------------------------------------------------------------ the end of the window

    void SaveWindow()
    {
        // What the page in sight holds opens so at the next start; the others were kept when they were left.
        Remember(_view);
        if (WindowState == WindowState.Normal)
        {
            _settings.Width = Width;
            _settings.Height = Height;
        }
        // The divider as it was left: the width beside the cards, not the width over the whole window.
        _settings.JournalWidth = Math.Round(_wide ? _journalWidth : RightZone.Bounds.Width);
        _settings.Save();
    }
}
