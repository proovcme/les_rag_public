using System;
using System.IO;
using System.Text;
using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;

namespace LES.Revit.JsonExport;

[Transaction(TransactionMode.Manual)]
[Regeneration(RegenerationOption.Manual)]
public sealed class LesJsonPushCommand : IExternalCommand
{
    public Result Execute(ExternalCommandData commandData, ref string message, ElementSet elements)
    {
        var document = commandData.Application.ActiveUIDocument?.Document;
        if (document == null)
        {
            message = "No active Revit document.";
            return Result.Failed;
        }

        try
        {
            var payload = LesJsonExportCommand.BuildPayload(document);
            var settings = LesUploadSettings.Load();
            var result = LesUploader.UploadAsync(payload, "revit", settings).GetAwaiter().GetResult();
            if (result.Success)
            {
                TaskDialog.Show("LES JSON Push", $"Imported {payload.Elements.Count} Revit elements via:\n{result.Url}");
                return Result.Succeeded;
            }

            var fallback = FallbackOutputPath(document);
            File.WriteAllText(fallback, LesJsonWriter.Serialize(payload), Encoding.UTF8);
            TaskDialog.Show("LES JSON Push", $"Upload failed; saved fallback JSON:\n{fallback}\n\n{result.Error}");
            return Result.Failed;
        }
        catch (Exception error)
        {
            message = error.Message;
            return Result.Failed;
        }
    }

    private static string FallbackOutputPath(Document document)
    {
        var documents = Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments);
        var stem = LesJsonExportCommand.SafeStem(document.Title, "revit_model");
        return Path.Combine(documents, $"{stem}.cad_bim_graph.json");
    }
}
