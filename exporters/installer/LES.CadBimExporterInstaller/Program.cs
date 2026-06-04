using System.Reflection;
using System.Text;
using Microsoft.Win32;

namespace LES.CadBimExporterInstaller;

internal static class Program
{
    private const string AutoCadDll = "LES.AutoCAD.JsonExport.dll";
    private const string RevitDll = "LES.Revit.JsonExport.dll";

    private static int Main(string[] args)
    {
        var pauseOnExit = args.Length == 0 || args.Contains("--pause", StringComparer.Ordinal);
        try
        {
            var options = InstallOptions.Parse(args);
            var payloadDir = options.PayloadDir ?? AppContext.BaseDirectory;
            InstallAutoCad(payloadDir, options.AutoCadYear);
            InstallRevit(payloadDir, options.RevitYear);
            Console.WriteLine("LES CAD/BIM exporters installed.");
            Console.WriteLine("AutoCAD: restart AutoCAD and use ribbon tab LES, or run LESJSONEXPORT / LESJSONPUSH.");
            Console.WriteLine("Revit: restart Revit and use ribbon tab LES.");
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
            Console.Error.WriteLine("  LES.CadBimExporterInstaller.exe [--payload-dir <dir>] [--autocad-year 2025] [--revit-year 2025] [--pause]");
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

internal sealed record InstallOptions(string AutoCadYear, string RevitYear, string? PayloadDir)
{
    public static InstallOptions Parse(string[] args)
    {
        string? autocadYear = null;
        string? revitYear = null;
        string? payloadDir = null;
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
                case "--payload-dir":
                    payloadDir = RequireValue(args, ref i, "--payload-dir");
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

        return new InstallOptions(autocadYear, revitYear, payloadDir);
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
}
