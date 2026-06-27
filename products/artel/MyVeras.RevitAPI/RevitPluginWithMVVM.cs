using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using Autodesk.Revit.ApplicationServices;
using Autodesk.Revit.Attributes;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using MyVeras.Core;
using MyVeras.Models;
using MyVeras.Settings;

namespace MyVeras.RevitAPI
{
    /// <summary>
    /// Расширенная команда плагина с MVVM функциональностью
    /// </summary>
    [Transaction(TransactionMode.Manual)]
    [Regeneration(RegenerationOption.Manual)]
    public class RevitPluginWithMVVM : IExternalCommand
    {
        public Result Execute(ExternalCommandData commandData, ref string message, ElementSet elements)
        {
            try
            {
                var uidoc = commandData.Application.ActiveUIDocument;
                if (uidoc == null)
                {
                    TaskDialog.Show("Ошибка", "Нет активного документа");
                    return Result.Failed;
                }

                var settings = SettingsManager.Instance.Settings;

                // Показываем главное меню с тремя опциями
                var result = TaskDialog.Show("MyVeras AI Rendering", 
                    "🎨 Выберите действие:\n\n" +
                    "1. ⚙️ Настройка API - настройте провайдер и ключ\n" +
                    "2. 👁️ Выбор вида - выберите 3D вид для рендеринга\n" +
                    "3. 🎨 Рендер - запустите AI рендеринг\n\n" +
                    "AI рендеринг изображений из Revit с локальными и облачными движками",
                    TaskDialogCommonButtons.Ok | TaskDialogCommonButtons.Cancel);
                
                if (result == TaskDialogResult.Cancel)
                    return Result.Cancelled;

                // Показываем опции выбора
                ShowApiSettingsOption(uidoc, settings);
                ShowViewSelectionOption(uidoc, settings);
                ShowRenderingOption(uidoc, settings);

                return Result.Succeeded;
            }
            catch (Exception ex)
            {
                message = $"Ошибка: {ex.Message}";
                TaskDialog.Show("MyVeras Error", message);
                return Result.Failed;
            }
        }

        private void ShowApiSettingsOption(UIDocument uidoc, AppSettings settings)
        {
            var apiResult = TaskDialog.Show("⚙️ Настройка API", 
                "Текущий провайдер: " + (settings.ApiProvider ?? "не настроен") + "\n" +
                "API ключ: " + (string.IsNullOrEmpty(settings.ApiKey) ? "не указан" : "настроен") + "\n" +
                "API URL: " + (settings.ApiUrl ?? "не указан") + "\n\n" +
                "Доступные действия:\n" +
                "1. Ввести API ключ\n" +
                "2. Выбрать провайдера\n" +
                "3. Настроить папку выгрузки\n\n" +
                "Провайдеры:\n" +
                "• OpenAI (DALL-E 3)\n" +
                "• Stability AI\n" +
                "• Custom API",
                TaskDialogCommonButtons.Yes | TaskDialogCommonButtons.No);
            
            if (apiResult == TaskDialogResult.Yes)
            {
                // Показываем детальные настройки API
                ShowDetailedApiSettings(uidoc, settings);
            }
        }

        private void ShowDetailedApiSettings(UIDocument uidoc, AppSettings settings)
        {
            // Ввод API ключа
            var keyResult = TaskDialog.Show("🔑 API ключ", 
                $"Текущий ключ: {(string.IsNullOrEmpty(settings.ApiKey) ? "не указан" : "**********")}\n\n" +
                "Хотите ввести новый API ключ?",
                TaskDialogCommonButtons.Yes | TaskDialogCommonButtons.No);
            
            if (keyResult == TaskDialogResult.Yes)
            {
                // В реальном приложении здесь было бы окно ввода
                var newKey = ShowInputDialog("Введите API ключ", settings.ApiKey);
                if (!string.IsNullOrEmpty(newKey))
                {
                    settings.ApiKey = newKey;
                    SettingsManager.Instance.SaveSettings();
                    TaskDialog.Show("✅ Успех", "API ключ сохранен!");
                }
            }

            // Выбор провайдера
            var providerResult = TaskDialog.Show("🏢 Провайдер API", 
                $"Текущий провайдер: {settings.ApiProvider ?? "не выбран"}\n\n" +
                "Выберите провайдера:\n" +
                "1. OpenAI\n" +
                "2. Stability AI\n" +
                "3. Custom",
                TaskDialogCommonButtons.Yes | TaskDialogCommonButtons.No);
            
            if (providerResult == TaskDialogResult.Yes)
            {
                settings.ApiProvider = "OpenAI"; // В реальном приложении был бы выбор
                SettingsManager.Instance.SaveSettings();
            }

            // Настройка папки выгрузки
            ShowFolderSettings(uidoc, settings);
        }

        private void ShowFolderSettings(UIDocument uidoc, AppSettings settings)
        {
            var currentPath = settings.ExportFolderPath ?? Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments), 
                "MyVeras", "Renderings");
            
            var folderResult = TaskDialog.Show("📁 Папка выгрузки", 
                $"Текущая папка:\n{currentPath}\n\n" +
                "Хотите изменить папку для сохранения рендеров?",
                TaskDialogCommonButtons.Yes | TaskDialogCommonButtons.No);
            
            if (folderResult == TaskDialogResult.Yes)
            {
                var newPath = ShowFolderDialog(currentPath);
                if (!string.IsNullOrEmpty(newPath))
                {
                    settings.ExportFolderPath = newPath;
                    SettingsManager.Instance.SaveSettings();
                    TaskDialog.Show("✅ Успех", $"Папка изменена на:\n{newPath}");
                }
            }
        }

        private void ShowViewSelectionOption(UIDocument uidoc, AppSettings settings)
        {
            var viewResult = TaskDialog.Show("👁️ Выбор вида", 
                "Выбрать 3D вид для рендеринга?",
                TaskDialogCommonButtons.Yes | TaskDialogCommonButtons.No);
            
            if (viewResult == TaskDialogResult.Yes)
            {
                var availableViews = GetAvailable3DViews(uidoc.Document);
                
                if (!availableViews.Any())
                {
                    TaskDialog.Show("Виды 3D", "В документе нет 3D видов");
                    return;
                }

                var viewList = string.Join("\n", availableViews.Select((v, i) => $"{i + 1}. {v.Name}"));
                
                var selectionResult = TaskDialog.Show("👁️ Выбор вида", 
                    $"Доступные 3D виды:\n\n{viewList}\n\n" +
                    $"Текущий вид: {uidoc.ActiveView.Name}\n\n" +
                    "Выберите вид (введите номер):",
                    TaskDialogCommonButtons.Ok);
                
                // В реальном приложении здесь был бы выбор из списка
                if (availableViews.Any())
                {
                    settings.SelectedViewName = availableViews.First().Name;
                    SettingsManager.Instance.SaveSettings();
                    TaskDialog.Show("✅ Успех", $"Выбран вид: {settings.SelectedViewName}");
                }
            }
        }

        private void ShowRenderingOption(UIDocument uidoc, AppSettings settings)
        {
            var renderResult = TaskDialog.Show("🎨 Рендер", 
                "Запустить AI рендеринг?",
                TaskDialogCommonButtons.Yes | TaskDialogCommonButtons.No);
            
            if (renderResult == TaskDialogResult.Yes)
            {
                StartRenderingWithMVVM(uidoc, settings);
            }
        }

        private async void StartRenderingWithMVVM(UIDocument uidoc, AppSettings settings)
        {
            try
            {
                // Проверка API ключа
                if (string.IsNullOrEmpty(settings.ApiKey))
                {
                    TaskDialog.Show("🎨 Рендеринг", 
                        "❌ API ключ не настроен!\n\n" +
                        "Для начала рендеринга:\n" +
                        "1. Нажмите '⚙️ Настройка API'\n" +
                        "2. Введите API ключ\n" +
                        "3. Попробуйте снова",
                        TaskDialogCommonButtons.Ok);
                    return;
                }

                // Показываем прогресс
                var progressResult = TaskDialog.Show("🎨 Рендеринг", 
                    "🚀 Запуск AI рендеринга...\n\n" +
                    $"Провайдер: {settings.ApiProvider}\n" +
                    $"Вид: {settings.SelectedViewName ?? uidoc.ActiveView.Name}\n" +
                    $"Качество: {settings.DefaultQuality ?? "standard"}\n" +
                    $"Стиль: {settings.DefaultStyle ?? "realistic"}\n" +
                    $"Папка: {settings.ExportFolderPath ?? "Documents/MyVeras/Renderings"}\n\n" +
                    "⏳ Инициализация...",
                    TaskDialogCommonButtons.Ok);
                
                // Запускаем рендеринг
                await PerformRenderingAsync(uidoc, settings);
            }
            catch (Exception ex)
            {
                TaskDialog.Show("Ошибка рендеринга", ex.Message);
            }
        }

        private async Task PerformRenderingAsync(UIDocument uidoc, AppSettings settings)
        {
            try
            {
                // Создаем запрос
                var request = new RenderingRequest
                {
                    Prompt = settings.DefaultPrompt ?? "Architectural visualization, realistic, high quality",
                    Width = 1024,
                    Height = 1024,
                    Quality = settings.DefaultQuality ?? "standard",
                    Style = settings.DefaultStyle ?? "realistic"
                };

                // Используем MockRenderingEngine с настройками
                var engine = new MockRenderingEngine();
                
                if (!await engine.IsAvailableAsync())
                {
                    TaskDialog.Show("Ошибка", $"Движок {engine.Name} недоступен");
                    return;
                }

                var result = await engine.RenderAsync(request);

                if (result.Success && result.ImageData != null)
                {
                    var outputPath = SaveRenderingResult(result, settings, uidoc.ActiveView.Name);
                    TaskDialog.Show("✅ Рендеринг завершен!", 
                        $"Изображение сохранено:\n{outputPath}\n\n" +
                        $"Время выполнения: {result.ExecutionTimeMs}мс\n" +
                        $"Размер: {result.ImageData.Length} байт");
                }
                else
                {
                    TaskDialog.Show("❌ Ошибка рендеринга", result.ErrorMessage ?? "Неизвестная ошибка");
                }
            }
            catch (Exception ex)
            {
                TaskDialog.Show("❌ Критическая ошибка", ex.Message);
            }
        }

        private string SaveRenderingResult(RenderingResult result, AppSettings settings, string viewName)
        {
            try
            {
                var exportPath = settings.ExportFolderPath ?? Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments), 
                    "MyVeras", "Renderings");
                
                Directory.CreateDirectory(exportPath);

                var timestamp = DateTime.Now.ToString("yyyyMMdd_HHmmss");
                var fileName = $"Render_{viewName}_{timestamp}.png";
                var outputPath = Path.Combine(exportPath, fileName);

                File.WriteAllBytes(outputPath, result.ImageData);
                return outputPath;
            }
            catch (Exception ex)
            {
                return "Ошибка сохранения: " + ex.Message;
            }
        }

        private IEnumerable<View3D> GetAvailable3DViews(Document doc)
        {
            return new FilteredElementCollector(doc)
                .OfClass(typeof(View3D))
                .Cast<View3D>()
                .Where(v => !v.IsTemplate)
                .OrderBy(v => v.Name);
        }

        private string ShowInputDialog(string title, string defaultValue)
        {
            // В реальном приложении здесь было бы окно ввода
            // Для демонстрации возвращаем тестовое значение
            return "sk-test123456789";
        }

        private string ShowFolderDialog(string initialPath)
        {
            // В реальном приложении здесь был бы FolderBrowserDialog
            // Для демонстрации возвращаем тестовое значение
            return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments), "MyVeras", "Renderings");
        }
    }
}
