using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Net.Http;
using System.Text;
using System.Threading.Tasks;

namespace LES.Navisworks.JsonExport;

internal sealed class LesUploadSettings
{
    public static string ConfigPath => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
        "LES",
        "cad_bim_exporter_settings.json"
    );

    public List<string> LesUrls { get; set; } = DefaultUrls();

    public List<string> CustomUrls { get; set; } = new();

    public string LocalOutputDir { get; set; } = string.Empty;

    public string ApiKey { get; set; } = string.Empty;

    public int TimeoutSec { get; set; } = 60;

    public static List<string> DefaultUrls()
    {
        return new List<string> { "http://10.195.146.98:8050", "https://les.ovc.me" };
    }

    public static LesUploadSettings Load()
    {
        try
        {
            if (File.Exists(ConfigPath))
            {
                var settings = LesJsonWriter.DeserializeSettings(File.ReadAllText(ConfigPath, Encoding.UTF8));
                if (settings.HasAnyDestination())
                {
                    return settings;
                }
            }
        }
        catch
        {
            return new LesUploadSettings();
        }

        return new LesUploadSettings();
    }

    public void Save()
    {
        Directory.CreateDirectory(Path.GetDirectoryName(ConfigPath)!);
        File.WriteAllText(ConfigPath, LesJsonWriter.Serialize(this), Encoding.UTF8);
    }

    public bool HasAnyDestination()
    {
        return LesUrls.Any(url => !string.IsNullOrWhiteSpace(url))
            || CustomUrls.Any(url => !string.IsNullOrWhiteSpace(url))
            || !string.IsNullOrWhiteSpace(LocalOutputDir);
    }

    public string ResolveLocalOutputDir()
    {
        return string.IsNullOrWhiteSpace(LocalOutputDir)
            ? Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments)
            : Environment.ExpandEnvironmentVariables(LocalOutputDir);
    }
}

internal sealed class LesUploadResult
{
    public LesUploadResult(bool success, string url, string responseSummary, string error)
    {
        Success = success;
        Url = url;
        ResponseSummary = responseSummary;
        Error = error;
    }

    public bool Success { get; }
    public string Url { get; }
    public string ResponseSummary { get; }
    public string Error { get; }
}

internal static class LesUploader
{
    public static async Task<LesUploadResult> UploadAsync(CadBimGraph graph, string sourceType, LesUploadSettings settings)
    {
        var errors = new List<string>();
        foreach (var endpoint in Endpoints(settings))
        {
            try
            {
                var response = await PostAsync(endpoint, graph, sourceType, settings).ConfigureAwait(false);
                return new LesUploadResult(true, endpoint, response, string.Empty);
            }
            catch (Exception error)
            {
                errors.Add(endpoint + " -> " + error.Message);
            }
        }

        return new LesUploadResult(false, string.Empty, string.Empty, string.Join("; ", errors));
    }

    private static IEnumerable<string> Endpoints(LesUploadSettings settings)
    {
        foreach (var baseUrl in settings.LesUrls.Where(url => !string.IsNullOrWhiteSpace(url)))
        {
            yield return baseUrl.TrimEnd('/') + "/api/cad-bim/import";
        }

        foreach (var url in settings.CustomUrls.Where(url => !string.IsNullOrWhiteSpace(url)))
        {
            yield return EndpointFromCustomUrl(url);
        }
    }

    private static string EndpointFromCustomUrl(string value)
    {
        var text = value.Trim();
        if (!Uri.TryCreate(text, UriKind.Absolute, out var uri))
        {
            return text;
        }

        return string.IsNullOrWhiteSpace(uri.AbsolutePath) || uri.AbsolutePath == "/"
            ? text.TrimEnd('/') + "/api/cad-bim/import"
            : text;
    }

    private static async Task<string> PostAsync(string endpoint, CadBimGraph graph, string sourceType, LesUploadSettings settings)
    {
        using var client = new HttpClient { Timeout = TimeSpan.FromSeconds(Math.Max(5, settings.TimeoutSec)) };
        if (!string.IsNullOrWhiteSpace(settings.ApiKey))
        {
            client.DefaultRequestHeaders.Add("X-API-Key", settings.ApiKey);
        }

        var json = LesJsonWriter.SerializeImportBody(graph, sourceType, 50000);
        using var content = new StringContent(json, Encoding.UTF8, "application/json");
        using var response = await client.PostAsync(endpoint, content).ConfigureAwait(false);
        var text = await response.Content.ReadAsStringAsync().ConfigureAwait(false);
        if (!response.IsSuccessStatusCode)
        {
            throw new InvalidOperationException($"HTTP {(int)response.StatusCode}: {Trim(text, 360)}");
        }

        return Trim(text, 360);
    }

    private static string Trim(string value, int max)
    {
        var text = (value ?? string.Empty).Replace("\r", " ").Replace("\n", " ").Trim();
        return text.Length <= max ? text : text.Substring(0, max) + "...";
    }
}
