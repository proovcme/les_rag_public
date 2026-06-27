using System;
using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using MyVeras.UI.Windows;
using MyVeras.Core;

namespace MyVeras.RevitAPI.Commands
{
    /// <summary>
    /// Команда для экспорта сгенерированного изображения
    /// </summary>
    [Transaction(TransactionMode.Manual)]
    [Regeneration(RegenerationOption.Manual)]
    public class ExportCommand : IExternalCommand
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

                // Открываем диалог экспорта
                var exportWindow = new ExportWindow();
                exportWindow.ShowDialog();
                
                return Result.Succeeded;
            }
            catch (Exception ex)
            {
                message = $"Ошибка экспорта: {ex.Message}";
                TaskDialog.Show("MyVeras Error", message);
                return Result.Failed;
            }
        }
    }
}
