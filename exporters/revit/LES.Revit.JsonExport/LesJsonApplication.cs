using System;
using System.Reflection;
using Autodesk.Revit.UI;

namespace LES.Revit.JsonExport;

public sealed class LesJsonApplication : IExternalApplication
{
    private const string TabName = "LES";
    private const string PanelName = "CAD/BIM";

    public Result OnStartup(UIControlledApplication application)
    {
        try
        {
            try
            {
                application.CreateRibbonTab(TabName);
            }
            catch
            {
                // The tab already exists.
            }

            var panel = application.CreateRibbonPanel(TabName, PanelName);
            var assemblyPath = Assembly.GetExecutingAssembly().Location;
            var exportButton = new PushButtonData(
                "LES_JSON_EXPORT",
                "Export\nJSON",
                assemblyPath,
                typeof(LesJsonExportCommand).FullName
            )
            {
                ToolTip = "Save current Revit model as LES cad_bim_graph.json.",
                Image = LesRibbonIcons.ExportJson(),
                LargeImage = LesRibbonIcons.ExportJson(),
            };
            panel.AddItem(exportButton);

            var pushButton = new PushButtonData(
                "LES_JSON_PUSH",
                "Push\nto LES",
                assemblyPath,
                typeof(LesJsonPushCommand).FullName
            )
            {
                ToolTip = "Export current Revit model and upload it to LES over ZeroTier or tunnel.",
                Image = LesRibbonIcons.PushToLes(),
                LargeImage = LesRibbonIcons.PushToLes(),
            };
            panel.AddItem(pushButton);

            var configButton = new PushButtonData(
                "LES_JSON_CONFIG",
                "Config",
                assemblyPath,
                typeof(LesJsonConfigCommand).FullName
            )
            {
                ToolTip = "Open LES exporter destination config.",
                Image = LesRibbonIcons.PushToLes(),
                LargeImage = LesRibbonIcons.PushToLes(),
            };
            panel.AddItem(configButton);
            return Result.Succeeded;
        }
        catch
        {
            return Result.Succeeded;
        }
    }

    public Result OnShutdown(UIControlledApplication application)
    {
        return Result.Succeeded;
    }
}
