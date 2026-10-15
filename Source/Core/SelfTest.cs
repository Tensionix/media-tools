using System;
using System.Collections.Generic;
using System.Linq;
using System.Runtime.InteropServices;
using System.Text.Json;
using System.Threading.Tasks;

namespace AudionMediaTools.Core;

/// <summary>
/// What --self-test checks once the window has been put together: the parts of the window that
/// need no screen - what the door says of the program, the values of the fields, the line a run
/// is written with, the colours of the terminal. Each check answers with a line; one that failed
/// is named on the error stream, and the program ends with 2.
/// </summary>
public static class SelfTest
{
    /// <summary>
    /// Lines in the colours their writer gave them: a colour closed on its own line, the kinds of
    /// a colour and of a look, a colour left open and closed on the next line, a line nobody
    /// coloured. A picture of the terminal is taken with the same lines (MainWindow.Run.cs).
    /// </summary>
    public static readonly string[] ColouredLines =
    {
        "\u001b[33m[WARN] yellow by its writer\u001b[0m and plain after it",
        "\u001b[96mVivaldi\u001b[0m [\u001b[36mVivaldi.Vivaldi\u001b[0m] \u001b[1mbold\u001b[0m \u001b[2mdim\u001b[0m \u001b[4munderlined\u001b[0m \u001b[38;5;208mthe 208th\u001b[0m \u001b[38;2;120;200;80m24-bit\u001b[0m",
        "\u001b[31mred \u001b[32mgreen \u001b[34mblue \u001b[35mmagenta \u001b[90mgrey \u001b[97mwhite \u001b[93myellow",
        "still yellow: the colour was left open\u001b[0m",
        "[OK] a line nobody coloured",
    };

    sealed class Report
    {
        public readonly List<string> Passed = new();
        public readonly List<string> Failed = new();

        public void Check(string name, bool good, string found = "")
        {
            if (good) Passed.Add(name);
            else Failed.Add(found.Length > 0 ? name + ": " + found : name);
        }
    }

    /// <summary>A file the report is written to as well, "ok" and "FAIL" lines alike; "" - the two streams alone.</summary>
    public static string ReportFile { get; set; } = "";

    /// <summary>True when the build of App\ asks: the window was built a moment ago, and its number is checked too.</summary>
    public static bool JustBuilt { get; set; }

    /// <summary>Runs every check. What passed is written to the output, what failed to the error stream; true when nothing failed.</summary>
    public static bool Run()
    {
        var report = new Report();
        foreach (var check in new (string Name, Action<Report> Body)[]
        {
            ("version", Number),
            ("describe", Describe),
            ("forms", Forms),
            ("run line", RunLine),
            ("source", SourceOfARun),
            ("colours", Colours),
            ("error stream", ErrorStream),
            ("code pages", CodePages),
        })
        {
            try { check.Body(report); }
            catch (Exception error) { report.Failed.Add($"{check.Name}: {error.GetType().Name}: {error.Message}"); }
        }
        foreach (var line in report.Passed) try { Console.Out.WriteLine("ok   " + line); } catch { }
        foreach (var line in report.Failed) try { Console.Error.WriteLine("FAIL " + line); } catch { }
        if (ReportFile.Length > 0)
            try
            {
                System.IO.File.WriteAllLines(ReportFile, report.Passed.Select(line => "ok   " + line).Concat(report.Failed.Select(line => "FAIL " + line)), new System.Text.UTF8Encoding(false));
            }
            catch { }
        return report.Failed.Count == 0;
    }

    // ------------------------------------------------------------ what the console command tells of the program

    /// <summary>What the door said, for the checks that read the program itself.</summary>
    static Described? _told;

    static void Describe(Report report)
    {
        // Off the window's thread: nothing turns its queue here, and an answer awaited on it would never come.
        var (told, trouble) = Task.Run(Door.Describe).GetAwaiter().GetResult();
        report.Check("describe: the console command answered and the answer reads", told is not null, trouble);
        if (told is null) return;
        _told = told;
        var pages = told.Layout.Sections.SelectMany(section => section.Pages).ToList();
        var nameless = pages.Where(page => page.Name.Length == 0 || page.Node.Id.Length == 0).Select(page => page.Key).ToList();
        report.Check($"describe: {told.Layout.Sections.Count} sections, {pages.Count} pages, each with its operation and its name",
            told.Layout.Sections.Count > 0 && pages.Count > 0 && nameless.Count == 0, string.Join(", ", nameless));
        var keys = pages.Select(page => page.Key).ToList();
        report.Check("describe: no two pages share a key", keys.Distinct().Count() == keys.Count, string.Join(", ", keys.GroupBy(key => key).Where(group => group.Count() > 1).Select(group => group.Key)));
        var service = told.Layout.Service.Where(id => told.Find(id) is null).ToList();
        report.Check("describe: every operation of SERVICE is described", service.Count == 0, string.Join(", ", service));
    }

    /// <summary>Kinds of field the form does not draw yet, named so the check passes over them; none is left.</summary>
    static readonly HashSet<string> Later = new();

    /// <summary>
    /// Every page is opened by the form server as the window opens it, and every field in sight of it has a control: a
    /// field of a kind the window cannot draw would be an empty place, and is named here.
    /// </summary>
    static void Forms(Report report)
    {
        if (_told is not { } told) { report.Check("forms: the console command described the program", false, "no description"); return; }
        using var server = new FormServer();
        var unknown = new List<string>();
        var silent = new List<string>();
        int opened = 0, fields = 0;
        foreach (var page in told.Layout.Sections.SelectMany(section => section.Pages))
        {
            var values = new Values(server, page);
            if (!values.Open(null)) { silent.Add($"{page.Key}: {server.Trouble}"); continue; }
            opened++;
            var form = new Views.Form(values, () => { });
            form.Build(page.Node);
            fields += values.Blocks.Sum(block => block.Fields.Count);
            unknown.AddRange(form.Unknown.Where(kind => !Later.Contains(kind.Split(": ").Last())).Select(kind => page.Key + " " + kind));
        }
        report.Check($"forms: the form server opened {opened} pages", silent.Count == 0 && opened > 0, string.Join("; ", silent));
        report.Check($"forms: every one of their {fields} fields in sight has its control", unknown.Count == 0, string.Join(", ", unknown));
    }

    // ------------------------------------------------------------ a run names the folders

    static void SourceOfARun(Report report)
    {
        const string folder = @"D:\Chosen Source", target = @"E:\Results";
        var launch = Door.Run("storage_run", folder, target);
        bool named = launch.Args.SkipWhile(word => word != "--source").Skip(1).FirstOrDefault() == folder
                     && launch.Args.SkipWhile(word => word != "--target").Skip(1).FirstOrDefault() == target;
        report.Check("source: a run names the Source and the Target to the console command", named, string.Join(" ", launch.Args.Skip(5).Take(10)));
    }

    // ------------------------------------------------------------ the number of the program

    static void Number(Report report)
    {
        if (!JustBuilt) return;
        var built = typeof(SelfTest).Assembly.GetName().Version;
        var wanted = Paths.Version;
        var carried = built is null ? "" : $"{built.Major}.{built.Minor}.{built.Build}";
        report.Check("version: the executable carries the number of config\\version.json", wanted is not null && carried == wanted.Split('-', '+')[0], $"the executable {carried}, the file {wanted ?? "(unreadable)"}");
    }

    // ------------------------------------------------------------ what the door says of the program


    // ------------------------------------------------------------ the values of the fields

    // ------------------------------------------------------------ the line a run is written with

    [DllImport("shell32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    static extern IntPtr CommandLineToArgvW(string line, out int count);

    [DllImport("kernel32.dll")]
    static extern IntPtr LocalFree(IntPtr memory);

    /// <summary>A line as Windows hands it to a program, word by word.</summary>
    static List<string> Words(string line)
    {
        var words = new List<string>();
        var raw = CommandLineToArgvW(line, out int count);
        if (raw == IntPtr.Zero) return words;
        try
        {
            for (int i = 0; i < count; i++) words.Add(Marshal.PtrToStringUni(Marshal.ReadIntPtr(raw, i * IntPtr.Size)) ?? "");
        }
        finally { LocalFree(raw); }
        return words;
    }

    static void RunLine(Report report)
    {
        // What a value may hold that a line has rules for: a space, a quote, a backslash at its end.
        var values = new Dictionary<string, string>
        {
            ["plain"] = "word",
            ["space"] = "two words",
            ["quote"] = "say \"yes\" twice",
            ["slash_end"] = @"C:\Some Folder\",
            ["slash_quote"] = "a\\\"b",
            ["slashes_end"] = @"name\\",
            ["empty"] = "",
            ["signs"] = "a&b|c<d>e^f",
        };
        var target = @"D:\Down Loads\";
        var source = @"E:\Some Source\";
        var line = Door.RunLine("storage_run", source, target, values);
        var expected = new List<string> { Paths.DoorName, "run", "--operation", "storage_run", "--source", Paths.Short(source), "--target", Paths.Short(target) };
        foreach (var (name, value) in values) { expected.Add("--set"); expected.Add(name + "=" + value); }
        var read = Words(line);
        var wrong = Enumerable.Range(0, Math.Max(expected.Count, read.Count))
            .Where(i => i >= expected.Count || i >= read.Count || expected[i] != read[i])
            .Select(i => $"word {i}: wanted <{(i < expected.Count ? expected[i] : "")}> read <{(i < read.Count ? read[i] : "")}>").ToList();
        report.Check("run line: read back word for word - a space, a quote, a backslash at the end of a value", wrong.Count == 0, string.Join("; ", wrong) + " | " + line);
    }

    // ------------------------------------------------------------ the lines of the error stream

    static void ErrorStream(Report report)
    {
        var read = new[] { "a plain word", "[ERR] named an error by its writer", "", "[ERROR] another word of the writer" }.Select(Runner.ErrorLine).ToArray();
        var expected = new[] { "[ERR] a plain word", "[ERR] named an error by its writer", "[ERR] ", "[ERR] [ERROR] another word of the writer" };
        report.Check("error stream: a line is marked [ERR] once", read.SequenceEqual(expected), string.Join(" ~ ", read));
    }

    // ------------------------------------------------------------ the code page of a command

    /// <summary>
    /// Lines a command may write, each in the code pages it is written in by programs of Windows: what comes into the
    /// journal must be the line itself. Russian of cp1251 and cp866 - lower-case, capitals, a word of two letters, a
    /// path; the signs of a table of cp866; the accents of cp1252; UTF-8 with its mark; UTF-16 with and without its mark.
    /// </summary>
    static void CodePages(Report report)
    {
        static string[] Lines(byte[] bytes)
        {
            var lines = new List<string>();
            OutputText.Read(new System.IO.MemoryStream(bytes), lines.Add);
            return lines.ToArray();
        }
        System.Text.Encoding.RegisterProvider(System.Text.CodePagesEncodingProvider.Instance);
        var pages = new (int Page, string[] Lines)[]
        {
            (65001, new[] { "Привет, мир — «кавычки» и ёлка", "ОШИБКА: ФАЙЛ НЕ НАЙДЕН", "Größe über Straße", "да" }),
            (1251, new[] { "Привет, мир — «кавычки» и ёлка", "ОШИБКА: ФАЙЛ НЕ НАЙДЕН", "Обработано файлов: 12 из 40", "да",
                           @"Файл C:\Музыка\track.mp3 не найден", "окно", "Traceback: ошибка в строке 5" }),
            (866, new[] { "Привет, мир и ёлка", "ОШИБКА: ФАЙЛ НЕ НАЙДЕН", "╔══════════╗", "║ Имя файла ║", "╚══════════╝",
                          "Том в устройстве C имеет метку System", "да" }),
            (1252, new[] { "Größe über Straße", "Paramètres avancés", "Configuración del sistema", "Ångström", "naïve café" }),
        };
        foreach (var (page, lines) in pages)
        {
            var encoding = System.Text.Encoding.GetEncoding(page);
            var bytes = encoding.GetBytes(string.Join("\r\n", lines) + "\r\n");
            var read = Lines(bytes);
            var wrong = lines.Zip(read).Where(pair => pair.First != pair.Second).Select(pair => pair.Second).ToList();
            report.Check($"code pages: {lines.Length} lines of {encoding.WebName} come as they were written",
                read.Length == lines.Length && wrong.Count == 0, read.Length != lines.Length ? $"{read.Length} lines" : string.Join(" ~ ", wrong));
        }
        var bom = new byte[] { 0xEF, 0xBB, 0xBF }.Concat(System.Text.Encoding.UTF8.GetBytes("Первая строка\nвторая")).ToArray();
        var withBom = Lines(bom);
        report.Check("code pages: the mark of UTF-8 is not in the first line", withBom.SequenceEqual(new[] { "Первая строка", "вторая" }), string.Join(" ~ ", withBom));
        // UTF-8 with one byte nobody could read stays UTF-8: one sign for the byte, the letters around it as they were.
        var broken = Lines(System.Text.Encoding.UTF8.GetBytes("Привет, мир").Concat(new byte[] { 0xFF }).Concat(System.Text.Encoding.UTF8.GetBytes(" и ёлка")).ToArray());
        report.Check("code pages: UTF-8 with a wrong byte stays UTF-8", broken.SequenceEqual(new[] { "Привет, мир� и ёлка" }), string.Join(" ~ ", broken));
        foreach (var (name, wide) in new[] { ("UTF-16 with its mark", System.Text.Encoding.Unicode.GetPreamble()), ("UTF-16 without a mark", Array.Empty<byte>()) })
        {
            var bytes = wide.Concat(System.Text.Encoding.Unicode.GetBytes("Node,Name\r\nAUDION,Привет\r\n")).ToArray();
            var read = Lines(bytes);
            report.Check($"code pages: {name} (wmic)", read.SequenceEqual(new[] { "Node,Name", "AUDION,Привет" }), string.Join(" ~ ", read));
        }
        // As a reader of .NET cuts: at CR, at LF, at CR LF; an empty line stays; the last line comes without its end too.
        var cut = Lines(System.Text.Encoding.ASCII.GetBytes("a\r\nb\rc\n\nd"));
        report.Check("code pages: lines are cut at CR, LF and CR LF", cut.SequenceEqual(new[] { "a", "b", "c", "", "d" }), string.Join(" ~ ", cut));
    }

    // ------------------------------------------------------------ the colours of the terminal

    static void Colours(Report report)
    {
        static string Piece((string Text, Hue Hue) part) =>
            part.Text + "|" + (part.Hue.Own is { } own ? $"#{own.R:x2}{own.G:x2}{own.B:x2}" + (own.A < 255 ? "/" + own.A : "") : part.Hue.Key)
            + (part.Hue.Bold ? "|bold" : "") + (part.Hue.Underline ? "|underline" : "") + (part.Hue.Faint ? "|faint" : "");

        // The eight colours of every console in the tones of the theme; the 256 and the 24 bits as they are asked.
        var expected = new[]
        {
            new[] { "[WARN] yellow by its writer|LogWarn", " and plain after it|LogPlain" },
            new[]
            {
                "Vivaldi|LogHead", " [|LogPlain", "Vivaldi.Vivaldi|LogHead", "] |LogPlain", "bold|LogPlain|bold", " |LogPlain", "dim|LogMuted", " |LogPlain",
                "underlined|LogPlain|underline", " |LogPlain", "the 208th|#ff8700", " |LogPlain", "24-bit|#87d75f",
            },
            new[] { "red |LogBad", "green |LogGood", "blue |LiveSpeed", "magenta |#d946ef", "grey |LogMuted", "white |LogPlain", "yellow|LogWarn" },
            new[] { "still yellow: the colour was left open|LogWarn" },
            new[] { "[OK] a line nobody coloured|LogPlain" },
        };
        var plain = new[]
        {
            "[WARN] yellow by its writer and plain after it",
            "Vivaldi [Vivaldi.Vivaldi] bold dim underlined the 208th 24-bit",
            "red green blue magenta grey white yellow",
            "still yellow: the colour was left open",
            "[OK] a line nobody coloured",
        };
        var ansi = new Ansi();
        for (int i = 0; i < ColouredLines.Length; i++)
        {
            var parts = ansi.Read(ColouredLines[i], out var text).Select(Piece).ToArray();
            report.Check($"colours: line {i + 1} is read into its pieces", parts.SequenceEqual(expected[i]), string.Join(" ~ ", parts));
            report.Check($"colours: line {i + 1} as text alone", text == plain[i], text);
        }
        // A colour left open is over with the run: the next run starts plain.
        ansi.Read("\u001b[31mopen", out _);
        ansi.Reset();
        var after = ansi.Read("next run", out _).Select(Piece).ToArray();
        report.Check("colours: a colour left open does not outlive Reset", after.SequenceEqual(new[] { "next run|LogPlain" }), string.Join(" ~ ", after));
        // A dimmed colour is the same colour, fainter: one of the theme and one of its writer's own.
        var dim = new Ansi().Read("\u001b[2;31mfaint\u001b[0m \u001b[2;38;5;208mfainter\u001b[0m", out _).Select(Piece).ToArray();
        report.Check("colours: a dimmed colour keeps its tone", dim.SequenceEqual(new[] { "faint|LogBad|faint", " |LogPlain", "fainter|#ff8700/184" }), string.Join(" ~ ", dim));
    }
}
