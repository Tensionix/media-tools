using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace AudionMediaTools.Core;

/// <summary>
/// The commands typed under the journal: the history (the newest first, two hundred at most), the pinned ones, the
/// last, the shell and the folder they run in. The file is the one the window on NiceGUI kept, in its shape -
/// config\terminal_commands.json - so a history goes on from one window to the other. The folder of the program is
/// kept relative: the program is portable, and a copy elsewhere must not run in the folder of the first.
/// </summary>
public sealed class CommandHistory
{
    public const int Limit = 200;

    readonly string _file;

    public List<string> History { get; private set; } = new();
    public List<string> Pinned { get; private set; } = new();
    public string Last { get; set; } = "";
    /// <summary>"pwsh" - PowerShell of the program; "cmd".</summary>
    public string Shell { get; set; } = "pwsh";
    /// <summary>Where a command runs: a full path.</summary>
    public string Folder { get; set; } = Paths.Root;

    public CommandHistory(string file)
    {
        _file = file;
        try
        {
            if (!File.Exists(file)) return;
            var raw = JsonNode.Parse(File.ReadAllText(file, Encoding.UTF8)) as JsonObject;
            if (raw is null) return;
            History = Clean(raw["history"]);
            Pinned = Clean(raw["pinned"]);
            Last = raw["last"]?.GetValue<string>()?.Trim() ?? "";
            Shell = raw["shell"]?.GetValue<string>()?.Trim().ToLowerInvariant() == "cmd" ? "cmd" : "pwsh";
            var folder = raw["cwd"]?.GetValue<string>()?.Trim() ?? "";
            if (folder.Length > 0)
            {
                var full = Path.IsPathRooted(folder) ? folder : Path.Combine(Paths.Root, folder);
                if (Directory.Exists(full)) Folder = Path.GetFullPath(full);
            }
        }
        catch { }
    }

    static List<string> Clean(JsonNode? items)
    {
        var told = new List<string>();
        if (items is not JsonArray array) return told;
        foreach (var item in array)
        {
            var text = item?.GetValue<string>()?.Trim() ?? "";
            if (text.Length > 0 && !told.Contains(text)) told.Add(text);
        }
        return told.Take(Limit).ToList();
    }

    /// <summary>A command run: it goes to the top of the history.</summary>
    public void Ran(string command)
    {
        command = command.Trim();
        if (command.Length == 0) return;
        History.Remove(command);
        History.Insert(0, command);
        if (History.Count > Limit) History.RemoveRange(Limit, History.Count - Limit);
        Last = command;
        Save();
    }

    public bool IsPinned(string command) => Pinned.Contains(command);

    public void TogglePin(string command)
    {
        if (!Pinned.Remove(command)) Pinned.Insert(0, command);
        Save();
    }

    /// <summary>A command leaves the history; a pinned one stays pinned until it is unpinned.</summary>
    public void Forget(string command)
    {
        History.Remove(command);
        Pinned.Remove(command);
        Save();
    }

    /// <summary>What the list shows: the pinned ones first, then the rest of the history.</summary>
    public IEnumerable<string> Listed() => Pinned.Concat(History.Where(command => !Pinned.Contains(command)));

    /// <summary>Written whole or not at all; a history that could not be saved is nobody's loss.</summary>
    public void Save()
    {
        var root = Paths.Root.TrimEnd('\\') + "\\";
        var folder = Folder.StartsWith(root, StringComparison.OrdinalIgnoreCase) ? Folder[root.Length..] : Folder;
        if (string.Equals(Folder.TrimEnd('\\'), Paths.Root.TrimEnd('\\'), StringComparison.OrdinalIgnoreCase)) folder = ".";
        var payload = new JsonObject
        {
            ["history"] = new JsonArray(History.Select(item => (JsonNode?)JsonValue.Create(item)).ToArray()),
            ["pinned"] = new JsonArray(Pinned.Select(item => (JsonNode?)JsonValue.Create(item)).ToArray()),
            ["last"] = Last,
            ["shell"] = Shell,
            ["cwd"] = folder,
        };
        var temp = _file + ".tmp";
        try
        {
            Directory.CreateDirectory(Path.GetDirectoryName(_file)!);
            File.WriteAllText(temp, payload.ToJsonString(new JsonSerializerOptions
            {
                WriteIndented = true, Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
            }), new UTF8Encoding(false));
            File.Move(temp, _file, overwrite: true);
        }
        catch
        {
            try { if (File.Exists(temp)) File.Delete(temp); } catch { }
        }
    }
}
