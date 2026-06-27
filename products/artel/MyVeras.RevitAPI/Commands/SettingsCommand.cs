using System;
using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using MyVeras.UI.Windows;
using MyVeras.Settings;

namespace MyVeras.RevitAPI.Commands
{
    /// <summary>
    /// Команда для открытия окна настроек API ключа
    /// </summary>
    [Transaction(TransactionMode.Manual)]
    [Regeneration(RegenerationOption.Manual)]
    public class SettingsCommand : IExternalCommand
    {
        public Result Execute(ExternalCommandData commandData, ref string message, ElementSet elements)
        {
            try
            {
                var uiApp = commandData.Application;
                var uidoc = uiApp.ActiveUIDocument;
                
                if (uidoc == null)
                {
                    TaskDialog.Show("MyVeras", "Нет активного документа Revit");
                    return Result.Failed;
                }

                // Открываем окно настроек
                var settingsWindow = new SettingsWindow();
                settingsWindow.ShowDialog();
                
                return Result.Succeeded;
            }
            catch (Exception ex)
            {
                message = $"Ошибка открытия настроек: {ex.Message}\n\nStack Trace:\n{ex.StackTrace}";
                TaskDialog.Show("MyVeras Error", message);
                return Result.Failed;
            }
        }
    }
}
