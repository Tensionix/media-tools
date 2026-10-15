using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Primitives;
using Avalonia.Input;
using Avalonia.Layout;
using Avalonia.LogicalTree;
using Avalonia.Media;
using Avalonia.Platform.Storage;
using Avalonia.Threading;
using AudionMediaTools.Core;

namespace AudionMediaTools.Views;

/// <summary>
/// The form of a page, drawn as the form server holds it (Core\Values.cs): the blocks it names, the fields in sight in
/// them, the choices with those switched off. The form keeps nothing itself and decides nothing: a control used is a
/// question to the server, and its answer repaints the controls - or, when what is in sight changed, builds the form
/// again. A choice is a row of switches, never a drop-down list.
/// </summary>
public sealed partial class Form
{
    readonly Values _values;
    /// <summary>What a change of what is in sight asks for: the form is built again.</summary>
    readonly Action _rebuild;

    /// <summary>What repaints the controls of a field, by the id of the field: a form built now, gone at the next build.</summary>
    readonly Dictionary<string, List<Action>> _cells = new();

    /// <summary>Kinds of field met while building that the form cannot draw.</summary>
    public HashSet<string> Unknown { get; } = new();

    /// <summary>The kinds this form draws; anything else is said in the journal, not left as an empty place.</summary>
    static readonly HashSet<string> Drawn = new()
    {
        "radio", "select", "checkbox", "checkboxes", "number", "int", "integer", "float", "text", "file", "remux_format",
        "profile_buttons", "profile_select", "lut_select",
    };

    public Form(Values values, Action rebuild)
    {
        _values = values;
        _rebuild = rebuild;
        _values.Reshaped += _reshaped = () => _rebuild();
        _values.Changed += _heard = id =>
        {
            if (!_cells.TryGetValue(id, out var repaint)) return;
            foreach (var action in repaint.ToArray()) action();
        };
    }

    readonly Action<string> _heard;
    readonly Action _reshaped;

    /// <summary>The page is thrown away - the language changed: this form stops hearing its values.</summary>
    public void Detach()
    {
        _values.Changed -= _heard;
        _values.Reshaped -= _reshaped;
    }

    /// <summary>A new build begins: the controls of the last one are forgotten.</summary>
    public void Forget()
    {
        _cells.Clear();
        _build++;
    }

    int _build;

    /// <summary>The rows of a long list below the first screen are built a row at a time; false - the whole form at once.</summary>
    public bool Lazy { get; set; } = true;

    /// <summary>Raised when a row built later has joined the form: its words want centring too.</summary>
    public Action? Grown { get; set; }

    void Watch(Field field, Action repaint)
    {
        if (!_cells.TryGetValue(field.Id, out var list)) _cells[field.Id] = list = new List<Action>();
        list.Add(repaint);
        repaint();
    }

    static string Upper(string text) => text.ToUpper(CultureInfo.CurrentCulture);

    // ------------------------------------------------------------ the form

    /// <summary>The fields in sight, block by block, in the order the server names the blocks: the usual ones, then the rare.</summary>
    public Control Build(Node node)
    {
        var host = new StackPanel { Spacing = 6 };
        // The names of the fields of every block take one width: the controls begin on one line.
        Grid.SetIsSharedSizeScope(host, true);
        bool rareHeaded = false;
        // A block the section puts last (window_layout.yaml, blocks_last) goes to the very end, among the rare fields.
        var last = _values.Page.Section?.BlocksLast ?? new List<string>();
        var blocks = _values.Blocks.Where(block => !last.Contains(block.Name))
            .Concat(_values.Blocks.Where(block => last.Contains(block.Name)).Select(block => block with { Advanced = true }));
        foreach (var block in blocks)
        {
            var fields = block.Fields.Select(node.Field).OfType<Field>().ToList();
            if (fields.Count == 0) continue;
            if (block.Advanced && !rareHeaded)
            {
                // The rare fields stay in sight, under their heading with a rule (the owner, 10.10.2026: "Оставь Дополнительно и разделитель").
                host.Children.Add(Rule(Lang.T("Дополнительно")));
                rareHeaded = true;
            }
            var body = new StackPanel();
            var name = GroupName(block.Name);
            bool headed = false;
            WrapPanel? flags = null;
            var lists = new List<Field>();
            var lines = new List<Field>();
            void Lists()
            {
                if (lists.Count > 0) body.Children.Add(Groups(lists));
                lists.Clear();
            }
            void Lines()
            {
                if (lines.Count == 0) return;
                body.Children.Add(TwoColumns(lines, name.Length > 0 && body.Children.Count == 0, out bool took));
                headed |= took;
                lines.Clear();
            }
            foreach (var field in fields)
            {
                if (TrimKinds.Contains(field.Kind) || field.Kind == "lut_select")
                {
                    // A trim and a list of LUTs take the width of their block (Form.Trim.cs, Form.Lut.cs).
                    flags = null;
                    Lists();
                    Lines();
                    body.Children.Add(field.Kind == "lut_select" ? LutList(field) : TrimControl(field));
                    continue;
                }
                if (!Drawn.Contains(field.Kind)) { Unknown.Add($"{field.Id}: {field.Kind}"); continue; }
                if (field.Kind == "checkboxes") { flags = null; Lines(); lists.Add(field); continue; }
                Lists();
                if (field.IsPresets)
                {
                    flags = null;
                    Lines();
                    body.Children.Add(Presets(field));
                    continue;
                }
                if (field.Kind == "checkbox")
                {
                    Lines();
                    // Flags that follow one another stand in one row.
                    if (flags is null) body.Children.Add(flags = new WrapPanel { Orientation = Orientation.Horizontal });
                    flags.Children.Add(Flag(field));
                    continue;
                }
                flags = null;
                lines.Add(field);
            }
            Lists();
            Lines();
            // The colour block shows where its gamma takes 18% gray (Form.Colour.cs).
            if (block.Name == "color" && !block.Advanced && _values.Gamma is not null) body.Children.Add(GammaPreview());
            if (body.Children.Count == 0) continue;
            if (name.Length > 0 && !headed) body.Children.Insert(0, new TextBlock { Classes = { "grp" }, Text = Upper(name) });
            bool onlyLists = fields.All(field => field.Kind == "checkboxes");
            host.Children.Add(onlyLists && name.Length == 0 ? body : new Border { Classes = { "grp" }, Child = Striped(body, block.Name) });
        }
        return host;
    }

    /// <summary>The heading of the rare fields: a name and a rule across the form.</summary>
    static Control Rule(string name)
    {
        var line = new Border { Height = 1, VerticalAlignment = VerticalAlignment.Center, Margin = new Thickness(10, 1, 0, 0) }.Ink(Border.BackgroundProperty, "SepInk");
        var title = new TextBlock { Classes = { "grp" }, Text = Upper(name), VerticalAlignment = VerticalAlignment.Center, Margin = new Thickness(2, 6, 0, 0) };
        Grid.SetColumn(line, 1);
        return new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,*"), Children = { title, line } };
    }

    /// <summary>
    /// Fields of one line that follow one another, in two columns with a rule between them (the owner of Audion Get Tools,
    /// 10.10.2026: "в две колонки, разделённые палкой"). With <paramref name="heads"/> the first choice of each column
    /// gives its name to the line where the name of the block stood.
    /// </summary>
    Control TwoColumns(List<Field> fields, bool heads, out bool took)
    {
        int half = fields.Count < 2 ? fields.Count : (fields.Count + 1) / 2;
        static bool Heads(Field field) => field.Kind is "radio" or "select" or "remux_format" && field.Name.Length > 0;
        bool second = half < fields.Count;
        took = heads && Heads(fields[0]) && (!second || Heads(fields[half]));
        var lines = new List<Control>();
        for (int i = 0; i < fields.Count; i++)
        {
            var field = fields[i];
            if (!took || (i != 0 && i != half)) { lines.Add(Cell(field)); continue; }
            var head = new TextBlock { Classes = { "grp" }, Text = Upper(field.Name) };
            if (field.Tip.Length > 0) ToolTip.SetTip(head, field.Tip);
            Control row = Choice(field);
            var under = i == 0 ? fields.Skip(1).Take(half - 1) : fields.Skip(half + 1);
            if (under.Any(other => other.Name.Length > 0))
            {
                var line = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,*") };
                line.ColumnDefinitions[0].SharedSizeGroup = "FieldName";
                Grid.SetColumn(row, 1);
                line.Children.Add(row);
                row = line;
            }
            row.Margin = new Thickness(0, 0, 0, 2);
            lines.Add(new StackPanel { Children = { head, row } });
        }
        var left = new StackPanel();
        if (lines.Count < 2)
        {
            foreach (var line in lines) left.Children.Add(line);
            return left;
        }
        var right = new StackPanel();
        for (int i = 0; i < lines.Count; i++) (i < half ? left : right).Children.Add(lines[i]);
        var rule = new Border { Width = 1, Margin = new Thickness(0, 1, 0, 5), HorizontalAlignment = HorizontalAlignment.Center }.Ink(Border.BackgroundProperty, "SepInk");
        var grid = new Grid { ColumnDefinitions = new ColumnDefinitions("*,21,*"), RowDefinitions = new RowDefinitions("Auto,Auto") };
        Grid.SetColumn(rule, 1);
        grid.Children.Add(left);
        grid.Children.Add(rule);
        grid.Children.Add(right);
        bool? wide = null;
        void Fit(double width)
        {
            bool now = width >= TwoColumnsFrom;
            if (wide == now) return;
            wide = now;
            rule.IsVisible = now;
            Grid.SetColumn(right, now ? 2 : 0);
            Grid.SetRow(right, now ? 0 : 1);
            Grid.SetColumnSpan(left, now ? 1 : 3);
            Grid.SetColumnSpan(right, now ? 1 : 3);
        }
        Fit(TwoColumnsFrom);
        grid.SizeChanged += (_, e) => Fit(e.NewSize.Width);
        return grid;
    }

    /// <summary>The width from which a block holds two columns of fields: a name and its row of switches, twice.</summary>
    const double TwoColumnsFrom = 760;

    static void Lay(Grid grid, int columns)
    {
        columns = Math.Max(1, columns);
        int rows = Math.Max(1, (grid.Children.Count + columns - 1) / columns);
        if (grid.ColumnDefinitions.Count != columns)
        {
            grid.ColumnDefinitions.Clear();
            for (int c = 0; c < columns; c++) grid.ColumnDefinitions.Add(new ColumnDefinition(GridLength.Star));
        }
        if (grid.RowDefinitions.Count != rows)
        {
            grid.RowDefinitions.Clear();
            for (int r = 0; r < rows; r++) grid.RowDefinitions.Add(new RowDefinition(GridLength.Auto));
        }
        for (int i = 0; i < grid.Children.Count; i++)
        {
            Grid.SetColumn(grid.Children[i], i % columns);
            Grid.SetRow(grid.Children[i], i / columns);
        }
    }

    /// <summary>What a field is called to the person: its own name, or - for a list the manifest gives none - the name of its block.</summary>
    public static string NameOf(Field field) => field.Name.Length > 0 ? field.Name : GroupName(field.Block);

    /// <summary>The name of a block, as the window on NiceGUI named it (`section_*` of its words); "" - the block needs none.</summary>
    public static string GroupName(string block) => block switch
    {
        "source" => Lang.T("Источник"),
        "workflow" => Lang.T("Режим"),
        "preset" => Lang.T("Профиль"),
        "decode" => Lang.T("Декодирование"),
        "codecs" => Lang.T("Кодеки / цели"),
        "backend" => Lang.T("Бэкенд кодирования"),
        "format" => Lang.T("Формат"),
        "options" => Lang.T("Опции"),
        "audio" => Lang.T("Аудио"),
        "color" => Lang.T("Цвет"),
        "fps" => "FPS",
        "parameters" => Lang.T("Параметры"),
        "encoding" => Lang.T("Кодирование"),
        "package" => Lang.T("Упаковка"),
        "run" => Lang.T("Запуск"),
        "" => "",
        _ => char.ToUpperInvariant(block[0]) + block[1..].Replace('_', ' '),
    };

    Control Cell(Field field)
    {
        Control control = field.Kind switch
        {
            "radio" or "select" or "remux_format" or "lut_select" => Choice(field),
            "number" or "int" or "integer" or "float" => NumberBox(field),
            "file" => FileBox(field),
            _ => TextBox(field),
        };
        var box = control as TextBox ?? control.GetLogicalDescendants().OfType<TextBox>().FirstOrDefault();
        if (Beside.TryGetValue(field.Id, out var beside)) control = WithButton(control, beside.Node, beside.Icon, beside.Words);
        if (Paste.Contains(field.Id) && box is not null) control = WithPaste(control, field, box);
        if (field.Name.Length == 0) return control;
        var line = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,*"), Margin = new Thickness(0, 0, 0, 2) };
        line.ColumnDefinitions[0].SharedSizeGroup = "FieldName";
        var label = new TextBlock { Classes = { "fieldname" }, Text = field.Name, Margin = new Thickness(1, 0, 14, 4), VerticalAlignment = VerticalAlignment.Center, MaxWidth = 210, TextWrapping = TextWrapping.Wrap };
        if (field.Tip.Length > 0) ToolTip.SetTip(label, field.Tip);
        line.Children.Add(label);
        Grid.SetColumn(control, 1);
        line.Children.Add(control);
        return line;
    }

    /// <summary>Operations that stand as a button beside a field, by the id of the field (window_layout.yaml, buttons).</summary>
    public Dictionary<string, (Node Node, string Icon, bool Words)> Beside { get; set; } = new();

    /// <summary>A button beside a field pressed: its operation runs with the values of this page.</summary>
    public Action<Node>? RunBeside { get; set; }

    /// <summary>Fields of a link or a path with PASTE at their right (window_layout.yaml, paste).</summary>
    public HashSet<string> Paste { get; set; } = new();

    /// <summary>
    /// An operation beside a field: its sign and its name, or - <paramref name="words"/> false - its sign alone, the name in the
    /// tooltip (the owner, 15.10.2026: the formats of a link as the sign [i]).
    /// </summary>
    Control WithButton(Control control, Node node, string icon, bool words)
    {
        var sign = Icons.Sign(icon.Length > 0 ? icon : "play");
        var button = words
            ? new Button { Classes = { "small" }, Content = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 6, Children = { sign, new TextBlock { Text = Upper(node.Name) } } } }
            : new Button { Classes = { "tool" }, Content = sign };
        button.Margin = new Thickness(words ? 6 : 4, 0, 0, 4);
        button.VerticalAlignment = VerticalAlignment.Top;
        Avalonia.Automation.AutomationProperties.SetAutomationId(button, "beside_" + node.Id);
        ToolTip.SetTip(button, words || node.About.Length == 0 ? (node.About.Length > 0 ? node.About : node.Name) : node.Name + "\n" + node.About);
        button.Click += (_, _) => RunBeside?.Invoke(node);
        return WithRight(control, button);
    }

    /// <summary>
    /// PASTE at the right of a link or a path: the clipboard into the field, as if typed and taken. Of several lines the
    /// first; the quotes of "Copy as path" of Explorer come off.
    /// </summary>
    Control WithPaste(Control control, Field field, TextBox box)
    {
        var button = new Button
        {
            Classes = { "small" }, Margin = new Thickness(6, 0, 0, 4), VerticalAlignment = VerticalAlignment.Top,
            Content = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 6, Children = { Icons.Sign("clipboard-paste"), new TextBlock { Text = Lang.T("ВСТАВИТЬ") } } },
        };
        Avalonia.Automation.AutomationProperties.SetAutomationId(button, "paste_" + field.Id);
        ToolTip.SetTip(button, Lang.T("Вставить из буфера обмена: ссылку или путь. Из нескольких строк берётся первая."));
        button.Click += async (_, _) =>
        {
            string? text = null;
            try
            {
                if (TopLevel.GetTopLevel(button)?.Clipboard is { } clipboard)
                    text = await Avalonia.Input.Platform.ClipboardExtensions.TryGetTextAsync(clipboard);
            }
            catch (Exception ex) { Say(Lang.F("Буфер обмена не прочитан: {0}", ex.Message), refused: true); return; }
            var value = Pasted(text ?? "");
            if (value.Length == 0) { Say(Lang.T("В буфере обмена нет текста."), refused: true); return; }
            _values.Set(field, value);
            box.Text = _values.Get(field);
        };
        return WithRight(control, button);
    }

    /// <summary>What PASTE puts in: the first line that is not empty, without the quotes around a path.</summary>
    internal static string Pasted(string text)
    {
        var line = text.Replace("\r", "").Split('\n').Select(part => part.Trim()).FirstOrDefault(part => part.Length > 0) ?? "";
        return line.Length >= 2 && line[0] == '"' && line[^1] == '"' ? line[1..^1].Trim() : line;
    }

    /// <summary>A control with a button at its right.</summary>
    static Control WithRight(Control control, Button button)
    {
        var line = new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto"), Children = { control, button } };
        Grid.SetColumn(button, 1);
        return line;
    }

    // ------------------------------------------------------------ controls

    static readonly Geometry Tick = Geometry.Parse("M 1.5,5 L 4,7.5 L 8.5,2.5");

    static Border TickBox() => new()
    {
        Classes = { "tickbox" },
        Child = new Avalonia.Controls.Shapes.Path { Classes = { "tick" }, Data = Tick },
    };

    static Control Faced(string text) => new StackPanel
    {
        Orientation = Orientation.Horizontal, Spacing = 7,
        Children = { TickBox(), new TextBlock { Text = text, VerticalAlignment = VerticalAlignment.Center } },
    };

    ToggleButton Flag(Field field)
    {
        var flag = new ToggleButton { Classes = { "switch" }, Content = Faced(field.Name), Margin = new Thickness(0, 0, 6, 6) };
        Avalonia.Automation.AutomationProperties.SetAutomationId(flag, "field_" + field.Id);
        if (field.Tip.Length > 0) ToolTip.SetTip(flag, field.Tip);
        flag.Click += (_, _) => _values.Set(field, flag.IsChecked == true ? "true" : "false");
        Watch(field, () => flag.IsChecked = _values.IsOn(field));
        return flag;
    }

    /// <summary>The choices of a field in sight: as the server holds them, or - before it said - those of the manifest.</summary>
    IReadOnlyList<(string Key, bool Off, string Name, Option? Option)> ChoicesOf(Field field)
    {
        var held = _values.ChoicesOf(field);
        if (held.Count == 0) return field.Options.Select(option => (option.Key, false, option.Name, (Option?)option)).ToList();
        return held.Select(choice =>
        {
            var option = field.OptionOf(choice.Key);
            var name = option?.Name ?? (choice.Label.Length > 0 ? choice.Label : choice.Key);
            return (choice.Key, choice.Off, name, option);
        }).ToList();
    }

    /// <summary>
    /// A choice of a few: a row of switches, one of them on, which goes into an even grid when it does not fit its line
    /// (EvenWrap). A choice that is switched off stays in its place, greyed.
    /// </summary>
    Control Choice(Field field)
    {
        var row = new EvenWrap();
        var buttons = new List<(ToggleButton Button, string Key)>();
        foreach (var (key, off, name, option) in ChoicesOf(field))
        {
            var button = new ToggleButton
            {
                Classes = { "switch" }, Content = name, Margin = new Thickness(0, 0, 4, 4), IsEnabled = !off,
                HorizontalAlignment = HorizontalAlignment.Stretch, HorizontalContentAlignment = HorizontalAlignment.Center,
            };
            if (option is not null) ChoiceTones.Wear(button, option.ToneInUse);
            Avalonia.Automation.AutomationProperties.SetAutomationId(button, $"field_{field.Id}_{key}");
            var tip = option is { Tip.Length: > 0 } ? option.Tip : field.Tip;
            if (tip.Length > 0) ToolTip.SetTip(button, tip);
            // A greyed switch still says what it is and why it is off.
            if (off) ToolTip.SetShowOnDisabled(button, true);
            button.Click += (_, _) =>
            {
                _values.Set(field, key);
                // A press on the chosen one must not switch it off: one of the row is always on.
                button.IsChecked = _values.Get(field) == key;
            };
            buttons.Add((button, key));
            row.Children.Add(button);
        }
        Watch(field, () =>
        {
            var current = _values.Get(field);
            foreach (var (button, key) in buttons) button.IsChecked = key == current;
        });
        return row;
    }

    /// <summary>
    /// The presets of a field: buttons in the tones of what they make, the one that stands on lit (the former window,
    /// theme.css: .audion-preset-*). The presets of one group stand together under its name - the data names a group on
    /// its first preset only, and a group need not stand together in it ("Video PCM" is lossless, far below the others).
    /// Every group lays its buttons on one grid of columns stretched over the width, so the groups stand under one
    /// another (the owner, 15.10.2026: not stacked to the left - stretched on a grid): six at most in a row, a longer
    /// group in rows of its half.
    /// </summary>
    Control Presets(Field field)
    {
        var column = new StackPanel { Margin = new Thickness(0, 0, 0, 2) };
        var buttons = new List<(ToggleButton Button, string Id)>();
        var groups = new List<(string Id, string Name, List<Preset> Items)>();
        foreach (var preset in field.Presets)
        {
            int at = groups.FindIndex(group => group.Id == preset.Group);
            if (at < 0) { groups.Add((preset.Group, preset.GroupName, new List<Preset>())); at = groups.Count - 1; }
            else if (groups[at].Name.Length == 0 && preset.GroupName.Length > 0) groups[at] = (groups[at].Id, preset.GroupName, groups[at].Items);
            groups[at].Items.Add(preset);
        }
        int widest = groups.Select(group => group.Items.Count).DefaultIfEmpty(1).Max();
        int columns = widest <= 6 ? widest : (widest + 1) / 2;
        bool named = groups.Any(group => group.Name.Length > 0);
        foreach (var (_, name, items) in groups)
        {
            var row = new UniformGrid { Columns = columns };
            if (named)
            {
                var line = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,*") };
                line.ColumnDefinitions[0].SharedSizeGroup = "FieldName";
                // At the top: a group of two rows is named at its first.
                line.Children.Add(new TextBlock { Classes = { "fieldname" }, Text = name, Margin = new Thickness(1, 5, 14, 4), VerticalAlignment = VerticalAlignment.Top });
                Grid.SetColumn(row, 1);
                line.Children.Add(row);
                column.Children.Add(line);
            }
            else column.Children.Add(row);
            foreach (var preset in items) row.Children.Add(PresetButton(field, preset, buttons));
        }
        Watch(field, () =>
        {
            var current = _values.PresetOf(field);
            foreach (var (button, id) in buttons) button.IsChecked = id == current;
        });
        return column;
    }

    ToggleButton PresetButton(Field field, Preset preset, List<(ToggleButton Button, string Id)> buttons)
    {
        var id = preset.Id;
        // A name too long for its cell goes on in a second line, never cut (the rule of the windows: two lines, not an ellipsis).
        var button = new ToggleButton
        {
            Classes = { "switch", "preset" }, Margin = new Thickness(0, 0, 4, 4),
            Content = new TextBlock { Text = Upper(preset.Name), TextWrapping = TextWrapping.Wrap, TextAlignment = TextAlignment.Center },
            HorizontalAlignment = HorizontalAlignment.Stretch, HorizontalContentAlignment = HorizontalAlignment.Center,
            VerticalAlignment = VerticalAlignment.Stretch, VerticalContentAlignment = VerticalAlignment.Center,
            // The switch of the shell is one line high; a preset grows to its second line.
            Height = double.NaN, Padding = new Thickness(8, 3),
        };
        ChoiceTones.Wear(button, preset.Tone);
        Avalonia.Automation.AutomationProperties.SetAutomationId(button, $"preset_{field.Id}_{id}");
        var tip = preset.Tip.Length > 0 ? preset.Name + "\n" + preset.Tip : preset.Name;
        ToolTip.SetTip(button, tip);
        button.Click += (_, _) =>
        {
            _values.Set(field, id);
            button.IsChecked = _values.PresetOf(field) == id;
        };
        buttons.Add((button, id));
        return button;
    }

    /// <summary>Lists of ticks that follow one another, as framed groups: a long one takes a row to itself, short ones share a row by two.</summary>
    Control Groups(List<Field> fields)
    {
        var host = new StackPanel();
        bool Wide(int at) => ChoicesOf(fields[at]).Count > 12 || ChoicesOf(fields[at]).Select(choice => choice.Name.Length).DefaultIfEmpty(0).Max() > 30;
        var rows = new List<(int First, int Count)>();
        for (int i = 0; i < fields.Count;)
        {
            int perRow = Wide(i) || i + 1 >= fields.Count || Wide(i + 1) ? 1 : 2;
            rows.Add((i, perRow));
            i += perRow;
        }
        foreach (var at in rows)
        {
            var row = new Grid();
            for (int c = 0; c < at.Count; c++)
            {
                row.ColumnDefinitions.Add(new ColumnDefinition(GridLength.Star));
                var block = Ticks(fields[at.First + c]);
                Grid.SetColumn(block, c);
                row.Children.Add(block);
            }
            host.Children.Add(row);
        }
        return host;
    }

    /// <summary>
    /// A group of ticks: a framed block with its name, how many are ticked, ALL and NONE, and its ticks as cards in the
    /// tone of what each is; as many columns as hold the longest name whole. A tick switched off is greyed in its place.
    /// </summary>
    Control Ticks(Field field)
    {
        var choices = ChoicesOf(field);
        var column = new StackPanel();
        var title = new TextBlock { Classes = { "blockname" }, Text = NameOf(field), TextWrapping = TextWrapping.Wrap };
        if (field.Tip.Length > 0) ToolTip.SetTip(title, field.Tip);
        var head = new WrapPanel { Orientation = Orientation.Horizontal, ItemSpacing = 8, LineSpacing = 2, Margin = new Thickness(0, 0, 0, 6), MinHeight = 20 };
        head.Children.Add(title);
        column.Children.Add(head);
        var block = new Border { Classes = { "block", "ticks" }, Child = column };
        if (choices.Count == 0)
        {
            column.Children.Add(new TextBlock { Classes = { "note" }, Text = Lang.T("список пуст") });
            return block;
        }
        int longest = choices.Select(choice => choice.Name.Length).Max();
        double usual = App.SizeOf("FontCard", 11.5);
        double need = 20 + longest * 6.4 * usual / 11.5 + 26;
        var grid = new Grid();
        column.Children.Add(grid);
        int columns = 0;
        void Fit(double width)
        {
            if (width <= 0) return;
            int fit = Math.Clamp((int)((width - 16) / need), 1, 4);
            fit = Math.Min(fit, choices.Count);
            if (fit == columns) return;
            columns = fit;
            Lay(grid, columns);
        }
        block.SizeChanged += (_, e) => Fit(e.NewSize.Width);
        var ticks = new List<(ToggleButton Tick, string Key)>();
        foreach (var (key, off, name, option) in choices)
        {
            var look = Tones.Of(option is { ToneInUse.Length: > 0 } ? option.ToneInUse : "plain");
            var box = TickBox();
            box.BorderBrush = look.BoxRim;
            box.Background = look.Box;
            var words = new TextBlock { Text = name, Foreground = look.Ink, VerticalAlignment = VerticalAlignment.Center, Margin = new Thickness(7, 0, 0, 0) };
            Grid.SetColumn(words, 1);
            var face = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,*"), Children = { box, words } };
            var tick = new ToggleButton { Classes = { "ptick" }, Content = face, IsEnabled = !off };
            Avalonia.Automation.AutomationProperties.SetAutomationId(tick, $"field_{field.Id}_{key}");
            var tip = option is { Tip.Length: > 0 } ? option.Tip : field.Tip;
            if (tip.Length > 0) ToolTip.SetTip(tick, tip);
            if (off) ToolTip.SetShowOnDisabled(tick, true);
            ticks.Add((tick, key));
            var card = new Border { Classes = { "ptile" }, Child = tick, BorderBrush = look.Rim, Background = look.Wash };
            void Wear()
            {
                bool on = tick.IsChecked == true, over = card.IsPointerOver;
                card.BorderBrush = on ? look.RimOn : over ? look.RimOver : look.Rim;
                card.Background = on ? look.WashOn : over ? look.WashOver : look.Wash;
                box.BorderBrush = on ? look.FillRim : look.BoxRim;
                box.Background = on ? look.Fill : look.Box;
            }
            tick.IsCheckedChanged += (_, _) => Wear();
            card.PointerEntered += (_, _) => Wear();
            card.PointerExited += (_, _) => Wear();
            grid.Children.Add(card);
        }
        Lay(grid, 1);
        void Take() => _values.Set(field, string.Join(Values.ListSeparator, ticks.Where(item => item.Tick.IsChecked == true).Select(item => item.Key)));
        foreach (var (tick, _) in ticks) tick.Click += (_, _) => Take();
        Watch(field, () =>
        {
            var picked = _values.Picked(field);
            foreach (var (tick, key) in ticks) tick.IsChecked = picked.Contains(key);
        });
        var count = new TextBlock { Classes = { "count" } };
        Watch(field, () => count.Text = Lang.F("{0} из {1}", _values.Picked(field).Count(key => ticks.Any(item => item.Key == key)), ticks.Count));
        head.Children.Add(count);
        if (ticks.Count > 3)
        {
            Button Mini(string word, string tip, bool on)
            {
                var mini = new Button { Classes = { "small" }, Content = Lang.T(word), VerticalAlignment = VerticalAlignment.Center };
                ToolTip.SetTip(mini, Lang.T(tip));
                mini.Click += (_, _) => _values.Set(field, on ? string.Join(Values.ListSeparator, ticks.Where(item => item.Tick.IsEnabled).Select(item => item.Key)) : "");
                return mini;
            }
            head.Children.Add(Mini("ВСЕ", "Отметить все.", true));
            head.Children.Add(Mini("СНЯТЬ", "Снять все отметки.", false));
        }
        return block;
    }

    TextBox TextBox(Field field)
    {
        var box = new TextBox { PlaceholderText = field.Placeholder, Classes = { "masks" }, MinHeight = 24, Padding = new Thickness(8, 2), VerticalContentAlignment = VerticalAlignment.Center, Margin = new Thickness(0, 0, 0, 4) };
        PixelGrid.Field(box);
        Avalonia.Automation.AutomationProperties.SetAutomationId(box, "field_" + field.Id);
        if (field.Tip.Length > 0) ToolTip.SetTip(box, field.Tip);
        // A text goes to the server when it is taken - Enter, or the box let go - not at every letter.
        void Take() { if ((box.Text ?? "") != _values.Get(field)) _values.Set(field, box.Text ?? ""); }
        box.LostFocus += (_, _) => Take();
        box.KeyDown += (_, e) => { if (e.Key == Key.Enter) { Take(); e.Handled = true; } };
        // The box a person types in is not rewritten under the cursor: only a value that came from elsewhere is put in.
        Watch(field, () => { if (!box.IsFocused && (box.Text ?? "") != _values.Get(field)) box.Text = _values.Get(field); });
        return box;
    }

    /// <summary>A file: the path, typed or picked.</summary>
    Control FileBox(Field field)
    {
        var box = TextBox(field);
        var pick = new Button { Classes = { "tool" }, Content = Icons.Sign("file"), Margin = new Thickness(4, 0, 0, 4), VerticalAlignment = VerticalAlignment.Top };
        ToolTip.SetTip(pick, Lang.T("Выбрать файл."));
        Avalonia.Automation.AutomationProperties.SetAutomationId(pick, "pick_" + field.Id);
        pick.Click += async (_, _) =>
        {
            if (TopLevel.GetTopLevel(pick) is not { } top) return;
            var files = await top.StorageProvider.OpenFilePickerAsync(new FilePickerOpenOptions { AllowMultiple = false, Title = field.Name });
            if (files.Count == 0 || files[0].TryGetLocalPath() is not { } path) return;
            _values.Set(field, path);
            box.Text = _values.Get(field);
        };
        var grid = new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto"), Children = { box } };
        Grid.SetColumn(pick, 1);
        grid.Children.Add(pick);
        return grid;
    }

    /// <summary>The body of a block with the stripe of its block at its left: the mark the blocks of the former window had.</summary>
    static Control Striped(Control body, string block)
    {
        var stripe = new Border { Classes = { "stripe", "g-" + (block.Length > 0 ? block : "parameters") } };
        var grid = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,*") };
        grid.Children.Add(stripe);
        Grid.SetColumn(body, 1);
        grid.Children.Add(body);
        return grid;
    }

    /// <summary>A number: typed, or stepped with the arrow keys; kept inside min and max of the manifest.</summary>
    TextBox NumberBox(Field field)
    {
        var box = new TextBox { Width = 120, HorizontalAlignment = HorizontalAlignment.Left, Classes = { "masks" }, Height = 24, MinHeight = 24, Padding = new Thickness(8, 0), VerticalContentAlignment = VerticalAlignment.Center, Margin = new Thickness(0, 0, 0, 4) };
        Avalonia.Automation.AutomationProperties.SetAutomationId(box, "field_" + field.Id);
        if (field.Tip.Length > 0) ToolTip.SetTip(box, field.Tip);
        PixelGrid.Field(box);
        double step = field.Step is { } given && given > 0 ? given : 1;
        string Fit(double number)
        {
            if (field.Min is { } min && number < min) number = min;
            if (field.Max is { } max && number > max) number = max;
            return number.ToString("0.######", CultureInfo.InvariantCulture);
        }
        void Take()
        {
            var typed = (box.Text ?? "").Trim().Replace(',', '.');
            if (double.TryParse(typed, NumberStyles.Float, CultureInfo.InvariantCulture, out var number)) _values.Set(field, Fit(number));
            box.Text = _values.Get(field);
        }
        void Move(int direction)
        {
            if (!double.TryParse(_values.Get(field), NumberStyles.Float, CultureInfo.InvariantCulture, out var number)) number = 0;
            _values.Set(field, Fit(Math.Round(number + direction * step, 6)));
        }
        box.LostFocus += (_, _) => Take();
        box.KeyDown += (_, e) =>
        {
            if (e.Key == Key.Enter) { Take(); e.Handled = true; }
            else if (e.Key == Key.Up) { Take(); Move(1); e.Handled = true; }
            else if (e.Key == Key.Down) { Take(); Move(-1); e.Handled = true; }
        };
        Watch(field, () => { if (!box.IsFocused || (box.Text ?? "") != _values.Get(field)) box.Text = _values.Get(field); });
        return box;
    }
}
