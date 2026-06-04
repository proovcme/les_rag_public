using System.Windows;
using System.Windows.Media;

namespace LES.AutoCAD.JsonExport;

internal static class LesRibbonIcons
{
    public static ImageSource ExportJson() => Create(IconKind.Export);

    public static ImageSource PushToLes() => Create(IconKind.Push);

    public static ImageSource Settings() => Create(IconKind.Settings);

    private static ImageSource Create(IconKind kind)
    {
        var group = new DrawingGroup();
        using (var context = group.Open())
        {
            var blue = Brush("#1d4ed8");
            var cyan = Brush("#06b6d4");
            var green = Brush("#22c55e");
            var orange = Brush("#f97316");
            var white = Brushes.White;
            var ink = Brush("#0f172a");
            var soft = Brush("#e0f2fe");

            context.DrawRoundedRectangle(Brush("#f8fafc"), Pen("#cbd5e1", 1.2), new Rect(2, 2, 28, 28), 5, 5);

            if (kind == IconKind.Export)
            {
                context.DrawRoundedRectangle(soft, Pen("#38bdf8", 1.1), new Rect(8, 5, 14, 20), 2, 2);
                context.DrawGeometry(null, Pen(ink, 1.6), Geometry.Parse("M 12 12 L 10 16 L 12 20"));
                context.DrawGeometry(null, Pen(ink, 1.6), Geometry.Parse("M 20 12 L 22 16 L 20 20"));
                context.DrawGeometry(null, Pen(blue, 1.8), Geometry.Parse("M 16 20 L 16 26"));
                context.DrawGeometry(green, null, Geometry.Parse("M 16 27 L 12 23 L 20 23 Z"));
            }
            else if (kind == IconKind.Push)
            {
                context.DrawEllipse(cyan, null, new Point(12, 16), 6, 5);
                context.DrawEllipse(cyan, null, new Point(19, 15), 7, 6);
                context.DrawRectangle(cyan, null, new Rect(8, 15, 18, 7));
                context.DrawGeometry(null, new Pen(white, 2.2), Geometry.Parse("M 16 23 L 16 10"));
                context.DrawGeometry(white, null, Geometry.Parse("M 16 8 L 11 14 L 21 14 Z"));
                context.DrawGeometry(null, Pen(blue, 1.3), Geometry.Parse("M 8 23 L 26 23"));
            }
            else
            {
                context.DrawEllipse(Brush("#fee2e2"), Pen("#f97316", 1.1), new Point(16, 16), 9, 9);
                for (var i = 0; i < 8; i++)
                {
                    var angle = i * 45.0 * 3.141592653589793 / 180.0;
                    var x1 = 16 + 10.5 * System.Math.Cos(angle);
                    var y1 = 16 + 10.5 * System.Math.Sin(angle);
                    var x2 = 16 + 13 * System.Math.Cos(angle);
                    var y2 = 16 + 13 * System.Math.Sin(angle);
                    context.DrawGeometry(null, Pen("#f97316", 2), Geometry.Parse($"M {x1.ToString(System.Globalization.CultureInfo.InvariantCulture)} {y1.ToString(System.Globalization.CultureInfo.InvariantCulture)} L {x2.ToString(System.Globalization.CultureInfo.InvariantCulture)} {y2.ToString(System.Globalization.CultureInfo.InvariantCulture)}"));
                }
                context.DrawEllipse(orange, null, new Point(16, 16), 5, 5);
                context.DrawEllipse(white, null, new Point(16, 16), 2, 2);
            }
        }

        group.Freeze();
        var image = new DrawingImage(group);
        image.Freeze();
        return image;
    }

    private static SolidColorBrush Brush(string color)
    {
        var brush = new SolidColorBrush((Color)ColorConverter.ConvertFromString(color));
        brush.Freeze();
        return brush;
    }

    private static Pen Pen(string color, double thickness)
    {
        var pen = new Pen(Brush(color), thickness);
        pen.Freeze();
        return pen;
    }

    private static Pen Pen(Brush brush, double thickness)
    {
        var pen = new Pen(brush, thickness);
        pen.Freeze();
        return pen;
    }

    private enum IconKind
    {
        Export,
        Push,
        Settings,
    }
}
