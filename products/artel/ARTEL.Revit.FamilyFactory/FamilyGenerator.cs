using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
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

        // Plugin-owned picker (not the OS file dialog): choose plan + FOP.
        var picked = ArtelPlanPicker.Pick();
        if (picked is null)
        {
            return Result.Cancelled;
        }
        var planPath = picked.PlanPath;
        if (!string.IsNullOrWhiteSpace(picked.SharedParamsPath))
        {
            Environment.SetEnvironmentVariable("ARTEL_SHARED_PARAMS_FILE", picked.SharedParamsPath);
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
            // Идемпотентность геометрии: снести ранее сгенерированные тела, чтобы повторный
            // запуск не множил солиды (иначе при каждом «Сгенерировать» геометрия стопкой).
            if (operations.Any(o => Str(o, "op") == "create_extrusion"))
            {
                var priorSolids = new FilteredElementCollector(document).OfClass(typeof(GenericForm)).ToElementIds();
                if (priorSolids.Count > 0)
                {
                    document.Delete(priorSolids);
                    results.Add(Record("clear_geometry", "", "ok", $"Снесено ранее сгенерированных тел: {priorSolids.Count}."));
                }
            }
            // Контекст корпуса (halfW, halfD, height в футах) — фичи (дверь/полки/задняя
            // стенка) размещаются относительно него. Корпус компилятор эмитит первым.
            var body = new double[] { 0, 0, 0 };
            foreach (var op in operations.Where(o => Str(o, "op") == "create_extrusion"))
            {
                results.Add(RunExtrusion(op, document, familyManager, body));
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
            results.Add(Record("transaction", "", "failed", $"{error.GetType().Name}: {error.Message}", error));
        }

        var executed = results.Count(r => Convert.ToString(r["status"]) == "ok");
        var failed = results.Count(r => Convert.ToString(r["status"]) == "failed");
        try { WriteLog(Str(plan, "plan_id"), results, failed); } catch { /* лог best-effort */ }
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

    // Человекочитаемый rolling-лог рядом с отчётами (%APPDATA%\ARTEL\family_factory\artel_generate.log).
    // Со стектрейсами по упавшим операциям — чтобы диагностировать, не дёргая оператора.
    private static void WriteLog(string planId, List<Dictionary<string, object?>> results, int failed)
    {
        var dir = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "ARTEL", "family_factory");
        Directory.CreateDirectory(dir);
        var sb = new StringBuilder();
        sb.AppendLine($"[{DateTimeOffset.Now:yyyy-MM-dd HH:mm:ss}] plan={planId} {(failed > 0 ? "FAIL" : "PASS")} ops={results.Count} failed={failed}");
        foreach (var r in results)
        {
            sb.AppendLine($"  {Convert.ToString(r.GetValueOrDefault("status")),-8} {Convert.ToString(r.GetValueOrDefault("op"))}/{Convert.ToString(r.GetValueOrDefault("target"))}: {Convert.ToString(r.GetValueOrDefault("message"))}");
            if (r.TryGetValue("detail", out var detail) && detail != null)
            {
                sb.AppendLine("      " + Convert.ToString(detail)?.Replace("\n", "\n      "));
            }
        }
        File.AppendAllText(Path.Combine(dir, "artel_generate.log"), sb.ToString() + "\n", Encoding.UTF8);
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
            var existing = familyManager.get_Parameter(name);

            if (Str(op, "op") == "add_shared_parameter")
            {
                // Идемпотентно + параметр обязан быть ОБЩИМ: уже shared — пропускаем;
                // существует как НЕ shared (отсюда «параметры не общие») — снимаем и пересоздаём.
                if (existing != null)
                {
                    if (existing.IsShared)
                    {
                        return Record("add_shared_parameter", name, "ok", "Уже есть как shared (идемпотентно).");
                    }
                    familyManager.RemoveParameter(existing);
                }
                var guid = Str(op, "guid");
                var external = EnsureSharedDefinition(application, name, guid, Str(op, "data_type"), out var source);
                if (external is null)
                {
                    return Record("add_shared_parameter", name, "failed",
                        "Не удалось получить/создать shared-определение (нет GUID и нет ФОП-файла).");
                }
                familyManager.AddParameter(external, groupType, isInstance);
                return Record("add_shared_parameter", name, "ok",
                    $"Shared-параметр {(existing != null ? "пересоздан как общий" : "добавлен")} (GUID {external.GUID}, источник: {source}).");
            }

            // family parameter — идемпотентно
            if (existing != null)
            {
                return Record("add_family_parameter", name, "ok", "Уже есть (идемпотентно).");
            }
            var specType = SpecTypeFor(Str(op, "data_type"));
            familyManager.AddParameter(name, groupType, specType, isInstance);
            return Record("add_family_parameter", name, "ok", $"Family parameter added ({Str(op, "data_type")}).");
        }
        catch (Exception error)
        {
            return Record(Str(op, "op"), name, "failed", $"{error.GetType().Name}: {error.Message}", error);
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
            return Record("set_formula", name, "failed", $"{error.GetType().Name}: {error.Message}", error);
        }
    }

    private static Dictionary<string, object?> RunCreateType(JsonElement op, FamilyManager familyManager)
    {
        var typeName = Str(op, "name");
        try
        {
            // Идемпотентно: тип уже есть — выбираем и обновляем значения; иначе создаём.
            var existing = familyManager.Types.Cast<FamilyType>().FirstOrDefault(t => t.Name == typeName);
            if (existing != null)
            {
                familyManager.CurrentType = existing;
            }
            else
            {
                familyManager.NewType(typeName);
            }
            foreach (var value in Items(Prop(op, "values")))
            {
                var parameter = familyManager.get_Parameter(Str(value, "parameter"));
                if (parameter is null)
                {
                    continue;
                }
                SetParameterValue(familyManager, parameter, Prop(value, "value"));
            }
            return Record("create_type", typeName, "ok",
                existing != null ? "Тип обновлён (идемпотентно)." : "Тип создан, значения заданы.");
        }
        catch (Exception error)
        {
            return Record("create_type", typeName, "failed", $"{error.GetType().Name}: {error.Message}", error);
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
            return Record("assign_material", name, "failed", $"{error.GetType().Name}: {error.Message}", error);
        }
    }

    private static Dictionary<string, object?> RunExtrusion(
        JsonElement op, Document document, FamilyManager familyManager, double[] body)
    {
        var id = Str(op, "id");
        try
        {
            var isBody = Str(op, "role") == "body" || id == "body";
            var placement = Prop(op, "placement");
            var plane = Str(placement, "plane");
            if (string.IsNullOrEmpty(plane))
            {
                plane = "level";
            }
            if (!isBody && body[2] <= 0)
            {
                return Record("create_extrusion", id, "skipped", "Нет корпуса для размещения элемента.");
            }
            var profile = Prop(op, "profile");
            var shape = Str(profile, "shape");

            // Вертикальная панель на передней/задней грани корпуса (дверь, задняя стенка).
            if (plane == "front" || plane == "back")
            {
                var panelW = NominalFeet(Prop(profile, "width"), familyManager, 1000);
                var panelH = NominalFeet(Prop(profile, "depth"), familyManager, 1800); // depth-поле = высота
                var thickness = NominalFeet(Prop(op, "extrusion"), familyManager, 18);
                var y = plane == "front" ? -body[1] : body[1];
                var sp = SketchPlane.Create(document, Plane.CreateByNormalAndOrigin(XYZ.BasisY, new XYZ(0, y, 0)));
                var hw = panelW / 2.0;
                var loop = new CurveArray();
                loop.Append(Line.CreateBound(new XYZ(-hw, y, 0), new XYZ(hw, y, 0)));
                loop.Append(Line.CreateBound(new XYZ(hw, y, 0), new XYZ(hw, y, panelH)));
                loop.Append(Line.CreateBound(new XYZ(hw, y, panelH), new XYZ(-hw, y, panelH)));
                loop.Append(Line.CreateBound(new XYZ(-hw, y, panelH), new XYZ(-hw, y, 0)));
                var profiles = new CurveArrArray();
                profiles.Append(loop);
                var end = plane == "front" ? -thickness : thickness; // наружу грани
                document.FamilyCreate.NewExtrusion(true, profiles, sp, end);
                document.Regenerate();
                return Record("create_extrusion", id, "ok",
                    $"{(plane == "front" ? "Дверь" : "Задняя стенка")} построена на {plane}-грани корпуса.");
            }

            // Горизонтальная плоскость: корпус (z=0) или полка (z=доля·высота).
            var z = isBody ? 0.0 : NumOr(Prop(placement, "z_fraction"), 0.0) * body[2];
            var sketchPlane = SketchPlane.Create(document, Plane.CreateByNormalAndOrigin(XYZ.BasisZ, new XYZ(0, 0, z)));
            double halfW = 0, halfD = 0;
            var loopL = new CurveArray();
            if (shape == "circle")
            {
                var radius = NominalFeet(Prop(profile, "diameter"), familyManager, 300) / 2.0;
                loopL.Append(Arc.Create(new XYZ(0, 0, z), radius, 0, 2 * Math.PI, XYZ.BasisX, XYZ.BasisY));
            }
            else
            {
                halfW = NominalFeet(Prop(profile, "width"), familyManager, 1000) / 2.0;
                halfD = NominalFeet(Prop(profile, "depth"), familyManager, 1000) / 2.0;
                loopL.Append(Line.CreateBound(new XYZ(-halfW, -halfD, z), new XYZ(halfW, -halfD, z)));
                loopL.Append(Line.CreateBound(new XYZ(halfW, -halfD, z), new XYZ(halfW, halfD, z)));
                loopL.Append(Line.CreateBound(new XYZ(halfW, halfD, z), new XYZ(-halfW, halfD, z)));
                loopL.Append(Line.CreateBound(new XYZ(-halfW, halfD, z), new XYZ(-halfW, -halfD, z)));
            }
            var profilesL = new CurveArrArray();
            profilesL.Append(loopL);
            var thickOrHeight = NominalFeet(Prop(op, "extrusion"), familyManager, isBody ? 1000 : 18);
            var extrusion = document.FamilyCreate.NewExtrusion(true, profilesL, sketchPlane, thickOrHeight);
            document.Regenerate();

            if (!isBody)
            {
                return Record("create_extrusion", id, "ok",
                    $"Полка построена (z={Math.Round(NumOr(Prop(placement, "z_fraction"), 0.0), 2)}·H).");
            }

            // Корпус: запомнить габариты + флекс высоты/ширины/глубины.
            body[0] = halfW;
            body[1] = halfD;
            body[2] = thickOrHeight;
            var flex = new List<string>();
            var heightName = ParamName(Prop(op, "extrusion"));
            if (heightName != null)
            {
                var heightParam = familyManager.get_Parameter(heightName);
                var endParam = extrusion.get_Parameter(BuiltInParameter.EXTRUSION_END_PARAM);
                if (heightParam != null && endParam != null)
                {
                    familyManager.AssociateElementParameterToFamilyParameter(endParam, heightParam);
                    flex.Add($"высота→{heightName}");
                }
            }
            if (shape != "circle")
            {
                var view = PlanView(document);
                if (view != null)
                {
                    var faces = CollectPlanarFaces(extrusion);
                    var margin = UnitUtils.ConvertToInternalUnits(150, UnitTypeId.Millimeters);
                    TryDimension(document, familyManager, view, faces, XYZ.BasisX,
                        new XYZ(0, -halfD - margin, 0), halfW + margin, ParamName(Prop(profile, "width")), "ширина", flex);
                    TryDimension(document, familyManager, view, faces, XYZ.BasisY,
                        new XYZ(halfW + margin, 0, 0), halfD + margin, ParamName(Prop(profile, "depth")), "глубина", flex);
                    document.Regenerate();
                }
            }
            return Record("create_extrusion", id, "ok",
                $"Корпус '{shape}' построен ({(flex.Count > 0 ? string.Join(", ", flex) : "номинал")}).");
        }
        catch (Exception error)
        {
            return Record("create_extrusion", id, "failed", $"{error.GetType().Name}: {error.Message}", error);
        }
    }

    private static double NumOr(JsonElement element, double fallback)
    {
        return element.ValueKind == JsonValueKind.Number ? element.GetDouble() : fallback;
    }

    private static string? ParamName(JsonElement dimRef)
    {
        return dimRef.ValueKind == JsonValueKind.Object
               && dimRef.TryGetProperty("parameter", out var p)
               && p.ValueKind == JsonValueKind.String
            ? p.GetString()
            : null;
    }

    private static View? PlanView(Document document)
    {
        return new FilteredElementCollector(document)
            .OfClass(typeof(ViewPlan))
            .Cast<ViewPlan>()
            .FirstOrDefault(v => !v.IsTemplate);
    }

    private static List<PlanarFace> CollectPlanarFaces(Extrusion extrusion)
    {
        var faces = new List<PlanarFace>();
        var options = new Options { ComputeReferences = true };
        foreach (var geometry in extrusion.get_Geometry(options))
        {
            if (geometry is Solid solid)
            {
                foreach (Face face in solid.Faces)
                {
                    if (face is PlanarFace planar)
                    {
                        faces.Add(planar);
                    }
                }
            }
        }
        return faces;
    }

    private static void TryDimension(
        Document document, FamilyManager familyManager, View view, List<PlanarFace> faces,
        XYZ normal, XYZ offset, double halfLength, string? paramName, string label, List<string> flex)
    {
        if (paramName is null)
        {
            return;
        }
        try
        {
            var pos = faces.FirstOrDefault(f => f.FaceNormal.IsAlmostEqualTo(normal));
            var neg = faces.FirstOrDefault(f => f.FaceNormal.IsAlmostEqualTo(normal.Negate()));
            if (pos is null || neg is null)
            {
                return;
            }
            var references = new ReferenceArray();
            references.Append(neg.Reference);
            references.Append(pos.Reference);
            var dimension = document.FamilyCreate.NewDimension(
                view,
                Line.CreateBound(offset.Subtract(normal.Multiply(halfLength)), offset.Add(normal.Multiply(halfLength))),
                references);
            var parameter = familyManager.get_Parameter(paramName);
            if (parameter != null)
            {
                dimension.FamilyLabel = parameter;
                flex.Add($"{label}→{paramName}");
            }
        }
        catch
        {
            // Dimensioning is best-effort; the solid is already created.
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

    // Guarantee a shared-parameter definition bound to the plan's GUID. Prefer the
    // configured FOP file; if the GUID/name is absent there, create the definition with
    // the EXACT GUID from the plan in an ARTEL shared-parameter file. This is what makes
    // the family carry the canonical ADSK_*/FOP shared parameters with the right GUID.
    private static ExternalDefinition? EnsureSharedDefinition(
        Autodesk.Revit.ApplicationServices.Application application,
        string name, string guid, string dataType, out string source)
    {
        source = "не найдено";

        // 1) Configured FOP file (real ФОП) — match by name or GUID.
        var fopFile = Environment.GetEnvironmentVariable("ARTEL_SHARED_PARAMS_FILE");
        if (!string.IsNullOrWhiteSpace(fopFile) && File.Exists(fopFile))
        {
            application.SharedParametersFilename = fopFile;
            var fromFop = FindInFile(application.OpenSharedParameterFile(), name, guid);
            if (fromFop is not null)
            {
                source = "ФОП-файл";
                return fromFop;
            }
        }

        // 2) Create the definition with the exact GUID from the plan in an ARTEL file.
        if (!Guid.TryParse(guid, out var parsedGuid))
        {
            return null;
        }
        var artelFile = Path.Combine(Path.GetTempPath(), "ARTEL", "artel_shared_params.txt");
        Directory.CreateDirectory(Path.GetDirectoryName(artelFile)!);
        if (!File.Exists(artelFile))
        {
            File.WriteAllText(artelFile, "# ARTEL shared parameters\n");
        }
        application.SharedParametersFilename = artelFile;
        var definitionFile = application.OpenSharedParameterFile();
        if (definitionFile is null)
        {
            return null;
        }
        var existing = FindInFile(definitionFile, name, guid);
        if (existing is not null)
        {
            source = "ARTEL-файл";
            return existing;
        }
        var group = definitionFile.Groups.get_Item("ARTEL") ?? definitionFile.Groups.Create("ARTEL");
        var options = new ExternalDefinitionCreationOptions(name, SpecTypeFor(dataType)) { GUID = parsedGuid };
        source = "создан с GUID плана";
        return group.Definitions.Create(options) as ExternalDefinition;
    }

    private static ExternalDefinition? FindInFile(DefinitionFile? definitionFile, string name, string guid)
    {
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

    private static Dictionary<string, object?> Record(string op, string target, string status, string message, Exception? error = null)
    {
        var rec = new Dictionary<string, object?>
        {
            ["op"] = op,
            ["target"] = target,
            ["status"] = status,
            ["message"] = message
        };
        if (error != null)
        {
            rec["detail"] = error.ToString();  // полный стектрейс — в лог
        }
        return rec;
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
