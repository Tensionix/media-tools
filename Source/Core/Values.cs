using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace AudionMediaTools.Core;

/// <summary>A choice of a field as the form stands now: whether it is switched off, and its name when the engine made the choice (a LUT, a take).</summary>
public sealed record Choice(string Key, bool Off, string Label, JsonElement Value);

/// <summary>A block of the form: its name, whether it holds the rare fields, the fields in sight in it.</summary>
public sealed record Block(string Name, bool Advanced, IReadOnlyList<string> Fields);

/// <summary>
/// The values of one page, held by the form server (Core\FormServer.cs): the window keeps the last answer and reads
/// it; a control used is a question, and the answer replaces what was held. Every page has a form of its own (the
/// owner, 15.10.2026: "формы раздельные"); the encoder and the decoder are one for every page - the server sets them
/// on all. A value is read as text: a flag as "true" or "false", a number without a tail of zeros, a group of ticks
/// as its values joined by a line break.
/// </summary>
public sealed class Values
{
    readonly FormServer _server;
    public Page Page { get; }

    Dictionary<string, JsonElement> _values = new();
    HashSet<string> _shown = new();
    Dictionary<string, List<Choice>> _choices = new();
    Dictionary<string, string> _presets = new();
    Dictionary<string, HashSet<string>> _pinned = new();

    /// <summary>The blocks of the form with the fields in sight, in the order the former window drew them.</summary>
    public List<Block> Blocks { get; private set; } = new();
    /// <summary>Why the form may not be run now; "" when it may.</summary>
    public string Refusal { get; private set; } = "";
    /// <summary>Of a colour operation: where its gamma before the LUT takes 18% gray (operation_model.gamma_preview); null - none.</summary>
    public JsonElement? Gamma { get; private set; }
    /// <summary>The values a person would type: the line of the journal, `--set name=value`.</summary>
    public Dictionary<string, string> Typed { get; private set; } = new();

    /// <summary>A value changed: the id of its field.</summary>
    public event Action<string>? Changed;
    /// <summary>What is in sight changed - a field came or went, a choice was switched off or on: the form is built again.</summary>
    public event Action? Reshaped;
    /// <summary>The server did not answer: why, in the words of the window.</summary>
    public event Action<string>? Failed;

    public const char ListSeparator = '\n';

    public Values(FormServer server, Page page)
    {
        _server = server;
        Page = page;
    }

    /// <summary>The page is opened in the server with what it held before (`remembered`); false - the server did not answer.</summary>
    public bool Open(JsonObject? remembered)
    {
        var request = new JsonObject { ["do"] = "open", ["page"] = Page.Key, ["operation"] = Page.Node.Id };
        if (Page.ModeField.Length > 0)
            request["mode"] = new JsonObject { ["field"] = Page.ModeField, ["value"] = JsonNode.Parse(Page.ModeValue.GetRawText()) };
        if (remembered is { Count: > 0 }) request["values"] = remembered.DeepClone();
        return Answer(_server.Ask(request), initial: true);
    }

    /// <summary>The form as the server holds it now - after it was started anew, or another page set a field of the machine.</summary>
    public bool Refresh() => Answer(_server.Ask(new JsonObject { ["do"] = "state", ["page"] = Page.Key }));

    /// <summary>Back to the form as the page opened; the machine stays as it is.</summary>
    public bool Reset() => Answer(_server.Ask(new JsonObject { ["do"] = "reset", ["page"] = Page.Key }));

    bool Answer(JsonElement? answer, bool initial = false)
    {
        if (answer is not { } state)
        {
            Failed?.Invoke(_server.Trouble);
            return false;
        }
        var values = new Dictionary<string, JsonElement>();
        if (state.TryGetProperty("values", out var given) && given.ValueKind == JsonValueKind.Object)
            foreach (var item in given.EnumerateObject()) values[item.Name] = item.Value.Clone();
        var shown = new HashSet<string>();
        if (state.TryGetProperty("shown", out var seen) && seen.ValueKind == JsonValueKind.Array)
            foreach (var item in seen.EnumerateArray()) shown.Add(item.GetString() ?? "");
        var blocks = new List<Block>();
        if (state.TryGetProperty("blocks", out var told) && told.ValueKind == JsonValueKind.Array)
            foreach (var block in told.EnumerateArray())
                blocks.Add(new Block(block.GetProperty("name").GetString() ?? "", block.GetProperty("advanced").GetBoolean(),
                    block.GetProperty("fields").EnumerateArray().Select(item => item.GetString() ?? "").ToList()));
        var choices = new Dictionary<string, List<Choice>>();
        if (state.TryGetProperty("choices", out var offered) && offered.ValueKind == JsonValueKind.Object)
            foreach (var field in offered.EnumerateObject())
                choices[field.Name] = field.Value.EnumerateArray().Select(item =>
                {
                    var parts = item.EnumerateArray().ToList();
                    var value = parts[0].Clone();
                    return new Choice(FieldKinds.Text(value), parts.Count > 1 && parts[1].ValueKind == JsonValueKind.True,
                        parts.Count > 2 ? parts[2].GetString() ?? "" : "", value);
                }).ToList();
        var presets = new Dictionary<string, string>();
        if (state.TryGetProperty("presets", out var marked) && marked.ValueKind == JsonValueKind.Object)
            foreach (var item in marked.EnumerateObject()) presets[item.Name] = item.Value.GetString() ?? "";
        var typed = new Dictionary<string, string>();
        if (state.TryGetProperty("set", out var set) && set.ValueKind == JsonValueKind.Object)
            foreach (var item in set.EnumerateObject()) typed[item.Name] = item.Value.GetString() ?? "";
        var pinned = new Dictionary<string, HashSet<string>>();
        if (state.TryGetProperty("pinned", out var pins) && pins.ValueKind == JsonValueKind.Object)
            foreach (var item in pins.EnumerateObject())
                pinned[item.Name] = item.Value.EnumerateArray().Select(path => path.GetString() ?? "").ToHashSet(StringComparer.OrdinalIgnoreCase);
        bool pinsMoved = !SamePins(pinned, _pinned);
        _pinned = pinned;

        // What changed: a field that came or went, a choice switched off or on, another block - the form is another form.
        bool reshaped = initial || !shown.SetEquals(_shown) || !SameBlocks(blocks, Blocks) || !SameChoices(choices, _choices) || pinsMoved;
        var moved = values.Where(item => !_values.TryGetValue(item.Key, out var was) || was.GetRawText() != item.Value.GetRawText())
            .Select(item => item.Key).ToList();
        bool presetMoved = !presets.OrderBy(item => item.Key).SequenceEqual(_presets.OrderBy(item => item.Key));

        (_values, _shown, Blocks, _choices, _presets) = (values, shown, blocks, choices, presets);
        Refusal = state.TryGetProperty("refusal", out var refusal) ? refusal.GetString() ?? "" : "";
        Gamma = state.TryGetProperty("gamma", out var gamma) && gamma.ValueKind == JsonValueKind.Object ? gamma.Clone() : null;
        Typed = typed;
        if (initial) return true;
        if (reshaped) { Reshaped?.Invoke(); return true; }
        foreach (var id in moved) Changed?.Invoke(id);
        if (presetMoved) foreach (var id in presets.Keys) Changed?.Invoke(id);
        return true;
    }

    static bool SameBlocks(List<Block> one, List<Block> two) =>
        one.Count == two.Count && one.Zip(two).All(pair => pair.First.Name == pair.Second.Name && pair.First.Advanced == pair.Second.Advanced
                                                          && pair.First.Fields.SequenceEqual(pair.Second.Fields));

    static bool SamePins(Dictionary<string, HashSet<string>> one, Dictionary<string, HashSet<string>> two) =>
        one.Count == two.Count && one.All(item => two.TryGetValue(item.Key, out var other) && item.Value.SetEquals(other));

    static bool SameChoices(Dictionary<string, List<Choice>> one, Dictionary<string, List<Choice>> two) =>
        one.Count == two.Count && one.All(item => two.TryGetValue(item.Key, out var other)
            && item.Value.Select(choice => (choice.Key, choice.Off, choice.Label)).SequenceEqual(other.Select(choice => (choice.Key, choice.Off, choice.Label))));

    // ------------------------------------------------------------ reading

    public bool Shown(Field field) => _shown.Contains(field.Id);

    /// <summary>The choices of a field as they stand: those in sight, each switched off or on. Empty - the field has none now.</summary>
    public IReadOnlyList<Choice> ChoicesOf(Field field) => _choices.TryGetValue(field.Id, out var list) ? list : Array.Empty<Choice>();

    /// <summary>Whether a LUT of a LUT field is pinned: it stands first in the list.</summary>
    public bool IsPinned(Field field, string path) => _pinned.TryGetValue(field.Id, out var paths) && paths.Contains(path);

    /// <summary>A question of a page that changes more than its form (a LUT pinned, LUT files added): the form comes back with it, and what else it says.</summary>
    public JsonElement? Request(string what, JsonObject more)
    {
        more["do"] = what;
        more["page"] = Page.Key;
        var answer = _server.Ask(more);
        Answer(answer);
        return answer;
    }

    /// <summary>The preset of a preset field that stands on.</summary>
    public string PresetOf(Field field) => _presets.TryGetValue(field.Id, out var id) ? id : "";

    public string Get(Field field) => Get(field.Id);

    public string Get(string id)
    {
        if (!_values.TryGetValue(id, out var value)) return "";
        return value.ValueKind == JsonValueKind.Array
            ? string.Join(ListSeparator, value.EnumerateArray().Select(FieldKinds.Text))
            : FieldKinds.Text(value);
    }

    public JsonElement Raw(string id) => _values.TryGetValue(id, out var value) ? value : default;

    public bool IsOn(Field field) => Get(field) == "true";

    public HashSet<string> Picked(Field field) =>
        Get(field).Split(ListSeparator, StringSplitOptions.RemoveEmptyEntries).ToHashSet();

    // ------------------------------------------------------------ a control used

    /// <summary>The person sets a field: the click of its control goes to the server, in the type its field holds.</summary>
    public void Set(Field field, string text)
    {
        if (Get(field) == text && !field.IsPresets) return;
        var request = new JsonObject
        {
            ["do"] = "click", ["page"] = Page.Key, ["action"] = field.Action.Length > 0 ? field.Action : "type",
            ["field"] = field.Id, ["value"] = Json(field, text),
        };
        Answer(_server.Ask(request));
    }

    /// <summary>A control of a trim, which says more than a value: a point of a row, a point of a split, a row added.</summary>
    public void Click(string action, string field, JsonNode? value) =>
        Answer(_server.Ask(new JsonObject { ["do"] = "click", ["page"] = Page.Key, ["action"] = action, ["field"] = field, ["value"] = value }));

    /// <summary>A question of a trim page that is not its form: "take" - the file it points at, "probe" - what ffprobe knows of it.</summary>
    public JsonElement? Ask(string what)
    {
        var answer = _server.Ask(new JsonObject { ["do"] = what, ["page"] = Page.Key });
        if (answer is { } told && told.TryGetProperty(what, out var part)) return part.Clone();
        if (answer is null) Failed?.Invoke(_server.Trouble);
        return null;
    }

    JsonNode? Json(Field field, string text)
    {
        switch (field.Action)
        {
            case "tick":
                return JsonValue.Create(text == "true");
            case "ticks":
                var list = new JsonArray();
                foreach (var key in text.Split(ListSeparator, StringSplitOptions.RemoveEmptyEntries))
                    list.Add(ChoiceValue(field, key));
                return list;
            case "number":
                if (double.TryParse(text.Replace(',', '.'), NumberStyles.Float, CultureInfo.InvariantCulture, out var number))
                    return field.Whole || (number == Math.Floor(number) && Math.Abs(number) < 1e15) ? JsonValue.Create((long)number) : JsonValue.Create(number);
                return JsonValue.Create(text);
            case "choose" or "select" or "remux":
                return ChoiceValue(field, text);
            default:
                return JsonValue.Create(text);
        }
    }

    /// <summary>A choice as the manifest writes its value: a number stays a number.</summary>
    JsonNode? ChoiceValue(Field field, string key)
    {
        var made = ChoicesOf(field).FirstOrDefault(choice => choice.Key == key);
        if (made is not null && made.Value.ValueKind != JsonValueKind.Undefined) return JsonNode.Parse(made.Value.GetRawText());
        return field.OptionOf(key) is { } option ? JsonNode.Parse(option.Value.GetRawText()) : JsonValue.Create(key);
    }

    // ------------------------------------------------------------ what leaves the window

    /// <summary>
    /// The values of the form as the door reads them (--params): every field of the operation, in the type it holds; with
    /// <paramref name="only"/>, those of these fields - what another operation of the page takes (FORMATS of the link).
    /// </summary>
    public string ForDoor(ISet<string>? only = null)
    {
        var payload = new JsonObject();
        foreach (var (id, value) in _values)
            if (only is null || only.Contains(id)) payload[id] = JsonNode.Parse(value.GetRawText());
        return payload.ToJsonString(new JsonSerializerOptions
        {
            WriteIndented = true,
            Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
        });
    }

    /// <summary>What the page holds, to open it so at the next start (config\window_settings.json): the values a person set.</summary>
    public JsonObject Remember()
    {
        var kept = new JsonObject();
        foreach (var (id, _) in Typed)
            if (id != Page.ModeField && _values.TryGetValue(id, out var value)) kept[id] = JsonNode.Parse(value.GetRawText());
        return kept;
    }
}
