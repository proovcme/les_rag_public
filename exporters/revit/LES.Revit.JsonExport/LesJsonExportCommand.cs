using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Windows.Forms;
using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;

namespace LES.Revit.JsonExport;

[Transaction(TransactionMode.Manual)]
[Regeneration(RegenerationOption.Manual)]
public sealed class LesJsonExportCommand : IExternalCommand
{
    public Result Execute(ExternalCommandData commandData, ref string message, ElementSet elements)
    {
        var document = commandData.Application.ActiveUIDocument?.Document;
        if (document == null)
        {
            message = "No active Revit document.";
            return Result.Failed;
        }

        try
        {
            using var dialog = new SaveFileDialog
            {
                Title = "Save LES CAD/BIM JSON",
                Filter = "JSON (*.json)|*.json",
                FileName = $"{SafeStem(document.Title, "revit_model")}.cad_bim_graph.json",
                AddExtension = true,
                DefaultExt = "json",
            };

            if (dialog.ShowDialog() != DialogResult.OK)
            {
                return Result.Cancelled;
            }

            var payload = BuildPayload(document);
            var json = LesJsonWriter.Serialize(payload);
            File.WriteAllText(dialog.FileName, json, Encoding.UTF8);
            TaskDialog.Show("LES JSON Export", $"Exported {payload.Elements.Count} Revit elements to:\n{dialog.FileName}");
            return Result.Succeeded;
        }
        catch (Exception error)
        {
            message = error.Message;
            return Result.Failed;
        }
    }

    internal static CadBimGraph BuildPayload(Document document)
    {
        var stem = SafeStem(document.Title, "revit_model");
        var modelId = $"rvt:{stem}";
        var graph = new CadBimGraph
        {
            Id = modelId,
            Type = "RVTModel",
            Name = stem,
            SourceFormat = "rvt",
            SourcePath = document.PathName ?? string.Empty,
            ExtractedAt = DateTimeOffset.UtcNow.ToString("O"),
            Properties = new Dictionary<string, object?>
            {
                ["revit_title"] = document.Title,
                ["project_number"] = document.ProjectInformation?.Number ?? string.Empty,
                ["project_name"] = document.ProjectInformation?.Name ?? string.Empty,
            },
        };

        var collector = new FilteredElementCollector(document)
            .WhereElementIsNotElementType()
            .ToElements();

        foreach (var element in collector)
        {
            if (!ShouldExport(element))
            {
                continue;
            }

            var graphElement = ElementToGraphElement(document, element);
            graph.Elements.Add(graphElement);
            graph.Relations.Add(new CadBimRelation
            {
                SourceId = modelId,
                TargetId = graphElement.Id,
                RelationType = "contains",
            });
        }

        graph.Properties["element_count"] = graph.Elements.Count;
        graph.Properties["categories"] = graph.Elements.Select(e => e.Category).Where(v => !string.IsNullOrWhiteSpace(v)).Distinct().OrderBy(v => v).ToArray();
        return graph;
    }

    private static bool ShouldExport(Element element)
    {
        if (element.Id == ElementId.InvalidElementId || element.Category == null)
        {
            return false;
        }

        var categoryType = element.Category.CategoryType;
        if (categoryType != CategoryType.Model && categoryType != CategoryType.Annotation)
        {
            return false;
        }

        return element.ViewSpecific == false || categoryType == CategoryType.Annotation;
    }

    private static CadBimElement ElementToGraphElement(Document document, Element element)
    {
        var elementType = document.GetElement(element.GetTypeId()) as ElementType;
        var family = FamilyName(element, elementType);
        var properties = ElementProperties(document, element, elementType);
        var graphElement = new CadBimElement
        {
            Id = !string.IsNullOrWhiteSpace(element.UniqueId) ? element.UniqueId : element.Id.IntegerValue.ToString(),
            Type = element.GetType().Name,
            Name = SafeName(element.Name, element.GetType().Name),
            Category = element.Category?.Name ?? string.Empty,
            Family = family,
            Level = LevelName(document, element),
            Material = MaterialNames(document, element),
            Properties = properties,
        };
        return graphElement;
    }

    private static Dictionary<string, object?> ElementProperties(Document document, Element element, ElementType? elementType)
    {
        var properties = new Dictionary<string, object?>
        {
            ["element_id"] = element.Id.IntegerValue,
            ["unique_id"] = element.UniqueId ?? string.Empty,
            ["type_id"] = element.GetTypeId() == ElementId.InvalidElementId ? string.Empty : element.GetTypeId().IntegerValue.ToString(),
            ["type_name"] = elementType?.Name ?? string.Empty,
            ["family"] = FamilyName(element, elementType),
            ["category"] = element.Category?.Name ?? string.Empty,
            ["level"] = LevelName(document, element),
            ["materials"] = MaterialNames(document, element),
        };

        var bbox = element.get_BoundingBox(null);
        if (bbox != null)
        {
            properties["bbox_min"] = Point(bbox.Min);
            properties["bbox_max"] = Point(bbox.Max);
        }

        var parameters = new Dictionary<string, object?>();
        foreach (Parameter parameter in element.Parameters)
        {
            if (!parameter.HasValue)
            {
                continue;
            }

            var name = parameter.Definition?.Name;
            if (string.IsNullOrWhiteSpace(name) || parameters.ContainsKey(name))
            {
                continue;
            }

            var value = ParameterValue(parameter);
            if (value != null)
            {
                parameters[name] = value;
            }
        }

        if (parameters.Count > 0)
        {
            properties["parameters"] = parameters;
        }

        return properties;
    }

    private static object? ParameterValue(Parameter parameter)
    {
        try
        {
            return parameter.StorageType switch
            {
                StorageType.Double => new Dictionary<string, object?>
                {
                    ["value"] = parameter.AsDouble(),
                    ["displayValue"] = parameter.AsValueString() ?? string.Empty,
                    ["unit"] = UnitTypeId(parameter),
                },
                StorageType.Integer => parameter.AsInteger(),
                StorageType.String => parameter.AsString() ?? string.Empty,
                StorageType.ElementId => parameter.AsElementId().IntegerValue,
                _ => parameter.AsValueString() ?? string.Empty,
            };
        }
        catch
        {
            return parameter.AsValueString();
        }
    }

    private static string UnitTypeId(Parameter parameter)
    {
        try
        {
            return parameter.GetUnitTypeId()?.TypeId ?? string.Empty;
        }
        catch
        {
            return string.Empty;
        }
    }

    private static string FamilyName(Element element, ElementType? elementType)
    {
        if (element is FamilyInstance familyInstance)
        {
            return familyInstance.Symbol?.FamilyName ?? familyInstance.Symbol?.Name ?? string.Empty;
        }

        return elementType?.FamilyName ?? elementType?.Name ?? string.Empty;
    }

    private static string LevelName(Document document, Element element)
    {
        try
        {
            if (element.LevelId != ElementId.InvalidElementId && document.GetElement(element.LevelId) is Level level)
            {
                return level.Name ?? string.Empty;
            }
        }
        catch
        {
            return string.Empty;
        }

        return string.Empty;
    }

    private static string MaterialNames(Document document, Element element)
    {
        try
        {
            var names = element.GetMaterialIds(false)
                .Select(id => document.GetElement(id))
                .OfType<Material>()
                .Select(material => material.Name)
                .Where(name => !string.IsNullOrWhiteSpace(name))
                .Distinct()
                .Take(8)
                .ToArray();
            return string.Join(", ", names);
        }
        catch
        {
            return string.Empty;
        }
    }

    private static double[] Point(XYZ point)
    {
        return new[] { Math.Round(point.X, 6), Math.Round(point.Y, 6), Math.Round(point.Z, 6) };
    }

    internal static string SafeStem(string? value, string fallback)
    {
        var text = SafeName(value, fallback);
        foreach (var invalid in Path.GetInvalidFileNameChars())
        {
            text = text.Replace(invalid, '_');
        }

        return string.IsNullOrWhiteSpace(text) ? fallback : text;
    }

    private static string SafeName(string? value, string fallback)
    {
        var text = (value ?? string.Empty).Trim();
        return string.IsNullOrWhiteSpace(text) ? fallback : text;
    }

}
