using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using Autodesk.AutoCAD.ApplicationServices.Core;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.EditorInput;
using Autodesk.AutoCAD.Geometry;
using Autodesk.AutoCAD.Runtime;

[assembly: CommandClass(typeof(LES.AutoCAD.JsonExport.LesJsonExportCommand))]

namespace LES.AutoCAD.JsonExport;

public sealed class LesJsonExportCommand
{
    [CommandMethod("LESJSONEXPORT")]
    public void Export()
    {
        var document = Application.DocumentManager.MdiActiveDocument;
        if (document == null)
        {
            return;
        }

        var editor = document.Editor;
        try
        {
            var database = document.Database;
            var defaultName = $"{SafeStem(database.Filename, "autocad_model")}.cad_bim_graph.json";
            var saveOptions = new PromptSaveFileOptions("\nSave LES CAD/BIM JSON")
            {
                Filter = "JSON (*.json)|*.json",
                InitialFileName = defaultName,
            };
            var saveResult = editor.GetFileNameForSave(saveOptions);
            if (saveResult.Status != PromptStatus.OK)
            {
                editor.WriteMessage("\nLESJSONEXPORT cancelled.");
                return;
            }

            var payload = BuildPayload(database);
            var json = LesJsonWriter.Serialize(payload);
            File.WriteAllText(saveResult.StringResult, json, Encoding.UTF8);
            editor.WriteMessage($"\nLESJSONEXPORT wrote {payload.Elements.Count} entities to {saveResult.StringResult}");
        }
        catch (System.Exception error)
        {
            editor.WriteMessage($"\nLESJSONEXPORT failed: {error.Message}");
        }
    }

    [CommandMethod("LESJSONPUSH")]
    public void Push()
    {
        var document = Application.DocumentManager.MdiActiveDocument;
        if (document == null)
        {
            return;
        }

        var editor = document.Editor;
        try
        {
            var payload = BuildPayload(document.Database);
            var settings = LesUploadSettings.Load();
            var result = LesUploader.UploadAsync(payload, "autocad", settings).GetAwaiter().GetResult();
            if (result.Success)
            {
                editor.WriteMessage($"\nLESJSONPUSH imported {payload.Elements.Count} entities via {result.Url}");
                editor.WriteMessage($"\nLES response: {result.ResponseSummary}");
                return;
            }

            var fallback = FallbackOutputPath(document.Database);
            File.WriteAllText(fallback, LesJsonWriter.Serialize(payload), Encoding.UTF8);
            editor.WriteMessage($"\nLESJSONPUSH failed: {result.Error}");
            editor.WriteMessage($"\nSaved fallback JSON: {fallback}");
        }
        catch (System.Exception error)
        {
            editor.WriteMessage($"\nLESJSONPUSH failed: {error.Message}");
        }
    }

    [CommandMethod("LESJSONCONFIG")]
    public void Config()
    {
        var document = Application.DocumentManager.MdiActiveDocument;
        if (document == null)
        {
            return;
        }

        var settings = LesUploadSettings.Load();
        var editor = document.Editor;
        editor.WriteMessage($"\nCurrent LES URLs: {string.Join(",", settings.LesUrls)}");
        if (!PromptUrls(editor, "\nLES base URLs, comma-separated", settings.LesUrls, out var lesUrls))
        {
            editor.WriteMessage("\nLESJSONCONFIG cancelled.");
            return;
        }

        settings.LesUrls = lesUrls;
        if (settings.LesUrls.Count == 0)
        {
            settings.LesUrls = LesUploadSettings.DefaultUrls();
        }

        editor.WriteMessage($"\nCurrent custom POST URLs: {string.Join(",", settings.CustomUrls)}");
        if (!PromptUrls(editor, "\nCustom POST URLs or bases, comma-separated", settings.CustomUrls, out var customUrls))
        {
            editor.WriteMessage("\nLESJSONCONFIG cancelled.");
            return;
        }

        settings.CustomUrls = customUrls;

        editor.WriteMessage($"\nCurrent local output dir: {settings.ResolveLocalOutputDir()}");
        var localPrompt = new PromptStringOptions("\nLocal output dir, blank for Documents")
        {
            AllowSpaces = true,
        };
        var local = editor.GetString(localPrompt);
        if (local.Status != PromptStatus.OK)
        {
            editor.WriteMessage("\nLESJSONCONFIG cancelled.");
            return;
        }

        settings.LocalOutputDir = local.StringResult.Trim();
        settings.Save();
        editor.WriteMessage($"\nLES exporter config saved: {LesUploadSettings.ConfigPath}");
    }

    internal static CadBimGraph BuildPayload(Database database)
    {
        var sourcePath = database.Filename ?? string.Empty;
        var stem = SafeStem(sourcePath, "autocad_model");
        var modelId = $"dwg:{stem}";
        var graph = new CadBimGraph
        {
            Id = modelId,
            Type = "DWGModel",
            Name = stem,
            SourceFormat = "dwg",
            SourcePath = sourcePath,
            ExtractedAt = DateTimeOffset.UtcNow.ToString("O"),
            Properties = new Dictionary<string, object?>
            {
                ["database_fingerprint_guid"] = database.FingerprintGuid.ToString(),
                ["measurement"] = database.Measurement.ToString(),
                ["insunits"] = database.Insunits.ToString(),
            },
        };

        using var transaction = database.TransactionManager.StartTransaction();
        var blockTable = (BlockTable)transaction.GetObject(database.BlockTableId, OpenMode.ForRead);
        var modelSpace = (BlockTableRecord)transaction.GetObject(blockTable[BlockTableRecord.ModelSpace], OpenMode.ForRead);

        foreach (ObjectId objectId in modelSpace)
        {
            if (transaction.GetObject(objectId, OpenMode.ForRead, false) is not Entity entity)
            {
                continue;
            }

            var element = EntityToElement(entity, transaction);
            graph.Elements.Add(element);
            graph.Relations.Add(new CadBimRelation
            {
                SourceId = modelId,
                TargetId = element.Id,
                RelationType = "contains",
            });
        }

        graph.Properties["entity_count"] = graph.Elements.Count;
        graph.Properties["layers"] = graph.Elements.Select(e => e.Layer).Where(v => !string.IsNullOrWhiteSpace(v)).Distinct().OrderBy(v => v).ToArray();
        transaction.Commit();
        return graph;
    }

    private static CadBimElement EntityToElement(Entity entity, Transaction transaction)
    {
        var type = entity.GetRXClass()?.DxfName ?? entity.GetType().Name;
        var element = new CadBimElement
        {
            Id = entity.Handle.ToString(),
            Type = type,
            Name = EntityName(entity, type),
            Layer = entity.Layer ?? string.Empty,
            Category = IsAnnotation(type) ? "Annotation" : "Geometry",
            Family = BlockName(entity, transaction),
            Material = entity.Material ?? string.Empty,
            Properties = CommonProperties(entity, type),
        };

        AddGeometryProperties(entity, element.Properties, transaction);
        return element;
    }

    private static Dictionary<string, object?> CommonProperties(Entity entity, string type)
    {
        return new Dictionary<string, object?>
        {
            ["handle"] = entity.Handle.ToString(),
            ["entity_type"] = type,
            ["layer"] = entity.Layer ?? string.Empty,
            ["color_index"] = entity.ColorIndex,
            ["linetype"] = entity.Linetype ?? string.Empty,
            ["lineweight"] = entity.LineWeight.ToString(),
        };
    }

    private static void AddGeometryProperties(Entity entity, Dictionary<string, object?> properties, Transaction transaction)
    {
        switch (entity)
        {
            case Line line:
                properties["start"] = Point(line.StartPoint);
                properties["end"] = Point(line.EndPoint);
                break;
            case Circle circle:
                properties["center"] = Point(circle.Center);
                properties["radius"] = circle.Radius;
                break;
            case Arc arc:
                properties["center"] = Point(arc.Center);
                properties["radius"] = arc.Radius;
                properties["start_angle"] = arc.StartAngle;
                properties["end_angle"] = arc.EndAngle;
                break;
            case Polyline polyline:
                var preview = new List<double[]>();
                for (var index = 0; index < Math.Min(polyline.NumberOfVertices, 32); index++)
                {
                    preview.Add(Point(polyline.GetPoint3dAt(index)));
                }
                properties["points_count"] = polyline.NumberOfVertices;
                properties["points_preview"] = preview;
                properties["closed"] = polyline.Closed;
                break;
            case DBText text:
                properties["text"] = text.TextString ?? string.Empty;
                properties["insert"] = Point(text.Position);
                properties["height"] = text.Height;
                break;
            case MText text:
                properties["text"] = text.Contents ?? string.Empty;
                properties["insert"] = Point(text.Location);
                properties["height"] = text.TextHeight;
                break;
            case BlockReference block:
                properties["block_name"] = BlockName(block, transaction);
                properties["insert"] = Point(block.Position);
                properties["rotation"] = block.Rotation;
                properties["scale"] = new[] { block.ScaleFactors.X, block.ScaleFactors.Y, block.ScaleFactors.Z };
                var attributes = BlockAttributes(block, transaction);
                if (attributes.Count > 0)
                {
                    properties["attributes"] = attributes;
                }
                break;
            case Dimension dimension:
                properties["dimension_text"] = dimension.DimensionText ?? string.Empty;
                properties["measurement"] = dimension.Measurement;
                break;
        }
    }

    private static Dictionary<string, string> BlockAttributes(BlockReference block, Transaction transaction)
    {
        var attributes = new Dictionary<string, string>();
        foreach (ObjectId attributeId in block.AttributeCollection)
        {
            if (transaction.GetObject(attributeId, OpenMode.ForRead, false) is AttributeReference attribute)
            {
                attributes[attribute.Tag ?? string.Empty] = attribute.TextString ?? string.Empty;
            }
        }

        return attributes.Where(pair => !string.IsNullOrWhiteSpace(pair.Key)).ToDictionary(pair => pair.Key, pair => pair.Value);
    }

    private static string BlockName(Entity entity, Transaction transaction)
    {
        if (entity is not BlockReference block)
        {
            return string.Empty;
        }

        try
        {
            var recordId = block.DynamicBlockTableRecord.IsNull ? block.BlockTableRecord : block.DynamicBlockTableRecord;
            if (transaction.GetObject(recordId, OpenMode.ForRead, false) is BlockTableRecord record)
            {
                return record.Name ?? string.Empty;
            }
        }
        catch
        {
            return block.Name ?? string.Empty;
        }

        return block.Name ?? string.Empty;
    }

    private static string EntityName(Entity entity, string type)
    {
        return entity switch
        {
            DBText text => Trim(text.TextString, type),
            MText text => Trim(text.Contents, type),
            BlockReference block => Trim(block.Name, "Block reference"),
            Dimension => "Dimension / annotation",
            _ => type,
        };
    }

    private static bool IsAnnotation(string type)
    {
        return string.Equals(type, "TEXT", StringComparison.OrdinalIgnoreCase)
            || string.Equals(type, "MTEXT", StringComparison.OrdinalIgnoreCase)
            || string.Equals(type, "DIMENSION", StringComparison.OrdinalIgnoreCase)
            || string.Equals(type, "LEADER", StringComparison.OrdinalIgnoreCase)
            || string.Equals(type, "MLEADER", StringComparison.OrdinalIgnoreCase);
    }

    private static string Trim(string? value, string fallback)
    {
        var text = (value ?? string.Empty).Replace("\r", " ").Replace("\n", " ").Trim();
        if (text.Length == 0)
        {
            return fallback;
        }

        return text.Length <= 80 ? text : text.Substring(0, 80);
    }

    private static double[] Point(Point3d point)
    {
        return new[] { Math.Round(point.X, 6), Math.Round(point.Y, 6), Math.Round(point.Z, 6) };
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

    private static string FallbackOutputPath(Database database)
    {
        var settings = LesUploadSettings.Load();
        var documents = settings.ResolveLocalOutputDir();
        Directory.CreateDirectory(documents);
        var stem = SafeStem(database.Filename, "autocad_model");
        return Path.Combine(documents, $"{stem}.cad_bim_graph.json");
    }

    private static bool PromptUrls(Editor editor, string message, IReadOnlyCollection<string> current, out List<string> values)
    {
        var prompt = new PromptStringOptions(message)
        {
            AllowSpaces = true,
            DefaultValue = string.Join(",", current),
            UseDefaultValue = current.Count > 0,
        };
        var result = editor.GetString(prompt);
        if (result.Status != PromptStatus.OK)
        {
            values = new List<string>();
            return false;
        }

        values = result.StringResult.Split(',')
            .Select(item => item.Trim())
            .Where(item => item.StartsWith("http://", StringComparison.OrdinalIgnoreCase) || item.StartsWith("https://", StringComparison.OrdinalIgnoreCase))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();
        return true;
    }
}
