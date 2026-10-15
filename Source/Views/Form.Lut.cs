using System;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Primitives;
using Avalonia.Layout;
using Avalonia.Platform.Storage;
using AudionMediaTools.Core;

namespace AudionMediaTools.Views;

/// <summary>
/// The LUT of a colour operation as a list of rows, never a drop-down (the plan, 6.2: "список LUT строками с закреплением и
/// «ДОБАВИТЬ LUT»"): the pinned first, then the chosen one, the recent ones and the rest of LUTs\ - the order of the window
/// on NiceGUI (config\gui_lut_cache.json, kept by the form server). A pin before every row; under the list - LUT files or a
/// folder of them copied into LUTs\, and the folder itself opened.
/// </summary>
public sealed partial class Form
{
    Control LutList(Field field)
    {
        var rows = new StackPanel { Spacing = 2 };
        var choices = _values.ChoicesOf(field);
        var current = _values.Get(field);
        foreach (var choice in choices)
        {
            var path = choice.Key;
            bool pinned = _values.IsPinned(field, path);
            var pin = new Button { Classes = { "tool" }, Content = Icons.Sign("pin"), Margin = new Thickness(0, 0, 4, 0) };
            pin.Classes.Set("on", pinned);
            ToolTip.SetTip(pin, Lang.T(pinned ? "Снять закрепление." : "Закрепить: стоит первым в списке."));
            Avalonia.Automation.AutomationProperties.SetAutomationId(pin, "lut_pin_" + Path.GetFileName(path));
            pin.Click += (_, _) => _values.Request("lut_pin", new JsonObject { ["value"] = path, ["pinned"] = !pinned });
            var take = new ToggleButton
            {
                Classes = { "switch" }, Content = new TextBlock { Text = choice.Label.Length > 0 ? choice.Label : Path.GetFileName(path), TextTrimming = Avalonia.Media.TextTrimming.CharacterEllipsis },
                HorizontalAlignment = HorizontalAlignment.Stretch, HorizontalContentAlignment = HorizontalAlignment.Left,
                IsChecked = string.Equals(path, current, StringComparison.OrdinalIgnoreCase),
            };
            ToolTip.SetTip(take, path);
            Avalonia.Automation.AutomationProperties.SetAutomationId(take, "lut_" + Path.GetFileName(path));
            take.Click += (_, _) =>
            {
                _values.Set(field, path);
                take.IsChecked = string.Equals(_values.Get(field), path, StringComparison.OrdinalIgnoreCase);
            };
            var line = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,*"), Children = { pin, take } };
            Grid.SetColumn(take, 1);
            rows.Children.Add(line);
        }
        if (choices.Count == 0)
            rows.Children.Add(new TextBlock { Classes = { "note" }, Text = Lang.T("В папке LUTs нет ни одного LUT: добавьте файлы или папку."), Margin = new Thickness(2, 4) });

        var files = Tool("file", "lut_add_files", "Добавить файлы LUT (.cube, .3dl, .lut): они копируются в папку LUTs программы.");
        var folder = Tool("folder", "lut_add_folder", "Добавить папку с LUT: она копируется в LUTs со своими подпапками.");
        var open = Tool("folder-open", "lut_open", "Открыть папку LUTs.");
        files.Click += async (_, _) => await AddLuts(field, files, folder: false);
        folder.Click += async (_, _) => await AddLuts(field, folder, folder: true);
        open.Click += (_, _) =>
        {
            var luts = Path.Combine(Paths.Root, "LUTs");
            Directory.CreateDirectory(luts);
            try { Process.Start(new ProcessStartInfo("explorer.exe") { ArgumentList = { luts }, UseShellExecute = false }); }
            catch (Exception error) { Say(error.Message, refused: true); }
        };
        var count = new TextBlock { Classes = { "note" }, Text = Lang.F("LUT в списке: {0}", choices.Count), VerticalAlignment = VerticalAlignment.Center, Margin = new Thickness(8, 0, 0, 0) };
        var tools = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 4, Margin = new Thickness(0, 6, 0, 2), Children = { files, folder, open, count } };
        var list = new ScrollViewer { Content = rows, MaxHeight = 260, HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled, VerticalScrollBarVisibility = ScrollBarVisibility.Auto };
        return Labelled(field, new StackPanel { Children = { list, tools } });

        static Button Tool(string sign, string id, string tip)
        {
            var button = new Button { Classes = { "tool" }, Content = Icons.Sign(sign) };
            Avalonia.Automation.AutomationProperties.SetAutomationId(button, id);
            ToolTip.SetTip(button, Lang.T(tip));
            return button;
        }
    }

    async Task AddLuts(Field field, Control from, bool folder)
    {
        if (TopLevel.GetTopLevel(from) is not { } top) return;
        var request = new JsonObject { ["field"] = field.Id };
        if (folder)
        {
            var picked = await top.StorageProvider.OpenFolderPickerAsync(new FolderPickerOpenOptions { AllowMultiple = false, Title = Lang.T("Папка с LUT") });
            if (picked.Count == 0 || picked[0].TryGetLocalPath() is not { } path) return;
            request["folder"] = path;
        }
        else
        {
            var picked = await top.StorageProvider.OpenFilePickerAsync(new FilePickerOpenOptions
            {
                AllowMultiple = true, Title = Lang.T("Файлы LUT"),
                FileTypeFilter = new[] { new FilePickerFileType("LUT") { Patterns = new[] { "*.cube", "*.3dl", "*.lut" } } },
            });
            var paths = picked.Select(file => file.TryGetLocalPath()).OfType<string>().ToList();
            if (paths.Count == 0) return;
            request["files"] = new JsonArray(paths.Select(path => (JsonNode?)JsonValue.Create(path)).ToArray());
        }
        var answer = _values.Request("lut_add", request);
        int added = answer is { } told && told.TryGetProperty("added", out var count) && count.ValueKind == JsonValueKind.Number ? count.GetInt32() : 0;
        Say(added > 0 ? Lang.F("Добавлено LUT: {0}", added) : Lang.T("LUT не добавлены: среди выбранного нет файлов .cube, .3dl или .lut."), refused: added == 0);
    }
}
