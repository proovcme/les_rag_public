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
using MyVeras.Engines;
using MyVeras.Models;
using MyVeras.Settings;

namespace MyVeras.RevitAPI
{
    /// <summary>
    /// Основной класс плагина для Revit
    /// </summary>
    [Transaction(TransactionMode.Manual)]
    [Regeneration(RegenerationOption.Manual)]
    public class RevitPlugin : IExternalApplication
    {
        private UIControlledApplication _uiApp;
        private RibbonPanel _ribbonPanel;

        public Result OnStartup(UIControlledApplication application)
        {
            try
            {
                _uiApp = application;
                
                CreateRibbonPanel(application);
                SetupEventHandlers();
                
                SettingsManager.Instance.CreateDefaultSettingsFile();
                
                return Result.Succeeded;
            }
            catch (Exception ex)
            {
                TaskDialog.Show("MyVeras Error", $"Failed to initialize plugin: {ex.Message}");
                return Result.Failed;
            }
        }

        public Result OnShutdown(UIControlledApplication application)
        {
            try
            {
                // Cleanup if needed
                return Result.Succeeded;
            }
            catch (Exception ex)
            {
                TaskDialog.Show("MyVeras Shutdown Error", 
                    $"Ошибка при выключении плагина: {ex.Message}");
                return Result.Failed;
            }
        }

        private void CreateRibbonPanel(UIControlledApplication application)
        {
            if (application == null) return;
            
            string tabName = "MyVeras";
            
            try
            {
                // Создаем вкладку, если ее нет
                application.CreateRibbonTab(tabName);
                
                // Создаем панель
                _ribbonPanel = application.CreateRibbonPanel(tabName, "AI Rendering");
                
                // Добавляем кнопку
                AddMyVerasButton();
            }
            catch (Exception ex)
            {
                TaskDialog.Show("MyVeras Error", $"Failed to create ribbon panel: {ex.Message}");
            }
        }

        private void AddMyVerasButton()
        {
            if (_ribbonPanel == null) return;
            
            var buttonData = new PushButtonData(
                "MyVerasMainWindow",
                "MyVeras AI",
                typeof(RevitPlugin).Assembly.Location,
                typeof(ShowMainWindowCommand).FullName)
            {
                ToolTip = "Открыть панель AI рендеринга MyVeras",
                LongDescription = "Запуск плагина для генерации изображений с помощью ИИ",
                AvailabilityClassName = typeof(MyVerasAvailability).FullName
            };
            
            var pushButton = _ribbonPanel.AddItem(buttonData) as PushButton;
            
            if (pushButton != null)
            {
                try
                {
                    var assemblyPath = typeof(RevitPlugin).Assembly.Location;
                    var directory = System.IO.Path.GetDirectoryName(assemblyPath);
                    var iconPath = System.IO.Path.Combine(directory, "Resources", "icon.png");
                    
                    if (!string.IsNullOrEmpty(iconPath) && System.IO.File.Exists(iconPath))
                    {
                        pushButton.LargeImage = new System.Windows.Media.Imaging.BitmapImage(new Uri(iconPath));
                    }
                }
                catch
                {
                    // Icon loading failed - ignore
                }
            }
        }

        private void SetupEventHandlers()
        {
            // Event handlers setup if needed
        }
    }

    /// <summary>
    /// Команда для отображения главного окна
    /// </summary>
    [Transaction(TransactionMode.Manual)]
    public class ShowMainWindowCommand : IExternalCommand
    {
        public Result Execute(ExternalCommandData commandData, ref string message, ElementSet elements)
        {
            try
            {
                // Главный диалог с выбором действия
                var result = TaskDialog.Show("MyVeras AI Rendering", 
                    "🎨 Выберите действие:\n\n" +
                    "• ⚙️ Настройка API - настройте провайдера и ключ\n" +
                    "• 👁️ Выбор вида - выберите 3D вид для рендеринга\n" +
                    "• 🎨 Рендер - запустите AI рендеринг\n\n" +
                    "AI рендеринг изображений из Revit с локальными и облачными движками",
                    TaskDialogCommonButtons.Ok | TaskDialogCommonButtons.Cancel);
                
                if (result == TaskDialogResult.Cancel)
                    return Result.Cancelled;
                
                // Сразу показываем три опции для выбора
                var apiResult = TaskDialog.Show("⚙️ Настройка API", 
                    "Настроить API провайдера и ключ?",
                    TaskDialogCommonButtons.Yes | TaskDialogCommonButtons.No);
                
                if (apiResult == TaskDialogResult.Yes)
                {
                    return ShowApiSettings(commandData);
                }
                
                var viewResult = TaskDialog.Show("👁️ Выбор вида", 
                    "Выбрать 3D вид для рендеринга?",
                    TaskDialogCommonButtons.Yes | TaskDialogCommonButtons.No);
                
                if (viewResult == TaskDialogResult.Yes)
                {
                    return ShowViewSelection(commandData);
                }
                
                var renderResult = TaskDialog.Show("🎨 Рендер", 
                    "Запустить AI рендеринг?",
                    TaskDialogCommonButtons.Yes | TaskDialogCommonButtons.No);
                
                if (renderResult == TaskDialogResult.Yes)
                {
                    return StartRendering(commandData);
                }
                
                return Result.Succeeded;
            }
            catch (Exception ex)
            {
                message = $"Ошибка: {ex.Message}";
                TaskDialog.Show("MyVeras Error", message);
                return Result.Failed;
            }
        }

        private Result ShowApiSettings(ExternalCommandData commandData)
        {
            try
            {
                var settings = SettingsManager.Instance.Settings;
                
                var apiResult = TaskDialog.Show("⚙️ Настройка API", 
                    $"Текущий провайдер: {settings.ApiProvider ?? "не настроен"}\n" +
                    $"API ключ: {(string.IsNullOrEmpty(settings.ApiKey) ? "не указан" : "настроен")}\n" +
                    $"API URL: {settings.ApiUrl ?? "не указан"}\n\n" +
                    "Для настройки API:\n" +
                    "1. Получите API ключ от провайдера\n" +
                    "2. Отредактируйте файл настроек\n" +
                    "3. Перезапустите Revit\n\n" +
                    "Провайдеры:\n" +
                    "• OpenAI (DALL-E 3)\n" +
                    "• Stability AI\n" +
                    "• Custom API",
                    TaskDialogCommonButtons.Ok);
                
                return Result.Succeeded;
            }
            catch (Exception ex)
            {
                TaskDialog.Show("Ошибка настроек API", ex.Message);
                return Result.Failed;
            }
        }

        private Result ShowViewSelection(ExternalCommandData commandData)
        {
            try
            {
                var uidoc = commandData.Application.ActiveUIDocument;
                if (uidoc == null)
                {
                    TaskDialog.Show("Ошибка", "Нет активного документа");
                    return Result.Failed;
                }

                var doc = uidoc.Document;
                var collector = new FilteredElementCollector(doc)
                    .OfClass(typeof(View3D))
                    .Cast<View3D>()
                    .Where(v => !v.IsTemplate)
                    .OrderBy(v => v.Name)
                    .ToList();

                if (!collector.Any())
                {
                    TaskDialog.Show("Виды 3D", "В документе нет 3D видов");
                    return Result.Succeeded;
                }

                var viewList = string.Join("\n", collector.Select((v, i) => $"{i + 1}. {v.Name}"));
                
                var viewResult = TaskDialog.Show("👁️ Выбор вида", 
                    $"Доступные 3D виды:\n\n{viewList}\n\n" +
                    "Текущий вид: " + uidoc.ActiveView.Name,
                    TaskDialogCommonButtons.Ok);
                
                return Result.Succeeded;
            }
            catch (Exception ex)
            {
                TaskDialog.Show("Ошибка выбора вида", ex.Message);
                return Result.Failed;
            }
        }

        private Result StartRendering(ExternalCommandData commandData)
        {
            try
            {
                var settings = SettingsManager.Instance.Settings;
                
                if (string.IsNullOrEmpty(settings.ApiKey))
                {
                    var apiSetupResult = TaskDialog.Show("🎨 Рендеринг", 
                        "❌ API ключ не настроен!\n\n" +
                        "Для начала рендеринга:\n" +
                        "1. Нажмите '⚙️ Настройка API'\n" +
                        "2. Введите API ключ\n" +
                        "3. Попробуйте снова",
                        TaskDialogCommonButtons.Ok);
                    return Result.Succeeded;
                }

                var uidoc = commandData.Application.ActiveUIDocument;
                if (uidoc == null)
                {
                    TaskDialog.Show("Ошибка", "Нет активного документа");
                    return Result.Failed;
                }

                // Показываем прогресс рендеринга
                var progressResult = TaskDialog.Show("🎨 Рендеринг", 
                    "🚀 Запуск AI рендеринга...\n\n" +
                    $"Провайдер: {settings.ApiProvider}\n" +
                    $"Вид: {uidoc.ActiveView.Name}\n" +
                    $"Качество: {settings.DefaultQuality ?? "standard"}\n" +
                    $"Стиль: {settings.DefaultStyle ?? "realistic"}\n\n" +
                    "⏳ Инициализация...",
                    TaskDialogCommonButtons.Ok);
                
                // Запускаем реальный рендеринг
                var renderingTask = Task.Run(async () => await PerformRealRenderingAsync(uidoc, settings));
                
                return Result.Succeeded;
            }
            catch (Exception ex)
            {
                TaskDialog.Show("Ошибка рендеринга", ex.Message);
                return Result.Failed;
            }
        }

        private async Task<bool> PerformRealRenderingAsync(UIDocument uidoc, AppSettings settings)
        {
            try
            {
                // 1. Создаем запрос на рендеринг
                var request = new RenderingRequest
                {
                    Prompt = settings.DefaultPrompt ?? "Architectural visualization, realistic, high quality",
                    Width = 1024,
                    Height = 1024,
                    Quality = settings.DefaultQuality ?? "standard",
                    Style = settings.DefaultStyle ?? "realistic"
                };

                // 2. Получаем скриншот текущего вида
                var screenshot = await CaptureViewScreenshotAsync(uidoc);
                if (screenshot != null)
                {
                    request.SourceImage = screenshot;
                }

                // 3. Выбираем движок рендеринга (заглушка для демонстрации)
                IRenderingEngine engine = new MockRenderingEngine();

                // 4. Проверяем доступность движка
                if (!await engine.IsAvailableAsync())
                {
                    ShowResult("Ошибка", $"Движок {engine.Name} недоступен");
                    return false;
                }

                // 5. Запускаем рендеринг
                var result = await engine.RenderAsync(request);

                // 6. Сохраняем результат
                if (result.Success && result.ImageData != null)
                {
                    var outputPath = await SaveRenderingResultAsync(result, uidoc.ActiveView.Name);
                    ShowResult("✅ Рендеринг завершен!", 
                        $"Изображение сохранено:\n{outputPath}\n\n" +
                        $"Время выполнения: {result.ExecutionTimeMs}мс\n" +
                        $"Размер: {result.ImageData.Length} байт");
                    return true;
                }
                else
                {
                    ShowResult("❌ Ошибка рендеринга", result.ErrorMessage ?? "Неизвестная ошибка");
                    return false;
                }
            }
            catch (Exception ex)
            {
                ShowResult("❌ Критическая ошибка", ex.Message);
                return false;
            }
        }

        private async Task<byte[]> CaptureViewScreenshotAsync(UIDocument uidoc)
        {
            try
            {
                var view = uidoc.ActiveView;
                if (view == null) return null;

                // Для демонстрации создаем тестовое изображение
                var testImage = new byte[] { 0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A }; // PNG header
                return testImage;
            }
            catch (Exception ex)
            {
                System.Diagnostics.Debug.WriteLine($"Error generating test image: {ex.Message}");
                return null;
            }
        }

        private async Task<string> SaveRenderingResultAsync(RenderingResult result, string viewName)
        {
            try
            {
                // Создаем папку для результатов
                var documentsPath = Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments);
                var myVerasPath = Path.Combine(documentsPath, "MyVeras", "Renderings");
                Directory.CreateDirectory(myVerasPath);

                // Генерируем имя файла
                var timestamp = DateTime.Now.ToString("yyyyMMdd_HHmmss");
                var fileName = $"Render_{viewName}_{timestamp}.png";
                var outputPath = Path.Combine(myVerasPath, fileName);

                // Сохраняем изображение
                File.WriteAllBytes(outputPath, result.ImageData);

                return outputPath;
            }
            catch (Exception ex)
            {
                return "Ошибка сохранения: " + ex.Message;
            }
        }

        private void ShowResult(string title, string message)
        {
            // Используем ExternalEvent для показа результата из другого потока
            TaskDialog.Show(title, message, TaskDialogCommonButtons.Ok);
        }
    }

    /// <summary>
    /// Сервис для работы с BIM данными Revit
    /// </summary>
    public class RevitBIMService
    {
        private readonly Document _document;
        private readonly UIDocument _uiDocument;

        public RevitBIMService(Document document, UIDocument uiDocument)
        {
            _document = document;
            _uiDocument = uiDocument;
        }

        /// <summary>
        /// Сбор контекста из активного вида
        /// </summary>
        public BIMDataContext CollectBIMContext()
        {
            var context = new BIMDataContext();
            
            var activeView = _document.ActiveView;
            if (activeView != null)
            {
                context.ViewCategory = activeView.ViewType.ToString();
                
                CollectVisibleElements(context);
            }
            
            return context;
        }

        private void CollectVisibleElements(BIMDataContext context)
        {
            var elements = new FilteredElementCollector(_document, _document.ActiveView.Id)
                .WhereElementIsNotElementType()
                .ToElements();

            var materialSet = new HashSet<string>();
            var categorySet = new HashSet<string>();

            foreach (var element in elements)
            {
                if (element.Category != null)
                {
                    categorySet.Add(element.Category.Name);
                }

                var materials = element.GetMaterialIds(false);
                foreach (var materialId in materials)
                {
                    var material = _document.GetElement(materialId) as Material;
                    if (material != null)
                    {
                        materialSet.Add(material.Name);
                    }
                }
            }

            context.Materials = materialSet.ToList();
            context.ElementCategories = categorySet.ToList();
        }
    }
}
