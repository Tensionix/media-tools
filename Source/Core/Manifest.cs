using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace AudionMediaTools.Core;

/// <summary>
/// What the door tells of the program (media_cli.cmd describe): the sections of the window and the modes of each,
/// the operations with their fields. The window draws by it and knows no section and no operation by its name:
/// what stands where is config\window_layout.yaml, what an operation is - config\tool_manifest.yaml.
/// </summary>
public sealed class Described
{
    public string Version { get; set; } = "";
    public ProjectPaths Paths { get; set; } = new();
    public Layout Layout { get; set; } = new();
    public Dictionary<string, Node> Operations { get; set; } = new();
    /// <summary>The operations that download - the installers of SERVICE: what they fetch is named before they run (Door.Plan).</summary>
    public List<string> Plans { get; set; } = new();

    static readonly JsonSerializerOptions Json = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        PropertyNameCaseInsensitive = true,
        NumberHandling = JsonNumberHandling.AllowReadingFromString,
    };

    /// <summary>The answer of "describe" read; an answer that is no description throws.</summary>
    public static Described Parse(string json)
    {
        var told = JsonSerializer.Deserialize<Described>(json, Json) ?? throw new JsonException("the door gave no description");
        foreach (var (id, node) in told.Operations) if (node.Id.Length == 0) node.Id = id;
        foreach (var section in told.Layout.Sections)
        {
            section.Pages = new List<Page>();
            foreach (var mode in section.Modes)
            {
                if (!told.Operations.TryGetValue(mode.Op, out var node)) throw new JsonException($"the layout names an operation the door did not describe: {mode.Op}");
                // A mode that is a choice of a field is that choice; a mode that is an operation of its own is the operation.
                var id = mode.Field.Length > 0 ? FieldKinds.Text(mode.Value) : mode.Op;
                section.Pages.Add(new Page
                {
                    Id = id, Title = mode.Title, TitleRu = mode.TitleRu, Icon = mode.Icon, Section = section, Node = node,
                    ModeField = mode.Field, ModeValue = mode.Value,
                });
            }
        }
        return told;
    }

    /// <summary>An operation by its id; null for one the door did not describe.</summary>
    public Node? Find(string id) => Operations.TryGetValue(id, out var node) ? node : null;
}

/// <summary>The folders of the project, as the door resolves them.</summary>
public sealed class ProjectPaths
{
    public string Root { get; set; } = "";
    public string Input { get; set; } = "";
    public string Output { get; set; } = "";
    public string Logs { get; set; } = "";
    public string Report { get; set; } = "";
    public string Config { get; set; } = "";
}

public sealed class Layout
{
    public List<Section> Sections { get; set; } = new();
    /// <summary>The operations of the button SERVICE of the header: checks and installers.</summary>
    public List<string> Service { get; set; } = new();
    /// <summary>What the panel DETAILS under the paths runs: ffprobe of the Source.</summary>
    public List<string> Details { get; set; } = new();
    /// <summary>Operations of the manifest the window does by itself, another way: it clears the folders through the Recycle Bin.</summary>
    public List<string> Own { get; set; } = new();
    /// <summary>Operations a page runs with its own values, as a button beside one of its fields (FORMATS beside the link).</summary>
    public List<FieldButton> Buttons { get; set; } = new();
    /// <summary>Fields of a link or a path with PASTE at their right: the clipboard into the field.</summary>
    public List<string> Paste { get; set; } = new();
}

/// <summary>An operation as a button beside a field: what it runs, and the field it stands beside.</summary>
public sealed class FieldButton
{
    public string Op { get; set; } = "";
    public string Beside { get; set; } = "";
    /// <summary>A name of Lucide for the sign of the button; "" - the sign of a run.</summary>
    public string Icon { get; set; } = "";
    /// <summary>False - the sign alone, the name of the operation in its tooltip.</summary>
    public bool Words { get; set; } = true;
}

/// <summary>A section of the window: a large button of the row under the header; its modes are the ribbon inside it.</summary>
public sealed class Section
{
    public string Id { get; set; } = "";
    public string Title { get; set; } = "";
    public string TitleRu { get; set; } = "";
    public string Icon { get; set; } = "";
    public string About { get; set; } = "";
    public string AboutRu { get; set; } = "";
    public string Op { get; set; } = "";
    public string ModeField { get; set; } = "";
    public List<Mode> Modes { get; set; } = new();
    /// <summary>Blocks of the form drawn at its very end, under the rare fields: a block seldom wanted (AUDIO: the filter of the Source).</summary>
    public List<string> BlocksLast { get; set; } = new();

    [JsonIgnore] public List<Page> Pages { get; set; } = new();
    [JsonIgnore] public string Name => Words.Pick(TitleRu, Title);
    [JsonIgnore] public string Line => Words.Pick(AboutRu, About);
}

/// <summary>A mode of a section as the layout writes it: an operation, and the field and the value it stands for when it is a choice.</summary>
public sealed class Mode
{
    public string Op { get; set; } = "";
    public string Field { get; set; } = "";
    public JsonElement Value { get; set; }
    public string Title { get; set; } = "";
    public string TitleRu { get; set; } = "";
    public string Icon { get; set; } = "";
}

/// <summary>A page of the window: a mode of a section, with a form of its own (the owner, 15.10.2026: "формы раздельные").</summary>
public sealed class Page
{
    public string Id { get; set; } = "";
    public string Title { get; set; } = "";
    public string TitleRu { get; set; } = "";
    public string Icon { get; set; } = "";
    public Section? Section { get; set; }
    public Node Node { get; set; } = new();
    /// <summary>The field the mode is a choice of, and its value: the form holds it set and does not draw it. "" - the mode is an operation.</summary>
    public string ModeField { get; set; } = "";
    public JsonElement ModeValue { get; set; }

    public string Name => Words.Pick(TitleRu, Title);
    /// <summary>The page among all of the window: the ids of modes repeat across sections.</summary>
    public string Key => (Section?.Id ?? "") + "/" + Id;
}

/// <summary>An operation: what a button runs.</summary>
public sealed class Node
{
    public string Id { get; set; } = "";
    public string Title { get; set; } = "";
    public string TitleRu { get; set; } = "";
    public string Description { get; set; } = "";
    public string DescriptionRu { get; set; } = "";
    /// <summary>"safe" or "dangerous": a dangerous one is asked about.</summary>
    public string Kind { get; set; } = "";
    public bool Runs { get; set; }
    public List<Field> Fields { get; set; } = new();

    [JsonIgnore] public string Name => Words.Pick(TitleRu, Title);
    [JsonIgnore] public string About => Words.Pick(DescriptionRu, Description);
    [JsonIgnore] public bool Dangerous => Kind == "dangerous";

    public Field? Field(string id) => Fields.FirstOrDefault(field => field.Id == id);
}

public sealed class Field
{
    public string Id { get; set; } = "";
    /// <summary>The kind as the manifest names it: radio, select, checkbox, checkboxes, number, text, profile_buttons…</summary>
    public string Kind { get; set; } = "";
    /// <summary>What a control of the field does, as the form server names it: choose, select, tick, ticks, preset, profile, number, type, lut, remux, take.</summary>
    public string Action { get; set; } = "";
    public JsonElement Default { get; set; }
    /// <summary>The block of the form the field stands in.</summary>
    [JsonPropertyName("section")] public string Block { get; set; } = "";
    public bool Advanced { get; set; }
    public string Label { get; set; } = "";
    public string LabelRu { get; set; } = "";
    public string Hint { get; set; } = "";
    public string HintRu { get; set; } = "";
    public string Tooltip { get; set; } = "";
    public string TooltipRu { get; set; } = "";
    public string Placeholder { get; set; } = "";
    public double? Min { get; set; }
    public double? Max { get; set; }
    public double? Step { get; set; }
    public bool Whole { get; set; }
    public List<Option> Options { get; set; } = new();
    public List<Preset> Presets { get; set; } = new();

    [JsonIgnore] public string Name => Words.Pick(LabelRu, Label);
    [JsonIgnore] public string Note => Words.Pick(HintRu, Hint);
    [JsonIgnore] public bool IsPresets => Action is "preset" or "profile";

    /// <summary>The tooltip: the short line of the manifest, then the full explanation.</summary>
    [JsonIgnore]
    public string Tip
    {
        get
        {
            var more = Words.Pick(TooltipRu, Tooltip);
            return Note.Length > 0 && more.Length > 0 && more != Note ? Note + "\n\n" + more : more.Length > 0 ? more : Note;
        }
    }

    /// <summary>The words of the manifest a field keeps beside its tooltip - add_tooltip, point_tooltip of a trim - by their keys.</summary>
    [JsonExtensionData] public Dictionary<string, JsonElement> More { get; set; } = new();

    public string Extra(string key) => More.TryGetValue(key, out var value) && value.ValueKind == JsonValueKind.String ? value.GetString() ?? "" : "";

    public Option? OptionOf(string key) => Options.FirstOrDefault(option => option.Key == key);
}

public sealed class Option
{
    public JsonElement Value { get; set; }
    public string Label { get; set; } = "";
    public string LabelRu { get; set; } = "";
    public string Tooltip { get; set; } = "";
    public string TooltipRu { get; set; } = "";
    public string Description { get; set; } = "";
    public string DescriptionRu { get; set; } = "";
    /// <summary>The colour of the choice by what it is - copy, uncompressed, lossless, lossy - worked out by the door.</summary>
    public string Tone { get; set; } = "";
    public string ToneRu { get; set; } = "";

    [JsonIgnore] public string Name => Words.Pick(LabelRu, Label);
    [JsonIgnore] public string Tip => Words.Pick(TooltipRu, Tooltip) is { Length: > 0 } tip ? tip : Words.Pick(DescriptionRu, Description);
    /// <summary>The value as the text the form keeps and compares.</summary>
    [JsonIgnore] public string Key => FieldKinds.Text(Value);
    [JsonIgnore] public string ToneInUse => Words.Pick(ToneRu, Tone);
}

/// <summary>A preset of a field: a button that writes several values of the form at once.</summary>
public sealed class Preset
{
    public string Id { get; set; } = "";
    public string Label { get; set; } = "";
    public string LabelRu { get; set; } = "";
    public string Description { get; set; } = "";
    public string DescriptionRu { get; set; } = "";
    public string Tooltip { get; set; } = "";
    public string TooltipRu { get; set; } = "";
    public string Tone { get; set; } = "";
    public string Group { get; set; } = "";
    public string GroupLabel { get; set; } = "";
    public string GroupLabelRu { get; set; } = "";

    [JsonIgnore] public string Name => Words.Pick(LabelRu, Label);
    [JsonIgnore] public string Tip => Words.Pick(TooltipRu, Tooltip) is { Length: > 0 } tip ? tip : Words.Pick(DescriptionRu, Description);
    [JsonIgnore] public string GroupName => Words.Pick(GroupLabelRu, GroupLabel);
}

public static class Words
{
    /// <summary>The Russian text in the Russian window; the English one otherwise, and wherever the Russian is missing.</summary>
    public static string Pick(string ru, string en) => Lang.Code == "ru" && ru.Length > 0 ? ru : en;
}

public static class FieldKinds
{
    /// <summary>A value of the manifest as text: a number without a tail of zeros, a flag as true or false.</summary>
    public static string Text(JsonElement value) => value.ValueKind switch
    {
        JsonValueKind.String => value.GetString() ?? "",
        JsonValueKind.Number => value.GetDouble().ToString("0.############", CultureInfo.InvariantCulture),
        JsonValueKind.True => "true",
        JsonValueKind.False => "false",
        JsonValueKind.Null or JsonValueKind.Undefined => "",
        _ => value.GetRawText(),
    };
}
