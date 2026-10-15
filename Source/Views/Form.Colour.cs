using System.Globalization;
using System.Text.Json;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using AudionMediaTools.Core;

namespace AudionMediaTools.Views;

/// <summary>
/// The swatches of COLOUR (the window on NiceGUI, render_color_gamma_preview): where the gamma before the LUT takes 18% gray
/// - the gray before, the gray after, "lighter · 22.5%"; of HDR to SDR, the reference of the tone map. The form server
/// reckons it (operation_model.gamma_preview); the swatches follow the gamma and the colour operation as they change.
/// </summary>
public sealed partial class Form
{
    Control GammaPreview()
    {
        // The patches are 21:9 and the row stands in the middle of the block (the owner, 15.10.2026: "Патчи с соотношением 21:9.
        // Вытягиваем и центрируем эту строку по горизонтали").
        Border Swatch() => new Border { Width = 84, Height = 36, CornerRadius = new CornerRadius(4), BorderThickness = new Thickness(1) }
            .Ink(Border.BorderBrushProperty, "BorderSoft");
        var before = Swatch();
        var after = Swatch();
        var arrow = new TextBlock { Classes = { "note" }, Text = "→", VerticalAlignment = VerticalAlignment.Center, Margin = new Thickness(10, 0) };
        var title = new TextBlock { Classes = { "fieldname" }, Text = Lang.T("18% серый") };
        var status = new TextBlock { Classes = { "note" } };
        var words = new StackPanel { Margin = new Thickness(14, 0, 0, 0), VerticalAlignment = VerticalAlignment.Center, Children = { title, status } };
        var row = new StackPanel
        {
            Orientation = Orientation.Horizontal, HorizontalAlignment = HorizontalAlignment.Center, Margin = new Thickness(0, 6, 0, 8),
            Children = { before, arrow, after, words },
        };
        Avalonia.Automation.AutomationProperties.SetAutomationId(row, "gamma_preview");
        var culture = Lang.Code == "ru" ? new CultureInfo("ru-RU") : CultureInfo.InvariantCulture;

        void Paint()
        {
            if (_values.Gamma is not { } gamma) { row.IsVisible = false; return; }
            row.IsVisible = true;
            string Text(string name) => gamma.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String ? value.GetString() ?? "" : "";
            var mode = Text("mode");
            bool error = mode == "error";
            before.IsVisible = after.IsVisible = arrow.IsVisible = !error;
            if (error)
            {
                status.Text = Text("error");
                ToolTip.SetTip(row, Text("error"));
                return;
            }
            before.Background = Brush.Parse(Text("source"));
            after.Background = Brush.Parse(Text("target"));
            var percent = (gamma.TryGetProperty("percent", out var share) && share.ValueKind == JsonValueKind.Number ? share.GetDouble() : 18.0).ToString("0.0", culture) + "%";
            status.Text = mode == "hdr" ? "HDR/Hable · tonemap" : Text("tone") switch
            {
                "lighter" => Lang.T("светлее") + " · " + percent,
                "darker" => Lang.T("темнее") + " · " + percent,
                _ => Lang.T("нейтрально") + " · " + percent,
            };
            ToolTip.SetTip(row, Lang.T(mode == "hdr"
                ? "18% серый - технический ориентир этапа HDR-to-SDR, а не полная симуляция изображения."
                : "Показывает, куда Gamma до LUT переносит 18% серый. Сам LUT может дополнительно изменить итоговое изображение."));
        }

        foreach (var id in new[] { "pre_gamma", "script_preset" }) WatchId(id, Paint);
        Paint();
        return row;
    }
}
