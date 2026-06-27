using System;
using System.Collections.Generic;
using System.Linq;
using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using MyVeras.UI.ViewModels;

namespace MyVeras.RevitAPI
{
    /// <summary>
    /// Команда для показа Modeless окна MyVeras
    /// </summary>
    [Transaction(TransactionMode.Manual)]
    [Regeneration(RegenerationOption.Manual)]
    public class RevitCommand : IExternalCommand
    {
        public Result Execute(ExternalCommandData commandData, ref string message, Autodesk.Revit.DB.ElementSet elements)
        {
            try
            {
                // ПЕРВОЕ ДЕЙСТВИЕ - диагностическое сообщение
                TaskDialog.Show("MyVeras", "Начало загрузки...");

                // Получаем UIApplication и Document
                var uiApp = commandData.Application;
                var doc = uiApp.ActiveUIDocument?.Document;

                if (doc == null)
                {
                    TaskDialog.Show("MyVeras Error", "Нет активного документа Revit");
                    return Result.Failed;
                }

                // Создаем ExternalEvent для безопасного доступа к Revit API из UI
                var eventHandler = new RevitExternalEventHandler();
                var externalEvent = ExternalEvent.Create(eventHandler);

                // Собираем 3D виды для передачи в UI
                var view3DNames = GetView3DNames(doc);

                // Создаем ViewModel с доступом к Revit
                var viewModel = new MainViewModel(externalEvent, doc, view3DNames);

                // Создаем и показываем Modeless окно
                var window = new MyVeras.UI.MyVerasWindow
                {
                    DataContext = viewModel
                };

                // Показываем Modeless окно
                window.Show();

                return Result.Succeeded;
            }
            catch (Exception ex)
            {
                // Подробное логирование исключений
                var fullException = GetFullExceptionString(ex);
                TaskDialog.Show("MyVeras Debug", fullException);
                message = $"Ошибка запуска MyVeras: {ex.Message}";
                return Result.Failed;
            }
        }

        /// <summary>
        /// Получает список имен 3D видов из документа с жесткой обработкой ошибок
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
                        // Игнорируем ошибки с конкретными видами - просто пропускаем их
                        continue;
                    }
                }
                
                // Сортируем по имени для удобства
                viewNames.Sort();
                
                // Если видов нет, добавляем заглушку
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

        /// <summary>
        /// Получает полное строковое представление исключения со всеми вложенными исключениями
        /// </summary>
        private string GetFullExceptionString(Exception ex)
        {
            var result = $"Exception: {ex.GetType().Name}\n";
            result += $"Message: {ex.Message}\n";
            result += $"Source: {ex.Source}\n";
            result += $"StackTrace: {ex.StackTrace}\n";
            
            var innerEx = ex.InnerException;
            var level = 1;
            
            while (innerEx != null)
            {
                result += $"\n--- Inner Exception Level {level} ---\n";
                result += $"Type: {innerEx.GetType().Name}\n";
                result += $"Message: {innerEx.Message}\n";
                result += $"Source: {innerEx.Source}\n";
                result += $"StackTrace: {innerEx.StackTrace}\n";
                
                innerEx = innerEx.InnerException;
                level++;
            }
            
            return result;
        }
    }

    /// <summary>
    /// Класс доступности команды
    /// </summary>
    public class MyVerasAvailability : IExternalCommandAvailability
    {
        public bool IsCommandAvailable(UIApplication applicationData, Autodesk.Revit.DB.CategorySet selectedCategories)
        {
            // Команда доступна всегда
            return true;
        }
    }
}
