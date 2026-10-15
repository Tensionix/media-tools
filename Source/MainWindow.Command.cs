using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Primitives;
using Avalonia.Input;
using Avalonia.Layout;
using Avalonia.Platform.Storage;
using AudionMediaTools.Core;
using AudionMediaTools.Views;

namespace AudionMediaTools;

/// <summary>
/// The command line under the journal: a command of PowerShell - the program's own, App\AudionPs.exe, never one of the
/// machine - or of CMD, run in a folder of one's choice. Its lines come into the journal in the colours their writer
/// gave them, its run is a run like any other - STOP ends it - and its end is told by its exit code. A command sent
/// while an operation goes waits its turn and runs after it; the arrows of the box go through the commands run before.
/// The history is the one the window on NiceGUI kept (config\terminal_commands.json): two hundred commands, the pinned
/// first. What Audion Get Tools does with its command line (MainWindow.Terminal.cs there) is taken from there: the queue,
/// the arrows, the search in the list.
/// </summary>
public partial class MainWindow
{
    CommandHistory _commands = null!;
    /// <summary>The commands sent while an operation went: each runs when its turn comes.</summary>
    readonly Queue<(string Shell, string Command, string Folder)> _queued = new();
    /// <summary>Where the arrows of the box stand in the commands run before; -1 - at what is being typed.</summary>
    int _recall = -1;
    string _typed = "";

    /// <summary>What a PowerShell command is started with: UTF-8 both ways, and its colours as ANSI, so the journal shows them.</summary>
    const string PsStart = "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8\n$OutputEncoding = [System.Text.Encoding]::UTF8\n"
                           + "try { $PSStyle.OutputRendering = 'ANSI' } catch {}\n";

    void WireCommand()
    {
        // A check keeps a history of its own, beside its build: the commands it tries are not the owner's.
        var file = Paths.Released ? Path.Combine(Paths.Config, "terminal_commands.json") : Path.Combine(Paths.Runtime, "terminal_commands.json");
        _commands = new CommandHistory(file);
        CommandBox.Text = _commands.Last;
        PixelGrid.Field(CommandBox);
        MarkShell();
        ShowCommandFolder();
        ShellPs.Click += (_, _) => SetShell("pwsh");
        ShellCmd.Click += (_, _) => SetShell("cmd");
        CommandRunButton.Click += (_, _) => SendCommand();
        CommandBox.KeyDown += (_, e) =>
        {
            if (e.Key == Key.Enter) { SendCommand(); e.Handled = true; }
            else if (e.Key == Key.Up) { Recall(1); e.Handled = true; }
            else if (e.Key == Key.Down) { Recall(-1); e.Handled = true; }
        };
        WireCommandHistory();
        CommandFolderButton.Click += async (_, _) =>
        {
            var folders = await StorageProvider.OpenFolderPickerAsync(new FolderPickerOpenOptions { AllowMultiple = false, Title = Lang.T("Папка, в которой идёт команда") });
            if (folders.Count == 0 || folders[0].TryGetLocalPath() is not { } folder) return;
            _commands.Folder = Paths.Full(folder);
            _commands.Save();
            ShowCommandFolder();
        };
        CommandFileButton.Click += async (_, _) =>
        {
            var files = await StorageProvider.OpenFilePickerAsync(new FilePickerOpenOptions { AllowMultiple = false, Title = Lang.T("Файл для команды") });
            if (files.Count == 0 || files[0].TryGetLocalPath() is not { } path) return;
            // The path goes in quoted, after what was typed - an argument of the command.
            var typed = (CommandBox.Text ?? "").TrimEnd();
            Put((typed.Length > 0 ? typed + " " : "") + "\"" + path + "\"");
        };
    }

    void SetShell(string shell)
    {
        _commands.Shell = shell;
        _commands.Save();
        MarkShell();
    }

    void MarkShell()
    {
        ShellPs.IsChecked = _commands.Shell != "cmd";
        ShellCmd.IsChecked = _commands.Shell == "cmd";
        CommandBox.PlaceholderText = Lang.T(_commands.Shell == "cmd" ? "команда CMD" : "команда PowerShell");
    }

    /// <summary>The folder a command runs in, named in the tooltip of its button: from the program, when it is inside it.</summary>
    void ShowCommandFolder() =>
        ToolTip.SetTip(CommandFolderButton, Lang.F("Папка, в которой идёт команда: {0}. Нажать - выбрать другую.", Paths.Short(_commands.Folder)));

    /// <summary>A command goes into the box, the caret after it.</summary>
    void Put(string command)
    {
        CommandBox.Text = command;
        CommandBox.CaretIndex = command.Length;
        CommandBox.Focus();
    }

    /// <summary>The arrows of the box: up - the command before, down - the one after, and back to what was being typed.</summary>
    void Recall(int step)
    {
        var known = _commands.History;
        if (known.Count == 0) return;
        if (_recall < 0) _typed = CommandBox.Text ?? "";
        _recall = Math.Clamp(_recall + step, -1, known.Count - 1);
        Put(_recall < 0 ? _typed : known[_recall]);
    }

    /// <summary>Enter, or the button: the command is remembered and runs - at once, or after the operation that goes now.</summary>
    void SendCommand()
    {
        var text = (CommandBox.Text ?? "").Trim();
        if (text.Length == 0) { SetStatus("Введите команду."); return; }
        if (_commands.Shell != "cmd" && Paths.Ps.Length == 0)
        {
            AppendLines(new[] { "[GUI] " + Lang.T("нет PowerShell программы: App\\AudionPs.exe не собран (install\\Build-App.cmd)") });
            SetStatus("PowerShell программы не собран: причина в терминале.");
            return;
        }
        _commands.Ran(text);
        _commands.Last = "";
        _commands.Save();
        _recall = -1;
        CommandBox.Text = "";
        var folder = Directory.Exists(_commands.Folder) ? _commands.Folder : Paths.Root;
        if (_runner.Running || _asking || _clearing)
        {
            _queued.Enqueue((_commands.Shell, text, folder));
            SetStatus(Lang.F("Команда в очереди ({0}): пойдёт, когда закончится операция.", _queued.Count));
            return;
        }
        StartCommand(_commands.Shell, text, folder);
    }

    void StartCommand(string shell, string text, string folder)
    {
        bool cmd = shell == "cmd";
        var launch = cmd
            // A cmd started after the code page is UTF-8 writes in it: one that changed it on its own line went on in the
            // OEM code page (measured: "привет" came as "�ਢ��").
            ? new Launch { Exe = "cmd.exe", Line = "/d /s /c \"chcp 65001 >nul & cmd /d /s /c \"" + text + "\"\"", Folder = folder }
            : new Launch { Exe = Paths.Ps, Args = { "-NoLogo", "-NoProfile", "-Command", PsStart + text }, Folder = folder };
        Open(Lang.T("КОМАНДА") + (cmd ? " · CMD" : " · PS"), $"[GUI] {Paths.Short(folder)}{(cmd ? ">" : " PS>")} {text}", bare: true);
        Go(launch);
    }

    /// <summary>A run has ended: the next command of the queue runs.</summary>
    void NextCommand()
    {
        if (_queued.Count == 0 || _runner.Running) return;
        var (shell, text, folder) = _queued.Dequeue();
        StartCommand(shell, text, folder);
    }

    /// <summary>The window closes: the command left in the box is kept for the next start; what waited its turn does not run.</summary>
    void KeepCommand()
    {
        _queued.Clear();
        if (_commands is null) return;
        _commands.Last = (CommandBox.Text ?? "").Trim();
        _commands.Save();
    }

    /// <summary>
    /// The list of the history: a search over it, the pinned commands first, then the others - the command itself takes
    /// it into the box, the pin pins it or lets it go, the cross takes it out of the list.
    /// </summary>
    void WireCommandHistory()
    {
        var search = new TextBox { Classes = { "masks" }, PlaceholderText = Lang.T("поиск по списку"), MinHeight = 24, Height = 24, Padding = new Thickness(8, 0), VerticalContentAlignment = VerticalAlignment.Center };
        PixelGrid.Field(search);
        Avalonia.Automation.AutomationProperties.SetAutomationId(search, "find_commands");
        var rows = new StackPanel { Spacing = 2 };
        var panel = new StackPanel
        {
            Children = { search, new ScrollViewer { Content = rows, MaxHeight = 380, Margin = new Thickness(0, 6, 0, 0), HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled } },
        };
        var flyout = new Flyout { Content = panel, Placement = PlacementMode.TopEdgeAlignedRight };
        CommandHistoryButton.Flyout = flyout;

        void Fill()
        {
            rows.Children.Clear();
            var words = (search.Text ?? "").Split(' ', StringSplitOptions.RemoveEmptyEntries);
            foreach (var command in _commands.Listed())
            {
                if (words.Any(word => !command.Contains(word, StringComparison.OrdinalIgnoreCase))) continue;
                bool pinned = _commands.IsPinned(command);
                var pin = new Button { Classes = { "tool" }, Content = Icons.Sign("pin"), Margin = new Thickness(0, 0, 4, 0) };
                pin.Classes.Set("on", pinned);
                ToolTip.SetTip(pin, Lang.T(pinned ? "Снять закрепление." : "Закрепить: стоит первым в списке."));
                Avalonia.Automation.AutomationProperties.SetAutomationId(pin, "pin_command_" + command);
                pin.Click += (_, _) => { _commands.TogglePin(command); Fill(); };
                var take = new Button
                {
                    Classes = { "crumb" }, Content = new TextBlock { Text = command, TextTrimming = Avalonia.Media.TextTrimming.CharacterEllipsis },
                    HorizontalAlignment = HorizontalAlignment.Stretch, HorizontalContentAlignment = HorizontalAlignment.Left,
                };
                ToolTip.SetTip(take, command);
                Avalonia.Automation.AutomationProperties.SetAutomationId(take, "command_" + command);
                take.Click += (_, _) => { flyout.Hide(); Put(command); };
                var forget = new Button { Classes = { "tool" }, Content = Icons.Sign("x"), Margin = new Thickness(4, 0, 0, 0) };
                ToolTip.SetTip(forget, Lang.T("Убрать из истории."));
                Avalonia.Automation.AutomationProperties.SetAutomationId(forget, "forget_command_" + command);
                forget.Click += (_, _) => { _commands.Forget(command); Fill(); };
                var line = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,*,Auto"), Children = { pin } };
                Grid.SetColumn(take, 1);
                Grid.SetColumn(forget, 2);
                line.Children.Add(take);
                line.Children.Add(forget);
                rows.Children.Add(line);
            }
            if (rows.Children.Count == 0)
                rows.Children.Add(new TextBlock { Classes = { "note" }, Text = Lang.T(_commands.Listed().Any() ? "ничего не найдено" : "История команд пуста."), Margin = new Thickness(4, 2) });
        }
        search.TextChanged += (_, _) => Fill();
        flyout.Opening += (_, _) =>
        {
            panel.Width = Math.Max((CommandBox.Parent as Control)?.Bounds.Width - 18 ?? 420, 420);
            Fill();
        };
        flyout.Opened += (_, _) => search.Focus();
    }
}
