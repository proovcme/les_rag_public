using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text;
using System.Windows.Forms;
using Autodesk.Navisworks.Api;
using Autodesk.Navisworks.Api.Plugins;

namespace LES.Navisworks.JsonExport;

[Plugin("LES.Navisworks.JsonExport", "LES", DisplayName = "LES JSON Export", ToolTip = "Export Navisworks model to LES cad_bim_graph.json")]
public sealed class LesNavisworksPlugin : AddInPlugin
{
    public override int Execute(params string[] parameters)
    {
        var action = parameters.FirstOrDefault(value => !string.IsNullOrWhiteSpace(value))?.Trim().ToLowerInvariant() ?? "export";
        try
        {
            return action switch
            {
                "push" => Push(),
                "config" => Config(),
                _ => Export(),
            };
        }
        catch (Exception error)
        {
            MessageBox.Show(error.Message, "LES Navisworks JSON Export", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }

    internal static int Export()
    {
        var graph = BuildPayload();
        using var dialog = new SaveFileDialog
        {
            Title = "Save LES CAD/BIM JSON",
            Filter = "JSON (*.json)|*.json",
            FileName = SafeStem(graph.Name, "navisworks_model") + ".cad_bim_graph.json",
        };

        if (dialog.ShowDialog() != DialogResult.OK)
        {
            return 0;
        }

        File.WriteAllText(dialog.FileName, LesJsonWriter.Serialize(graph), Encoding.UTF8);
        MessageBox.Show(
            $"Exported {graph.Elements.Count} Navisworks items:\n{dialog.FileName}",
            "LES Navisworks JSON Export",
            MessageBoxButtons.OK,
            MessageBoxIcon.Information
        );
        return 0;
    }

    internal static int Push()
    {
        var graph = BuildPayload();
        var settings = LesUploadSettings.Load();
        var result = LesUploader.UploadAsync(graph, "navisworks", settings).GetAwaiter().GetResult();
        if (result.Success)
        {
            MessageBox.Show(
                $"Imported {graph.Elements.Count} Navisworks items via:\n{result.Url}",
                "LES Navisworks JSON Push",
                MessageBoxButtons.OK,
                MessageBoxIcon.Information
            );
            return 0;
        }

        var fallback = FallbackOutputPath(settings, graph);
        File.WriteAllText(fallback, LesJsonWriter.Serialize(graph), Encoding.UTF8);
        MessageBox.Show(
            $"Upload failed; saved fallback JSON:\n{fallback}\n\n{result.Error}",
            "LES Navisworks JSON Push",
            MessageBoxButtons.OK,
            MessageBoxIcon.Warning
        );
        return 1;
    }

    internal static int Config()
    {
        var settings = LesUploadSettings.Load();
        settings.Save();
        Process.Start(new ProcessStartInfo
        {
            FileName = LesUploadSettings.ConfigPath,
            UseShellExecute = true,
        });
        MessageBox.Show(
            "Opened exporter config:\n" + LesUploadSettings.ConfigPath,
            "LES Navisworks JSON Config",
            MessageBoxButtons.OK,
            MessageBoxIcon.Information
        );
        return 0;
    }

    internal static CadBimGraph BuildPayload()
    {
        var document = Autodesk.Navisworks.Api.Application.ActiveDocument;
        if (document == null)
        {
            throw new InvalidOperationException("No active Navisworks document.");
        }

        var sourcePath = ReadString(document, "FileName");
        var stem = SafeStem(sourcePath, "navisworks_model");
        var modelId = "navisworks:" + stem;
        var graph = new CadBimGraph
        {
            Id = modelId,
            Type = "NavisworksModel",
            Name = stem,
            SourceFormat = Path.GetExtension(sourcePath).TrimStart('.').ToLowerInvariant(),
            SourcePath = sourcePath,
            ExtractedAt = DateTimeOffset.UtcNow.ToString("O", CultureInfo.InvariantCulture),
            Properties = new Dictionary<string, object?>
            {
                ["exporter"] = "LES.Navisworks.JsonExport",
            },
        };
        if (string.IsNullOrWhiteSpace(graph.SourceFormat))
        {
            graph.SourceFormat = "nwd";
        }

        var models = ReadObject(document, "Models");
        var root = ReadObject(models, "RootItem") as ModelItem;
        if (root == null)
        {
            throw new InvalidOperationException("Navisworks model tree is empty.");
        }

        var visited = 0;
        Walk(root, modelId, graph, "0", ref visited);
        graph.Properties["item_count"] = graph.Elements.Count;
        graph.Properties["categories"] = graph.Elements.Select(item => item.Category).Where(v => !string.IsNullOrWhiteSpace(v)).Distinct().OrderBy(v => v).ToArray();
        return graph;
    }

    private static void Walk(ModelItem item, string parentId, CadBimGraph graph, string path, ref int visited)
    {
        if (visited >= 50000)
        {
            return;
        }

        visited++;
        var element = ItemToElement(item, path);
        graph.Elements.Add(element);
        graph.Relations.Add(new CadBimRelation
        {
            SourceId = parentId,
            TargetId = element.Id,
            RelationType = "contains",
        });

        var index = 0;
        foreach (var child in ReadEnumerable<ModelItem>(item, "Children"))
        {
            Walk(child, element.Id, graph, path + "." + index.ToString(CultureInfo.InvariantCulture), ref visited);
            index++;
        }
    }

    private static CadBimElement ItemToElement(ModelItem item, string path)
    {
        var properties = ReadProperties(item);
        var id = ReadGuid(item, "InstanceGuid");
        if (string.IsNullOrWhiteSpace(id))
        {
            id = "nw:" + path;
        }

        var category = ReadString(item, "ClassDisplayName");
        if (string.IsNullOrWhiteSpace(category))
        {
            category = ReadString(item, "ClassName");
        }

        var element = new CadBimElement
        {
            Id = id,
            Type = category,
            Name = Trim(ReadString(item, "DisplayName"), category.Length == 0 ? "Navisworks item" : category),
            Category = category,
            Properties = properties,
        };
        AddBoundingBox(item, element);
        return element;
    }

    private static Dictionary<string, object?> ReadProperties(ModelItem item)
    {
        var values = new Dictionary<string, object?>(StringComparer.Ordinal);
        foreach (var category in ReadEnumerable<object>(item, "PropertyCategories"))
        {
            var categoryName = Trim(ReadString(category, "DisplayName"), "Property");
            foreach (var property in ReadEnumerable<object>(category, "Properties"))
            {
                var propertyName = Trim(ReadString(property, "DisplayName"), "Value");
                var value = ReadObject(property, "Value");
                values[categoryName + "." + propertyName] = DisplayValue(value);
            }
        }

        return values;
    }

    private static void AddBoundingBox(ModelItem item, CadBimElement element)
    {
        var box = Invoke(item, "BoundingBox");
        if (box == null)
        {
            return;
        }

        var min = ReadObject(box, "Min");
        var max = ReadObject(box, "Max");
        var vertices = new[]
        {
            ReadDouble(min, "X"), ReadDouble(min, "Y"), ReadDouble(min, "Z"),
            ReadDouble(max, "X"), ReadDouble(max, "Y"), ReadDouble(max, "Z"),
        };
        element.Geometry = new CadBimGeometry
        {
            Type = "bbox",
            Vertices = vertices,
            Stats = new Dictionary<string, object?>
            {
                ["bbox_min"] = new[] { vertices[0], vertices[1], vertices[2] },
                ["bbox_max"] = new[] { vertices[3], vertices[4], vertices[5] },
            },
        };
    }

    private static string FallbackOutputPath(LesUploadSettings settings, CadBimGraph graph)
    {
        var directory = settings.ResolveLocalOutputDir();
        Directory.CreateDirectory(directory);
        return Path.Combine(directory, SafeStem(graph.Name, "navisworks_model") + ".cad_bim_graph.json");
    }

    private static IEnumerable<T> ReadEnumerable<T>(object source, string propertyName)
    {
        var value = ReadObject(source, propertyName);
        if (value is not IEnumerable enumerable)
        {
            yield break;
        }

        foreach (var item in enumerable)
        {
            if (item is T typed)
            {
                yield return typed;
            }
        }
    }

    private static object? ReadObject(object? source, string propertyName)
    {
        if (source == null)
        {
            return null;
        }

        return source.GetType().GetProperty(propertyName, BindingFlags.Instance | BindingFlags.Public)?.GetValue(source);
    }

    private static object? Invoke(object source, string methodName)
    {
        return source.GetType().GetMethod(methodName, BindingFlags.Instance | BindingFlags.Public, null, Type.EmptyTypes, null)?.Invoke(source, null);
    }

    private static string ReadString(object? source, string propertyName)
    {
        return ReadObject(source, propertyName)?.ToString() ?? string.Empty;
    }

    private static string ReadGuid(object source, string propertyName)
    {
        var value = ReadObject(source, propertyName);
        return value is Guid guid && guid != Guid.Empty ? guid.ToString("D") : string.Empty;
    }

    private static double ReadDouble(object? source, string propertyName)
    {
        var value = ReadObject(source, propertyName);
        return value == null ? 0 : Convert.ToDouble(value, CultureInfo.InvariantCulture);
    }

    private static string DisplayValue(object? value)
    {
        if (value == null)
        {
            return string.Empty;
        }

        var display = Invoke(value, "ToDisplayString");
        return Trim(display?.ToString() ?? value.ToString() ?? string.Empty, string.Empty);
    }

    private static string SafeStem(string? path, string fallback)
    {
        if (string.IsNullOrWhiteSpace(path))
        {
            return fallback;
        }

        var stem = Path.GetFileNameWithoutExtension(path);
        return string.IsNullOrWhiteSpace(stem) ? fallback : stem;
    }

    private static string Trim(string? value, string fallback)
    {
        var text = (value ?? string.Empty).Replace("\r", " ").Replace("\n", " ").Trim();
        if (text.Length == 0)
        {
            return fallback;
        }

        return text.Length <= 160 ? text : text.Substring(0, 160);
    }
}

[Plugin("LES.Navisworks.JsonPush", "LES", DisplayName = "LES JSON Push", ToolTip = "Export Navisworks model and push it to configured destinations")]
public sealed class LesNavisworksPushPlugin : AddInPlugin
{
    public override int Execute(params string[] parameters)
    {
        try
        {
            return LesNavisworksPlugin.Push();
        }
        catch (Exception error)
        {
            MessageBox.Show(error.Message, "LES Navisworks JSON Push", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }
}

[Plugin("LES.Navisworks.JsonConfig", "LES", DisplayName = "LES JSON Config", ToolTip = "Open LES CAD/BIM exporter destination config")]
public sealed class LesNavisworksConfigPlugin : AddInPlugin
{
    public override int Execute(params string[] parameters)
    {
        try
        {
            return LesNavisworksPlugin.Config();
        }
        catch (Exception error)
        {
            MessageBox.Show(error.Message, "LES Navisworks JSON Config", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }
}
