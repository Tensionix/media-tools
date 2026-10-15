using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.IO.Pipes;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading;
using System.Threading.Tasks;

namespace AudionMediaTools.Core;

/// <summary>
/// The player of a trim: mpv of the program (Tools\mpv\bin\mpv.exe), its own program, spoken to over a pipe with JSON
/// lines - one command, one answer, nothing in between (system_core\services\mpv_service.py of the window on NiceGUI,
/// whose rules stand: a pipe of Windows is one handle, and the events mpv writes on it are passed over). The window
/// asks it itself, so a button of the player answers at once, without a start of Python.
/// mpv already holds the two numbers a cut needs: its A/B loop - `l` for A, `l` again for B - is the cut, the piece
/// between plays round and round; the window reads `ab-loop-a`, `ab-loop-b` and `time-pos` and asks `path`, so the
/// points are taken only of the file the player shows. One player, kept open between takes - its window stays where
/// it was put, on a second monitor as a rule; it goes with the window, and STOP of a run does not touch it.
/// </summary>
public sealed class Player
{
    public static Player Shared { get; } = new();

    public static string Binary => Path.Combine(Paths.Root, "Tools", "mpv", "bin", "mpv.exe");
    static string ConfigFolder => Path.Combine(Paths.Root, "config", "mpv");

    /// <summary>A pipe name is one for the machine: the id of the window keeps two windows out of each other's player.</summary>
    static readonly string PipeName = $"audion-media-tools-mpv-{Environment.ProcessId}";

    static readonly TimeSpan AnswerTimeout = TimeSpan.FromSeconds(4);
    static readonly TimeSpan StartTimeout = TimeSpan.FromSeconds(12);

    Process? _process;
    NamedPipeClientStream? _pipe;
    string _media = "";
    int _request;
    readonly List<byte> _held = new();
    readonly SemaphoreSlim _gate = new(1, 1);

    public bool Installed => File.Exists(Binary);

    public bool Running
    {
        get
        {
            try { return _process is { HasExited: false } && _pipe is { IsConnected: true }; }
            catch { return false; }
        }
    }

    /// <summary>Shows a file: the player starts if it is not up; a player that is up loads it, and its A and B are cleared -
    /// they are options of the player, not of a file, and the new take would loop the cut of the old one.</summary>
    public async Task Open(string media)
    {
        if (!Running)
        {
            await Start(media);
            return;
        }
        if (string.Equals(Path.GetFullPath(_media), Path.GetFullPath(media), StringComparison.OrdinalIgnoreCase)) return;
        await Send("loadfile", media, "replace");
        await ClearLoop();
        _media = media;
    }

    async Task Start(string media)
    {
        Close();
        var info = new ProcessStartInfo(Binary)
        {
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = false,
            RedirectStandardError = false,
        };
        foreach (var arg in new[]
        {
            $@"--input-ipc-server=\\.\pipe\{PipeName}",
            // Its own folder of settings: an mpv.conf of the machine cannot change what is seen here.
            $"--config-dir={ConfigFolder}",
            "--force-window=yes", "--keep-open=yes", "--pause",
            // Always the frame asked for, never the nearest keyframe.
            "--hr-seek=yes", "--no-resume-playback", "--osd-fractions",
            "--title=Audion Media Tools - ${filename}",
            media,
        }) info.ArgumentList.Add(arg);
        // A walk shows nothing on the screen - of the Debug window, or of the built one (AUDION_WALK=1, Source\Tools\release-walk.ps1):
        // the player of a walk stays minimised and takes no focus.
        bool walked = Program.Walk;
#if DEBUG
        walked |= Program.ShotFolder.Length > 0;
#endif
        if (walked)
        {
            info.ArgumentList.Insert(0, "--window-minimized=yes");
            info.ArgumentList.Insert(0, "--focus-on=never");
        }
        var process = Process.Start(info) ?? throw new InvalidOperationException("mpv was not created");
        ChildJob.HoldApart(process);
        _process = process;
        _media = media;
        var clock = Stopwatch.StartNew();
        Exception? last = null;
        while (clock.Elapsed < StartTimeout)
        {
            if (process.HasExited) throw new InvalidOperationException("mpv ended before it opened its pipe");
            var pipe = new NamedPipeClientStream(".", PipeName, PipeDirection.InOut, PipeOptions.Asynchronous);
            try
            {
                await pipe.ConnectAsync(200);
                _pipe = pipe;
                _held.Clear();
                return;
            }
            catch (Exception error)
            {
                last = error;
                await pipe.DisposeAsync();
                await Task.Delay(50);
            }
        }
        throw new InvalidOperationException("mpv did not open its pipe: " + last?.Message);
    }

    /// <summary>True once mpv knows the length of the file - and can be asked about it.</summary>
    public async Task<bool> Loaded(TimeSpan within)
    {
        var clock = Stopwatch.StartNew();
        while (clock.Elapsed < within)
        {
            if ((await Send("get_property", "duration")) is { ValueKind: JsonValueKind.Number }) return true;
            await Task.Delay(100);
        }
        return false;
    }

    /// <summary>The file the player shows, as mpv says it - a file can also be dropped into its window.</summary>
    public async Task<string> Shown() => (await Send("get_property", "path")) is { ValueKind: JsonValueKind.String } path ? path.GetString() ?? "" : "";

    public async Task<double?> Position() => Seconds(await Send("get_property", "time-pos"));

    /// <summary>The A and B of the player; mpv answers false for a point not set - A alone is the usual state of a search.</summary>
    public async Task<(double? A, double? B)> Loop() => (Seconds(await Send("get_property", "ab-loop-a")), Seconds(await Send("get_property", "ab-loop-b")));

    public Task SetLoop(bool a, double seconds) => Send("set_property", a ? "ab-loop-a" : "ab-loop-b", seconds);

    public async Task ClearLoop()
    {
        await Send("set_property", "ab-loop-a", "no");
        await Send("set_property", "ab-loop-b", "no");
    }

    static double? Seconds(JsonElement? value) => value is { ValueKind: JsonValueKind.Number } number ? number.GetDouble() : null;

    /// <summary>Leaves nothing running: a player that outlives its window is a leak.</summary>
    public void Close()
    {
        var (process, pipe) = (_process, _pipe);
        (_process, _pipe, _media) = (null, null, "");
        if (pipe is not null)
        {
            try
            {
                pipe.Write(Encoding.UTF8.GetBytes("{\"command\":[\"quit\"]}\n"));
                pipe.Flush();
            }
            catch { }
            try { pipe.Dispose(); } catch { }
        }
        if (process is null) return;
        try
        {
            if (!process.WaitForExit(4000)) process.Kill();
        }
        catch { }
        process.Dispose();
    }

    /// <summary>One command, one answer. Null when the player is not there, refused, or did not answer in time - all three
    /// leave the fields alone.</summary>
    async Task<JsonElement?> Send(params object[] command)
    {
        await _gate.WaitAsync();
        try
        {
            if (!Running || _pipe is not { } pipe) return null;
            int id = ++_request;
            var words = new JsonArray();
            foreach (var word in command)
                words.Add(word switch { double number => JsonValue.Create(number), string text => JsonValue.Create(text), _ => JsonValue.Create(word.ToString()) });
            var line = new JsonObject { ["command"] = words, ["request_id"] = id }.ToJsonString() + "\n";
            using var limit = new CancellationTokenSource(AnswerTimeout);
            try
            {
                await pipe.WriteAsync(Encoding.UTF8.GetBytes(line), limit.Token);
                await pipe.FlushAsync(limit.Token);
                var buffer = new byte[4096];
                while (true)
                {
                    // Lines already in hand first: an answer may have come with an event before it.
                    while (_held.IndexOf((byte)'\n') is var end and >= 0)
                    {
                        var text = Encoding.UTF8.GetString(_held.GetRange(0, end).ToArray());
                        _held.RemoveRange(0, end + 1);
                        if (text.Trim().Length == 0) continue;
                        JsonElement message;
                        try { message = JsonDocument.Parse(text).RootElement.Clone(); }
                        catch (JsonException) { continue; }
                        // Events come on the same pipe and are passed over: all the window needs is asked, never pushed.
                        if (!message.TryGetProperty("request_id", out var answered) || answered.ValueKind != JsonValueKind.Number || answered.GetInt32() != id) continue;
                        if (!message.TryGetProperty("error", out var error) || error.GetString() != "success") return null;
                        return message.TryGetProperty("data", out var data) ? data.Clone() : null;
                    }
                    int read = await pipe.ReadAsync(buffer, limit.Token);
                    if (read == 0) return null;
                    _held.AddRange(buffer.AsSpan(0, read).ToArray());
                }
            }
            catch (OperationCanceledException) { return null; }
            catch (IOException) { return null; }
            catch (ObjectDisposedException) { return null; }
        }
        finally { _gate.Release(); }
    }
}
