using System;
using System.Diagnostics;
using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;

namespace LES.Revit.JsonExport;

[Transaction(TransactionMode.Manual)]
[Regeneration(RegenerationOption.Manual)]
public sealed class LesJsonConfigCommand : IExternalCommand
{
    public Result Execute(ExternalCommandData commandData, ref string message, ElementSet elements)
    {
        try
        {
            var settings = LesUploadSettings.Load();
            settings.Save();
            Process.Start(new ProcessStartInfo
            {
                FileName = LesUploadSettings.ConfigPath,
                UseShellExecute = true,
            });
            TaskDialog.Show(
                "LES JSON Config",
                "Opened exporter config:\n" + LesUploadSettings.ConfigPath + "\n\n" +
                "Use les_urls for LES/local LES bases, custom_urls for arbitrary POST endpoints, " +
                "and local_output_dir for offline JSON saves."
            );
            return Result.Succeeded;
        }
        catch (Exception error)
        {
            message = error.Message;
            return Result.Failed;
        }
    }
}
