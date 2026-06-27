using System;
using System.Collections.Generic;
using System.Linq;
using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using MyVeras.UI.Windows;

namespace MyVeras.RevitAPI.Commands
{
    /// <summary>
    /// Команда для открытия главного рабочего окна MyVeras
    /// </summary>
    [Transaction(TransactionMode.Manual)]
    [Regeneration(RegenerationOption.Manual)]
    public class OpenCommand : IExternalCommand
    {
        public Result Execute(ExternalCommandData commandData, ref string message, ElementSet elements)
        {
            try
            {
                var uidoc = commandData.Application.ActiveUIDocument;
                var doc = uidoc.Document;

                if (doc == null)
                {
                    message = "No active document found";
                    return Result.Failed;
                }

                // Получаем 3D виды
                var viewNames = GetAllViewNames(doc);
                
                // Открываем главное окно
                var mainWindow = new MainWindow(doc, viewNames);
                mainWindow.Show();
                
                message = "MyVeras window opened successfully";
                return Result.Succeeded;
            }
            catch (Exception ex)
            {
                message = $"Error opening MyVeras: {ex.Message}";
                TaskDialog.Show("MyVeras Error", message);
                return Result.Failed;
            }
        }

        /// <summary>
        /// Получает список имен всех видов (2D и 3D) со строгой фильтрацией
        /// </summary>
        private List<string> GetAllViewNames(Document doc)
        {
            var viewNames = new List<string>();
            
            try
            {
                // Создаем строгий фильтр для View3D и ViewPlan
                var view3DCollector = new FilteredElementCollector(doc)
                    .OfClass(typeof(View3D))
                    .WhereElementIsNotElementType();
                
                var viewPlanCollector = new FilteredElementCollector(doc)
                    .OfClass(typeof(ViewPlan))
                    .WhereElementIsNotElementType();
                
                // Объединяем результаты
                var allValidViews = new List<View>();
                allValidViews.AddRange(view3DCollector.Cast<View>());
                allValidViews.AddRange(viewPlanCollector.Cast<View>());
                
                foreach (var view in allValidViews)
                {
                    try
                    {
                        // СТРОГАЯ ФИЛЬТРАЦИЯ:
                        // 1. Исключаем шаблоны
                        if (view.IsTemplate)
                            continue;
                        
                        // 2. Исключаем невалидные объекты
                        if (!view.IsValidObject)
                            continue;
                        
                        // 3. Исключаем листы (ViewSheet)
                        if (view is ViewSheet)
                            continue;
                        
                        // 4. Исключаем спецификации (Schedule)
                        if (view.ViewType == ViewType.Schedule)
                            continue;
                        
                        // 5. Исключаем системные виды (символы < и >)
                        if (string.IsNullOrEmpty(view.Name) || 
                            view.Name.Contains("<") || 
                            view.Name.Contains(">"))
                            continue;
                        
                        // 6. Исключаем виды с ключевыми словами системных элементов
                        var systemKeywords = new[] { "Schedule", "Legend", "Template", "Drafting", "Detail" };
                        if (systemKeywords.Any(keyword => view.Name.Contains(keyword, StringComparison.OrdinalIgnoreCase)))
                            continue;
                        
                        // 7. Добавляем только виды с непустыми именами
                        if (!string.IsNullOrWhiteSpace(view.Name))
                        {
                            viewNames.Add(view.Name.Trim());
                        }
                    }
                    catch (Exception ex)
                    {
                        System.Diagnostics.Debug.WriteLine($"Error processing view {view.Name}: {ex.Message}");
                        continue;
                    }
                }
                
                // Сортируем по алфавиту
                viewNames.Sort(StringComparer.OrdinalIgnoreCase);
                
                // Если нет видов, добавляем сообщение
                if (viewNames.Count == 0)
                {
                    viewNames.Add("Нет доступных 3D видов или планов");
                }
            }
            catch (Exception ex)
            {
                System.Diagnostics.Debug.WriteLine($"Error collecting views: {ex.Message}");
                viewNames.Add("Ошибка загрузки видов");
            }
            
            return viewNames;
        }
    }
}
