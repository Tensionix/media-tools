using System;
using System.IO;
using System.Runtime.InteropServices;
using System.Threading;
using Avalonia;
using Avalonia.Threading;

namespace AudionMediaTools;

class Program
{
    // Initialization code. Don't use any Avalonia, third-party APIs or any
    // SynchronizationContext-reliant code before AppMain is called: things aren't initialized
    // yet and stuff might break.
    [STAThread]
    public static int Main(string[] args)
    {
        bool selfTest = false;
        for (int i = 0; i < args.Length; i++)
        {
            if (Is(args[i], "--self-test")) selfTest = true;
            // --to "<file>": where --self-test writes what it checked - the build of App\ reads it; a
            // windowed program has no console to write to.
            else if (Is(args[i], "--to") && i + 1 < args.Length) Core.SelfTest.ReportFile = args[++i].Trim().Trim('"');
            // --just-built: the build of App\ adds the check that the executable carries the number of the project.
            else if (Is(args[i], "--just-built")) Core.SelfTest.JustBuilt = true;
#if DEBUG
            // A check of the window without a mouse: -Shot "<file.png>" opens the window, takes
            // its picture section by section and closes (MainWindow.Dev.cs).
            else if (Is(args[i], "-Shot") && i + 1 < args.Length) ShotFolder = args[++i].Trim().Trim('"');
#endif
        }

        if (selfTest) return SelfTest();
#if DEBUG
        // A run a walk starts keeps its journals and reports beside the pictures, not in logs\ and report\ of the program
        // (system_core\core\paths.py: AUDION_LOGS, AUDION_REPORT).
        if (ShotFolder.Length > 0)
        {
            Environment.SetEnvironmentVariable("AUDION_LOGS", System.IO.Path.Combine(ShotFolder, "logs"));
            Environment.SetEnvironmentVariable("AUDION_REPORT", System.IO.Path.Combine(ShotFolder, "report"));
        }
#endif
#if !DEBUG
        // One window per folder of the program: a second start brings the first one forward and
        // ends. A check (a Debug build, --self-test) is not held back by the window at work.
        if (!Core.OneWindow.Claim("AudionMediaTools")) return 0;
#endif

        // A window that fell left its files of a run behind: they go before this one makes its own.
        Core.Paths.DropDeadSessions();

        // Before anything is said: a start that fails speaks the language of the window too.
        try { Core.Lang.Set(Core.Settings.Load().LanguageInUse); } catch { }

        // The taskbar groups the window under its own name.
        try { SetCurrentProcessExplicitAppUserModelID("Audion.MediaTools"); } catch { }

        try
        {
            BuildAvaloniaApp().StartWithClassicDesktopLifetime(args);
            return Environment.ExitCode;
        }
        catch (Exception error)
        {
            // The window never came up: the reason goes into logs\gui-startup-TIME.log and is shown.
            Core.Guard.StartFailed(error);
            return 1;
        }
    }

    static bool Is(string arg, string word) => string.Equals(arg, word, StringComparison.OrdinalIgnoreCase);

    /// <summary>
    /// AUDION_WALK=1: the built window is walked by UI Automation (Source\Tools\release-walk.ps1).
    /// The window and its questions stand off every screen and take no focus - a walk is not for
    /// the person at the screen; everything else is the window as it is.
    /// </summary>
    public static bool Walk { get; } = Environment.GetEnvironmentVariable("AUDION_WALK") == "1";

    /// <summary>
    /// --self-test: the window is put together - its markup, its styles, its fonts - and not
    /// shown; then the parts of it that need no screen are checked (Core\SelfTest.cs). 0 when the
    /// window came up and every check passed, 2 otherwise, the reason on the error stream.
    /// </summary>
    static int SelfTest()
    {
        try
        {
            BuildAvaloniaApp().SetupWithoutStarting();
            _ = new MainWindow();
            return Core.SelfTest.Run() ? 0 : 2;
        }
        catch (Exception error)
        {
            try { Console.Error.WriteLine(error); } catch { }
            return 2;
        }
        finally
        {
            // A check that builds the call of a run makes the folder of its session: it leaves none behind.
            Core.Paths.DropSession();
        }
    }

#if DEBUG
    /// <summary>Where a check wants the pictures of the window; empty - an ordinary start.</summary>
    public static string ShotFolder { get; private set; } = "";

#endif

    [DllImport("shell32.dll", CharSet = CharSet.Unicode)]
    static extern int SetCurrentProcessExplicitAppUserModelID(string appId);

    // Avalonia configuration, don't remove; also used by visual designer.
    public static AppBuilder BuildAvaloniaApp()
        => AppBuilder.Configure<App>()
            .UsePlatformDetect()
            .WithInterFont()
            // JetBrains Mono (SIL OFL, Assets\Fonts\JetBrainsMono) ships inside the program like Inter:
            // the font of the window and of the terminal, with Cyrillic, nothing to fetch or install.
            .ConfigureFonts(fonts => fonts.AddFontCollection(new Avalonia.Media.Fonts.EmbeddedFontCollection(
                new Uri("fonts:JetBrainsMono"), new Uri("avares://AudionMediaTools/Assets/Fonts/JetBrainsMono"))))
            // The menu of the themes and the tooltips are drawn inside the window, not as separate
            // native windows: a picture of the window shows them too.
            .With(new Win32PlatformOptions { OverlayPopups = true })
            .LogToTrace();
}
