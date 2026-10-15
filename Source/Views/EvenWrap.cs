using System;
using System.Linq;
using Avalonia;
using Avalonia.Controls;

namespace AudionMediaTools.Views;

/// <summary>
/// A row of switches that stands as it is while it fits its line, and goes into an even grid when it does not: as many
/// columns as make the lines equal, each cell as wide as the widest switch or wider, stretched over the width - never a
/// lone switch on a line of its own under a full one (the owner, 15.10.2026: not stacked to the left - stretched on a
/// grid). The switches keep their own margins.
/// </summary>
public sealed class EvenWrap : Panel
{
    /// <summary>The columns and the lines of the grid at a width; 0 columns - the row fits its line as it is.</summary>
    (int Columns, int Lines, double Cell, double Line) Plan(double width)
    {
        var shown = Children.Where(child => child.IsVisible).ToList();
        if (shown.Count == 0) return (0, 0, 0, 0);
        double line = shown.Max(child => child.DesiredSize.Height);
        double whole = shown.Sum(child => child.DesiredSize.Width);
        if (double.IsInfinity(width) || whole <= width + 0.5) return (0, 1, 0, line);
        double widest = shown.Max(child => child.DesiredSize.Width);
        int fit = Math.Max(1, (int)Math.Floor(width / widest));
        int lines = (shown.Count + fit - 1) / fit;
        int columns = (shown.Count + lines - 1) / lines;
        return (columns, lines, Math.Max(widest, width / columns), line);
    }

    protected override Size MeasureOverride(Size availableSize)
    {
        foreach (var child in Children) child.Measure(new Size(double.PositiveInfinity, availableSize.Height));
        var (columns, lines, _, line) = Plan(availableSize.Width);
        if (columns == 0) return new Size(Children.Where(child => child.IsVisible).Sum(child => child.DesiredSize.Width), line);
        return new Size(availableSize.Width, lines * line);
    }

    protected override Size ArrangeOverride(Size finalSize)
    {
        var (columns, _, cell, line) = Plan(finalSize.Width);
        double x = 0;
        int at = 0;
        foreach (var child in Children)
        {
            if (!child.IsVisible) continue;
            if (columns == 0)
            {
                child.Arrange(new Rect(x, 0, child.DesiredSize.Width, line));
                x += child.DesiredSize.Width;
            }
            else child.Arrange(new Rect(at % columns * cell, at / columns * line, cell, line));
            at++;
        }
        return finalSize;
    }
}
