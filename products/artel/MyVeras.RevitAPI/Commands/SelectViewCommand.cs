using System;
using System.Collections.Generic;
using System.Linq;
using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using MyVeras.UI.Windows;
using MyVeras.Core;

namespace MyVeras.RevitAPI.Commands
{
    /// <summary>
    /// Команда для выбора 3D вида
    /// </summary>
    [Transaction(TransactionMode.Manual)]
    [Regeneration(RegenerationOption.Manual)]
    public class SelectViewCommand : IExternalCommand
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

                // Собираем 3D виды
                var viewNames = GetView3DNames(uidoc.Document);
                
                // Открываем окно выбора вида
                var selectViewWindow = new SelectViewWindow(viewNames);
                selectViewWindow.ShowDialog();
                
                return Result.Succeeded;
            }
            catch (Exception ex)
            {
                message = $"Ошибка выбора вида: {ex.Message}";
                TaskDialog.Show("MyVeras Error", message);
                return Result.Failed;
            }
        }

        /// <summary>
        /// Получает список имен 3D видов
        /// </summary>
        private List<string> GetView3DNames(Document doc)
        {
            var viewNames = new List<string>();
            
            try
            {
                var collector = new FilteredElementCollector(doc);
                var allViews = collector.OfClass(typeof(View3D));
                
                foreach (Element element in allViews)
                {
                    try
                    {
                        var view3D = element as View3D;
                        
                        // Пропускаем шаблоны и невалидные виды
                        if (view3D == null || view3D.IsTemplate || !view3D.IsValidObject)
                        {
                            continue;
                        }
                        
                        // Добавляем только валидные имена
                        if (!string.IsNullOrEmpty(view3D.Name))
                        {
                            viewNames.Add(view3D.Name);
                        }
                    }
                    catch
                    {
                        // Игнорируем ошибки с конкретными видами
                        continue;
                    }
                }
                
                // Сортируем по имени
                viewNames.Sort();
                
                if (viewNames.Count == 0)
                {
                    viewNames.Add("Нет доступных 3D видов");
                }
            }
            catch (Exception ex)
            {
                System.Diagnostics.Debug.WriteLine($"Error collecting 3D views: {ex.Message}");
                viewNames.Add("Ошибка загрузки видов");
            }
            
            return viewNames;
        }
    }
}
