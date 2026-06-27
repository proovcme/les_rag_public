using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using Autodesk.Revit.UI.Events;

namespace ARTEL.Revit.FamilyFactory;

public sealed class ArtelFamilyFactoryApplication : IExternalApplication
{
    private UIControlledApplication? _application;
    private bool _autorunStarted;

    public Result OnStartup(UIControlledApplication application)
    {
        _application = application;
        BuildRibbon(application);
        if (!string.IsNullOrWhiteSpace(Environment.GetEnvironmentVariable("ARTEL_AUTORUN_VALIDATE_PATH"))
            || !string.IsNullOrWhiteSpace(Environment.GetEnvironmentVariable("ARTEL_AUTORUN_GENERATE_PLAN")))
        {
            application.Idling += OnIdling;
            // Headless-устойчивость: на «замусоренном» Revit (чужие аддины) старт упирается в
            // модальные диалоги (напр. «External Tools Duplicate ClientId», предупреждения загрузки),
            // которые в автономном запуске некому закрыть — Revit не доходит до Idling и автозапуск не
            // стреляет. Пока ждём автозапуск, сами гасим всплывающие диалоги. Только в autorun-режиме —
            // обычный интерактив (ручные кнопки ленты) не трогаем.
            application.DialogBoxShowing += OnDialogBoxShowing;
        }
        return Result.Succeeded;
    }

    // Best-effort авто-закрытие модальных диалогов в режиме автозапуска. Логируем, что погасили,
    // рядом с отчётами — чтобы было видно, какие диалоги мешали headless-старту.
    private void OnDialogBoxShowing(object? sender, DialogBoxShowingEventArgs args)
    {
        try
        {
            string id;
            switch (args)
            {
                case TaskDialogShowingEventArgs taskDialog:
                    id = taskDialog.DialogId ?? "TaskDialog";
                    // Close=8 закрывает информационные стартовые диалоги; если кнопки Close нет,
                    // Cancel=2/Ok=1 как запасной — Revit игнорирует невалидный id, поэтому шлём по очереди.
                    if (!taskDialog.OverrideResult((int)TaskDialogResult.Close))
                    {
                        if (!taskDialog.OverrideResult((int)TaskDialogResult.Cancel))
                        {
                            taskDialog.OverrideResult((int)TaskDialogResult.Ok);
                        }
                    }
                    break;
                case MessageBoxShowingEventArgs messageBox:
                    id = "MessageBox:" + messageBox.Message;
                    messageBox.OverrideResult(1); // IDOK
                    break;
                default:
                    id = args.DialogId ?? args.GetType().Name;
                    args.OverrideResult(1);
                    break;
            }
            AppendAutorunLog($"[dialog-dismiss] {id}");
        }
        catch
        {
            // Подавление диалога — best-effort; никогда не валим старт из-за этого.
        }
    }

    private static void AppendAutorunLog(string line)
    {
        try
        {
            var dir = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "ARTEL", "family_factory");
            Directory.CreateDirectory(dir);
            File.AppendAllText(
                Path.Combine(dir, "artel_generate.log"),
                $"[{DateTimeOffset.Now:yyyy-MM-dd HH:mm:ss}] {line}\n",
                Encoding.UTF8);
        }
        catch { /* лог best-effort */ }
    }

    private static void BuildRibbon(UIControlledApplication application)
    {
        const string tab = "ARTEL";
        var assembly = typeof(ArtelFamilyFactoryApplication).Assembly.Location;
        try
        {
            try { application.CreateRibbonTab(tab); }
            catch { /* tab already exists across reloads */ }

            var panel = application.CreateRibbonPanel(tab, "Фабрика семейств");

            panel.AddItem(new PushButtonData(
                "ArtelGenerate", "Сгенерировать", assembly,
                "ARTEL.Revit.FamilyFactory.ArtelFamilyGenerateCommand")
            {
                ToolTip = "Выбрать план действий (family_action_plan.v1) и исполнить его в активном семействе.",
                LargeImage = LoadImage("ARTEL.Revit.FamilyFactory.Resources.gen32.png"),
                Image = LoadImage("ARTEL.Revit.FamilyFactory.Resources.gen16.png")
            });
            panel.AddSeparator();
            panel.AddItem(new PushButtonData(
                "ArtelValidate", "Проверить", assembly,
                "ARTEL.Revit.FamilyFactory.ArtelFamilyValidateCommand")
            {
                ToolTip = "Проверить активное семейство и при настройке отправить отчёт в бэкенд ARTEL.",
                LargeImage = LoadImage("ARTEL.Revit.FamilyFactory.Resources.val32.png"),
                Image = LoadImage("ARTEL.Revit.FamilyFactory.Resources.val16.png")
            });
            panel.AddItem(new PushButtonData(
                "ArtelExtract", "Экспорт", assembly,
                "ARTEL.Revit.FamilyFactory.ArtelFamilyExtractCommand")
            {
                ToolTip = "Экспортировать метаданные активного семейства в ARTEL JSON.",
                LargeImage = LoadImage("ARTEL.Revit.FamilyFactory.Resources.ext32.png"),
                Image = LoadImage("ARTEL.Revit.FamilyFactory.Resources.ext16.png")
            });
        }
        catch
        {
            // Never fail add-in startup because of ribbon construction.
        }
    }

    private static ImageSource? LoadImage(string resourceName)
    {
        try
        {
            using var stream = typeof(ArtelFamilyFactoryApplication).Assembly.GetManifestResourceStream(resourceName);
            if (stream is null)
            {
                return null;
            }
            var image = new BitmapImage();
            image.BeginInit();
            image.StreamSource = stream;
            image.CacheOption = BitmapCacheOption.OnLoad;
            image.EndInit();
            image.Freeze();
            return image;
        }
        catch
        {
            return null;
        }
    }

    public Result OnShutdown(UIControlledApplication application)
    {
        application.Idling -= OnIdling;
        application.DialogBoxShowing -= OnDialogBoxShowing;
        return Result.Succeeded;
    }

    private void OnIdling(object? sender, IdlingEventArgs args)
    {
        if (_autorunStarted || _application is null)
        {
            return;
        }

        _autorunStarted = true;
        _application.Idling -= OnIdling;

        var uiApp = sender as UIApplication;
        if (uiApp is null)
        {
            FamilyFactoryPaths.WriteJson("autorun_error", new Dictionary<string, object?>
            {
                ["schema"] = "artel.revit_family_autorun_error.v1",
                ["status"] = "fail",
                ["error"] = "Idling sender is not UIApplication.",
                ["created_at"] = DateTimeOffset.UtcNow.ToString("O")
            });
            return;
        }

        RunAutorun(uiApp);
    }

    private static void RunAutorun(UIApplication uiApp)
    {
        if (!string.IsNullOrWhiteSpace(Environment.GetEnvironmentVariable("ARTEL_AUTORUN_GENERATE_PLAN")))
        {
            RunGenerateAutorun(uiApp);
            return;
        }

        var path = Environment.GetEnvironmentVariable("ARTEL_AUTORUN_VALIDATE_PATH") ?? "";
        try
        {
            if (string.IsNullOrWhiteSpace(path) || !File.Exists(path))
            {
                throw new FileNotFoundException("ARTEL_AUTORUN_VALIDATE_PATH does not point to an existing file.", path);
            }

            var uidoc = uiApp.OpenAndActivateDocument(path);
            var options = ArtelOptions.Load();
            var package = string.IsNullOrWhiteSpace(options.TaskId)
                ? null
                : ArtelClient.TryGetTaskPackage(options);

            var validation = FamilyFactoryValidator.Validate(
                uidoc.Document,
                uiApp.Application,
                uiApp.Application.VersionNumber,
                package,
                options);
            validation["autorun"] = new Dictionary<string, object?>
            {
                ["source_path"] = path,
                ["opened_document"] = uidoc.Document.PathName,
                ["started_by"] = "ARTEL_AUTORUN_VALIDATE_PATH",
                ["completed_at"] = DateTimeOffset.UtcNow.ToString("O")
            };
            var reportPath = FamilyFactoryPaths.WriteJson("validation", validation);

            string submitMessage;
            if (!string.IsNullOrWhiteSpace(options.TaskId) && !string.IsNullOrWhiteSpace(options.ArtelBaseUrl))
            {
                submitMessage = ArtelClient.TrySubmitValidationReport(options, validation);
            }
            else
            {
                submitMessage = "Submission skipped: set ARTEL_TASK_ID and ARTEL_BASE_URL environment variables.";
            }

            FamilyFactoryPaths.WriteJson("autorun", new Dictionary<string, object?>
            {
                ["schema"] = "artel.revit_family_autorun.v1",
                ["status"] = validation["status"],
                ["source_path"] = path,
                ["validation_report"] = reportPath,
                ["submit"] = submitMessage,
                ["completed_at"] = DateTimeOffset.UtcNow.ToString("O")
            });

            if (ArtelOptions.EnvBool("ARTEL_AUTORUN_EXIT", false))
            {
                uiApp.PostCommand(RevitCommandId.LookupPostableCommandId(PostableCommand.ExitRevit));
            }
        }
        catch (Exception error)
        {
            FamilyFactoryPaths.WriteJson("autorun_error", new Dictionary<string, object?>
            {
                ["schema"] = "artel.revit_family_autorun_error.v1",
                ["status"] = "fail",
                ["source_path"] = path,
                ["error_type"] = error.GetType().Name,
                ["error"] = error.Message,
                ["created_at"] = DateTimeOffset.UtcNow.ToString("O")
            });
        }
    }

    private static void RunGenerateAutorun(UIApplication uiApp)
    {
        var planPath = Environment.GetEnvironmentVariable("ARTEL_AUTORUN_GENERATE_PLAN") ?? "";
        try
        {
            if (string.IsNullOrWhiteSpace(planPath) || !File.Exists(planPath))
            {
                throw new FileNotFoundException("ARTEL_AUTORUN_GENERATE_PLAN does not point to an existing file.", planPath);
            }
            var templatePath = Environment.GetEnvironmentVariable("ARTEL_AUTORUN_TEMPLATE") ?? "";
            if (string.IsNullOrWhiteSpace(templatePath) || !File.Exists(templatePath))
            {
                throw new FileNotFoundException("Set ARTEL_AUTORUN_TEMPLATE to a family template (.rft).", templatePath);
            }

            var document = uiApp.Application.NewFamilyDocument(templatePath);
            using var planDoc = JsonDocument.Parse(File.ReadAllText(planPath));
            var report = FamilyPlanExecutor.Execute(document, planDoc.RootElement, uiApp.Application);

            var savePath = Environment.GetEnvironmentVariable("ARTEL_AUTORUN_SAVE_RFA");
            var saved = "not saved";
            if (!string.IsNullOrWhiteSpace(savePath))
            {
                document.SaveAs(savePath, new SaveAsOptions { OverwriteExistingFile = true });
                saved = savePath;
            }

            report["autorun"] = new Dictionary<string, object?>
            {
                ["plan_path"] = planPath,
                ["template"] = templatePath,
                ["saved_rfa"] = saved,
                ["completed_at"] = DateTimeOffset.UtcNow.ToString("O")
            };
            FamilyFactoryPaths.WriteJson("generate_autorun", report);
            document.Close(false);

            if (ArtelOptions.EnvBool("ARTEL_AUTORUN_EXIT", false))
            {
                uiApp.PostCommand(RevitCommandId.LookupPostableCommandId(PostableCommand.ExitRevit));
            }
        }
        catch (Exception error)
        {
            FamilyFactoryPaths.WriteJson("generate_autorun_error", new Dictionary<string, object?>
            {
                ["schema"] = "artel.revit_family_generate_autorun_error.v1",
                ["status"] = "fail",
                ["plan_path"] = planPath,
                ["error_type"] = error.GetType().Name,
                ["error"] = error.Message,
                ["created_at"] = DateTimeOffset.UtcNow.ToString("O")
            });
        }
    }
}

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

        var validation = FamilyFactoryValidator.Validate(
            document,
            commandData.Application.Application,
            commandData.Application.Application.VersionNumber,
            package,
            options);
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
    public static Dictionary<string, object?> Validate(
        Document document,
        Autodesk.Revit.ApplicationServices.Application application,
        string revitVersion,
        Dictionary<string, object?>? taskPackage,
        ArtelOptions options)
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

        foreach (var required in options.RequiredSharedParameters)
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

        if (options.RunFlexTest)
        {
            RunFlexTest(document, issues, actions);
        }
        else
        {
            AddIssue(issues, "warning", "ARF-FLEX-000", "Flex test not executed", "Set ARTEL_RUN_FLEX_TEST=true before acceptance.");
            AddAction(actions, "flex", Convert.ToString(export["family_name"]) ?? document.Title, "skipped", "Flex test disabled by ARTEL_RUN_FLEX_TEST.");
        }

        if (options.RunLoadTest)
        {
            RunLoadTest(document, application, issues, actions);
        }
        else
        {
            AddIssue(issues, "warning", "ARF-LOAD-000", "Load test not executed", "Set ARTEL_RUN_LOAD_TEST=true to load the family into a scratch project document.");
            AddAction(actions, "load", Convert.ToString(export["family_name"]) ?? document.Title, "skipped", "Scratch project load test disabled by ARTEL_RUN_LOAD_TEST.");
        }

        if (options.RequireProjectAcceptanceChecks)
        {
            AddIssue(
                issues,
                "warning",
                "ARF-PROJECT-001",
                "Project acceptance checks are pending",
                "Before acceptance, verify insert, tag and schedule behavior in a representative project/template.");
            AddAction(
                actions,
                "project_acceptance",
                Convert.ToString(export["family_name"]) ?? document.Title,
                "pending",
                "Manual/project-template insert, tag and schedule checks are required before acceptance.");
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

    private static void AddAction(List<Dictionary<string, object?>> actions, string type, string target, string status, string message)
    {
        actions.Add(new Dictionary<string, object?>
        {
            ["type"] = type,
            ["target"] = target,
            ["status"] = status,
            ["message"] = message
        });
    }

    private static void RunFlexTest(Document document, List<Dictionary<string, object?>> issues, List<Dictionary<string, object?>> actions)
    {
        if (!document.IsFamilyDocument)
        {
            AddAction(actions, "flex", document.Title, "skipped", "Document is not a family document.");
            return;
        }

        var familyManager = document.FamilyManager;
        var types = familyManager.Types.Cast<FamilyType>().ToList();
        if (types.Count == 0)
        {
            AddAction(actions, "flex", document.Title, "skipped", "No family types to flex.");
            return;
        }

        Transaction? transaction = null;
        try
        {
            transaction = new Transaction(document, "ARTEL flex family types");
            transaction.Start();
            foreach (var type in types)
            {
                familyManager.CurrentType = type;
                document.Regenerate();
            }
            transaction.RollBack();
            AddAction(actions, "flex", document.Title, "completed", $"Flexed {types.Count} family type(s) with document.Regenerate().");
        }
        catch (Exception error)
        {
            if (transaction is not null && transaction.HasStarted())
            {
                transaction.RollBack();
            }
            AddIssue(issues, "error", "ARF-FLEX-001", "Family type flex failed", $"{error.GetType().Name}: {error.Message}");
            AddAction(actions, "flex", document.Title, "failed", $"{error.GetType().Name}: {error.Message}");
        }
    }

    private static void RunLoadTest(
        Document document,
        Autodesk.Revit.ApplicationServices.Application application,
        List<Dictionary<string, object?>> issues,
        List<Dictionary<string, object?>> actions)
    {
        if (!document.IsFamilyDocument)
        {
            AddAction(actions, "load", document.Title, "skipped", "Document is not a family document.");
            return;
        }

        Document? projectDocument = null;
        try
        {
            projectDocument = application.NewProjectDocument(UnitSystem.Metric);
            var loadedFamily = document.LoadFamily(projectDocument, new ArtelFamilyLoadOptions());
            if (loadedFamily is null)
            {
                AddIssue(issues, "error", "ARF-LOAD-001", "Family did not load into scratch project", "Document.LoadFamily returned null.");
                AddAction(actions, "load", document.Title, "failed", "Document.LoadFamily returned null.");
                return;
            }

            AddAction(actions, "load", document.Title, "completed", $"Family loaded into a scratch metric project document as {loadedFamily.Name}.");
        }
        catch (Exception error)
        {
            AddIssue(issues, "error", "ARF-LOAD-002", "Scratch project load test failed", $"{error.GetType().Name}: {error.Message}");
            AddAction(actions, "load", document.Title, "failed", $"{error.GetType().Name}: {error.Message}");
        }
        finally
        {
            if (projectDocument is not null)
            {
                projectDocument.Close(false);
            }
        }
    }

    private static string BuildSummary(Dictionary<string, object?> export, string status, int issueCount, Dictionary<string, object?>? taskPackage)
    {
        var taskInfo = taskPackage is null ? "without approved ARTEL package" : "against approved ARTEL package";
        return $"Validated {export["family_name"]} ({export["category"]}) {taskInfo}: status={status}, issues={issueCount}.";
    }
}

internal sealed class ArtelFamilyLoadOptions : IFamilyLoadOptions
{
    public bool OnFamilyFound(bool familyInUse, out bool overwriteParameterValues)
    {
        overwriteParameterValues = true;
        return true;
    }

    public bool OnSharedFamilyFound(
        Family sharedFamily,
        bool familyInUse,
        out FamilySource source,
        out bool overwriteParameterValues)
    {
        source = FamilySource.Family;
        overwriteParameterValues = true;
        return true;
    }
}

internal static class ArtelClient
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping
    };

    public static Dictionary<string, object?>? TryGetTaskPackage(ArtelOptions options)
    {
        try
        {
            using var client = CreateClient(options);
            var json = client.GetStringAsync($"{options.ArtelBaseUrl.TrimEnd('/')}/api/revit/tasks/{options.TaskId}/package").GetAwaiter().GetResult();
            return JsonSerializer.Deserialize<Dictionary<string, object?>>(json);
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
            var json = JsonSerializer.Serialize(payload, JsonOptions);
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
        : this(
            artelBaseUrl,
            taskId,
            apiKey,
            RequiredSharedParameters: new[] { "ADSK_Наименование" },
            RunFlexTest: true,
            RunLoadTest: false,
            RequireProjectAcceptanceChecks: true)
    {
    }

    public ArtelOptions(
        string artelBaseUrl,
        string taskId,
        string apiKey,
        IReadOnlyList<string> RequiredSharedParameters,
        bool RunFlexTest,
        bool RunLoadTest,
        bool RequireProjectAcceptanceChecks)
    {
        ArtelBaseUrl = artelBaseUrl;
        TaskId = taskId;
        ApiKey = apiKey;
        this.RequiredSharedParameters = RequiredSharedParameters;
        this.RunFlexTest = RunFlexTest;
        this.RunLoadTest = RunLoadTest;
        this.RequireProjectAcceptanceChecks = RequireProjectAcceptanceChecks;
    }

    public string ArtelBaseUrl { get; }
    public string TaskId { get; }
    public string ApiKey { get; }
    public IReadOnlyList<string> RequiredSharedParameters { get; }
    public bool RunFlexTest { get; }
    public bool RunLoadTest { get; }
    public bool RequireProjectAcceptanceChecks { get; }

    public static ArtelOptions Load()
    {
        return new ArtelOptions(
            Environment.GetEnvironmentVariable("ARTEL_BASE_URL") ?? "http://127.0.0.1:5057",
            Environment.GetEnvironmentVariable("ARTEL_TASK_ID") ?? "",
            Environment.GetEnvironmentVariable("ARTEL_API_KEY") ?? "",
            RequiredSharedParameters: RequiredParametersFromEnvironment(),
            RunFlexTest: EnvBool("ARTEL_RUN_FLEX_TEST", true),
            RunLoadTest: EnvBool("ARTEL_RUN_LOAD_TEST", false),
            RequireProjectAcceptanceChecks: EnvBool("ARTEL_REQUIRE_PROJECT_CHECKS", true));
    }

    private static IReadOnlyList<string> RequiredParametersFromEnvironment()
    {
        var raw = Environment.GetEnvironmentVariable("ARTEL_REQUIRED_SHARED_PARAMETERS") ?? "ADSK_Наименование";
        return raw.Split(new[] { ',', ';' }, StringSplitOptions.RemoveEmptyEntries)
            .Select(value => value.Trim())
            .Where(value => !string.IsNullOrWhiteSpace(value))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToArray();
    }

    public static bool EnvBool(string name, bool defaultValue)
    {
        var raw = Environment.GetEnvironmentVariable(name);
        if (string.IsNullOrWhiteSpace(raw))
        {
            return defaultValue;
        }
        return raw.Equals("1", StringComparison.OrdinalIgnoreCase)
            || raw.Equals("true", StringComparison.OrdinalIgnoreCase)
            || raw.Equals("yes", StringComparison.OrdinalIgnoreCase)
            || raw.Equals("on", StringComparison.OrdinalIgnoreCase);
    }
}

internal static class FamilyFactoryPaths
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping
    };

    public static string WriteJson(string prefix, Dictionary<string, object?> payload)
    {
        var root = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
            "ARTEL",
            "family_factory");
        Directory.CreateDirectory(root);
        var path = Path.Combine(root, $"{prefix}_{DateTime.UtcNow:yyyyMMdd_HHmmss}.json");
        File.WriteAllText(path, JsonSerializer.Serialize(payload, JsonOptions), Encoding.UTF8);
        return path;
    }
}
