using System;
using System.Collections.Concurrent;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading;

namespace AudionMediaTools.Core;

/// <summary>
/// The forms of the window are held by the engine (media_cli.cmd form - system_core\core\form_pages.py): the rules
/// of a form - what a preset writes, which choice is off, what a click pulls along - are one copy, in Python, held
/// to the record of the former window. The window keeps that process open while it is open and asks it a JSON line
/// at a time; the answer is the form as it stands. A question is answered in a few milliseconds: the window waits
/// for it in place, as a control waits for its own handler. A process that fell or went silent is started anew and
/// the pages are opened again with what they held (Values).
/// </summary>
public sealed class FormServer : IDisposable
{
    Process? _process;
    StreamWriter? _input;
    BlockingCollection<string>? _lines;
    int _asked;

    /// <summary>Why the last question was not answered; "" when it was.</summary>
    public string Trouble { get; private set; } = "";

    /// <summary>The process was started anew: every page asks to be opened again.</summary>
    public event Action? Restarted;

    /// <summary>How long a question may wait: a form with a folder of LUTs or of takes to read answers in a moment, never in seconds.</summary>
    public int Patience { get; set; } = 15_000;

    bool Alive => _process is { HasExited: false } && _input is not null && _lines is not null;

    bool Start()
    {
        Stop();
        if (!Door.Ready) { Trouble = Door.Trouble; return false; }
        var info = new ProcessStartInfo(Paths.Python)
        {
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardInput = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            StandardInputEncoding = new UTF8Encoding(false),
            StandardOutputEncoding = Encoding.UTF8,
            StandardErrorEncoding = Encoding.UTF8,
            WorkingDirectory = Paths.Root,
        };
        foreach (var word in new[] { "-X", "utf8", "-u", Paths.DoorScript, "--language", Lang.Code == "ru" ? "ru" : "en", "form" }) info.ArgumentList.Add(word);
        try
        {
            var process = Process.Start(info) ?? throw new InvalidOperationException("the process was not created");
            ChildJob.HoldApart(process);
            var lines = new BlockingCollection<string>();
            var output = process.StandardOutput;
            new Thread(() =>
            {
                try
                {
                    for (var line = output.ReadLine(); line is not null; line = output.ReadLine()) lines.Add(line);
                }
                catch { }
                lines.CompleteAdding();
            }) { IsBackground = true, Name = "form server out" }.Start();
            // What the engine prints while a form is drawn goes to the errors: read away, so the process never waits on a full pipe.
            var errors = process.StandardError;
            new Thread(() =>
            {
                try { while (errors.ReadLine() is not null) { } } catch { }
            }) { IsBackground = true, Name = "form server err" }.Start();
            _process = process;
            _input = process.StandardInput;
            _input.AutoFlush = true;
            _lines = lines;
            return true;
        }
        catch (Exception ex)
        {
            Trouble = ex.Message;
            return false;
        }
    }

    /// <summary>
    /// A question and its answer: the JSON object the server gave, or null - and <see cref="Trouble"/> says why. A
    /// process that is not there is started first; one that does not answer is ended, and the next question starts it.
    /// </summary>
    public JsonElement? Ask(JsonObject request)
    {
        bool fresh = false;
        if (!Alive)
        {
            if (!Start()) return null;
            fresh = _asked > 0;
        }
        if (fresh) Restarted?.Invoke();
        int id = ++_asked;
        request["id"] = id;
        request["language"] = Lang.Code == "ru" ? "ru" : "en";
        try
        {
            _input!.WriteLine(request.ToJsonString());
            var until = Environment.TickCount64 + Patience;
            while (true)
            {
                var left = (int)Math.Max(0, until - Environment.TickCount64);
                if (!_lines!.TryTake(out var line, left))
                {
                    Trouble = _lines.IsCompleted ? "the form server ended" : Lang.F("сервер формы не ответил за {0} с", Patience / 1000);
                    Stop();
                    return null;
                }
                if (!line.TrimStart().StartsWith('{')) continue;
                using var answer = JsonDocument.Parse(line);
                var root = answer.RootElement;
                if (!root.TryGetProperty("id", out var said) || said.ValueKind != JsonValueKind.Number || said.GetInt32() != id) continue;
                if (root.TryGetProperty("ok", out var ok) && ok.ValueKind == JsonValueKind.False)
                {
                    Trouble = root.TryGetProperty("error", out var error) ? error.GetString() ?? "" : "the form server refused";
                    return null;
                }
                Trouble = "";
                return root.Clone();
            }
        }
        catch (Exception ex)
        {
            Trouble = ex.Message;
            Stop();
            return null;
        }
    }

    void Stop()
    {
        var process = _process;
        _process = null;
        _input = null;
        _lines = null;
        if (process is null) return;
        try { process.StandardInput.Close(); } catch { }
        try { if (!process.WaitForExit(500)) process.Kill(entireProcessTree: true); } catch { }
        process.Dispose();
    }

    public void Dispose() => Stop();
}
