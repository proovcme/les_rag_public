using System;
using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using MyVeras.UI.Windows;
using MyVeras.Core;
using MyVeras.Settings;

namespace MyVeras.RevitAPI.Commands
{
    /// <summary>
    /// Команда для открытия окна генерации рендеринга
    /// </summary>
    [Transaction(TransactionMode.Manual)]
    [Regeneration(RegenerationOption.Manual)]
    public class RenderCommand : IExternalCommand
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

                // Получаем настройки
                var settingsManager = SettingsManager.Instance;
                settingsManager.LoadSettings();
                var settings = settingsManager.Settings;
                
                // Проверяем наличие API ключа
                if (string.IsNullOrEmpty(settings.ApiKey))
                {
                    TaskDialog.Show("MyVeras", "Сначала настройте API ключ в настройках!");
                    return Result.Failed;
                }

                // Открываем окно генерации
                var renderWindow = new RenderWindow(uidoc.Document, settings);
                renderWindow.ShowDialog();
                
                return Result.Succeeded;
            }
            catch (Exception ex)
            {
                message = $"Ошибка открытия генератора: {ex.Message}";
                TaskDialog.Show("MyVeras Error", message);
                return Result.Failed;
            }
        }
    }
}
