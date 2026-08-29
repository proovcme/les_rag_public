using System.Reflection;
using System.Text;
using Microsoft.Win32;

namespace LES.CadBimExporterInstaller;

internal static class Program
{
    private const string AutoCadDll = "LES.AutoCAD.JsonExport.dll";
    private const string RevitDll = "LES.Revit.JsonExport.dll";
    private const string NavisworksDll = "LES.Navisworks.JsonExport.dll";

    private static int Main(string[] args)
    {
        var pauseOnExit = args.Length == 0 || args.Contains("--pause", StringComparer.Ordinal);
        try
        {
            var options = InstallOptions.Parse(args);
            var payloadDir = options.PayloadDir ?? AppContext.BaseDirectory;
            EnsureSharedConfig(options);
            if (options.InstallAutoCad)
            {
                InstallAutoCad(payloadDir, options.AutoCadYear);
            }

            if (options.InstallRevit)
            {
                InstallRevit(payloadDir, options.RevitYear);
            }

            if (options.InstallNavisworks)
            {
                InstallNavisworks(payloadDir, options.NavisworksYear);
            }

            Console.WriteLine("LES CAD/BIM exporters installed.");
            if (options.InstallAutoCad)
            {
                Console.WriteLine("AutoCAD: restart AutoCAD and use ribbon tab LES, or run LESJSONEXPORT / LESJSONPUSH.");
            }

            if (options.InstallRevit)
            {
                Console.WriteLine("Revit: restart Revit and use ribbon tab LES.");
            }

            if (options.InstallNavisworks)
            {
                Console.WriteLine("Navisworks: restart Navisworks and use the Add-Ins plugin LES JSON Export.");
            }

            return 0;
        }
        catch (Exception error)
        {
            Console.Error.WriteLine("Install failed: " + error.Message);
            if (error is FileNotFoundException fileError && !string.IsNullOrWhiteSpace(fileError.FileName))
            {
                Console.Error.WriteLine("Missing file: " + fileError.FileName);
            }

            Console.Error.WriteLine();
            Console.Error.WriteLine("Usage:");
            Console.Error.WriteLine("  LES.CadBimPluginsSetup.exe [--only autocad,revit,navisworks] [--skip navisworks]");
            Console.Error.WriteLine("    [--payload-dir <dir>] [--autocad-year 2025] [--revit-year 2025] [--navisworks-year 2025]");
            Console.Error.WriteLine("    [--les-url <url>] [--custom-url <url>] [--local-output-dir <dir>] [--api-key <key>] [--timeout-sec 60]");
            return 1;
        }
        finally
        {
            if (pauseOnExit)
            {
                Console.WriteLine();
                Console.WriteLine("Press any key to close...");
                try
                {
                    Console.ReadKey(intercept: true);
                }
                catch (InvalidOperationException)
                {
                    // Standard input can be redirected in automation; do not fail the install.
                }
            }
        }
    }

    private static void EnsureSharedConfig(InstallOptions options)
    {
        var configPath = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
            "LES",
            "cad_bim_exporter_settings.json"
        );
        if (File.Exists(configPath) && !options.HasConfigOverrides)
        {
            Console.WriteLine("Shared destination config already exists: " + configPath);
            return;
        }

        var lesUrls = options.LesUrls.Count == 0
            ? new List<string> { "http://127.0.0.1:8050" }
            : options.LesUrls;
        var localOutputDir = string.IsNullOrWhiteSpace(options.LocalOutputDir)
            ? @"%USERPROFILE%\Documents\LES CAD BIM"
            : options.LocalOutputDir;

        Directory.CreateDirectory(Path.GetDirectoryName(configPath)!);
        File.WriteAllText(
            configPath,
            SharedConfigJson(lesUrls, options.CustomUrls, localOutputDir, options.ApiKey, options.TimeoutSec),
            Encoding.UTF8
        );
        Console.WriteLine("Shared destination config written: " + configPath);
    }

    private static string SharedConfigJson(
        IReadOnlyCollection<string> lesUrls,
        IReadOnlyCollection<string> customUrls,
        string localOutputDir,
        string apiKey,
        int timeoutSec
    )
    {
        var builder = new StringBuilder();
        builder.AppendLine("{");
        builder.Append("  \"les_urls\": ");
        AppendStringArray(builder, lesUrls);
        builder.AppendLine(",");
        builder.Append("  \"custom_urls\": ");
        AppendStringArray(builder, customUrls);
        builder.AppendLine(",");
        builder.AppendLine("  \"local_output_dir\": \"" + Escape(localOutputDir) + "\",");
        builder.AppendLine("  \"api_key\": \"" + Escape(apiKey) + "\",");
        builder.AppendLine("  \"timeout_sec\": " + Math.Max(5, timeoutSec));
        builder.AppendLine("}");
        return builder.ToString();
    }

    private static void AppendStringArray(StringBuilder builder, IReadOnlyCollection<string> values)
    {
        builder.Append('[');
        var first = true;
        foreach (var value in values.Where(item => !string.IsNullOrWhiteSpace(item)).Distinct(StringComparer.OrdinalIgnoreCase))
        {
            if (!first)
            {
                builder.Append(", ");
            }

            builder.Append('"');
            builder.Append(Escape(value));
            builder.Append('"');
            first = false;
        }

        builder.Append(']');
    }

    private static string Escape(string value)
    {
        return value.Replace("\\", "\\\\").Replace("\"", "\\\"");
    }

    private static void InstallAutoCad(string payloadDir, string year)
    {
        var sourceDll = ResolvePayloadFile(payloadDir, AutoCadDll);
        var bundleRoot = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
            "Autodesk",
            "ApplicationPlugins",
            "LES.AutoCAD.JsonExport.bundle"
        );
        var contentsDir = Path.Combine(bundleRoot, "Contents", "Windows");
        Directory.CreateDirectory(contentsDir);
        File.Copy(sourceDll, Path.Combine(contentsDir, AutoCadDll), overwrite: true);
        File.WriteAllText(Path.Combine(bundleRoot, "PackageContents.xml"), AutoCadPackageContents(year), Encoding.UTF8);
        Console.WriteLine("AutoCAD exporter installed: " + bundleRoot);
    }

    private static void InstallRevit(string payloadDir, string year)
    {
        var sourceDll = ResolvePayloadFile(payloadDir, RevitDll);
        var addinsDir = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
            "Autodesk",
            "Revit",
            "Addins",
            year
        );
        Directory.CreateDirectory(addinsDir);
        var targetDll = Path.Combine(addinsDir, RevitDll);
        File.Copy(sourceDll, targetDll, overwrite: true);
        File.WriteAllText(Path.Combine(addinsDir, "LES.Revit.JsonExport.addin"), RevitAddin(targetDll), Encoding.UTF8);
        Console.WriteLine("Revit exporter installed: " + addinsDir);
    }

    private static void InstallNavisworks(string payloadDir, string year)
    {
        var sourceDll = ResolvePayloadFile(payloadDir, NavisworksDll);
        var pluginDir = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
            "Autodesk Navisworks Manage " + year,
            "Plugins",
            "LES.Navisworks.JsonExport"
        );
        Directory.CreateDirectory(pluginDir);
        File.Copy(sourceDll, Path.Combine(pluginDir, NavisworksDll), overwrite: true);
        Console.WriteLine("Navisworks exporter installed: " + pluginDir);
    }

    private static string ResolvePayloadFile(string payloadDir, string fileName)
    {
        foreach (var path in PayloadCandidates(payloadDir, fileName))
        {
            if (File.Exists(path))
            {
                return path;
            }
        }

        var resourceName = "payload." + fileName;
        var assembly = Assembly.GetExecutingAssembly();
        using var resource = assembly.GetManifestResourceStream(resourceName);
        if (resource is null)
        {
            throw new FileNotFoundException(
                "Required payload DLL not found next to the installer and not embedded in the installer",
                Path.Combine(payloadDir, fileName)
            );
        }

        var extractedDir = Path.Combine(Path.GetTempPath(), "LES.CadBimExporterInstaller", "payload");
        Directory.CreateDirectory(extractedDir);
        var extractedPath = Path.Combine(extractedDir, fileName);
        using var output = File.Create(extractedPath);
        resource.CopyTo(output);
        return extractedPath;
    }

    private static IEnumerable<string> PayloadCandidates(string payloadDir, string fileName)
    {
        yield return Path.Combine(payloadDir, fileName);
        yield return Path.Combine(payloadDir, "payload", fileName);
        yield return Path.Combine(AppContext.BaseDirectory, fileName);
        yield return Path.Combine(AppContext.BaseDirectory, "payload", fileName);
    }

    private static string AutoCadPackageContents(string year)
    {
        return $$"""
<?xml version="1.0" encoding="utf-8"?>
<ApplicationPackage
  SchemaVersion="1.0"
  AutodeskProduct="AutoCAD"
  ProductType="Application"
  Name="LES AutoCAD JSON Export"
  Description="Exports DWG entities to LES cad_bim_graph.json."
  AppVersion="1.0.0"
  FriendlyVersion="1.0.0"
  ProductCode="{7D5EABAA-953B-4CEB-AE30-A154D0DC06C4}"
  UpgradeCode="{730762B4-08D4-498D-A9C0-D2F9B6C7E138}">
  <CompanyDetails Name="LES" />
  <Components>
    <RuntimeRequirements OS="Win64" Platform="AutoCAD" SeriesMin="R{{AutoCadSeries(year)}}.0" SeriesMax="R{{AutoCadSeries(year)}}.9" />
    <ComponentEntry AppName="LES AutoCAD JSON Export" ModuleName="./Contents/Windows/{{AutoCadDll}}" LoadOnAutoCADStartup="True" LoadOnCommandInvocation="True">
      <Commands GroupName="LES">
        <Command Global="LESJSONEXPORT" Local="LESJSONEXPORT" />
        <Command Global="LESJSONPUSH" Local="LESJSONPUSH" />
        <Command Global="LESJSONCONFIG" Local="LESJSONCONFIG" />
      </Commands>
    </ComponentEntry>
  </Components>
</ApplicationPackage>
""";
    }

    private static string RevitAddin(string targetDll)
    {
        return $"""
<?xml version="1.0" encoding="utf-8"?>
<RevitAddIns>
  <AddIn Type="Application">
    <Name>LES CAD/BIM Exporter</Name>
    <Assembly>{targetDll}</Assembly>
    <AddInId>B94B4B90-B896-4C68-9007-99BF98CA87DE</AddInId>
    <FullClassName>LES.Revit.JsonExport.LesJsonApplication</FullClassName>
    <VendorId>LES</VendorId>
    <VendorDescription>LES CAD/BIM JSON exporter</VendorDescription>
  </AddIn>
  <AddIn Type="Command">
    <Name>LES JSON Export</Name>
    <Assembly>{targetDll}</Assembly>
    <AddInId>9E7949B8-40EC-4CF6-BFC1-013EE651419E</AddInId>
    <FullClassName>LES.Revit.JsonExport.LesJsonExportCommand</FullClassName>
    <VendorId>LES</VendorId>
    <VendorDescription>LES CAD/BIM JSON exporter</VendorDescription>
    <Text>LES JSON Export</Text>
    <Description>Export active Revit model to LES cad_bim_graph.json.</Description>
  </AddIn>
  <AddIn Type="Command">
    <Name>LES JSON Push</Name>
    <Assembly>{targetDll}</Assembly>
    <AddInId>71847DCE-C59B-4787-9FDF-705D7D0E8E53</AddInId>
    <FullClassName>LES.Revit.JsonExport.LesJsonPushCommand</FullClassName>
    <VendorId>LES</VendorId>
    <VendorDescription>LES CAD/BIM JSON exporter</VendorDescription>
    <Text>LES JSON Push</Text>
    <Description>Export active Revit model and upload it to LES.</Description>
  </AddIn>
  <AddIn Type="Command">
    <Name>LES JSON Config</Name>
    <Assembly>{targetDll}</Assembly>
    <AddInId>6C4EA062-DDF6-49DB-9714-A4F018B2EFB3</AddInId>
    <FullClassName>LES.Revit.JsonExport.LesJsonConfigCommand</FullClassName>
    <VendorId>LES</VendorId>
    <VendorDescription>LES CAD/BIM JSON exporter</VendorDescription>
    <Text>LES JSON Config</Text>
    <Description>Open LES CAD/BIM exporter destination config.</Description>
  </AddIn>
</RevitAddIns>
""";
    }

    private static int AutoCadSeries(string year)
    {
        return year switch
        {
            "2021" => 24,
            "2022" => 24,
            "2023" => 24,
            "2024" => 24,
            "2025" => 25,
            "2026" => 25,
            _ => 24,
        };
    }
}

internal sealed record InstallOptions(
    string AutoCadYear,
    string RevitYear,
    string NavisworksYear,
    string? PayloadDir,
    bool InstallAutoCad,
    bool InstallRevit,
    bool InstallNavisworks,
    List<string> LesUrls,
    List<string> CustomUrls,
    string LocalOutputDir,
    string ApiKey,
    int TimeoutSec,
    bool HasConfigOverrides
)
{
    public static InstallOptions Parse(string[] args)
    {
        string? autocadYear = null;
        string? revitYear = null;
        string? navisworksYear = null;
        string? payloadDir = null;
        var installAutoCad = true;
        var installRevit = true;
        var installNavisworks = true;
        var lesUrls = new List<string>();
        var customUrls = new List<string>();
        var localOutputDir = string.Empty;
        var apiKey = string.Empty;
        var timeoutSec = 60;
        var hasConfigOverrides = false;
        for (var i = 0; i < args.Length; i++)
        {
            switch (args[i])
            {
                case "--autocad-year":
                    autocadYear = RequireValue(args, ref i, "--autocad-year");
                    break;
                case "--revit-year":
                    revitYear = RequireValue(args, ref i, "--revit-year");
                    break;
                case "--navisworks-year":
                    navisworksYear = RequireValue(args, ref i, "--navisworks-year");
                    break;
                case "--payload-dir":
                    payloadDir = RequireValue(args, ref i, "--payload-dir");
                    break;
                case "--only":
                    (installAutoCad, installRevit, installNavisworks) = TargetSelection(RequireValue(args, ref i, "--only"), only: true);
                    break;
                case "--skip":
                    var skipped = TargetSelection(RequireValue(args, ref i, "--skip"), only: false);
                    installAutoCad = installAutoCad && skipped.AutoCad;
                    installRevit = installRevit && skipped.Revit;
                    installNavisworks = installNavisworks && skipped.Navisworks;
                    break;
                case "--les-url":
                    lesUrls.AddRange(SplitCsv(RequireValue(args, ref i, "--les-url")));
                    hasConfigOverrides = true;
                    break;
                case "--custom-url":
                    customUrls.AddRange(SplitCsv(RequireValue(args, ref i, "--custom-url")));
                    hasConfigOverrides = true;
                    break;
                case "--local-output-dir":
                    localOutputDir = RequireValue(args, ref i, "--local-output-dir");
                    hasConfigOverrides = true;
                    break;
                case "--api-key":
                    apiKey = RequireValue(args, ref i, "--api-key");
                    hasConfigOverrides = true;
                    break;
                case "--timeout-sec":
                    if (!int.TryParse(RequireValue(args, ref i, "--timeout-sec"), out timeoutSec))
                    {
                        throw new InvalidOperationException("--timeout-sec requires an integer value");
                    }

                    hasConfigOverrides = true;
                    break;
                case "--pause":
                case "--no-pause":
                    break;
                case "--help":
                case "-h":
                    throw new InvalidOperationException("help requested");
                default:
                    throw new InvalidOperationException("Unknown argument: " + args[i]);
            }
        }

        autocadYear ??= DetectAutoCadYear() ?? "2025";
        revitYear ??= DetectRevitYear() ?? "2025";
        navisworksYear ??= DetectNavisworksYear() ?? "2025";

        if (!installAutoCad && !installRevit && !installNavisworks)
        {
            throw new InvalidOperationException("No installer targets selected");
        }

        return new InstallOptions(
            autocadYear,
            revitYear,
            navisworksYear,
            payloadDir,
            installAutoCad,
            installRevit,
            installNavisworks,
            CleanUrls(lesUrls),
            CleanUrls(customUrls),
            localOutputDir,
            apiKey,
            timeoutSec,
            hasConfigOverrides
        );
    }

    private static (bool AutoCad, bool Revit, bool Navisworks) TargetSelection(string value, bool only)
    {
        var autoCad = !only;
        var revit = !only;
        var navisworks = !only;
        foreach (var token in SplitCsv(value).Select(item => item.ToLowerInvariant()))
        {
            switch (token)
            {
                case "all":
                    autoCad = only;
                    revit = only;
                    navisworks = only;
                    break;
                case "autocad":
                case "dwg":
                    autoCad = only;
                    break;
                case "revit":
                case "rvt":
                    revit = only;
                    break;
                case "navisworks":
                case "nwd":
                case "nwf":
                    navisworks = only;
                    break;
                default:
                    throw new InvalidOperationException("Unknown installer target: " + token);
            }
        }

        return (autoCad, revit, navisworks);
    }

    private static List<string> SplitCsv(string value)
    {
        return value.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries).ToList();
    }

    private static List<string> CleanUrls(IEnumerable<string> urls)
    {
        return urls
            .Where(url => url.StartsWith("http://", StringComparison.OrdinalIgnoreCase) || url.StartsWith("https://", StringComparison.OrdinalIgnoreCase))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();
    }

    private static string RequireValue(string[] args, ref int index, string name)
    {
        if (index + 1 >= args.Length || args[index + 1].StartsWith("--", StringComparison.Ordinal))
        {
            throw new InvalidOperationException(name + " requires a value");
        }

        index++;
        return args[index];
    }

    private static string? DetectAutoCadYear()
    {
        using var root = Registry.LocalMachine.OpenSubKey(@"SOFTWARE\Autodesk\AutoCAD");
        if (root is null)
        {
            return null;
        }

        var years = new List<int>();
        foreach (var releaseKeyName in root.GetSubKeyNames())
        {
            using var releaseKey = root.OpenSubKey(releaseKeyName);
            if (releaseKey is null)
            {
                continue;
            }

            foreach (var productKeyName in releaseKey.GetSubKeyNames())
            {
                using var productKey = releaseKey.OpenSubKey(productKeyName);
                var year = productKey?.GetValue("UPIRELEASE")?.ToString();
                if (int.TryParse(year, out var parsed))
                {
                    years.Add(parsed);
                }
            }
        }

        return years.Count == 0 ? null : years.Max().ToString();
    }

    private static string? DetectRevitYear()
    {
        using var root = Registry.LocalMachine.OpenSubKey(@"SOFTWARE\Autodesk\Revit");
        if (root is null)
        {
            return null;
        }

        var years = new List<int>();
        foreach (var keyName in root.GetSubKeyNames())
        {
            foreach (var token in keyName.Split(' ', StringSplitOptions.RemoveEmptyEntries))
            {
                if (int.TryParse(token, out var parsed) && parsed >= 2020 && parsed <= 2035)
                {
                    years.Add(parsed);
                }
            }
        }

        return years.Count == 0 ? null : years.Max().ToString();
    }

    private static string? DetectNavisworksYear()
    {
        using var root = Registry.LocalMachine.OpenSubKey(@"SOFTWARE\Autodesk\Navisworks");
        if (root is null)
        {
            return null;
        }

        var years = new List<int>();
        foreach (var keyName in root.GetSubKeyNames())
        {
            foreach (var token in keyName.Split(' ', StringSplitOptions.RemoveEmptyEntries))
            {
                if (int.TryParse(token, out var parsed) && parsed >= 2020 && parsed <= 2035)
                {
                    years.Add(parsed);
                }
            }
        }

        return years.Count == 0 ? null : years.Max().ToString();
    }
}
