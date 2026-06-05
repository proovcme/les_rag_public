using System;
using System.Linq;
using System.Windows.Input;
using Autodesk.AutoCAD.ApplicationServices.Core;
using Autodesk.AutoCAD.Runtime;
using Autodesk.Windows;

[assembly: ExtensionApplication(typeof(LES.AutoCAD.JsonExport.LesAutoCadApplication))]

namespace LES.AutoCAD.JsonExport;

public sealed class LesAutoCadApplication : IExtensionApplication
{
    private static bool _ribbonCreated;

    public void Initialize()
    {
        TryCreateRibbon();
        Application.Idle += OnIdle;
    }

    public void Terminate()
    {
        Application.Idle -= OnIdle;
    }

    private static void OnIdle(object? sender, EventArgs e)
    {
        if (TryCreateRibbon())
        {
            Application.Idle -= OnIdle;
        }
    }

    private static bool TryCreateRibbon()
    {
        if (_ribbonCreated)
        {
            return true;
        }

        try
        {
            _ribbonCreated = CreateRibbon();
            return _ribbonCreated;
        }
        catch
        {
            // AutoCAD can load bundles before the ribbon is ready. Commands still work.
            return false;
        }
    }

    private static bool CreateRibbon()
    {
        var ribbon = ComponentManager.Ribbon;
        if (ribbon == null)
        {
            return false;
        }

        var tab = ribbon.Tabs.FirstOrDefault(item => item.Id == "LES_CAD_BIM_TAB");
        if (tab == null)
        {
            tab = new RibbonTab
            {
                Id = "LES_CAD_BIM_TAB",
                Title = "LES",
            };
            ribbon.Tabs.Add(tab);
        }

        if (tab.Panels.Any(panel => panel.Source?.Title == "CAD/BIM"))
        {
            return true;
        }

        var source = new RibbonPanelSource { Title = "CAD/BIM" };
        var panel = new RibbonPanel { Source = source };
        tab.Panels.Add(panel);

        source.Items.Add(Button("Export JSON", "Save cad_bim_graph.json", "LESJSONEXPORT ", LesRibbonIcons.ExportJson()));
        source.Items.Add(Button("Push to LES", "Export and upload to LES", "LESJSONPUSH ", LesRibbonIcons.PushToLes()));
        source.Items.Add(Button("Settings", "Configure LES URLs", "LESJSONCONFIG ", LesRibbonIcons.Settings()));
        return true;
    }

    private static RibbonButton Button(string text, string tooltip, string command, System.Windows.Media.ImageSource icon)
    {
        return new RibbonButton
        {
            Text = text,
            ShowText = true,
            ShowImage = true,
            Image = icon,
            LargeImage = icon,
            ToolTip = tooltip,
            CommandHandler = new AutoCadCommandHandler(command),
        };
    }
}

internal sealed class AutoCadCommandHandler : ICommand
{
    private readonly string _command;

    public AutoCadCommandHandler(string command)
    {
        _command = command;
    }

    public event EventHandler? CanExecuteChanged;

    public bool CanExecute(object? parameter)
    {
        return true;
    }

    public void Execute(object? parameter)
    {
        var document = Application.DocumentManager.MdiActiveDocument;
        document?.SendStringToExecute(_command, true, false, true);
    }
}
