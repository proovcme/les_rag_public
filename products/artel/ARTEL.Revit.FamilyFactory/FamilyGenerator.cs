using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text.Json;
using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;

namespace ARTEL.Revit.FamilyFactory;

// W10.3 — execute a deterministic family_action_plan.v1 (compiled on the LES/oracle
// side, schema in schema/family_action_plan.schema.json) inside a Revit family
// document. Parameters/formulas/types/materials are applied via FamilyManager;
// geometry (create_extrusion) is recorded for the next iteration (flex labelling is
// built live in Revit). Every operation is best-effort and reported per-op so the
// build/run loop on Legion sees exactly what landed.
//
// Targets Revit 2025 (.NET 8): the plan is parsed with System.Text.Json and navigated
// through JsonElement; the report uses Dictionary<string, object?> for WriteJson.
[Transaction(TransactionMode.Manual)]
public sealed class ArtelFamilyGenerateCommand : IExternalCommand
{
    public Result Execute(ExternalCommandData commandData, ref string message, ElementSet elements)
    {
        var document = commandData.Application.ActiveUIDocument?.Document;
        if (document is null)
        {
            message = "No active Revit document.";
            return Result.Failed;
        }
        if (!document.IsFamilyDocument)
        {
            message = "Active document is not a family document (.rfa/.rft).";
            return Result.Failed;
        }

        // Plan file: env override, else interactive picker (no console needed).
        var planPath = Environment.GetEnvironmentVariable("ARTEL_PLAN_PATH");
        if (string.IsNullOrWhiteSpace(planPath) || !File.Exists(planPath))
        {
            var dlg = new Microsoft.Win32.OpenFileDialog
            {
                Title = "ARTEL: выберите план действий (family_action_plan.v1)",
                Filter = "ARTEL action plan (*.json)|*.json|Все файлы (*.*)|*.*"
            };
            if (dlg.ShowDialog() != true)
            {
                return Result.Cancelled;
            }
            planPath = dlg.FileName;
        }

        // Shared-parameter (FOP) file: env override, else optional picker.
        if (string.IsNullOrWhiteSpace(Environment.GetEnvironmentVariable("ARTEL_SHARED_PARAMS_FILE")))
        {
            var fop = new Microsoft.Win32.OpenFileDialog
            {
                Title = "ARTEL: файл ФОП (shared parameters) — Отмена, если не нужен",
                Filter = "Revit shared parameters (*.txt)|*.txt|Все файлы (*.*)|*.*"
            };
            if (fop.ShowDialog() == true)
            {
                Environment.SetEnvironmentVariable("ARTEL_SHARED_PARAMS_FILE", fop.FileName);
            }
        }

        Dictionary<string, object?> report;
        try
        {
            using var planDoc = JsonDocument.Parse(File.ReadAllText(planPath));
            report = FamilyPlanExecutor.Execute(document, planDoc.RootElement, commandData.Application.Application);
        }
        catch (Exception error)
        {
            message = $"Failed to read/execute plan JSON: {error.Message}";
            return Result.Failed;
        }

        var reportPath = FamilyFactoryPaths.WriteJson("generate", report);
        TaskDialog.Show("ARTEL Family Generate",
            $"Status: {report["status"]}\nExecuted: {report["executed_count"]}/{report["operation_count"]}\nReport:\n{reportPath}");
        return Result.Succeeded;
    }
}

internal static class FamilyPlanExecutor
{
    public static Dictionary<string, object?> Execute(
        Document document,
        JsonElement plan,
        Autodesk.Revit.ApplicationServices.Application application)
    {
        var results = new List<Dictionary<string, object?>>();
        var operations = Items(Prop(plan, "operations")).ToList();
        var familyManager = document.FamilyManager;

        using var transaction = new Transaction(document, "ARTEL execute family action plan");
        transaction.Start();
        try
        {
            // Ordered passes so types/formulas/materials can reference parameters created first.
            foreach (var op in operations.Where(o => Str(o, "op") is "add_shared_parameter" or "add_family_parameter"))
            {
                results.Add(RunParameter(op, familyManager, application));
            }
            foreach (var op in operations.Where(o => Str(o, "op") == "set_formula"))
            {
                results.Add(RunFormula(op, familyManager));
            }
            foreach (var op in operations.Where(o => Str(o, "op") == "create_type"))
            {
                results.Add(RunCreateType(op, familyManager));
            }
            foreach (var op in operations.Where(o => Str(o, "op") == "assign_material"))
            {
                results.Add(RunMaterial(op, document));
            }
            // Sizing geometry from the first type's nominal values where available.
            var firstType = familyManager.Types.Cast<FamilyType>().FirstOrDefault();
            if (firstType != null)
            {
                familyManager.CurrentType = firstType;
            }
            foreach (var op in operations.Where(o => Str(o, "op") == "create_extrusion"))
            {
                results.Add(RunExtrusion(op, document, familyManager));
            }

            document.Regenerate();
            transaction.Commit();
        }
        catch (Exception error)
        {
            if (transaction.HasStarted())
            {
                transaction.RollBack();
            }
            results.Add(Record("transaction", "", "failed", $"{error.GetType().Name}: {error.Message}"));
        }

        var executed = results.Count(r => Convert.ToString(r["status"]) == "ok");
        var failed = results.Count(r => Convert.ToString(r["status"]) == "failed");
        return new Dictionary<string, object?>
        {
            ["schema"] = "artel.revit_family_generate_report.v1",
            ["status"] = failed > 0 ? "fail" : "pass",
            ["plan_id"] = Str(plan, "plan_id"),
            ["operation_count"] = operations.Count,
            ["executed_count"] = executed,
            ["failed_count"] = failed,
            ["results"] = results,
            ["executed_at"] = DateTimeOffset.UtcNow.ToString("O")
        };
    }

    private static Dictionary<string, object?> RunParameter(
        JsonElement op,
        FamilyManager familyManager,
        Autodesk.Revit.ApplicationServices.Application application)
    {
        var name = Str(op, "name");
        try
        {
            var groupType = GroupTypeFor(Str(op, "group"));
            var isInstance = Bool(op, "is_instance");

            if (Str(op, "op") == "add_shared_parameter")
            {
                var external = FindExternalDefinition(application, name, Str(op, "guid"));
                if (external is null)
                {
                    return Record("add_shared_parameter", name, "failed",
                        "Shared definition not found; set ARTEL_SHARED_PARAMS_FILE to the FOP .txt.");
                }
                familyManager.AddParameter(external, groupType, isInstance);
                return Record("add_shared_parameter", name, "ok", "Shared parameter added.");
            }

            var specType = SpecTypeFor(Str(op, "data_type"));
            familyManager.AddParameter(name, groupType, specType, isInstance);
            return Record("add_family_parameter", name, "ok", $"Family parameter added ({Str(op, "data_type")}).");
        }
        catch (Exception error)
        {
            return Record(Str(op, "op"), name, "failed", $"{error.GetType().Name}: {error.Message}");
        }
    }

    private static Dictionary<string, object?> RunFormula(JsonElement op, FamilyManager familyManager)
    {
        var name = Str(op, "parameter");
        try
        {
            var parameter = familyManager.get_Parameter(name);
            if (parameter is null)
            {
                return Record("set_formula", name, "failed", "Parameter not found.");
            }
            familyManager.SetFormula(parameter, Str(op, "formula"));
            return Record("set_formula", name, "ok", "Formula set.");
        }
        catch (Exception error)
        {
            return Record("set_formula", name, "failed", $"{error.GetType().Name}: {error.Message}");
        }
    }

    private static Dictionary<string, object?> RunCreateType(JsonElement op, FamilyManager familyManager)
    {
        var typeName = Str(op, "name");
        try
        {
            familyManager.NewType(typeName);
            foreach (var value in Items(Prop(op, "values")))
            {
                var parameter = familyManager.get_Parameter(Str(value, "parameter"));
                if (parameter is null)
                {
                    continue;
                }
                SetParameterValue(familyManager, parameter, Prop(value, "value"));
            }
            return Record("create_type", typeName, "ok", "Type created and values set.");
        }
        catch (Exception error)
        {
            return Record("create_type", typeName, "failed", $"{error.GetType().Name}: {error.Message}");
        }
    }

    private static Dictionary<string, object?> RunMaterial(JsonElement op, Document document)
    {
        var name = Str(op, "name");
        try
        {
            var exists = new FilteredElementCollector(document)
                .OfClass(typeof(Material))
                .Cast<Material>()
                .Any(material => string.Equals(material.Name, name, StringComparison.OrdinalIgnoreCase));
            if (!exists)
            {
                Material.Create(document, name);
            }
            return Record("assign_material", name, "ok", "Material ensured (parametric assignment is geometry-bound, next iteration).");
        }
        catch (Exception error)
        {
            return Record("assign_material", name, "failed", $"{error.GetType().Name}: {error.Message}");
        }
    }

    private static Dictionary<string, object?> RunExtrusion(JsonElement op, Document document, FamilyManager familyManager)
    {
        var id = Str(op, "id");
        try
        {
            // Build the primary body solid cleanly first; secondary features (door, etc.)
            // need their own placed planes — handled in a later iteration.
            if (Str(op, "role") != "body" && id != "body")
            {
                return Record("create_extrusion", id, "skipped",
                    "Доп. элемент геометрии (дверь и т.п.) — в работе; пока строим только корпус.");
            }

            var profile = Prop(op, "profile");
            var shape = Str(profile, "shape");
            var sketchPlane = SketchPlane.Create(document, Plane.CreateByNormalAndOrigin(XYZ.BasisZ, XYZ.Zero));
            var endFeet = NominalFeet(Prop(op, "extrusion"), familyManager, 1000);

            var loop = new CurveArray();
            if (shape == "circle")
            {
                var radius = NominalFeet(Prop(profile, "diameter"), familyManager, 300) / 2.0;
                loop.Append(Arc.Create(XYZ.Zero, radius, 0, 2 * Math.PI, XYZ.BasisX, XYZ.BasisY));
            }
            else
            {
                var x = NominalFeet(Prop(profile, "width"), familyManager, 1000) / 2.0;
                var y = NominalFeet(Prop(profile, "depth"), familyManager, 1000) / 2.0;
                var p0 = new XYZ(-x, -y, 0);
                var p1 = new XYZ(x, -y, 0);
                var p2 = new XYZ(x, y, 0);
                var p3 = new XYZ(-x, y, 0);
                loop.Append(Line.CreateBound(p0, p1));
                loop.Append(Line.CreateBound(p1, p2));
                loop.Append(Line.CreateBound(p2, p3));
                loop.Append(Line.CreateBound(p3, p0));
            }
            var profiles = new CurveArrArray();
            profiles.Append(loop);

            var extrusion = document.FamilyCreate.NewExtrusion(true, profiles, sketchPlane, endFeet);
            document.Regenerate();

            var flex = "height nominal";
            var extrusionRef = Prop(op, "extrusion");
            if (extrusionRef.ValueKind == JsonValueKind.Object
                && extrusionRef.TryGetProperty("parameter", out var heightName)
                && heightName.ValueKind == JsonValueKind.String)
            {
                var heightParam = familyManager.get_Parameter(heightName.GetString());
                var endParam = extrusion.get_Parameter(BuiltInParameter.EXTRUSION_END_PARAM);
                if (heightParam != null && endParam != null)
                {
                    familyManager.AssociateElementParameterToFamilyParameter(endParam, heightParam);
                    flex = $"height→{heightName.GetString()}";
                }
            }
            return Record("create_extrusion", id, "ok",
                $"Extrusion '{shape}' created ({flex}; профиль width/depth — номинал, flex-привязка следующим шагом).");
        }
        catch (Exception error)
        {
            return Record("create_extrusion", id, "failed", $"{error.GetType().Name}: {error.Message}");
        }
    }

    private static double NominalFeet(JsonElement dimRef, FamilyManager familyManager, double defaultMm)
    {
        if (dimRef.ValueKind == JsonValueKind.Object)
        {
            if (dimRef.TryGetProperty("constant", out var constant) && constant.ValueKind == JsonValueKind.Number)
            {
                return UnitUtils.ConvertToInternalUnits(constant.GetDouble(), UnitTypeId.Millimeters);
            }
            if (dimRef.TryGetProperty("parameter", out var name) && name.ValueKind == JsonValueKind.String)
            {
                var parameter = familyManager.get_Parameter(name.GetString());
                var currentType = familyManager.CurrentType;
                if (parameter != null && currentType != null)
                {
                    var value = currentType.AsDouble(parameter);
                    if (value.HasValue && value.Value > 0)
                    {
                        return value.Value;
                    }
                }
            }
        }
        return UnitUtils.ConvertToInternalUnits(defaultMm, UnitTypeId.Millimeters);
    }

    private static void SetParameterValue(FamilyManager familyManager, FamilyParameter parameter, JsonElement raw)
    {
        if (raw.ValueKind is JsonValueKind.Undefined or JsonValueKind.Null)
        {
            return;
        }
        switch (parameter.StorageType)
        {
            case StorageType.Double:
                // Plan dimensions are millimetres; convert to Revit internal units.
                familyManager.Set(parameter, UnitUtils.ConvertToInternalUnits(raw.GetDouble(), UnitTypeId.Millimeters));
                break;
            case StorageType.Integer:
                familyManager.Set(parameter, raw.GetInt32());
                break;
            case StorageType.String:
                familyManager.Set(parameter, raw.GetString());
                break;
        }
    }

    private static ExternalDefinition? FindExternalDefinition(
        Autodesk.Revit.ApplicationServices.Application application,
        string name,
        string guid)
    {
        var sharedFile = Environment.GetEnvironmentVariable("ARTEL_SHARED_PARAMS_FILE");
        if (!string.IsNullOrWhiteSpace(sharedFile) && File.Exists(sharedFile))
        {
            application.SharedParametersFilename = sharedFile;
        }

        var definitionFile = application.OpenSharedParameterFile();
        if (definitionFile is null)
        {
            return null;
        }

        foreach (DefinitionGroup group in definitionFile.Groups)
        {
            foreach (Definition definition in group.Definitions)
            {
                if (definition is ExternalDefinition external
                    && (string.Equals(external.Name, name, StringComparison.OrdinalIgnoreCase)
                        || (!string.IsNullOrWhiteSpace(guid) && external.GUID.ToString().Equals(guid, StringComparison.OrdinalIgnoreCase))))
                {
                    return external;
                }
            }
        }
        return null;
    }

    private static ForgeTypeId SpecTypeFor(string dataType)
    {
        switch ((dataType ?? "").Trim().ToLowerInvariant())
        {
            case "length": return SpecTypeId.Length;
            case "area": return SpecTypeId.Area;
            case "volume": return SpecTypeId.Volume;
            case "angle": return SpecTypeId.Angle;
            case "number": return SpecTypeId.Number;
            case "integer": return SpecTypeId.Int.Integer;
            case "yesno": return SpecTypeId.Boolean.YesNo;
            default: return SpecTypeId.String.Text;
        }
    }

    private static ForgeTypeId GroupTypeFor(string group)
    {
        switch ((group ?? "").Trim().ToLowerInvariant())
        {
            case "dimensions": return GroupTypeId.Geometry;
            case "constraints": return GroupTypeId.Constraints;
            case "materials and finishes":
            case "materials": return GroupTypeId.Materials;
            case "identity data": return GroupTypeId.IdentityData;
            case "text": return GroupTypeId.Text;
            default: return GroupTypeId.Data;
        }
    }

    private static Dictionary<string, object?> Record(string op, string target, string status, string message)
    {
        return new Dictionary<string, object?>
        {
            ["op"] = op,
            ["target"] = target,
            ["status"] = status,
            ["message"] = message
        };
    }

    private static JsonElement Prop(JsonElement element, string name)
    {
        return element.ValueKind == JsonValueKind.Object && element.TryGetProperty(name, out var value)
            ? value
            : default;
    }

    private static IEnumerable<JsonElement> Items(JsonElement element)
    {
        return element.ValueKind == JsonValueKind.Array ? element.EnumerateArray() : Enumerable.Empty<JsonElement>();
    }

    private static string Str(JsonElement element, string name)
    {
        var value = Prop(element, name);
        return value.ValueKind switch
        {
            JsonValueKind.String => value.GetString() ?? "",
            JsonValueKind.Number => value.GetRawText(),
            JsonValueKind.True => "true",
            JsonValueKind.False => "false",
            _ => ""
        };
    }

    private static bool Bool(JsonElement element, string name)
    {
        return Prop(element, name).ValueKind == JsonValueKind.True;
    }
}
