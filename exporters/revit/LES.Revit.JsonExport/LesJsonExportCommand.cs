using System;
using System.Collections.Generic;
using System.Globalization;
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
    private const int MaxMeshTrianglesPerElement = 1200;
    private const int MaxMeshVerticesPerElement = 3600;

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
                ["geometry_format"] = "mesh",
                ["geometry_units"] = "revit_internal_ft",
                ["geometry_max_triangles_per_element"] = MaxMeshTrianglesPerElement,
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
        graph.Properties["geometry_element_count"] = graph.Elements.Count(e => e.Geometry != null);
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
        var geometry = ElementGeometry(document, element);
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
            Geometry = geometry,
        };
        return graphElement;
    }

    private static CadBimGeometry? ElementGeometry(Document document, Element element)
    {
        if (element.Category?.CategoryType != CategoryType.Model)
        {
            return null;
        }

        try
        {
            var options = new Options
            {
                ComputeReferences = false,
                DetailLevel = ViewDetailLevel.Medium,
                IncludeNonVisibleObjects = false,
            };
            var geometryElement = element.get_Geometry(options);
            if (geometryElement == null)
            {
                return null;
            }

            var builder = new MeshBuilder(MaxMeshTrianglesPerElement, MaxMeshVerticesPerElement);
            AddGeometryElement(document, geometryElement, Transform.Identity, builder);
            if (builder.TriangleCount == 0)
            {
                return null;
            }

            return new CadBimGeometry
            {
                Type = "mesh",
                Units = "revit_internal_ft",
                Vertices = builder.Vertices.ToArray(),
                Faces = builder.Faces.ToArray(),
                Material = MeshMaterial(document, element),
                Stats = new Dictionary<string, object?>
                {
                    ["triangles"] = builder.TriangleCount,
                    ["vertices"] = builder.VertexCount,
                    ["source"] = "revit_geometry",
                },
                Truncated = builder.Truncated,
            };
        }
        catch
        {
            return null;
        }
    }

    private static void AddGeometryElement(Document document, GeometryElement geometryElement, Transform transform, MeshBuilder builder)
    {
        foreach (var child in geometryElement)
        {
            if (child is GeometryObject childObject)
            {
                AddGeometryObject(document, childObject, transform, builder);
            }
        }
    }

    private static void AddGeometryObject(Document document, GeometryObject geometryObject, Transform transform, MeshBuilder builder)
    {
        if (builder.IsFull)
        {
            return;
        }

        switch (geometryObject)
        {
            case GeometryInstance instance:
                var instanceTransform = transform.Multiply(instance.Transform);
                AddGeometryElement(document, instance.GetSymbolGeometry(), instanceTransform, builder);
                break;
            case Solid solid:
                if (solid.Volume <= 0 || solid.Faces.Size == 0)
                {
                    return;
                }

                foreach (Face face in solid.Faces)
                {
                    AddMesh(face.Triangulate(), transform, builder);
                    if (builder.IsFull)
                    {
                        return;
                    }
                }
                break;
            case Mesh mesh:
                AddMesh(mesh, transform, builder);
                break;
        }
    }

    private static void AddMesh(Mesh mesh, Transform transform, MeshBuilder builder)
    {
        for (var index = 0; index < mesh.NumTriangles; index++)
        {
            if (builder.IsFull)
            {
                builder.Truncated = true;
                return;
            }

            var triangle = mesh.get_Triangle(index);
            var a = transform.OfPoint(triangle.get_Vertex(0));
            var b = transform.OfPoint(triangle.get_Vertex(1));
            var c = transform.OfPoint(triangle.get_Vertex(2));
            builder.AddTriangle(a, b, c);
        }
    }

    private static Dictionary<string, object?> MeshMaterial(Document document, Element element)
    {
        var materialName = MaterialNames(document, element);
        var material = FirstMaterial(document, element);
        var color = material?.Color;
        return new Dictionary<string, object?>
        {
            ["name"] = materialName,
            ["color"] = color == null ? CategoryColor(element.Category?.Name ?? element.GetType().Name) : ColorHex(color),
            ["opacity"] = 0.86,
        };
    }

    private static Material? FirstMaterial(Document document, Element element)
    {
        try
        {
            return element.GetMaterialIds(false)
                .Select(id => document.GetElement(id))
                .OfType<Material>()
                .FirstOrDefault();
        }
        catch
        {
            return null;
        }
    }

    private static string ColorHex(Autodesk.Revit.DB.Color color)
    {
        return $"#{color.Red:X2}{color.Green:X2}{color.Blue:X2}";
    }

    private static string CategoryColor(string category)
    {
        var hash = 0;
        foreach (var ch in category)
        {
            hash = unchecked(hash * 31 + ch);
        }

        var palette = new[]
        {
            "#38bdf8",
            "#22c55e",
            "#f59e0b",
            "#ef4444",
            "#a78bfa",
            "#14b8a6",
            "#f97316",
            "#e879f9",
            "#84cc16",
        };
        return palette[Math.Abs(hash % palette.Length)];
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

    private sealed class MeshBuilder
    {
        private readonly int _maxTriangles;
        private readonly int _maxVertices;
        private readonly Dictionary<string, int> _vertexIndex = new();

        public MeshBuilder(int maxTriangles, int maxVertices)
        {
            _maxTriangles = maxTriangles;
            _maxVertices = maxVertices;
        }

        public List<double> Vertices { get; } = new();

        public List<int> Faces { get; } = new();

        public int TriangleCount => Faces.Count / 3;

        public int VertexCount => Vertices.Count / 3;

        public bool Truncated { get; set; }

        public bool IsFull => TriangleCount >= _maxTriangles || VertexCount >= _maxVertices;

        public void AddTriangle(XYZ a, XYZ b, XYZ c)
        {
            if (IsFull)
            {
                Truncated = true;
                return;
            }

            Faces.Add(AddVertex(a));
            Faces.Add(AddVertex(b));
            Faces.Add(AddVertex(c));
        }

        private int AddVertex(XYZ point)
        {
            var x = Math.Round(point.X, 6);
            var y = Math.Round(point.Y, 6);
            var z = Math.Round(point.Z, 6);
            var key = $"{x.ToString(CultureInfo.InvariantCulture)},{y.ToString(CultureInfo.InvariantCulture)},{z.ToString(CultureInfo.InvariantCulture)}";
            if (_vertexIndex.TryGetValue(key, out var existing))
            {
                return existing;
            }

            if (VertexCount >= _maxVertices)
            {
                Truncated = true;
                return Math.Max(0, VertexCount - 1);
            }

            var index = VertexCount;
            _vertexIndex[key] = index;
            Vertices.Add(x);
            Vertices.Add(y);
            Vertices.Add(z);
            return index;
        }
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
