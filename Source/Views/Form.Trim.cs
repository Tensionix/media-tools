using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using System.Threading.Tasks;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Primitives;
using Avalonia.Input;
using Avalonia.Interactivity;
using Avalonia.Layout;
using Avalonia.Media;
using AudionMediaTools.Core;

namespace AudionMediaTools.Views;

/// <summary>
/// The trim in the form (the plan, 6.4; the window on NiceGUI after its audit, app.py: render_trim_*): the take as a
/// badge walked by its arrows, with what ffprobe knows of it; the points - rows of IN and OUT for a keep or a cut, each
/// row a file of its own, or the points of a split, taken walking forward - with ▲▼ that step the section the caret
/// stands in and a + after the last; and the row of the player, mpv, which the window speaks to itself (Core\Player.cs).
/// The rules are the server's: a point, a row added, a take changed go to it as clicks (operation_model: point,
/// split_point, add_row, take), and what it holds comes back. The player writes into the last row or point, and only
/// points of the file it shows.
/// </summary>
public sealed partial class Form
{
    /// <summary>The kinds of a trim, drawn here.</summary>
    static readonly HashSet<string> TrimKinds = new() { "trim_file_pick", "file_badge", "trim_rows", "mpv_transport", "player_transport" };

    /// <summary>What a trim tells the person: a line of the status, and a notice when something was refused.</summary>
    public Action<string, bool>? Tell { get; set; }

    /// <summary>The take as the server last told it: path, kind, length, frame, the names of every take.</summary>
    JsonElement? _take;

    /// <summary>The take of the page, asked anew.</summary>
    JsonElement? Take(bool fresh = false)
    {
        if (fresh || _take is null) _take = _values.Ask("take");
        return _take;
    }

    string TakeText(string name) => Take() is { } take && take.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String ? value.GetString() ?? "" : "";

    double? TakeNumber(string name) => Take() is { } take && take.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.Number ? value.GetDouble() : null;

    Control TrimControl(Field field) => field.Kind switch
    {
        "trim_file_pick" or "file_badge" => TakeBar(field),
        "trim_rows" => TrimRows(field),
        _ => PlayerRow(field),
    };

    void Say(string text, bool refused = false) => Tell?.Invoke(text, refused);

    // ------------------------------------------------------------ the take

    /// <summary>
    /// A long name with its middle taken out, so the badge stays one line: the head and the tail tell a take
    /// (M001C008...R00H.mov), a name cut at its end loses the part that differs.
    /// </summary>
    static string ShortName(string name, int limit = 44)
    {
        if (name.Length <= limit) return name;
        int keep = (limit - 1) / 2;
        return name[..keep] + "…" + name[^(limit - keep - 1)..];
    }

    Control TakeBar(Field field)
    {
        var host = new ContentControl();
        void Fill()
        {
            var names = _values.ChoicesOf(field).Select(choice => choice.Key).Where(name => name.Length > 0).ToList();
            var current = _values.Get(field);
            Take(fresh: true);
            if (names.Count == 0)
            {
                host.Content = Labelled(field, new TextBlock { Classes = { "note" }, Text = Lang.T("В Источнике нет ни видео, ни звука"), VerticalAlignment = VerticalAlignment.Center });
                return;
            }
            int index = Math.Max(0, names.IndexOf(current));
            bool audio = TakeText("kind") == "audio";
            var back = new Button { Classes = { "tool" }, Content = Icons.Sign("chevron-left"), IsEnabled = names.Count > 1 };
            var next = new Button { Classes = { "tool" }, Content = Icons.Sign("chevron-right"), IsEnabled = names.Count > 1 };
            var probe = new Button { Classes = { "tool" }, Content = Icons.Sign("scan-search") };
            ToolTip.SetTip(back, Lang.T("Предыдущий файл"));
            ToolTip.SetTip(next, Lang.T("Следующий файл"));
            ToolTip.SetTip(probe, Lang.T("Что ffprobe знает об этом файле"));
            Avalonia.Automation.AutomationProperties.SetAutomationId(back, "trim_file_back");
            Avalonia.Automation.AutomationProperties.SetAutomationId(next, "trim_file_next");
            Avalonia.Automation.AutomationProperties.SetAutomationId(probe, "trim_file_probe");
            back.Click += (_, _) => _values.Set(field, names[(index - 1 + names.Count) % names.Count]);
            next.Click += (_, _) => _values.Set(field, names[(index + 1) % names.Count]);
            probe.Click += async (_, _) => await ShowProbe(probe);
            var name = new TextBlock { Classes = { "takename" }, Text = ShortName(names[index]), VerticalAlignment = VerticalAlignment.Center, TextTrimming = TextTrimming.CharacterEllipsis };
            ToolTip.SetTip(name, names[index]);
            var count = new TextBlock { Classes = { "note" }, Text = $"{index + 1}/{names.Count}", VerticalAlignment = VerticalAlignment.Center, Margin = new Thickness(10, 0, 0, 0) };
            var sign = Icons.Sign(audio ? "audio-lines" : "film");
            sign.Margin = new Thickness(0, 0, 8, 0);
            sign.VerticalAlignment = VerticalAlignment.Center;
            var inside = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,*,Auto"), Children = { sign, name, count } };
            Grid.SetColumn(name, 1);
            Grid.SetColumn(count, 2);
            var badge = new Border { Classes = { "takebadge" }, Child = inside, Margin = new Thickness(4, 0), Padding = new Thickness(10, 3), MinHeight = 28 };
            Avalonia.Automation.AutomationProperties.SetAutomationId(badge, "trim_file_badge");
            var row = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,*,Auto,Auto"), Children = { back, badge, next, probe } };
            Grid.SetColumn(badge, 1);
            Grid.SetColumn(next, 2);
            Grid.SetColumn(probe, 3);
            probe.Margin = new Thickness(4, 0, 0, 0);
            host.Content = Labelled(field, row);
        }
        Watch(field, Fill);
        return host;
    }

    /// <summary>A control with the name of its field before it, in the column of the names of the block.</summary>
    static Control Labelled(Field field, Control control)
    {
        if (field.Name.Length == 0) return control;
        var line = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,*"), Margin = new Thickness(0, 0, 0, 6) };
        line.ColumnDefinitions[0].SharedSizeGroup = "FieldName";
        var label = new TextBlock { Classes = { "fieldname" }, Text = field.Name, Margin = new Thickness(1, 0, 14, 0), VerticalAlignment = VerticalAlignment.Center };
        if (field.Tip.Length > 0) ToolTip.SetTip(label, field.Tip);
        line.Children.Add(label);
        Grid.SetColumn(control, 1);
        line.Children.Add(control);
        return line;
    }

    async Task ShowProbe(Control from)
    {
        if (TopLevel.GetTopLevel(from) is not Window owner) return;
        var probe = _values.Ask("probe");
        if (probe is not { } table || !table.TryGetProperty("ok", out var ok) || ok.ValueKind != JsonValueKind.True)
        {
            var why = probe is { } said && said.TryGetProperty("error", out var error) ? error.GetString() ?? "" : "";
            Say(why.Length > 0 ? why : Lang.T("ffprobe ничего не сказал"), refused: true);
            return;
        }
        var rows = table.GetProperty("rows").EnumerateArray()
            .Select(row => (Name: Lang.Code == "ru" && row.TryGetProperty("field_ru", out var ru) ? ru.GetString() ?? "" : row.GetProperty("field").GetString() ?? "",
                            Value: row.GetProperty("value").GetString() ?? "")).ToList();
        int width = rows.Select(row => row.Name.Length).DefaultIfEmpty(0).Max() + 2;
        var text = string.Join("\n", rows.Select(row => row.Name.PadRight(width) + row.Value));
        await AskDialog.Ok(owner, Lang.T("Сведения о файле") + ": " + (table.GetProperty("file").GetString() ?? ""), text);
    }

    // ------------------------------------------------------------ the points

    static readonly Regex Token = new(@"^\d+(?:[.,]\d+)?$");
    static readonly Regex Canonical = new(@"^\d{2,}:\d{2}:\d{2}[.,]\d{3}$");
    static readonly double[] Units = { 3600, 60, 1, 0.001 };

    /// <summary>A point as seconds: 00:01:28,4 or plain seconds; "" is the start; null - not a point.</summary>
    public static double? Seconds(string text)
    {
        var clean = Regex.Replace(text ?? "", @"\s", "");
        if (clean.Length == 0) return 0;
        var parts = clean.Split(':');
        if (parts.Length > 3 || !parts.All(part => Token.IsMatch(part))) return null;
        return parts.Aggregate(0.0, (total, part) => total * 60 + double.Parse(part.Replace(',', '.'), CultureInfo.InvariantCulture));
    }

    /// <summary>Seconds as a point is written: 00:01:28,400.</summary>
    public static string Timecode(double seconds)
    {
        long ms = (long)Math.Round(Math.Max(0, seconds) * 1000);
        return $"{ms / 3600000:00}:{ms / 60000 % 60:00}:{ms / 1000 % 60:00},{ms % 1000:000}";
    }

    /// <summary>The section the caret stands in: 0 hours, 1 minutes, 2 seconds, 3 the frame; anything but hh:mm:ss,mmm - the seconds.</summary>
    static int Section(string text, int? caret)
    {
        if (caret is not { } at || !Canonical.IsMatch(text)) return 2;
        int first = text.IndexOf(':'), second = text.IndexOf(':', first + 1);
        if (at <= first) return 0;
        if (at <= second) return 1;
        if (at <= second + 3) return 2;
        return 3;
    }

    string Action() => _values.Get("trim_action") is { Length: > 0 } action ? action : "keep";

    List<(string Start, string End)> Rows()
    {
        var rows = new List<(string, string)> { (_values.Get("trim_start"), _values.Get("trim_end")) };
        if (_values.Raw("trim_rows") is { ValueKind: JsonValueKind.Array } extra)
            foreach (var row in extra.EnumerateArray())
                if (row.ValueKind == JsonValueKind.Object)
                    rows.Add((Text(row, "start"), Text(row, "end")));
        return rows;

        static string Text(JsonElement row, string name) => row.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String ? value.GetString() ?? "" : "";
    }

    List<string> Points()
    {
        var points = _values.Raw("trim_points") is { ValueKind: JsonValueKind.Array } list
            ? list.EnumerateArray().Select(point => point.ValueKind == JsonValueKind.String ? point.GetString() ?? "" : point.ToString()).ToList()
            : new List<string>();
        return points.Count > 0 ? points : new List<string> { "" };
    }

    /// <summary>The + is lit once the last row holds what its action needs - a keep one point, a cut both - and until the limit.</summary>
    bool CanAdd()
    {
        if (Action() == "split")
        {
            var points = Points();
            return points[^1].Trim().Length > 0 && points.Count < SplitMaxPoints;
        }
        var rows = Rows();
        var (start, end) = rows[^1];
        bool filled = Action() == "cut" ? start.Trim().Length > 0 && end.Trim().Length > 0 : start.Trim().Length > 0 || end.Trim().Length > 0;
        return filled && rows.Count < TrimMaxVariants;
    }

    /// <summary>The limits of system_core\core\trim_contract.py.</summary>
    const int SplitMaxPoints = 30, TrimMaxVariants = 20;

    /// <summary>How long the piece of a row lasts: a keep with IN alone runs to the end of the file, with OUT alone from its start; a cut needs both.</summary>
    string PieceLength(string start, string end)
    {
        double? first = start.Trim().Length > 0 ? Seconds(start) : null, last = end.Trim().Length > 0 ? Seconds(end) : null;
        if ((start.Trim().Length > 0 && first is null) || (end.Trim().Length > 0 && last is null) || (first is null && last is null)) return "—";
        if (Action() == "cut" && (first is null || last is null)) return "—";
        last ??= TakeNumber("seconds");
        if (last is null) return "—";
        double from = first ?? 0;
        return last > from ? Timecode(last.Value - from) : "—";
    }

    Control TrimRows(Field field)
    {
        var host = new StackPanel { Spacing = 4 };
        string shape = "";
        var boxes = new List<(TextBox Box, Func<string> Held)>();
        var lengths = new List<(TextBlock Label, int Row)>();
        Button? add = null;

        void Sync()
        {
            var action = Action();
            var rows = Rows();
            var points = Points();
            var now = action == "split" ? $"split:{points.Count}" : $"{action}:{rows.Count}";
            if (now != shape)
            {
                shape = now;
                Draw(action, rows, points);
                return;
            }
            // The same rows: the texts a person is not typing in follow the form, the lengths and the + their points.
            foreach (var (box, held) in boxes)
                if (!box.IsFocused && box.Text != held()) box.Text = held();
            foreach (var (label, row) in lengths) label.Text = PieceLength(rows[row].Start, rows[row].End);
            if (add is not null) add.IsEnabled = CanAdd();
        }

        void Draw(string action, List<(string Start, string End)> rows, List<string> points)
        {
            host.Children.Clear();
            boxes.Clear();
            lengths.Clear();
            if (action == "split")
            {
                var line = new WrapPanel { Orientation = Orientation.Horizontal };
                for (int i = 0; i < points.Count; i++)
                {
                    int index = i;
                    var caption = new TextBlock { Classes = { "fieldname" }, Text = Lang.F("Точка {0}", index + 1), VerticalAlignment = VerticalAlignment.Center, Margin = new Thickness(0, 0, 8, 4) };
                    var box = TimeBox($"trim_point_{index}", index == 0 ? "00:01:28,400" : "", Words(field, "point_tooltip"),
                        text => _values.Click("split_point", "trim_rows", new JsonArray(index, text)), () => Points().ElementAtOrDefault(index) ?? "");
                    box.Width = 190;
                    box.Margin = new Thickness(0, 0, 14, 4);
                    boxes.Add((box, () => Points().ElementAtOrDefault(index) ?? ""));
                    line.Children.Add(new StackPanel { Orientation = Orientation.Horizontal, Children = { caption, box } });
                }
                add = AddButton(Words(field, "add_point_tooltip"));
                add.Margin = new Thickness(0, 0, 0, 4);
                line.Children.Add(add);
                host.Children.Add(Labelled(field, line));
                add.IsEnabled = CanAdd();
                return;
            }
            var start = _values.Page.Node.Field("trim_start");
            var end = _values.Page.Node.Field("trim_end");
            bool numbered = rows.Count > 1;
            var table = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,*,12,*,12,Auto,Auto") };
            void Put(Control control, int row, int column)
            {
                Grid.SetRow(control, row);
                Grid.SetColumn(control, column);
                table.Children.Add(control);
            }
            table.RowDefinitions.Add(new RowDefinition(GridLength.Auto));
            Put(Head(start?.Name ?? "IN"), 0, 1);
            Put(Head(end?.Name ?? "OUT"), 0, 3);
            var pieceHead = Head(Lang.T("Кусок"));
            ToolTip.SetTip(pieceHead, Lang.T(action == "cut" ? "Длительность куска, который будет вырезан" : "Длительность куска, который останется"));
            Put(pieceHead, 0, 5);
            for (int i = 0; i < rows.Count; i++)
            {
                int index = i;
                table.RowDefinitions.Add(new RowDefinition(GridLength.Auto));
                if (numbered) Put(new TextBlock { Classes = { "note" }, Text = (index + 1).ToString(CultureInfo.InvariantCulture), VerticalAlignment = VerticalAlignment.Center, Margin = new Thickness(0, 0, 10, 4) }, index + 1, 0);
                foreach (var (which, column, source) in new[] { ("start", 1, start), ("end", 3, end) })
                {
                    string Held() => which == "start" ? Rows().ElementAtOrDefault(index).Start ?? "" : Rows().ElementAtOrDefault(index).End ?? "";
                    var box = TimeBox($"trim_{which}_{index}", index == 0 ? source?.Placeholder ?? "" : "", source?.Tip ?? "",
                        text => _values.Click("point", "trim_rows", new JsonArray(index, which, text)), Held);
                    box.Margin = new Thickness(0, 0, 0, 4);
                    boxes.Add((box, Held));
                    Put(box, index + 1, column);
                }
                var length = new TextBlock { Classes = { "note" }, Text = PieceLength(rows[index].Start, rows[index].End), VerticalAlignment = VerticalAlignment.Center, MinWidth = 96, Margin = new Thickness(0, 0, 10, 4) };
                ToolTip.SetTip(length, Lang.T(action == "cut" ? "Длительность куска, который будет вырезан" : "Длительность куска, который останется"));
                lengths.Add((length, index));
                Put(length, index + 1, 5);
                if (index == rows.Count - 1)
                {
                    add = AddButton(Words(field, "add_tooltip"));
                    add.Margin = new Thickness(0, 0, 0, 4);
                    add.VerticalAlignment = VerticalAlignment.Center;
                    Put(add, index + 1, 6);
                }
            }
            host.Children.Add(Labelled(field, table));
            if (add is not null) add.IsEnabled = CanAdd();
        }

        static TextBlock Head(string text) => new() { Classes = { "note" }, Text = text, Margin = new Thickness(1, 0, 0, 2) };

        foreach (var id in new[] { "trim_action", "trim_start", "trim_end", "trim_rows", "trim_points" }) WatchId(id, Sync);
        Sync();
        return host;
    }

    /// <summary>A text of the field the manifest keeps beside its tooltip (add_tooltip, point_tooltip ...), in the language of the window.</summary>
    static string Words(Field field, string key) => field.Extra(Lang.Code == "ru" ? key + "_ru" : key) is { Length: > 0 } text ? text : field.Extra(key);

    void WatchId(string id, Action repaint)
    {
        if (!_cells.TryGetValue(id, out var list)) _cells[id] = list = new List<Action>();
        list.Add(repaint);
    }

    Button AddButton(string tip)
    {
        var add = new Button { Classes = { "tool" }, Content = Icons.Sign("plus") };
        Avalonia.Automation.AutomationProperties.SetAutomationId(add, "trim_add");
        // The tip stays on a grey +: it says what lights it.
        ToolTip.SetTip(add, tip);
        ToolTip.SetShowOnDisabled(add, true);
        add.Click += async (_, _) =>
        {
            if (!CanAdd()) return;
            _values.Click("add_row", "trim_rows", null);
            // The next piece is looked for from scratch: the loop of the last one is done with.
            if (Player.Shared.Running) await Player.Shared.ClearLoop();
        };
        return add;
    }

    /// <summary>
    /// The field of a point: one line of text, so a timecode is copied and pasted whole, with ▲▼ inside it that step the
    /// section the caret stands in - hours, minutes, seconds, or the last one, which steps by a frame of the file (a
    /// millisecond for sound) and lands on the frame grid. Without the caret in the field the seconds step. Held, a
    /// button repeats, each repeat one unit more than the last. What is typed goes to the form at Enter or when the
    /// field is left; what is stepped, when the button is let go.
    /// </summary>
    TextBox TimeBox(string id, string placeholder, string tip, Action<string> commit, Func<string> held)
    {
        var box = new TextBox { Classes = { "masks" }, Text = held(), PlaceholderText = placeholder, MinHeight = 26, Padding = new Thickness(8, 2), VerticalContentAlignment = VerticalAlignment.Center };
        PixelGrid.Field(box);
        Avalonia.Automation.AutomationProperties.SetAutomationId(box, id);
        if (tip.Length > 0) ToolTip.SetTip(box, tip);
        // Typed digit by digit, the separators put themselves (the owner, 15.10.2026: "при наборе двух чисел - автоматом
        // проставлялось ':'"): hours, ":", minutes, ":", seconds, ",", milliseconds. A field left half typed is completed with
        // zeros - 00:01: is a minute, not a second. Pasted, a timecode or plain seconds stay as they are.
        bool masked = false;
        void Commit()
        {
            var text = (box.Text ?? "").Trim();
            if (masked && MaskDigits(text) is { } digits && digits.Length > 0) text = Masked(digits.PadRight(9, '0'));
            masked = false;
            if (text != (box.Text ?? "").Trim()) box.Text = text;
            if (text != held()) commit(text);
        }
        // On the way down, before the box takes the key itself.
        box.AddHandler(InputElement.KeyDownEvent, (_, e) =>
        {
            if (e.Key == Key.Enter) { Commit(); e.Handled = true; return; }
            // Backspace after a separator the field put takes the digit before it too.
            if (e.Key == Key.Back && box.SelectionStart == box.SelectionEnd && box.CaretIndex == (box.Text ?? "").Length
                && MaskDigits(box.Text ?? "") is { Length: > 0 } typed && (box.Text ?? "").EndsWith(':') | (box.Text ?? "").EndsWith(','))
            {
                box.Text = Masked(typed[..^1], open: false);
                box.CaretIndex = box.Text.Length;
                masked = true;
                e.Handled = true;
            }
        }, RoutingStrategies.Tunnel);
        box.AddHandler(InputElement.TextInputEvent, (_, e) =>
        {
            var input = e.Text ?? "";
            var text = box.Text ?? "";
            bool all = text.Length > 0 && Math.Abs(box.SelectionEnd - box.SelectionStart) == text.Length;
            bool atEnd = box.SelectionStart == box.SelectionEnd && box.CaretIndex == text.Length;
            if (input.Length != 1 || !(all || atEnd)) return;
            var digits = all ? "" : MaskDigits(text);
            if (digits is null) return;
            if (char.IsDigit(input[0]))
            {
                if (digits.Length >= 9) { e.Handled = true; return; }
                box.Text = Masked(digits + input);
            }
            // The separators are the field's own: one typed after them changes nothing.
            else if (input is ":" or "," or "." && digits.Length > 0) { }
            else return;
            box.CaretIndex = (box.Text ?? "").Length;
            masked = true;
            e.Handled = true;
        }, RoutingStrategies.Tunnel);
        box.LostFocus += (_, _) => Commit();

        var spin = new StackPanel { VerticalAlignment = VerticalAlignment.Center, Margin = new Thickness(2, 0, 2, 0) };
        foreach (var (direction, sign) in new[] { (1, "chevron-up"), (-1, "chevron-down") })
        {
            var glyph = Icons.Sign(sign);
            glyph.Width = glyph.Height = 8;
            var button = new RepeatButton
            {
                Classes = { "spin" }, Content = glyph, Focusable = false, Delay = 420, Interval = 110,
                Padding = new Thickness(4, 0), MinHeight = 0, Height = 11, Background = Brushes.Transparent, BorderThickness = new Thickness(0),
            };
            Avalonia.Automation.AutomationProperties.SetAutomationId(button, $"{id}_{(direction > 0 ? "up" : "down")}");
            ToolTip.SetTip(button, Lang.T("Шаг по секции, где стоит курсор: часы, минуты, секунды или кадр (у звука — миллисекунда). Без курсора — секунды. Удержание ускоряет: каждый повтор на единицу больше."));
            int part = 2, units = 1;
            bool focused = false;
            button.AddHandler(InputElement.PointerPressedEvent, (_, _) =>
            {
                focused = box.IsFocused;
                part = Section(box.Text ?? "", focused ? box.CaretIndex : null);
                units = 1;
            }, RoutingStrategies.Tunnel, handledEventsToo: true);
            button.Click += (_, _) =>
            {
                Step(box, direction * units, part, focused);
                units++;
            };
            button.AddHandler(InputElement.PointerReleasedEvent, (_, _) => Commit(), RoutingStrategies.Tunnel, handledEventsToo: true);
            spin.Children.Add(button);
        }
        box.InnerRightContent = spin;
        return box;
    }

    static readonly Regex MaskShape = new(@"^(\d{0,2}|\d{2}:\d{0,2}|\d{2}:\d{2}:\d{0,2}|\d{2}:\d{2}:\d{2}[,.]\d{0,3})$");

    /// <summary>The digits of a field typed through the mask, in order; null - the field holds something else (pasted seconds, a longer hour).</summary>
    static string? MaskDigits(string text) => MaskShape.IsMatch(text) ? new string(text.Where(char.IsDigit).ToArray()) : null;

    /// <summary>
    /// Digits as the mask writes them: 01 → "01:", 0130 → "01:30:", 013005 → "01:30:05,", 013005250 → "01:30:05,250".
    /// <paramref name="open"/> false leaves the separator after a full pair off - what Backspace leaves.
    /// </summary>
    static string Masked(string digits, bool open = true)
    {
        var text = new StringBuilder();
        for (int i = 0; i < digits.Length; i++)
        {
            text.Append(digits[i]);
            if (i == digits.Length - 1 && !open) break;
            if (i is 1 or 3) text.Append(':');
            else if (i == 5) text.Append(',');
        }
        return text.ToString();
    }

    void Step(TextBox box, int count, int part, bool focused)
    {
        if (Seconds(box.Text ?? "") is not { } value) return;
        double frame = TakeNumber("frame") ?? 0;
        double next = part == 3 && frame > 0 ? (Math.Round(value / frame) + count) * frame : value + count * Units[part];
        var text = Timecode(next);
        box.Text = text;
        if (!focused) return;
        // The caret stays in the section it stepped.
        int first = text.IndexOf(':');
        box.CaretIndex = new[] { first, first + 3, first + 6, text.Length }[part];
    }

    // ------------------------------------------------------------ the player

    Control PlayerRow(Field field)
    {
        var row = new UniformGrid { Rows = 1 };
        foreach (var choice in _values.ChoicesOf(field).Where(choice => !choice.Off))
        {
            var option = field.OptionOf(choice.Key);
            var button = new Button
            {
                Classes = { "switch" }, Content = option?.Name ?? choice.Key, Margin = new Thickness(0, 0, 4, 4),
                HorizontalAlignment = HorizontalAlignment.Stretch, HorizontalContentAlignment = HorizontalAlignment.Center,
            };
            Avalonia.Automation.AutomationProperties.SetAutomationId(button, "player_" + choice.Key);
            if (option is { Tip.Length: > 0 }) ToolTip.SetTip(button, option.Tip);
            var action = choice.Key;
            button.Click += async (_, _) => await PlayerDo(action);
            row.Children.Add(button);
        }
        return Labelled(field, row);
    }

    async Task PlayerDo(string action)
    {
        var player = Player.Shared;
        try
        {
            switch (action)
            {
                case "open":
                    if (!player.Installed) { Say(Lang.T(@"Плеер не установлен: install\Install-Portable-mpv.cmd"), refused: true); return; }
                    Take(fresh: true);
                    var path = TakeText("path");
                    if (path.Length == 0) { Say(Lang.T("Сначала выберите файл выше"), refused: true); return; }
                    await player.Open(path);
                    await player.Loaded(TimeSpan.FromSeconds(6));
                    Say(Lang.T("Открыто в плеере") + ": " + Path.GetFileName(path));
                    return;
                case "close":
                    player.Close();
                    Say(Lang.T("Плеер закрыт"));
                    return;
            }
            if (!player.Running) { Say(Lang.T("Плеер не открыт"), refused: true); return; }
            if (!await ShowsChosen(player)) return;
            switch (action)
            {
                case "both":
                {
                    var (a, b) = await player.Loop();
                    WritePoints(a, b);
                    break;
                }
                case "take_a":
                    WriteSplit((await player.Loop()).A);
                    break;
                case "mark_point":
                    // A point of a split is a cut, not a loop: the A and B of the player stay as they are.
                    WriteSplit(await player.Position());
                    break;
                case "mark_in" or "mark_out":
                {
                    // The point lands in the field and the loop of the player moves with it: the piece keeps playing round,
                    // and a wrong point is heard at once.
                    if (await player.Position() is not { } position) { Say(Lang.T("В плеере нет точек A/B: поставьте их клавишей l"), refused: true); return; }
                    await player.SetLoop(action == "mark_in", position);
                    if (action == "mark_in") WritePoints(position, null);
                    else WritePoints(null, position);
                    break;
                }
            }
        }
        catch (Exception error)
        {
            Say(Lang.T("Плеер не запустился") + ": " + error.Message, refused: true);
        }
    }

    /// <summary>The arrows change the take here, not in the player, and its A and B are of what it shows: asked of mpv itself.</summary>
    async Task<bool> ShowsChosen(Player player)
    {
        var shown = await player.Shown();
        if (shown.Length == 0) { Say(Lang.T("В плеере нет точек A/B: поставьте их клавишей l"), refused: true); return false; }
        Take(fresh: true);
        var chosen = TakeText("path");
        static string Full(string path) { try { return Path.GetFullPath(path); } catch { return path; } }
        if (chosen.Length == 0 || !string.Equals(Full(shown), Full(chosen), StringComparison.OrdinalIgnoreCase))
        {
            Say(Lang.F("В плеере открыт другой файл: {0}. Нажмите «Открыть в плеере», чтобы показать выбранный — точки чужого файла сюда не переносятся.", Path.GetFileName(shown)), refused: true);
            return false;
        }
        return true;
    }

    /// <summary>The points the player found, into the last row: said back as "2: IN 00:00:05,000   OUT ...".</summary>
    void WritePoints(double? start, double? end)
    {
        if (start is null && end is null) { Say(Lang.T("В плеере нет точек A/B: поставьте их клавишей l"), refused: true); return; }
        int row = Rows().Count - 1;
        var written = new List<string>();
        var prefix = row > 0 ? $"{row + 1}: " : "";
        if (start is { } a)
        {
            _values.Click("point", "trim_rows", new JsonArray(row, "start", Timecode(a)));
            written.Add($"{prefix}IN {Timecode(a)}");
        }
        if (end is { } b)
        {
            _values.Click("point", "trim_rows", new JsonArray(row, "end", Timecode(b)));
            written.Add($"{prefix}OUT {Timecode(b)}");
        }
        Say(string.Join("   ", written));
    }

    /// <summary>A point of a split from the player - refused, with the reason, when it lies behind: a split is taken walking forward.</summary>
    void WriteSplit(double? position)
    {
        if (position is not { } at) { Say(Lang.T("В плеере нет точек A/B: поставьте их клавишей l"), refused: true); return; }
        var points = Points();
        var earlier = points.Take(points.Count - 1).Select(Seconds).OfType<double>().ToList();
        if (earlier.Count > 0 && at <= earlier.Max())
        {
            Say(Lang.F("Плеер стоит на {0} — это не дальше точки {1}. Сплит берётся только вперёд: прокрутите дальше.", Timecode(at), Timecode(earlier.Max())), refused: true);
            return;
        }
        _values.Click("split_point", "trim_rows", new JsonArray(points.Count - 1, Timecode(at)));
        Say(Lang.F("Точка {0}", points.Count) + ": " + Timecode(at));
    }
}
