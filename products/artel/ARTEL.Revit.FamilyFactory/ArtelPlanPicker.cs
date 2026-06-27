using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;

namespace ARTEL.Revit.FamilyFactory;

// Plugin-owned plan picker (not the OS file dialog): lists discovered
// family_action_plan.v1 files with their family name, plus an editable plan/FOP path.
internal sealed class PlanEntry
{
    public string Path { get; set; } = "";
    public string Display { get; set; } = "";
}

internal sealed class ArtelPlanPickerResult
{
    public string PlanPath { get; set; } = "";
    public string? SharedParamsPath { get; set; }
}

internal sealed class ArtelPlanPicker : Window
{
    private readonly ListBox _list = new();
    private readonly TextBox _planPath = new();
    private readonly TextBox _fopPath = new();

    private ArtelPlanPicker(IReadOnlyList<PlanEntry> plans, string fopDefault)
    {
        Title = "ARTEL — выбор плана действий";
        Width = 560;
        Height = 440;
        WindowStartupLocation = WindowStartupLocation.CenterScreen;
        ResizeMode = ResizeMode.CanResize;
        Background = new SolidColorBrush(Color.FromRgb(0xF5, 0xF5, 0xF3));

        var root = new Grid { Margin = new Thickness(16) };
        root.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        root.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });
        root.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        root.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        root.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });

        var header = new TextBlock
        {
            Text = "Доступные планы семейств",
            FontSize = 15,
            FontWeight = FontWeights.SemiBold,
            Margin = new Thickness(0, 0, 0, 8)
        };
        Grid.SetRow(header, 0);
        root.Children.Add(header);

        _list.ItemsSource = plans;
        _list.DisplayMemberPath = nameof(PlanEntry.Display);
        _list.SelectionChanged += (_, _) =>
        {
            if (_list.SelectedItem is PlanEntry entry)
            {
                _planPath.Text = entry.Path;
            }
        };
        _list.MouseDoubleClick += (_, _) => Confirm();
        if (plans.Count > 0)
        {
            _list.SelectedIndex = 0;
        }
        Grid.SetRow(_list, 1);
        root.Children.Add(_list);

        var planRow = LabeledRow("Путь к плану (.json):", _planPath, plans.FirstOrDefault()?.Path ?? "");
        Grid.SetRow(planRow, 2);
        root.Children.Add(planRow);

        var fopRow = LabeledRow("Файл ФОП (shared parameters, опционально):", _fopPath, fopDefault);
        Grid.SetRow(fopRow, 3);
        root.Children.Add(fopRow);

        var buttons = new StackPanel
        {
            Orientation = Orientation.Horizontal,
            HorizontalAlignment = HorizontalAlignment.Right,
            Margin = new Thickness(0, 12, 0, 0)
        };
        var ok = new Button { Content = "Сгенерировать", Width = 130, Height = 30, IsDefault = true, Margin = new Thickness(0, 0, 8, 0) };
        ok.Click += (_, _) => Confirm();
        var cancel = new Button { Content = "Отмена", Width = 90, Height = 30, IsCancel = true };
        buttons.Children.Add(ok);
        buttons.Children.Add(cancel);
        Grid.SetRow(buttons, 4);
        root.Children.Add(buttons);

        Content = root;
    }

    private static StackPanel LabeledRow(string label, TextBox box, string value)
    {
        box.Text = value;
        box.Height = 26;
        box.VerticalContentAlignment = VerticalAlignment.Center;
        var panel = new StackPanel { Margin = new Thickness(0, 8, 0, 0) };
        panel.Children.Add(new TextBlock { Text = label, Margin = new Thickness(0, 0, 0, 3) });
        panel.Children.Add(box);
        return panel;
    }

    public string PlanPath => _planPath.Text.Trim();
    public string FopPath => _fopPath.Text.Trim();

    private void Confirm()
    {
        if (string.IsNullOrWhiteSpace(PlanPath) || !File.Exists(PlanPath))
        {
            MessageBox.Show("Укажите существующий файл плана (.json).", "ARTEL", MessageBoxButton.OK, MessageBoxImage.Warning);
            return;
        }
        DialogResult = true;
        Close();
    }

    public static ArtelPlanPickerResult? Pick()
    {
        var plans = DiscoverPlans();
        var picker = new ArtelPlanPicker(plans, DefaultFop());
        return picker.ShowDialog() == true
            ? new ArtelPlanPickerResult
            {
                PlanPath = picker.PlanPath,
                SharedParamsPath = string.IsNullOrWhiteSpace(picker.FopPath) ? null : picker.FopPath
            }
            : null;
    }

    private static IReadOnlyList<PlanEntry> DiscoverPlans()
    {
        var entries = new List<PlanEntry>();
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var dir in PlanDirectories().Where(Directory.Exists))
        {
            foreach (var file in Directory.EnumerateFiles(dir, "*.json", SearchOption.AllDirectories))
            {
                if (!seen.Add(file))
                {
                    continue;
                }
                var display = TryDescribePlan(file);
                if (display != null)
                {
                    entries.Add(new PlanEntry { Path = file, Display = display });
                }
            }
        }
        return entries.OrderBy(e => e.Display, StringComparer.OrdinalIgnoreCase).ToList();
    }

    private static IEnumerable<string> PlanDirectories()
    {
        var env = Environment.GetEnvironmentVariable("ARTEL_PLANS_DIR");
        if (!string.IsNullOrWhiteSpace(env))
        {
            yield return env;
        }
        var home = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
        yield return Path.Combine(home, "les_rag", "products", "artel", "conformance", "expected");
        yield return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "ARTEL", "plans");
        yield return Path.Combine(home, "Documents", "ARTEL", "plans");
    }

    private static string? TryDescribePlan(string file)
    {
        try
        {
            using var doc = JsonDocument.Parse(File.ReadAllText(file));
            var root = doc.RootElement;
            if (root.ValueKind != JsonValueKind.Object
                || !root.TryGetProperty("schema_version", out var sv)
                || sv.GetString() != "artel.family_action_plan.v1")
            {
                return null;
            }
            var familyName = root.TryGetProperty("family", out var fam)
                             && fam.TryGetProperty("name", out var n)
                ? n.GetString()
                : null;
            var name = string.IsNullOrWhiteSpace(familyName) ? Path.GetFileName(file) : familyName;
            return $"{name}   ·   {Path.GetFileName(file)}";
        }
        catch
        {
            return null;
        }
    }

    private static string DefaultFop()
    {
        var env = Environment.GetEnvironmentVariable("ARTEL_SHARED_PARAMS_FILE");
        if (!string.IsNullOrWhiteSpace(env) && File.Exists(env))
        {
            return env;
        }
        var home = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
        var candidate = Path.Combine(home, "les_rag", "products", "artel", "conformance", "inputs", "fop_reference.txt");
        return File.Exists(candidate) ? candidate : "";
    }
}
