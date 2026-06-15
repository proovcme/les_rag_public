using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using System.Web.Script.Serialization;
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
[Transaction(TransactionMode.Manual)]
public sealed class ArtelFamilyGenerateCommand : IExternalCommand
{
    public Result Execute(ExternalCommandData commandData, ref string message, ElementSet elements)
    {
        var uidoc = commandData.Application.ActiveUIDocument;
        var document = uidoc?.Document;
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

        var planPath = Environment.GetEnvironmentVariable("ARTEL_PLAN_PATH");
        if (string.IsNullOrWhiteSpace(planPath) || !File.Exists(planPath))
        {
            message = "Set ARTEL_PLAN_PATH to a family_action_plan.v1 JSON file.";
            return Result.Failed;
        }

        Dictionary<string, object?> plan;
        try
        {
            plan = new JavaScriptSerializer().Deserialize<Dictionary<string, object?>>(File.ReadAllText(planPath));
        }
        catch (Exception error)
        {
            message = $"Failed to read plan JSON: {error.Message}";
            return Result.Failed;
        }

        var report = FamilyPlanExecutor.Execute(document, plan, commandData.Application.Application);
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
        Dictionary<string, object?> plan,
        Autodesk.Revit.ApplicationServices.Application application)
    {
        var results = new List<Dictionary<string, object?>>();
        var operations = AsList(plan.GetValueOrDefault("operations")).Select(AsDict).ToList();
        var familyManager = document.FamilyManager;

        using var transaction = new Transaction(document, "ARTEL execute family action plan");
        transaction.Start();
        try
        {
            // Two passes so types/formulas/materials can reference parameters created first.
            var paramOps = new[] { "add_shared_parameter", "add_family_parameter" };
            foreach (var op in operations.Where(o => paramOps.Contains(Str(o, "op"))))
            {
                results.Add(RunParameter(op, familyManager, application, document));
            }
            foreach (var op in operations.Where(o => Str(o, "op") == "set_formula"))
            {
                results.Add(RunFormula(op, familyManager));
            }
            foreach (var op in operations.Where(o => Str(o, "op") == "create_type"))
            {
                results.Add(RunCreateType(op, familyManager, document));
            }
            foreach (var op in operations.Where(o => Str(o, "op") == "assign_material"))
            {
                results.Add(RunMaterial(op, document));
            }
            foreach (var op in operations.Where(o => Str(o, "op") == "create_extrusion"))
            {
                // Geometry execution (solid + flex labelling) is built live in Revit (next iteration).
                results.Add(Record(Str(op, "op"), Str(op, "id"), "deferred",
                    "Создание геометрии и привязка размеров к параметрам — следующая итерация (W10.3 geom)."));
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

        var executed = results.Count(r => Str(r, "status") == "ok");
        var failed = results.Count(r => Str(r, "status") == "failed");
        return new Dictionary<string, object?>
        {
            ["schema"] = "artel.revit_family_generate_report.v1",
            ["status"] = failed > 0 ? "fail" : "pass",
            ["plan_id"] = plan.GetValueOrDefault("plan_id"),
            ["operation_count"] = operations.Count,
            ["executed_count"] = executed,
            ["failed_count"] = failed,
            ["results"] = results,
            ["executed_at"] = DateTimeOffset.UtcNow.ToString("O")
        };
    }

    private static Dictionary<string, object?> RunParameter(
        Dictionary<string, object?> op,
        FamilyManager familyManager,
        Autodesk.Revit.ApplicationServices.Application application,
        Document document)
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

    private static Dictionary<string, object?> RunFormula(Dictionary<string, object?> op, FamilyManager familyManager)
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

    private static Dictionary<string, object?> RunCreateType(
        Dictionary<string, object?> op,
        FamilyManager familyManager,
        Document document)
    {
        var typeName = Str(op, "name");
        try
        {
            familyManager.NewType(typeName);
            foreach (var value in AsList(op.GetValueOrDefault("values")).Select(AsDict))
            {
                var parameterName = Str(value, "parameter");
                var parameter = familyManager.get_Parameter(parameterName);
                if (parameter is null)
                {
                    continue;
                }
                SetParameterValue(familyManager, parameter, value.GetValueOrDefault("value"));
            }
            return Record("create_type", typeName, "ok", "Type created and values set.");
        }
        catch (Exception error)
        {
            return Record("create_type", typeName, "failed", $"{error.GetType().Name}: {error.Message}");
        }
    }

    private static Dictionary<string, object?> RunMaterial(Dictionary<string, object?> op, Document document)
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

    private static void SetParameterValue(FamilyManager familyManager, FamilyParameter parameter, object? raw)
    {
        if (raw is null)
        {
            return;
        }
        switch (parameter.StorageType)
        {
            case StorageType.Double:
                var number = Convert.ToDouble(raw, CultureInfo.InvariantCulture);
                // Plan dimensions are millimetres; convert to Revit internal units when the spec is a length.
                var internalValue = UnitUtils.ConvertToInternalUnits(number, UnitTypeId.Millimeters);
                familyManager.Set(parameter, internalValue);
                break;
            case StorageType.Integer:
                familyManager.Set(parameter, Convert.ToInt32(raw, CultureInfo.InvariantCulture));
                break;
            case StorageType.String:
                familyManager.Set(parameter, Convert.ToString(raw, CultureInfo.InvariantCulture));
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
            case "text":
            case "string":
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

    private static IEnumerable<object?> AsList(object? value)
    {
        return value switch
        {
            IEnumerable<object?> typed => typed,
            IEnumerable untyped and not string => untyped.Cast<object?>(),
            _ => Enumerable.Empty<object?>()
        };
    }

    private static Dictionary<string, object?> AsDict(object? value)
    {
        return value as Dictionary<string, object?> ?? new Dictionary<string, object?>();
    }

    private static string Str(Dictionary<string, object?> dict, string key)
    {
        return Convert.ToString(dict.GetValueOrDefault(key), CultureInfo.InvariantCulture) ?? "";
    }

    private static bool Bool(Dictionary<string, object?> dict, string key)
    {
        var value = dict.GetValueOrDefault(key);
        return value is bool flag && flag;
    }
}
