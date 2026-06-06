using System.Collections.Concurrent;
using System.Net.Http.Json;
using System.Text.Json;
using System.Text.Json.Nodes;
using Microsoft.Extensions.FileProviders;

var builder = WebApplication.CreateBuilder(args);

builder.Services.AddCors(options =>
{
    options.AddDefaultPolicy(policy =>
    {
        policy
            .AllowAnyHeader()
            .AllowAnyMethod()
            .AllowAnyOrigin();
    });
});
builder.Services.AddHttpClient();

var app = builder.Build();

app.UseCors();

var appRoot = ResolveAppRoot(app.Environment.ContentRootPath);
if (Directory.Exists(appRoot))
{
    app.UseDefaultFiles(new DefaultFilesOptions
    {
        FileProvider = new PhysicalFileProvider(appRoot)
    });
    app.UseStaticFiles(new StaticFileOptions
    {
        FileProvider = new PhysicalFileProvider(appRoot)
    });
}

var store = SeedData.Create();
var validationReportArchive = ValidationReportArchive.FromConfiguration(builder.Configuration, app.Environment.ContentRootPath);
validationReportArchive.LoadInto(store.ValidationReports);

app.MapGet("/health", () => Results.Ok(new HealthResponse("ok", DateTimeOffset.UtcNow)));

app.MapGet("/api/integrations/les/status", async (IHttpClientFactory httpClientFactory, IConfiguration configuration) =>
{
    var options = LesOptions.FromConfiguration(configuration);
    using var client = httpClientFactory.CreateClient();
    client.Timeout = TimeSpan.FromSeconds(options.TimeoutSeconds);
    using var request = CreateLesRequest(HttpMethod.Get, options, "/api/health");

    try
    {
        using var response = await client.SendAsync(request);
        var body = await response.Content.ReadAsStringAsync();
        var parsed = TryParseJson(body);

        return Results.Ok(new LesStatusResponse(
            Status: response.IsSuccessStatusCode ? "ok" : "unhealthy",
            BaseUrl: options.BaseUrl,
            HttpStatus: (int)response.StatusCode,
            Health: parsed,
            CheckedAt: DateTimeOffset.UtcNow));
    }
    catch (HttpRequestException error)
    {
        return Results.Ok(new LesStatusResponse(
            Status: "unreachable",
            BaseUrl: options.BaseUrl,
            HttpStatus: 0,
            Health: new JsonObject { ["error"] = error.GetType().Name },
            CheckedAt: DateTimeOffset.UtcNow));
    }
    catch (TaskCanceledException)
    {
        return Results.Ok(new LesStatusResponse(
            Status: "timeout",
            BaseUrl: options.BaseUrl,
            HttpStatus: 0,
            Health: CreateLesTimeoutBody(options.TimeoutSeconds),
            CheckedAt: DateTimeOffset.UtcNow));
    }
});

app.MapGet("/api/tasks", (string? status) =>
{
    var tasks = store.Tasks.Values
        .Where(task => string.IsNullOrWhiteSpace(status) || task.Status == status)
        .OrderByDescending(task => task.UpdatedAt)
        .Select(TaskSummary.FromTask)
        .ToArray();

    return Results.Ok(tasks);
});

app.MapPost("/api/tasks", (CreateTaskRequest request) =>
{
    if (string.IsNullOrWhiteSpace(request.Title))
    {
        return Results.BadRequest(ApiError.Create("invalid_title", "Task title is required."));
    }

    var sequence = store.Tasks.Count + 1;
    var task = new FamilyTask(
        Id: $"task_{sequence:0000}",
        Number: $"FAM-{sequence:0000}",
        Title: request.Title.Trim(),
        Description: request.Description?.Trim(),
        Status: TaskStatuses.Draft,
        RevitCategory: request.RevitCategory?.Trim(),
        AssignedTo: request.AssignedTo?.Trim(),
        DueDate: request.DueDate,
        CreatedAt: DateTimeOffset.UtcNow,
        UpdatedAt: DateTimeOffset.UtcNow);

    store.Tasks[task.Id] = task;
    return Results.Created($"/api/tasks/{task.Id}", task);
});

app.MapGet("/api/tasks/{taskId}", (string taskId) =>
{
    return store.Tasks.TryGetValue(taskId, out var task)
        ? Results.Ok(task)
        : Results.NotFound(ApiError.Create("task_not_found", "Task was not found."));
});

app.MapGet("/api/tasks/{taskId}/specification", (string taskId) =>
{
    if (!store.Tasks.ContainsKey(taskId))
    {
        return Results.NotFound(ApiError.Create("task_not_found", "Task was not found."));
    }

    return store.Specifications.TryGetValue(taskId, out var specification)
        ? Results.Ok(specification)
        : Results.NotFound(ApiError.Create("specification_not_found", "Specification was not found."));
});

app.MapPost("/api/tasks/{taskId}/ai-analysis", (string taskId, AIAnalysisRequest request) =>
{
    if (!store.Tasks.TryGetValue(taskId, out var task))
    {
        return Results.NotFound(ApiError.Create("task_not_found", "Task was not found."));
    }

    var specification = new FamilySpecification(
        Id: $"spec_{Guid.NewGuid():N}",
        TaskId: taskId,
        Status: SpecificationStatuses.Draft,
        FamilyName: task.Title,
        RevitCategory: task.RevitCategory ?? "Unspecified",
        TemplateFileId: request.TemplateFileId,
        SharedParameterProfileId: request.SharedParameterProfileId,
        Parameters:
        [
            new SpecificationParameter("param_ai_001", "ADSK_Наименование", "shared_parameter", null, "Text", "Identity Data", false, true, null, null, "Draft from AI analysis placeholder")
        ],
        Types: [],
        Materials: [],
        AcceptanceChecklist:
        [
            "Проверить обязательные параметры",
            "Проверить типы семейства",
            "Проверить заполненность каталожных данных"
        ],
        CreatedAt: DateTimeOffset.UtcNow,
        UpdatedAt: DateTimeOffset.UtcNow);

    store.Specifications[taskId] = specification;

    return Results.Accepted($"/api/tasks/{taskId}/specification", new AIAnalysisResult(
        Provider: "openrouter",
        Model: request.Model,
        Status: "completed",
        Specification: specification,
        Warnings:
        [
            "This MVP skeleton does not call OpenRouter yet. It reserves the endpoint and response contract."
        ]));
});

app.MapPost("/api/tasks/{taskId}/rag-context", async (
    string taskId,
    LesRagContextRequest request,
    IHttpClientFactory httpClientFactory,
    IConfiguration configuration) =>
{
    if (!store.Tasks.TryGetValue(taskId, out var task))
    {
        return Results.NotFound(ApiError.Create("task_not_found", "Task was not found."));
    }

    var specification = store.Specifications.GetValueOrDefault(taskId);
    var question = string.IsNullOrWhiteSpace(request.Question)
        ? BuildDefaultLesQuestion(task, specification)
        : request.Question.Trim();

    var options = LesOptions.FromConfiguration(configuration);
    using var client = httpClientFactory.CreateClient();
    client.Timeout = TimeSpan.FromSeconds(options.TimeoutSeconds);
    using var lesRequest = CreateLesRequest(HttpMethod.Post, options, "/api/search");
    lesRequest.Content = JsonContent.Create(new
    {
        query = question,
        dataset_filter = request.DatasetFilter ?? "ARTEL",
        top_k = request.TopK ?? 8,
        include_trace = request.IncludeTrace ?? false
    });

    try
    {
        using var response = await client.SendAsync(lesRequest);
        var body = await response.Content.ReadAsStringAsync();
        var parsed = TryParseJson(body);

        return Results.Ok(new LesRagContextResult(
            Status: response.IsSuccessStatusCode ? "ok" : "upstream_error",
            TaskId: taskId,
            DatasetFilter: request.DatasetFilter ?? "ARTEL",
            Question: question,
            LesBaseUrl: options.BaseUrl,
            HttpStatus: (int)response.StatusCode,
            Response: parsed,
            CreatedAt: DateTimeOffset.UtcNow));
    }
    catch (HttpRequestException error)
    {
        return Results.Ok(new LesRagContextResult(
            Status: "unreachable",
            TaskId: taskId,
            DatasetFilter: request.DatasetFilter ?? "ARTEL",
            Question: question,
            LesBaseUrl: options.BaseUrl,
            HttpStatus: 0,
            Response: new JsonObject { ["error"] = error.GetType().Name },
            CreatedAt: DateTimeOffset.UtcNow));
    }
    catch (TaskCanceledException)
    {
        return Results.Ok(new LesRagContextResult(
            Status: "timeout",
            TaskId: taskId,
            DatasetFilter: request.DatasetFilter ?? "ARTEL",
            Question: question,
            LesBaseUrl: options.BaseUrl,
            HttpStatus: 0,
            Response: CreateLesTimeoutBody(options.TimeoutSeconds),
            CreatedAt: DateTimeOffset.UtcNow));
    }
});

app.MapPut("/api/tasks/{taskId}/specification", (string taskId, FamilySpecification specification) =>
{
    if (!store.Tasks.ContainsKey(taskId))
    {
        return Results.NotFound(ApiError.Create("task_not_found", "Task was not found."));
    }

    var normalized = specification with
    {
        TaskId = taskId,
        UpdatedAt = DateTimeOffset.UtcNow
    };

    store.Specifications[taskId] = normalized;
    return Results.Ok(normalized);
});

app.MapPost("/api/tasks/{taskId}/specification/approve", (string taskId) =>
{
    if (!store.Specifications.TryGetValue(taskId, out var specification))
    {
        return Results.NotFound(ApiError.Create("specification_not_found", "Specification was not found."));
    }

    var approved = specification with
    {
        Status = SpecificationStatuses.Approved,
        UpdatedAt = DateTimeOffset.UtcNow
    };

    store.Specifications[taskId] = approved;
    return Results.Ok(approved);
});

app.MapGet("/api/revit/tasks", () =>
{
    var tasks = store.Tasks.Values
        .Where(task => task.Status is TaskStatuses.ReadyForDevelopment or TaskStatuses.InDevelopment)
        .OrderBy(task => task.DueDate)
        .Select(TaskSummary.FromTask)
        .ToArray();

    return Results.Ok(tasks);
});

app.MapGet("/api/revit/tasks/{taskId}/package", (string taskId) =>
{
    if (!store.Tasks.TryGetValue(taskId, out var task))
    {
        return Results.NotFound(ApiError.Create("task_not_found", "Task was not found."));
    }

    if (!store.Specifications.TryGetValue(taskId, out var specification))
    {
        return Results.NotFound(ApiError.Create("specification_not_found", "Specification was not found."));
    }

    if (specification.Status != SpecificationStatuses.Approved)
    {
        return Results.BadRequest(ApiError.Create(
            "specification_not_approved",
            "Specification must be approved before it can be issued to Revit."));
    }

    return Results.Ok(new RevitTaskPackage(
        Task: TaskSummary.FromTask(task),
        Specification: specification,
        Files: store.Files.Values.Where(file => file.TaskId == taskId).ToArray()));
});

app.MapPost("/api/revit/tasks/{taskId}/validation-reports", (string taskId, ValidationReportRequest request) =>
{
    if (!store.Tasks.ContainsKey(taskId))
    {
        return Results.NotFound(ApiError.Create("task_not_found", "Task was not found."));
    }

    var report = new ValidationReport(
        Id: $"report_{Guid.NewGuid():N}",
        TaskId: taskId,
        Status: request.Status,
        Summary: request.Summary,
        Issues: request.Issues,
        Actions: request.Actions,
        CreatedAt: DateTimeOffset.UtcNow);

    store.ValidationReports[report.Id] = report;
    validationReportArchive.Save(report);
    return Results.Created($"/api/validation-reports/{report.Id}", report);
});

app.MapGet("/api/validation-reports", (string? taskId) =>
{
    var reports = store.ValidationReports.Values
        .Where(report => string.IsNullOrWhiteSpace(taskId) || report.TaskId == taskId)
        .OrderByDescending(report => report.CreatedAt)
        .ToArray();

    return Results.Ok(reports);
});

app.MapGet("/api/validation-reports/{reportId}/learning-case", (string reportId) =>
{
    if (!store.ValidationReports.TryGetValue(reportId, out var report))
    {
        return Results.NotFound(ApiError.Create("validation_report_not_found", "Validation report was not found."));
    }

    if (!store.Tasks.TryGetValue(report.TaskId, out var task))
    {
        return Results.NotFound(ApiError.Create("task_not_found", "Task was not found."));
    }

    if (!store.Specifications.TryGetValue(report.TaskId, out var specification))
    {
        return Results.NotFound(ApiError.Create("specification_not_found", "Specification was not found."));
    }

    var catalogItem = store.Catalog.Values.FirstOrDefault(item =>
        string.Equals(item.Name, specification.FamilyName, StringComparison.OrdinalIgnoreCase)
        || string.Equals(item.Category, specification.RevitCategory, StringComparison.OrdinalIgnoreCase));

    return Results.Ok(BuildLearningCase(task, specification, report, catalogItem));
});

app.MapGet("/api/tasks/{taskId}/learning-case", (string taskId) =>
{
    if (!store.Tasks.TryGetValue(taskId, out var task))
    {
        return Results.NotFound(ApiError.Create("task_not_found", "Task was not found."));
    }

    if (!store.Specifications.TryGetValue(taskId, out var specification))
    {
        return Results.NotFound(ApiError.Create("specification_not_found", "Specification was not found."));
    }

    var report = store.ValidationReports.Values
        .Where(item => item.TaskId == taskId)
        .OrderByDescending(item => item.CreatedAt)
        .FirstOrDefault();

    if (report is null)
    {
        return Results.NotFound(ApiError.Create("validation_report_not_found", "No validation report exists for this task."));
    }

    var catalogItem = store.Catalog.Values.FirstOrDefault(item =>
        string.Equals(item.Name, specification.FamilyName, StringComparison.OrdinalIgnoreCase)
        || string.Equals(item.Category, specification.RevitCategory, StringComparison.OrdinalIgnoreCase));

    return Results.Ok(BuildLearningCase(task, specification, report, catalogItem));
});

app.MapGet("/api/catalog", (string? query) =>
{
    var items = store.Catalog.Values
        .Where(item =>
            string.IsNullOrWhiteSpace(query)
            || item.Name.Contains(query, StringComparison.OrdinalIgnoreCase)
            || item.Category.Contains(query, StringComparison.OrdinalIgnoreCase)
            || item.Tags.Any(tag => tag.Contains(query, StringComparison.OrdinalIgnoreCase)))
        .OrderBy(item => item.Name)
        .ToArray();

    return Results.Ok(items);
});

app.MapGet("/api/catalog/{catalogItemId}", (string catalogItemId) =>
{
    return store.Catalog.TryGetValue(catalogItemId, out var item)
        ? Results.Ok(new CatalogItemDetail(
            Item: item,
            Versions: store.FamilyVersions.Values
                .Where(version => version.CatalogItemId == catalogItemId)
                .OrderByDescending(version => version.SubmittedAt)
                .ToArray()))
        : Results.NotFound(ApiError.Create("catalog_item_not_found", "Catalog item was not found."));
});

app.MapGet("/api/catalog/{catalogItemId}/versions", (string catalogItemId) =>
{
    if (!store.Catalog.ContainsKey(catalogItemId))
    {
        return Results.NotFound(ApiError.Create("catalog_item_not_found", "Catalog item was not found."));
    }

    var versions = store.FamilyVersions.Values
        .Where(version => version.CatalogItemId == catalogItemId)
        .OrderByDescending(version => version.SubmittedAt)
        .ToArray();

    return Results.Ok(versions);
});

app.MapPost("/api/catalog/{catalogItemId}/publish", (string catalogItemId, PublishCatalogVersionRequest request) =>
{
    if (!store.Catalog.TryGetValue(catalogItemId, out var item))
    {
        return Results.NotFound(ApiError.Create("catalog_item_not_found", "Catalog item was not found."));
    }

    var version = new FamilyVersion(
        Id: $"version_{Guid.NewGuid():N}",
        CatalogItemId: catalogItemId,
        TaskId: request.TaskId,
        Version: request.Version,
        RfaFileId: request.RfaFileId,
        Status: "published",
        Changelog: request.Changelog,
        SubmittedBy: request.SubmittedBy,
        SubmittedAt: DateTimeOffset.UtcNow);

    store.FamilyVersions[version.Id] = version;
    store.Catalog[catalogItemId] = item with
    {
        CurrentVersion = request.Version,
        CurrentVersionId = version.Id,
        UpdatedAt = DateTimeOffset.UtcNow
    };

    return Results.Created($"/api/catalog/{catalogItemId}/versions/{version.Id}", version);
});

app.MapPost("/api/catalog/{catalogItemId}/update-task", (string catalogItemId, CreateCatalogUpdateTaskRequest request) =>
{
    if (!store.Catalog.TryGetValue(catalogItemId, out var item))
    {
        return Results.NotFound(ApiError.Create("catalog_item_not_found", "Catalog item was not found."));
    }

    var sequence = store.Tasks.Count + 1;
    var task = new FamilyTask(
        Id: $"task_{sequence:0000}",
        Number: $"FAM-{sequence:0000}",
        Title: $"Обновить: {item.Name}",
        Description: request.Reason,
        Status: TaskStatuses.Draft,
        RevitCategory: item.Category,
        AssignedTo: request.AssignedTo,
        DueDate: request.DueDate,
        CreatedAt: DateTimeOffset.UtcNow,
        UpdatedAt: DateTimeOffset.UtcNow);

    store.Tasks[task.Id] = task;
    return Results.Created($"/api/tasks/{task.Id}", new CatalogUpdateTaskResult(task.Id, task.Number, catalogItemId));
});

app.Run();

static HttpRequestMessage CreateLesRequest(HttpMethod method, LesOptions options, string path)
{
    var request = new HttpRequestMessage(method, new Uri(new Uri(options.BaseUrl), path));
    if (!string.IsNullOrWhiteSpace(options.ApiKey))
    {
        request.Headers.TryAddWithoutValidation("X-API-Key", options.ApiKey);
    }

    return request;
}

static string ResolveAppRoot(string contentRootPath)
{
    var candidates = new[]
    {
        Path.Combine(contentRootPath, "app"),
        Path.Combine(contentRootPath, "products", "artel", "app"),
        Path.Combine(contentRootPath, "..", "app"),
        Path.Combine(contentRootPath, "..", "..", "app"),
        Path.Combine(contentRootPath, "..", "..", "..", "app"),
        Path.Combine(AppContext.BaseDirectory, "..", "..", "..", "..", "..", "app"),
    };

    foreach (var candidate in candidates.Select(Path.GetFullPath))
    {
        if (Directory.Exists(candidate) && File.Exists(Path.Combine(candidate, "index.html")))
        {
            return candidate;
        }
    }

    return Path.GetFullPath(Path.Combine(contentRootPath, "app"));
}

static JsonNode? TryParseJson(string body)
{
    if (string.IsNullOrWhiteSpace(body))
    {
        return null;
    }

    try
    {
        return JsonNode.Parse(body);
    }
    catch
    {
        return new JsonObject { ["raw"] = body };
    }
}

static JsonObject CreateLesTimeoutBody(int timeoutSeconds)
{
    return new JsonObject
    {
        ["error"] = "timeout",
        ["timeoutSeconds"] = timeoutSeconds
    };
}

static string BuildDefaultLesQuestion(FamilyTask task, FamilySpecification? specification)
{
    var parameterNames = specification is null
        ? "нет утвержденной спецификации"
        : string.Join(", ", specification.Parameters.Select(parameter => parameter.Name));

    return
        $"Найди похожие ARTEL/RFA кейсы и типовые ошибки для разработки Revit-семейства. " +
        $"Задание: {task.Number} {task.Title}. Категория: {task.RevitCategory ?? "не указана"}. " +
        $"Параметры спецификации: {parameterNames}. " +
        "Нужны релевантные образцы, параметры, risks и checklist для приемки.";
}

static JsonObject BuildLearningCase(
    FamilyTask task,
    FamilySpecification specification,
    ValidationReport report,
    CatalogItem? catalogItem)
{
    var parameters = new JsonArray();
    foreach (var parameter in specification.Parameters)
    {
        parameters.Add(new JsonObject
        {
            ["name"] = parameter.Name,
            ["value_or_rule"] = parameter.DefaultValue ?? parameter.Formula ?? parameter.Notes ?? (parameter.IsRequired ? "required" : "optional"),
            ["group"] = parameter.Group
        });
    }

    var checks = new JsonArray();
    foreach (var item in specification.AcceptanceChecklist)
    {
        checks.Add(item);
    }
    foreach (var issue in report.Issues)
    {
        checks.Add($"{issue.Severity}: {issue.Code} - {issue.Title}");
    }

    var knownFailures = new JsonArray();
    foreach (var issue in report.Issues.Where(issue => !string.Equals(issue.Severity, "info", StringComparison.OrdinalIgnoreCase)))
    {
        knownFailures.Add($"{issue.Code}: {issue.Description}");
    }

    var fixes = new JsonArray();
    foreach (var action in report.Actions)
    {
        fixes.Add($"{action.Type} {action.Target}: {action.Status}{(string.IsNullOrWhiteSpace(action.Message) ? "" : " - " + action.Message)}");
    }

    return new JsonObject
    {
        ["schema_version"] = "artel.family_learning_case.v1",
        ["case_id"] = $"validation_{report.Id}",
        ["product"] = "ARTEL",
        ["visibility"] = "private_runtime",
        ["task"] = new JsonObject
        {
            ["title"] = task.Title,
            ["family_category"] = specification.RevitCategory,
            ["family_name"] = specification.FamilyName,
            ["goal"] = task.Description ?? task.Title,
            ["constraints"] = ToJsonArray(specification.AcceptanceChecklist)
        },
        ["source_summaries"] = new JsonArray
        {
            new JsonObject
            {
                ["kind"] = "validation_report",
                ["summary"] = report.Summary
            }
        },
        ["specification"] = new JsonObject
        {
            ["types"] = ToJsonArray(specification.Types.Select(type => type.Name)),
            ["geometry"] = "See approved ARTEL specification and Revit validation report.",
            ["materials"] = ToJsonArray(specification.Materials.Select(material => $"{material.Name}: {material.DefaultValue ?? material.ParameterName ?? "not specified"}")),
            ["parameters"] = parameters
        },
        ["parameter_profile"] = new JsonObject
        {
            ["fop_profile"] = specification.SharedParameterProfileId ?? "not specified",
            ["required_shared_parameters"] = ToJsonArray(specification.Parameters
                .Where(parameter => parameter.Source.Contains("shared", StringComparison.OrdinalIgnoreCase) || parameter.SharedParameterGuid is not null)
                .Select(parameter => string.IsNullOrWhiteSpace(parameter.SharedParameterGuid)
                    ? parameter.Name
                    : $"{parameter.Name} ({parameter.SharedParameterGuid})"))
        },
        ["validation_report"] = new JsonObject
        {
            ["status"] = report.Status,
            ["checks"] = checks,
            ["known_failures"] = knownFailures,
            ["fixes"] = fixes
        },
        ["catalog_card"] = new JsonObject
        {
            ["display_name"] = catalogItem?.Name ?? specification.FamilyName,
            ["category"] = catalogItem?.Category ?? specification.RevitCategory,
            ["tags"] = ToJsonArray(catalogItem?.Tags ?? [specification.RevitCategory, "revit-family"]),
            ["search_terms"] = ToJsonArray(new[]
            {
                specification.FamilyName,
                specification.RevitCategory,
                task.Number,
                "RFA",
                "ARTEL"
            })
        },
        ["acceptance"] = new JsonObject
        {
            ["outcome"] = report.Status,
            ["accepted_by_role"] = "ARTEL validation workflow",
            ["notes"] = report.Summary
        }
    };
}

static JsonArray ToJsonArray(IEnumerable<string> values)
{
    var array = new JsonArray();
    foreach (var value in values)
    {
        if (!string.IsNullOrWhiteSpace(value))
        {
            array.Add(value);
        }
    }
    return array;
}

static class TaskStatuses
{
    public const string Draft = "draft";
    public const string ReadyForDevelopment = "ready_for_development";
    public const string InDevelopment = "in_development";
}

static class SpecificationStatuses
{
    public const string Draft = "draft";
    public const string Approved = "approved";
}

record HealthResponse(string Status, DateTimeOffset CheckedAt);

record LesOptions(string BaseUrl, string? ApiKey, int TimeoutSeconds)
{
    public static LesOptions FromConfiguration(IConfiguration configuration)
    {
        var baseUrl = configuration["Les:BaseUrl"] ?? Environment.GetEnvironmentVariable("LES_BASE_URL") ?? "http://127.0.0.1:8050";
        var apiKey = configuration["Les:ApiKey"] ?? Environment.GetEnvironmentVariable("LES_API_KEY");
        var timeoutSeconds = ParseTimeoutSeconds(
            configuration["Les:TimeoutSeconds"]
            ?? Environment.GetEnvironmentVariable("LES_TIMEOUT_SECONDS"));

        return new LesOptions(baseUrl.TrimEnd('/') + "/", apiKey, timeoutSeconds);
    }

    private static int ParseTimeoutSeconds(string? value)
    {
        if (!int.TryParse(value, out var timeoutSeconds))
        {
            return 120;
        }

        return Math.Clamp(timeoutSeconds, 1, 600);
    }
}

record LesStatusResponse(
    string Status,
    string BaseUrl,
    int HttpStatus,
    JsonNode? Health,
    DateTimeOffset CheckedAt);

record ApiError(ApiErrorBody Error)
{
    public static ApiError Create(string code, string message) => new(new ApiErrorBody(code, message));
}

record ApiErrorBody(string Code, string Message);

record CreateTaskRequest(
    string Title,
    string? Description,
    string? RevitCategory,
    string? AssignedTo,
    DateOnly? DueDate);

record FamilyTask(
    string Id,
    string Number,
    string Title,
    string? Description,
    string Status,
    string? RevitCategory,
    string? AssignedTo,
    DateOnly? DueDate,
    DateTimeOffset CreatedAt,
    DateTimeOffset UpdatedAt);

record TaskSummary(
    string Id,
    string Number,
    string Title,
    string Status,
    string? RevitCategory,
    string? AssignedTo,
    DateOnly? DueDate)
{
    public static TaskSummary FromTask(FamilyTask task)
    {
        return new TaskSummary(
            task.Id,
            task.Number,
            task.Title,
            task.Status,
            task.RevitCategory,
            task.AssignedTo,
            task.DueDate);
    }
}

record SourceFile(
    string Id,
    string TaskId,
    string Name,
    string Kind,
    string DownloadUrl);

record AIAnalysisRequest(
    IReadOnlyList<string> SourceFileIds,
    string? SharedParameterProfileId,
    string? TemplateFileId,
    string? Model);

record AIAnalysisResult(
    string Provider,
    string? Model,
    string Status,
    FamilySpecification Specification,
    IReadOnlyList<string> Warnings);

record LesRagContextRequest(
    string? Question,
    string? DatasetFilter,
    int? TopK,
    bool? IncludeTrace,
    bool? ValidationEnabled,
    bool? RerankerEnabled,
    bool? SemanticCacheEnabled);

record LesRagContextResult(
    string Status,
    string TaskId,
    string DatasetFilter,
    string Question,
    string LesBaseUrl,
    int HttpStatus,
    JsonNode? Response,
    DateTimeOffset CreatedAt);

record FamilySpecification(
    string Id,
    string TaskId,
    string Status,
    string FamilyName,
    string RevitCategory,
    string? TemplateFileId,
    string? SharedParameterProfileId,
    IReadOnlyList<SpecificationParameter> Parameters,
    IReadOnlyList<SpecificationType> Types,
    IReadOnlyList<SpecificationMaterial> Materials,
    IReadOnlyList<string> AcceptanceChecklist,
    DateTimeOffset CreatedAt,
    DateTimeOffset UpdatedAt);

record SpecificationParameter(
    string Id,
    string Name,
    string Source,
    string? SharedParameterGuid,
    string DataType,
    string Group,
    bool IsInstance,
    bool IsRequired,
    string? DefaultValue,
    string? Formula,
    string? Notes);

record SpecificationType(
    string Id,
    string Name,
    IReadOnlyDictionary<string, object?> Values,
    string? Notes);

record SpecificationMaterial(
    string Id,
    string Name,
    string? ParameterName,
    string? DefaultValue);

record RevitTaskPackage(
    TaskSummary Task,
    FamilySpecification Specification,
    IReadOnlyList<SourceFile> Files);

record ValidationReportRequest(
    string Status,
    string Summary,
    IReadOnlyList<ValidationIssue> Issues,
    IReadOnlyList<ValidationAction> Actions);

record ValidationReport(
    string Id,
    string TaskId,
    string Status,
    string Summary,
    IReadOnlyList<ValidationIssue> Issues,
    IReadOnlyList<ValidationAction> Actions,
    DateTimeOffset CreatedAt);

record ValidationIssue(
    string Severity,
    string Code,
    string Title,
    string Description,
    string? RevitElementId,
    string? SuggestedFix);

record ValidationAction(
    string Type,
    string Target,
    string Status,
    string? Message);

record CatalogItem(
    string Id,
    string Name,
    string Category,
    string Description,
    string Status,
    string CurrentVersion,
    string? CurrentVersionId,
    string? CurrentRfaFileId,
    string RevitCompatibility,
    string FileSize,
    IReadOnlyList<string> Tags,
    DateTimeOffset UpdatedAt);

record CatalogItemDetail(
    CatalogItem Item,
    IReadOnlyList<FamilyVersion> Versions);

record FamilyVersion(
    string Id,
    string CatalogItemId,
    string? TaskId,
    string Version,
    string RfaFileId,
    string Status,
    string? Changelog,
    string? SubmittedBy,
    DateTimeOffset SubmittedAt);

record PublishCatalogVersionRequest(
    string Version,
    string RfaFileId,
    string? TaskId,
    string? Changelog,
    string? SubmittedBy);

record CreateCatalogUpdateTaskRequest(
    string Reason,
    string? AssignedTo,
    DateOnly? DueDate);

record CatalogUpdateTaskResult(
    string TaskId,
    string TaskNumber,
    string CatalogItemId);

record AppStore(
    ConcurrentDictionary<string, FamilyTask> Tasks,
    ConcurrentDictionary<string, FamilySpecification> Specifications,
    ConcurrentDictionary<string, SourceFile> Files,
    ConcurrentDictionary<string, ValidationReport> ValidationReports,
    ConcurrentDictionary<string, CatalogItem> Catalog,
    ConcurrentDictionary<string, FamilyVersion> FamilyVersions);

sealed class ValidationReportArchive
{
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web)
    {
        WriteIndented = true
    };

    private readonly string _reportsDir;

    private ValidationReportArchive(string reportsDir)
    {
        _reportsDir = reportsDir;
    }

    public static ValidationReportArchive FromConfiguration(IConfiguration configuration, string contentRootPath)
    {
        var dataRoot = configuration["ARTEL_DATA_DIR"];
        if (string.IsNullOrWhiteSpace(dataRoot))
        {
            dataRoot = Path.Combine(contentRootPath, "artel_data");
        }

        return new ValidationReportArchive(Path.Combine(dataRoot, "validation_reports"));
    }

    public void LoadInto(ConcurrentDictionary<string, ValidationReport> target)
    {
        if (!Directory.Exists(_reportsDir))
        {
            return;
        }

        foreach (var path in Directory.EnumerateFiles(_reportsDir, "*.json", SearchOption.TopDirectoryOnly))
        {
            try
            {
                var report = JsonSerializer.Deserialize<ValidationReport>(File.ReadAllText(path), JsonOptions);
                if (report is not null && !string.IsNullOrWhiteSpace(report.Id))
                {
                    target[report.Id] = report;
                }
            }
            catch
            {
                // Keep serving valid reports even if one archived file is corrupt.
            }
        }
    }

    public void Save(ValidationReport report)
    {
        Directory.CreateDirectory(_reportsDir);
        var path = Path.Combine(_reportsDir, $"{report.Id}.json");
        var tmpPath = path + ".tmp";
        File.WriteAllText(tmpPath, JsonSerializer.Serialize(report, JsonOptions));
        if (File.Exists(path))
        {
            File.Delete(path);
        }
        File.Move(tmpPath, path);
    }
}

static class SeedData
{
    public static AppStore Create()
    {
        var task = new FamilyTask(
            Id: "task_0241",
            Number: "FAM-0241",
            Title: "Шкаф архивный металлический",
            Description: "Параметрическое семейство шкафа с линейкой типоразмеров.",
            Status: TaskStatuses.ReadyForDevelopment,
            RevitCategory: "Furniture",
            AssignedTo: "family.developer@example.com",
            DueDate: new DateOnly(2026, 6, 12),
            CreatedAt: DateTimeOffset.UtcNow,
            UpdatedAt: DateTimeOffset.UtcNow);

        var specification = new FamilySpecification(
            Id: "spec_0241",
            TaskId: task.Id,
            Status: SpecificationStatuses.Approved,
            FamilyName: "Шкаф архивный металлический",
            RevitCategory: "Furniture",
            TemplateFileId: "file_template_001",
            SharedParameterProfileId: "fop_2026",
            Parameters:
            [
                new SpecificationParameter("param_001", "ADSK_Наименование", "shared_parameter", "4f5cb6a1-0000-0000-0000-000000000000", "Text", "Identity Data", false, true, null, null, null),
                new SpecificationParameter("param_002", "Ширина", "family_parameter", null, "Length", "Dimensions", false, true, null, null, null),
                new SpecificationParameter("param_003", "Высота", "family_parameter", null, "Length", "Dimensions", false, true, null, null, null)
            ],
            Types:
            [
                new SpecificationType("type_001", "Шкаф 800x400x1800", new Dictionary<string, object?>
                {
                    ["Ширина"] = 800,
                    ["Глубина"] = 400,
                    ["Высота"] = 1800
                }, null)
            ],
            Materials:
            [
                new SpecificationMaterial("mat_001", "Материал корпуса", "Материал корпуса", "RAL 7035")
            ],
            AcceptanceChecklist:
            [
                "Все обязательные параметры существуют",
                "Все типы из спецификации созданы",
                "Материалы назначены параметрически"
            ],
            CreatedAt: DateTimeOffset.UtcNow,
            UpdatedAt: DateTimeOffset.UtcNow);

        var catalogItem = new CatalogItem(
            Id: "catalog_001",
            Name: "Шкаф архивный металлический",
            Category: "Furniture",
            Description: "Параметрическое семейство шкафа.",
            Status: "active",
            CurrentVersion: "0.1.0",
            CurrentVersionId: "version_001",
            CurrentRfaFileId: "file_rfa_001",
            RevitCompatibility: "2023-2025",
            FileSize: "1.8 MB",
            Tags: ["мебель", "шкаф", "архив"],
            UpdatedAt: DateTimeOffset.UtcNow);

        var familyVersion = new FamilyVersion(
            Id: "version_001",
            CatalogItemId: catalogItem.Id,
            TaskId: task.Id,
            Version: "0.1.0",
            RfaFileId: "file_rfa_001",
            Status: "published",
            Changelog: "Initial MVP catalog version",
            SubmittedBy: "bim.manager@example.com",
            SubmittedAt: DateTimeOffset.UtcNow);

        return new AppStore(
            Tasks: new ConcurrentDictionary<string, FamilyTask>(new[] { KeyValuePair.Create(task.Id, task) }),
            Specifications: new ConcurrentDictionary<string, FamilySpecification>(new[] { KeyValuePair.Create(task.Id, specification) }),
            Files: new ConcurrentDictionary<string, SourceFile>(new[]
            {
                KeyValuePair.Create("file_001", new SourceFile("file_001", task.Id, "ТЗ_шкаф_архивный.pdf", "brief", "/api/files/file_001/download"))
            }),
            ValidationReports: new ConcurrentDictionary<string, ValidationReport>(),
            Catalog: new ConcurrentDictionary<string, CatalogItem>(new[]
            {
                KeyValuePair.Create(catalogItem.Id, catalogItem)
            }),
            FamilyVersions: new ConcurrentDictionary<string, FamilyVersion>(new[]
            {
                KeyValuePair.Create(familyVersion.Id, familyVersion)
            }));
    }
}
