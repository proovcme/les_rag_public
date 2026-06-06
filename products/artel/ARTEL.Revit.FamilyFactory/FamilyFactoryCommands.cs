using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Net.Http;
using System.Text;
using System.Web.Script.Serialization;
using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;

namespace ARTEL.Revit.FamilyFactory;

[Transaction(TransactionMode.Manual)]
public sealed class ArtelFamilyExtractCommand : IExternalCommand
{
    public Result Execute(ExternalCommandData commandData, ref string message, ElementSet elements)
    {
        var document = commandData.Application.ActiveUIDocument?.Document;
        if (document is null)
        {
            message = "No active Revit document.";
            return Result.Failed;
        }

        var output = FamilyFactoryExporter.Export(document, commandData.Application.Application.VersionNumber);
        var path = FamilyFactoryPaths.WriteJson("extract", output);
        TaskDialog.Show("ARTEL Family Extract", $"Family metadata exported:\n{path}");
        return Result.Succeeded;
    }
}

[Transaction(TransactionMode.Manual)]
public sealed class ArtelFamilyValidateCommand : IExternalCommand
{
    public Result Execute(ExternalCommandData commandData, ref string message, ElementSet elements)
    {
        var document = commandData.Application.ActiveUIDocument?.Document;
        if (document is null)
        {
            message = "No active Revit document.";
            return Result.Failed;
        }

        var options = ArtelOptions.Load();
        var package = string.IsNullOrWhiteSpace(options.TaskId)
            ? null
            : ArtelClient.TryGetTaskPackage(options);

        var validation = FamilyFactoryValidator.Validate(document, commandData.Application.Application.VersionNumber, package);
        var path = FamilyFactoryPaths.WriteJson("validation", validation);

        string submitMessage;
        if (!string.IsNullOrWhiteSpace(options.TaskId) && !string.IsNullOrWhiteSpace(options.ArtelBaseUrl))
        {
            submitMessage = ArtelClient.TrySubmitValidationReport(options, validation);
        }
        else
        {
            submitMessage = "Submission skipped: set ARTEL_TASK_ID and ARTEL_BASE_URL environment variables.";
        }

        TaskDialog.Show("ARTEL Family Validate", $"Validation status: {validation["status"]}\nReport:\n{path}\n\n{submitMessage}");
        return Result.Succeeded;
    }
}

internal static class FamilyFactoryExporter
{
    public static Dictionary<string, object?> Export(Document document, string revitVersion)
    {
        var familyManager = document.IsFamilyDocument ? document.FamilyManager : null;
        var ownerFamily = document.IsFamilyDocument ? document.OwnerFamily : null;
        var parameters = new List<Dictionary<string, object?>>();
        var types = new List<Dictionary<string, object?>>();

        if (familyManager is not null)
        {
            foreach (FamilyParameter parameter in familyManager.Parameters)
            {
                parameters.Add(new Dictionary<string, object?>
                {
                    ["name"] = parameter.Definition?.Name ?? "",
                    ["group"] = "",
                    ["storage_type"] = parameter.StorageType.ToString(),
                    ["is_instance"] = parameter.IsInstance,
                    ["is_shared"] = parameter.IsShared,
                    ["guid"] = parameter.IsShared ? parameter.GUID.ToString() : "",
                    ["formula"] = parameter.Formula ?? "",
                    ["is_reporting"] = parameter.IsReporting
                });
            }

            foreach (FamilyType type in familyManager.Types)
            {
                types.Add(new Dictionary<string, object?>
                {
                    ["name"] = type.Name
                });
            }
        }

        var materials = new FilteredElementCollector(document)
            .OfClass(typeof(Material))
            .Cast<Material>()
            .OrderBy(material => material.Name)
            .Select(material => new Dictionary<string, object?>
            {
                ["name"] = material.Name,
                ["id"] = ElementIdValue(material.Id)
            })
            .ToList();

        var symbols = new FilteredElementCollector(document)
            .OfClass(typeof(FamilySymbol))
            .Cast<FamilySymbol>()
            .OrderBy(symbol => symbol.FamilyName)
            .ThenBy(symbol => symbol.Name)
            .Select(symbol => new Dictionary<string, object?>
            {
                ["family"] = symbol.FamilyName,
                ["name"] = symbol.Name,
                ["category"] = symbol.Category?.Name ?? "",
                ["id"] = ElementIdValue(symbol.Id)
            })
            .ToList();

        return new Dictionary<string, object?>
        {
            ["schema"] = "artel.revit_family_catalog.v1",
            ["revit_version"] = revitVersion,
            ["source_path"] = document.PathName ?? "",
            ["document_title"] = document.Title,
            ["is_family_document"] = document.IsFamilyDocument,
            ["family_name"] = ownerFamily?.Name ?? document.Title,
            ["category"] = ownerFamily?.FamilyCategory?.Name ?? "",
            ["category_id"] = ownerFamily is null ? null : ElementIdValue(ownerFamily.FamilyCategoryId),
            ["types"] = types,
            ["parameters"] = parameters,
            ["materials"] = materials,
            ["family_symbols"] = symbols,
            ["warnings"] = document.GetWarnings().Select(warning => warning.GetDescriptionText()).ToList(),
            ["exported_at"] = DateTimeOffset.UtcNow.ToString("O")
        };
    }

    private static long ElementIdValue(ElementId id)
    {
        return id.Value;
    }
}

internal static class FamilyFactoryValidator
{
    private static readonly string[] RequiredSharedParameters =
    {
        "ADSK_Наименование"
    };

    public static Dictionary<string, object?> Validate(Document document, string revitVersion, Dictionary<string, object?>? taskPackage)
    {
        var export = FamilyFactoryExporter.Export(document, revitVersion);
        var issues = new List<Dictionary<string, object?>>();
        var actions = new List<Dictionary<string, object?>>();
        var parameters = (List<Dictionary<string, object?>>)export["parameters"]!;
        var types = (List<Dictionary<string, object?>>)export["types"]!;

        if (!document.IsFamilyDocument)
        {
            AddIssue(issues, "error", "ARF-DOC-001", "Document is not a family document", "Open a .rfa/.rft family document before validation.");
        }

        if (string.IsNullOrWhiteSpace(Convert.ToString(export["category"])))
        {
            AddIssue(issues, "error", "ARF-CATEGORY-001", "Family category is missing", "Family category controls scheduling, graphics and behavior.");
        }

        if (types.Count == 0)
        {
            AddIssue(issues, "warning", "ARF-TYPE-001", "No family types found", "Create at least one type or document the type catalog workflow.");
        }

        foreach (var required in RequiredSharedParameters)
        {
            var exists = parameters.Any(parameter =>
                string.Equals(Convert.ToString(parameter["name"]), required, StringComparison.OrdinalIgnoreCase)
                && Convert.ToBoolean(parameter["is_shared"]));
            if (!exists)
            {
                AddIssue(issues, "error", "ARF-FOP-001", $"Missing required shared parameter: {required}", "Add the parameter from the approved FOP/shared parameter profile.");
            }
        }

        foreach (var warning in document.GetWarnings())
        {
            AddIssue(issues, "warning", "ARF-REVIT-WARNING", "Revit warning", warning.GetDescriptionText());
        }

        actions.Add(new Dictionary<string, object?>
        {
            ["type"] = "extract",
            ["target"] = Convert.ToString(export["family_name"]) ?? document.Title,
            ["status"] = "completed",
            ["message"] = "Family metadata extracted to ARTEL JSON."
        });

        var hasErrors = issues.Any(issue => string.Equals(Convert.ToString(issue["severity"]), "error", StringComparison.OrdinalIgnoreCase));
        var hasWarnings = issues.Any(issue => string.Equals(Convert.ToString(issue["severity"]), "warning", StringComparison.OrdinalIgnoreCase));
        var status = hasErrors ? "fail" : hasWarnings ? "warning" : "pass";

        return new Dictionary<string, object?>
        {
            ["schema"] = "artel.revit_family_validation_report.v1",
            ["status"] = status,
            ["summary"] = BuildSummary(export, status, issues.Count, taskPackage),
            ["family"] = export,
            ["issues"] = issues,
            ["actions"] = actions,
            ["validated_at"] = DateTimeOffset.UtcNow.ToString("O")
        };
    }

    private static void AddIssue(List<Dictionary<string, object?>> issues, string severity, string code, string title, string description)
    {
        issues.Add(new Dictionary<string, object?>
        {
            ["severity"] = severity,
            ["code"] = code,
            ["title"] = title,
            ["description"] = description,
            ["revitElementId"] = null,
            ["suggestedFix"] = description
        });
    }

    private static string BuildSummary(Dictionary<string, object?> export, string status, int issueCount, Dictionary<string, object?>? taskPackage)
    {
        var taskInfo = taskPackage is null ? "without approved ARTEL package" : "against approved ARTEL package";
        return $"Validated {export["family_name"]} ({export["category"]}) {taskInfo}: status={status}, issues={issueCount}.";
    }
}

internal static class ArtelClient
{
    private static readonly JavaScriptSerializer Serializer = new();

    public static Dictionary<string, object?>? TryGetTaskPackage(ArtelOptions options)
    {
        try
        {
            using var client = CreateClient(options);
            var json = client.GetStringAsync($"{options.ArtelBaseUrl.TrimEnd('/')}/api/revit/tasks/{options.TaskId}/package").GetAwaiter().GetResult();
            return Serializer.Deserialize<Dictionary<string, object?>>(json);
        }
        catch
        {
            return null;
        }
    }

    public static string TrySubmitValidationReport(ArtelOptions options, Dictionary<string, object?> validation)
    {
        try
        {
            var payload = new Dictionary<string, object?>
            {
                ["status"] = validation["status"],
                ["summary"] = validation["summary"],
                ["issues"] = validation["issues"],
                ["actions"] = validation["actions"]
            };
            var json = Serializer.Serialize(payload);
            using var client = CreateClient(options);
            using var content = new StringContent(json, Encoding.UTF8, "application/json");
            var response = client.PostAsync($"{options.ArtelBaseUrl.TrimEnd('/')}/api/revit/tasks/{options.TaskId}/validation-reports", content).GetAwaiter().GetResult();
            var body = response.Content.ReadAsStringAsync().GetAwaiter().GetResult();
            return response.IsSuccessStatusCode
                ? $"Submitted validation report to ARTEL: HTTP {(int)response.StatusCode}."
                : $"ARTEL submission failed: HTTP {(int)response.StatusCode}: {body}";
        }
        catch (Exception error)
        {
            return $"ARTEL submission failed: {error.GetType().Name}: {error.Message}";
        }
    }

    private static HttpClient CreateClient(ArtelOptions options)
    {
        var client = new HttpClient { Timeout = TimeSpan.FromSeconds(60) };
        if (!string.IsNullOrWhiteSpace(options.ApiKey))
        {
            client.DefaultRequestHeaders.TryAddWithoutValidation("Authorization", $"Bearer {options.ApiKey}");
            client.DefaultRequestHeaders.TryAddWithoutValidation("X-API-Key", options.ApiKey);
        }
        return client;
    }
}

internal sealed class ArtelOptions
{
    public ArtelOptions(string artelBaseUrl, string taskId, string apiKey)
    {
        ArtelBaseUrl = artelBaseUrl;
        TaskId = taskId;
        ApiKey = apiKey;
    }

    public string ArtelBaseUrl { get; }
    public string TaskId { get; }
    public string ApiKey { get; }

    public static ArtelOptions Load()
    {
        return new ArtelOptions(
            Environment.GetEnvironmentVariable("ARTEL_BASE_URL") ?? "http://127.0.0.1:5057",
            Environment.GetEnvironmentVariable("ARTEL_TASK_ID") ?? "",
            Environment.GetEnvironmentVariable("ARTEL_API_KEY") ?? "");
    }
}

internal static class FamilyFactoryPaths
{
    private static readonly JavaScriptSerializer Serializer = new();

    public static string WriteJson(string prefix, Dictionary<string, object?> payload)
    {
        var root = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
            "ARTEL",
            "family_factory");
        Directory.CreateDirectory(root);
        var path = Path.Combine(root, $"{prefix}_{DateTime.UtcNow:yyyyMMdd_HHmmss}.json");
        File.WriteAllText(path, Serializer.Serialize(payload), Encoding.UTF8);
        return path;
    }
}
