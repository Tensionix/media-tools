using System.Collections.Generic;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Media;

namespace AudionMediaTools.Views;

/// <summary>
/// The colour a choice of a form wears, as the window on NiceGUI had it: what a format is - as it is and uncompressed
/// green, without loss teal, with loss rust. Which tone a choice has is told by the console command
/// (operation_model.option_tone) - the window does not guess it from the words of the choice. What a tone looks like is
/// here, and a switch wears it as brushes of its own under the keys its style reads.
/// </summary>
public static class ChoiceTones
{
    /// <summary>The colour of a tone, one soft colour in every theme (theme.css of the window on NiceGUI).</summary>
    static readonly Dictionary<string, string> Colours = new()
    {
        ["copy"] = "#22c55e", ["uncompressed"] = "#22c55e", ["lossless"] = "#38bdf8", ["lossy"] = "#f97316",
    };

    /// <summary>
    /// How much of the tone goes into the wash at rest: darker by a third and more than it was, the words as they were
    /// (the owner, 15.10.2026: "затемнять неактивные заливки, шрифты оставить ... хотя бы на треть").
    /// </summary>
    const double WashAtRest = 0.10;

    static readonly Dictionary<string, Dictionary<string, IBrush>> Made = new();
    static object? _madeFor;

    static Color Mix(Color a, double share, Color b) => Color.FromRgb(
        (byte)(a.R * share + b.R * (1 - share)), (byte)(a.G * share + b.G * (1 - share)), (byte)(a.B * share + b.B * (1 - share)));

    static bool Colour(string key, out Color colour)
    {
        colour = default;
        if (Application.Current is not { } app || !app.TryGetResource(key, app.ActualThemeVariant, out var value)) return false;
        if (value is Color plain) { colour = plain; return true; }
        if (value is ISolidColorBrush brush) { colour = brush.Color; return true; }
        return false;
    }

    /// <summary>
    /// A switch puts on its tone: the brushes go into its own resources under the keys the style
    /// of a switch reads, so the style needs no copy for every tone. A choice without a tone, or
    /// with one the window does not know, stays as the shell draws it.
    /// </summary>
    public static void Wear(Control button, string tone)
    {
        if (!Colours.TryGetValue(tone, out var hex)) return;
        var theme = Application.Current?.ActualThemeVariant;
        if (!ReferenceEquals(theme, _madeFor)) { Made.Clear(); _madeFor = theme; }
        if (!Made.TryGetValue(tone, out var brushes))
        {
            if (!Colour("PanelBg", out var ground)) return;
            var soft = Color.Parse(hex);
            Made[tone] = brushes = new Dictionary<string, IBrush>
            {
                ["SwitchBg"] = new SolidColorBrush(Mix(soft, WashAtRest, ground)),
                ["SwitchBorder"] = new SolidColorBrush(Mix(soft, 0.34, ground)),
                ["SwitchOn"] = new SolidColorBrush(Mix(soft, 0.38, ground)),
                ["Quasar"] = new SolidColorBrush(Mix(soft, 0.85, ground)),
            };
        }
        foreach (var (key, brush) in brushes) button.Resources[key] = brush;
    }
}
