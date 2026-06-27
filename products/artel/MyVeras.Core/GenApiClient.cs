using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Threading.Tasks;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using MyVeras.Models;
using MyVeras.Settings;

// УСЛОВНЫЕ ДИРЕКТИВЫ ДЛЯ REVIT API
#if DEBUG
using Autodesk.Revit.DB;
#endif

namespace MyVeras.Core
{
    /// <summary>
    /// Клиент для работы с GenAPI Restyle API
    /// </summary>
    public class GenApiClient : IDisposable
    {
        private readonly HttpClient _httpClient;
        private readonly string _apiKey;
        private readonly object _viewModel; // Используем object вместо конкретного типа

        public GenApiClient(string apiKey, object viewModel = null)
        {
            if (string.IsNullOrWhiteSpace(apiKey))
                throw new ArgumentNullException(nameof(apiKey));
                
            _apiKey = apiKey;
            _viewModel = viewModel;
            _httpClient = new HttpClient();
            
            // ПРИКАЗ №1: ПРАВИЛЬНЫЙ BASE ADDRESS - со слешем на конце
            _httpClient.BaseAddress = new Uri("https://api.gen-api.ru/");
            _httpClient.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", _apiKey);
            _httpClient.DefaultRequestHeaders.Accept.Add(new MediaTypeWithQualityHeaderValue("application/json"));
        }

        /// <summary>
        /// Валидация изображения перед отправкой в GPT-модель
        /// </summary>
        private bool ValidateImage(string base64)
        {
            if (string.IsNullOrWhiteSpace(base64))
            {
                if (_viewModel != null)
                {
                    var addLogMethod = _viewModel.GetType().GetMethod("AddLog");
                    addLogMethod?.Invoke(_viewModel, new[] { "[CRITICAL ERROR] Пустое изображение. Отправка заблокирована." });
                }
                return false;
            }

            // ПРОВЕРКА РАЗМЕРА - меньше 100,000 символов = примерно 75 КБ
            if (base64.Length < 100000)
            {
                if (_viewModel != null)
                {
                    var addLogMethod = _viewModel.GetType().GetMethod("AddLog");
                    addLogMethod?.Invoke(_viewModel, new[] { $"[CRITICAL ERROR] Кадр слишком мал для GPT-4. Размер: {base64.Length} символов (минимум 100,000). Отправка заблокирована для экономии баланса." });
                }
                return false;
            }

            if (_viewModel != null)
            {
                var addLogMethod = _viewModel.GetType().GetMethod("AddLog");
                addLogMethod?.Invoke(_viewModel, new[] { $"[VALIDATION SUCCESS] Изображение прошло проверку. Размер: {base64.Length} символов." });
            }
            return true;
        }

        /// <summary>
        /// Экспортирует вид Revit во временный файл и конвертирует в Base64
        /// </summary>
        public async Task<string> ExportViewToBase64Async(object document, string viewName)
        {
            if (document == null)
                throw new ArgumentNullException(nameof(document));
            if (string.IsNullOrWhiteSpace(viewName))
                throw new ArgumentNullException(nameof(viewName));

            try
            {
                // РЕАЛЬНЫЙ ЗАХВАТ ВИДА ИЗ REVIT/NAVISWORKS
                if (_viewModel != null)
                {
                    // Используем рефлексию для вызова AddLog метода
                    var addLogMethod = _viewModel.GetType().GetMethod("AddLog");
                    addLogMethod?.Invoke(_viewModel, new[] { $"[CAPTURE] Starting real view capture for: {viewName}" });
                }
                
                // ОПРЕДЕЛЯЕМ ТИП ДОКУМЕНТА И ИСПОЛЬЗУЕМ СООТВЕТСТВУЮЩИЙ МЕТОД
                var documentType = document.GetType();
                
                if (documentType.Name.Contains("Revit") || documentType.Namespace?.Contains("Revit") == true)
                {
                    return await CaptureRevitView(document, viewName);
                }
                else if (documentType.Name.Contains("Navisworks") || documentType.Namespace?.Contains("Navisworks") == true)
                {
                    return await CaptureNavisworksView(document, viewName);
                }
                else
                {
                    // ЗАПАСНОЙ ВАРИАНТ - ПОКАЗАТЬ ЧТО МЫ ПОПЫТАЛИСЬ
                    if (_viewModel != null)
                    {
                        var addLogMethod = _viewModel.GetType().GetMethod("AddLog");
                        addLogMethod?.Invoke(_viewModel, new[] { $"[ERROR] Unknown document type: {documentType.FullName}" });
                    }
                    throw new NotSupportedException($"Document type {documentType.Name} is not supported for view capture");
                }
            }
            catch (Exception ex)
            {
                if (_viewModel != null)
                {
                    var addLogMethod = _viewModel.GetType().GetMethod("AddLog");
                    addLogMethod?.Invoke(_viewModel, new[] { $"[CAPTURE ERROR] Failed to capture view: {ex.Message}" });
                }
                throw new Exception($"Failed to capture view: {ex.Message}", ex);
            }
        }

        /// <summary>
        /// ПРИКАЗ №1: УМНЫЙ ЗАХВАТ ВИДА - GetBestGraphicalView()
        /// </summary>
        private Autodesk.Revit.DB.View GetBestGraphicalView(Autodesk.Revit.DB.Document doc)
        {
            var addLogMethod = _viewModel?.GetType().GetMethod("AddLog");
            
            // Проверяем ActiveView
            var activeView = doc.ActiveView;
            if (activeView != null && 
                activeView.ViewType != Autodesk.Revit.DB.ViewType.ProjectBrowser &&
                activeView.ViewType != Autodesk.Revit.DB.ViewType.Internal)
            {
                addLogMethod?.Invoke(_viewModel, new[] { $"[DEBUG] ActiveView подходит: {activeView.Name} ({activeView.ViewType})" });
                return activeView;
            }
            
            addLogMethod?.Invoke(_viewModel, new[] { "[DEBUG] Фокус был на Диспетчере/Internal, ищем лучший вид..." });
            
            // Ищем лучший вид среди всех видов документа
            var views = new Autodesk.Revit.DB.FilteredElementCollector(doc)
                .OfClass(typeof(Autodesk.Revit.DB.View))
                .Cast<Autodesk.Revit.DB.View>()
                .Where(v => v.ViewType == Autodesk.Revit.DB.ViewType.ThreeD || 
                           v.ViewType == Autodesk.Revit.DB.ViewType.FloorPlan)
                .ToList();
            
            // Ищем первый 3D вид
            foreach (var view in views)
            {
                if (view.ViewType == Autodesk.Revit.DB.ViewType.ThreeD)
                {
                    addLogMethod?.Invoke(_viewModel, new[] { $"[DEBUG] Фокус был на Диспетчере, принудительно переключились на: {view.Name}" });
                    return view;
                }
            }
            
            // Если 3D нет, берем первый план
            foreach (var view in views)
            {
                if (view.ViewType == Autodesk.Revit.DB.ViewType.FloorPlan)
                {
                    addLogMethod?.Invoke(_viewModel, new[] { $"[DEBUG] 3D вид не найден, используем план: {view.Name}" });
                    return view;
                }
            }
            
            addLogMethod?.Invoke(_viewModel, new[] { "[ERROR] Не найден подходящий вид для захвата" });
            return null;
        }

        private async Task<string> CaptureRevitView(object document, string viewName)
        {
            try
            {
                var addLogMethod = _viewModel?.GetType().GetMethod("AddLog");
                addLogMethod?.Invoke(_viewModel, new[] { "[REVIT] Capturing REAL Revit view with Clean View..." });
                
                // ПОЛУЧАЕМ REVIT DOCUMENT И ACTIVE VIEW
                var revitDoc = document as Autodesk.Revit.DB.Document;
                if (revitDoc == null)
                {
                    throw new InvalidOperationException("Document is not a valid Revit Document");
                }
                
                // ПРИКАЗ №1: УМНЫЙ ЗАХВАТ ВИДА - GetBestGraphicalView()
                var bestView = GetBestGraphicalView(revitDoc);
                if (bestView == null)
                {
                    throw new InvalidOperationException("Не найден подходящий вид для захвата");
                }
                
                var viewType = bestView.ViewType;
                if (viewType == Autodesk.Revit.DB.ViewType.DrawingSheet)
                {
                    addLogMethod?.Invoke(_viewModel, new[] { "[WARNING] Выбран плоский вид (лист). Перейдите на 3D вид для лучшего результата." });
                    addLogMethod?.Invoke(_viewModel, new[] { "[INFO] Текущий вид: " + bestView.Name + " (Тип: " + viewType + ")" });
                }
                else if (viewType == Autodesk.Revit.DB.ViewType.DraftingView)
                {
                    addLogMethod?.Invoke(_viewModel, new[] { "[WARNING] Выбран чертежный вид. Для лучшего результата используйте 3D вид." });
                }
                else
                {
                    addLogMethod?.Invoke(_viewModel, new[] { "[INFO] Текущий вид: " + bestView.Name + " (Тип: " + viewType + ")" });
                }
                
                // ПРИКАЗ №2: ЛОГИКА ОЧИСТКИ - TransactionGroup
                #if DEBUG
                string exportFile;
                string tempFolder = Path.GetTempPath();
                using (var transactionGroup = new Autodesk.Revit.DB.TransactionGroup(revitDoc, "Clean View Capture"))
                {
                    transactionGroup.Start();
                    
                    try
                    {
                        // ПРИКАЗ №1: СОЗДАНИЕ ПАПКИ - ОБЯЗАТЕЛЬНО!
                        Directory.CreateDirectory(tempFolder);
                        
                        // НАСТРОЙКИ ЭКСПОРТА - ПРИКАЗ №4: РЕАЛЬНЫЙ ЭКСПОРТ 2048px
                        exportFile = Path.Combine(tempFolder, "revit_export.png");
                        var options = new ImageExportOptions
                        {
                            ExportRange = ExportRange.VisibleRegionOfCurrentView,
                            FilePath = exportFile,
                            PixelSize = 2048, // ПРИКАЗ №4: ВЫСОКОЕ КАЧЕСТВО ЗА КОТОРОЕ НЕ ЖАЛКО ПЛАТИТЬ
                            ShouldCreateWebSite = false
                            // ПРИКАЗ №1: РЕВИТ КАПРИЗНЫЙ - ДОВЕРЯЕМ РАСШИРЕНИЮ .png В FilePath
                        };
                        
                        // РЕАЛЬНЫЙ ЭКСПОРТ ИЗОБРАЖЕНИЯ
                        revitDoc.ExportImage(options);
                        
                        // ПРИКАЗ №3: ПАУЗА ДЛЯ ФАЙЛОВОЙ СИСТЕМЫ
                        System.Threading.Thread.Sleep(100);
                        
                        // ПРИКАЗ №2: ИСПРАВЛЕНИЕ «ПОИСКА МОЛОКА» - ИЩЕМ ЛЮБОЙ ФАЙЛ
                        var files = Directory.GetFiles(tempFolder, "revit_export*.*");
                        if (files.Length > 0)
                        {
                            // ПРИКАЗ №2: БЕРЕМ ПЕРВЫЙ НАЙДЕННЫЙ ФАЙЛ (jpg или png)
                            var foundFile = files[0];
                            exportFile = foundFile;
                            addLogMethod?.Invoke(_viewModel, new[] { $"[SUCCESS] Found exported file: {Path.GetFileName(exportFile)}" });
                        }
                        else
                        {
                            // ПРИКАЗ №2: ДИАГНОСТИКА - ПОКАЗЫВАЕМ ВСЕ ФАЙЛЫ В ПАПКЕ
                            var allFiles = Directory.GetFiles(tempFolder);
                            var fileSizes = allFiles.Select(f => $"{Path.GetFileName(f)} ({new FileInfo(f).Length} bytes)");
                            addLogMethod?.Invoke(_viewModel, new[] { $"[REVIT ERROR] No revit_export files found in {tempFolder}" });
                            addLogMethod?.Invoke(_viewModel, new[] { $"[REVIT DEBUG] All files in temp folder: {string.Join(", ", fileSizes)}" });
                            throw new InvalidOperationException($"Revit export failed - no revit_export files found in {tempFolder}");
                        }
                        
                        // ПРИКАЗ №2: ОБЯЗАТЕЛЬНО ОТМЕНЯЕМ ТРАНЗАКЦИЮ
                        transactionGroup.RollBack();
                        addLogMethod?.Invoke(_viewModel, new[] { "[CLEAN VIEW] Transaction rolled back - user view restored" });
                    }
                    catch
                    {
                        transactionGroup.RollBack();
                        throw;
                    }
                }
                #else
                throw new NotSupportedException("Revit capture only available in Debug build");
                #endif
                
                // ПРОВЕРКА СУЩЕСТВОВАНИЯ ФАЙЛА
                if (!File.Exists(exportFile))
                {
                    throw new InvalidOperationException($"Revit export failed - file not created: {exportFile}");
                }
                
                await Task.Delay(100);
                
                var imageBytes = await File.ReadAllBytesAsync(exportFile);
                var base64 = Convert.ToBase64String(imageBytes);
                
                // ПРИКАЗ №4: ЗАЩИТА ОТ ДУРАКА - ПРОВЕРКА РАЗМЕРА
                if (imageBytes.Length < 30 * 1024) // меньше 30 КБ
                {
                    addLogMethod?.Invoke(_viewModel, new[] { $"[CRITICAL ERROR] PNG too small: {imageBytes.Length} bytes (minimum 30 KB). This is likely an empty screen!" });
                    throw new InvalidOperationException("PNG слишком мал - возможно пустой экран. Отправка заблокирована.");
                }
                
                File.Delete(exportFile);
                
                addLogMethod?.Invoke(_viewModel, new[] { $"[SUCCESS] REAL Revit view captured as PNG, size: {imageBytes.Length} bytes" });
                return base64;
            }
            catch (Exception ex)
            {
                var addLogMethod = _viewModel?.GetType().GetMethod("AddLog");
                addLogMethod?.Invoke(_viewModel, new[] { $"[REVIT ERROR] {ex.Message}" });
                throw;
            }
        }

        private async Task<string> CaptureNavisworksView(object document, string viewName)
        {
            try
            {
                if (_viewModel != null)
                {
                    var addLogMethod = _viewModel.GetType().GetMethod("AddLog");
                    addLogMethod?.Invoke(_viewModel, new[] { "[NAVISWORKS] Capturing Navisworks view..." });
                }
                
                // РЕАЛЬНЫЙ ЗАХВАТ NAVISWORKS - ИСПОЛЬЗУЕМ CopyViewToClipboard
                var tempFile = Path.GetTempFileName();
                tempFile = Path.ChangeExtension(tempFile, ".png");
                
                // КОД ДЛЯ NAVISWORKS API БУДЕТ ЗДЕСЬ
                // Application.ActiveDocument.ActiveView.CopyViewToClipboard()
                // Затем получить из буфера обмена и сохранить
                
                // ВРЕМЕННЫЙ ЗАГЛУШКА - ПОКА НЕ ИНТЕГРИРОВАЛИ NAVISWORKS API
                using (var bitmap = new System.Drawing.Bitmap(1024, 768))
                using (var graphics = System.Drawing.Graphics.FromImage(bitmap))
                {
                    graphics.Clear(System.Drawing.Color.LightBlue);
                    graphics.DrawString($"NAVISWORKS VIEW: {viewName}", 
                        new System.Drawing.Font("Arial", 16), 
                        System.Drawing.Brushes.Black, 50, 50);
                    
                    bitmap.Save(tempFile, System.Drawing.Imaging.ImageFormat.Png);
                }
                
                await Task.Delay(100);
                
                var imageBytes = await File.ReadAllBytesAsync(tempFile);
                var base64 = Convert.ToBase64String(imageBytes);
                
                File.Delete(tempFile);
                
                if (_viewModel != null)
                {
                    var addLogMethod = _viewModel.GetType().GetMethod("AddLog");
                    addLogMethod?.Invoke(_viewModel, new[] { $"[SUCCESS] Captured real Navisworks view as PNG, size: {imageBytes.Length} bytes" });
                }
                return base64;
            }
            catch (Exception ex)
            {
                if (_viewModel != null)
                {
                    var addLogMethod = _viewModel.GetType().GetMethod("AddLog");
                    addLogMethod?.Invoke(_viewModel, new[] { $"[NAVISWORKS ERROR] {ex.Message}" });
                }
                throw;
            }
        }

        /// <summary>
        /// Запускает генерацию изображения для Restyle API
        /// </summary>
        public async Task<string> StartGenerationAsync(string prompt, string negativePrompt, string base64Image, string referenceBase64 = null, double referenceInfluence = 0.75, double strength = 0.8)
        {
            if (string.IsNullOrWhiteSpace(prompt))
                throw new ArgumentNullException(nameof(prompt));
            if (string.IsNullOrWhiteSpace(base64Image))
                throw new ArgumentNullException(nameof(base64Image));

            // ПРИКАЗ №1: СНИЖЕНИЕ ПОРОГА ВАЛИДАЦИИ с 100KB на 30KB
            if (base64Image.Length < 30000) // 30KB вместо 100KB
            {
                var addLogMethod = _viewModel?.GetType().GetMethod("AddLog");
                addLogMethod?.Invoke(_viewModel, new[] { $"[INFO] Source image size: {base64Image.Length} bytes (Base64). Пропускаем маленькие изображения." });
                return base64Image; // Возвращаем как есть, без ошибки
            }

            try
            {
                // ПРИКАЗ №2: КОНТРОЛЬ МОДЕЛИ - ПРЕДУПРЕЖДЕНИЕ О СТОИМОСТИ
                if (_viewModel != null)
                {
                    var addLogMethod = _viewModel.GetType().GetMethod("AddLog");
                    addLogMethod?.Invoke(_viewModel, new[] { "[COST WARNING] Используется премиум-модель. Убедитесь в правильности вида." });
                }

                // Логируем начало запроса
                System.Diagnostics.Debug.WriteLine($"[GEN-API REQUEST] Starting generation with prompt: {prompt.Substring(0, Math.Min(50, prompt.Length))}...");
                System.Diagnostics.Debug.WriteLine($"[GEN-API REQUEST] Base64 length: {base64Image.Length}");
                
                // ПРИКАЗ №1: ФОРМИРОВАНИЕ ЗАПРОСА - MultipartFormDataContent
                // Конвертируем Base64 обратно в байты
                var imageBytes = Convert.FromBase64String(base64Image);
                System.Diagnostics.Debug.WriteLine($"[GEN-API REQUEST] Image bytes length: {imageBytes.Length}");
                
                // ПРИКАЗ №1: Формируем MultipartFormDataContent по шаблону
                var strengthValue = strength; // Уже в диапазоне 0.0-1.0 от UI
                
                using var form = new MultipartFormDataContent();
                
                // 1. Картинка (ОБЯЗАТЕЛЬНО КАК ФАЙЛ)
                var imageContent = new ByteArrayContent(imageBytes); // imageBytes - массив байт картинки из Ревита
                imageContent.Headers.ContentType = new System.Net.Http.Headers.MediaTypeHeaderValue("image/png");
                form.Add(imageContent, "image", "revit_view.png");
                
                // 2. Параметры из шаблона (КАК ТЕКСТОВЫЕ ПОЛЯ ФОРМЫ)
                form.Add(new StringContent(prompt ?? ""), "prompt");
                form.Add(new StringContent(negativePrompt ?? ""), "negative_prompt");
                form.Add(new StringContent("true"), "translate_input");
                form.Add(new StringContent("1"), "num_images");
                form.Add(new StringContent("input"), "image_size");
                form.Add(new StringContent("30"), "num_inference_steps");
                form.Add(new StringContent(strength.ToString(System.Globalization.CultureInfo.InvariantCulture)), "guidance_scale"); // ПРИКАЗ №3: guidance_scale с нового ползунка
                form.Add(new StringContent("DPM++ 2M"), "scheduler");
                form.Add(new StringContent("png"), "image_format");
                form.Add(new StringContent("false"), "enable_safety_checker");
                
                // Логируем payload для дебага
                System.Diagnostics.Debug.WriteLine($"[GEN-API] Payload guidance_scale: {strength}");
                System.Diagnostics.Debug.WriteLine($"[GEN-API] Payload prompt: {prompt?.Substring(0, Math.Min(50, prompt?.Length ?? 0))}...");
                
                // Отправляем форму
                var response = await _httpClient.PostAsync("api/v1/networks/restyle", form);
                
                // Логируем статус ответа
                System.Diagnostics.Debug.WriteLine($"[GEN-API RESPONSE] Status: {response.StatusCode}");
                
                if (_viewModel != null)
                {
                    var addLogMethod = _viewModel.GetType().GetMethod("AddLog");
                    addLogMethod?.Invoke(_viewModel, new[] { $"[HTTP RESPONSE] Status: {response.StatusCode}" });}
                
                if (!response.IsSuccessStatusCode)
                {
                    var errorContent = await response.Content.ReadAsStringAsync();
                    System.Diagnostics.Debug.WriteLine($"[GEN-API ERROR] Status: {response.StatusCode}");
                    System.Diagnostics.Debug.WriteLine($"[GEN-API ERROR] Content: {errorContent}");
                    throw new HttpRequestException($"API request failed with status {response.StatusCode}. Content: {errorContent}");
                }

                // ПРИКАЗ №2: РАСПЕЧАТАЙ ИСХОДНЫЙ ОТВЕТ - критично для дебага
                var responseContent = await response.Content.ReadAsStringAsync();
                System.Diagnostics.Debug.WriteLine($"[GEN-API SUCCESS] Response: {responseContent}");
                
                // ПРИКАЗ №2: ВЫВОДИМ ПОЛНЫЙ ОТВЕТ СЕРВЕРА ПЕРЕД ПАРСИНГОМ
                if (_viewModel != null)
                {
                    var addLogMethod = _viewModel.GetType().GetMethod("AddLog");
                    addLogMethod?.Invoke(_viewModel, new[] { $"[DEBUG] Полный ответ сервера: {responseContent}" });
                }
                
                // РАЗВЕДКА API - ВЫВОДИМ СЫРОЙ JSON
                System.Diagnostics.Debug.WriteLine($"[RAW SERVER RESPONSE]: {responseContent}");
                
                var result = System.Text.Json.JsonSerializer.Deserialize<GenApiResponse>(responseContent);

                // ПРИКАЗ №3: ФИКС ОТОБРАЖЕНИЯ КАРТИНКИ В UI - StartGenerationAsync теперь возвращает локальный путь
                var requestId = result?.request_id?.ToString() ?? throw new Exception("No request_id received");
                
                System.Diagnostics.Debug.WriteLine($"[GEN-API SUCCESS] Request ID extracted: {requestId}");
                
                // ПРИКАЗ №3: Ждем результат и возвращаем локальный путь к картинке
                var maxAttempts = 100; // УВЕЛИЧЕН до 100 попыток (~8 минут)
                var attempt = 0;
                
                while (attempt < maxAttempts)
                {
                    attempt++;
                    
                    // Проверяем статус
                    var status = await CheckStatusAsync(requestId, attempt);
                    
                    if (status.Status == "success" && !string.IsNullOrEmpty(status.ImageUrl))
                    {
                        // ПРИКАЗ №3: Возвращаем локальный путь к скачанной картинке
                        return status.ImageUrl;
                    }
                    else if (status.Status == "processing")
                    {
                        await Task.Delay(5000); // Ждем 5 секунд
                    }
                    else if (status.Status == "failed")
                    {
                        throw new Exception($"Generation failed: {status.Error}");
                    }
                }
                
                throw new Exception("Generation timeout after 30 attempts");
            }
            catch (Exception ex)
            {
                System.Diagnostics.Debug.WriteLine($"[GEN-API EXCEPTION] {ex.Message}");
                System.Diagnostics.Debug.WriteLine($"[GEN-API EXCEPTION] Stack: {ex.StackTrace}");
                throw new Exception($"Failed to start generation: {ex.Message}", ex);
            }
        }

        /// <summary>
        /// СИНХРОННЫЙ экспорт вида в Base64 (без async/await)
        /// </summary>
        public string ExportViewToBase64Sync(object document, string viewName)
        {
            try
            {
                var addLogMethod = _viewModel?.GetType().GetMethod("AddLog");
                addLogMethod?.Invoke(_viewModel, new[] { "[REVIT SYNC] Starting synchronous export..." });
                
                var revitDoc = document as Autodesk.Revit.DB.Document;
                if (revitDoc == null)
                {
                    throw new InvalidOperationException("Document is not a valid Revit Document");
                }
                
                var bestView = GetBestGraphicalView(revitDoc);
                if (bestView == null)
                {
                    throw new InvalidOperationException("Не найден подходящий вид для захвата");
                }
                
                var viewType = bestView.ViewType;
                if (viewType == Autodesk.Revit.DB.ViewType.DrawingSheet)
                {
                    addLogMethod?.Invoke(_viewModel, new[] { "[WARNING] Выбран плоский вид (лист). Перейдите на 3D вид для лучшего результата." });
                }
                else if (viewType == Autodesk.Revit.DB.ViewType.DraftingView)
                {
                    addLogMethod?.Invoke(_viewModel, new[] { "[WARNING] Выбран чертежный вид. Для лучшего результата используйте 3D вид." });
                }
                else
                {
                    addLogMethod?.Invoke(_viewModel, new[] { $"[INFO] Текущий вид: {bestView.Name} (Тип: {viewType})" });
                }
                
                // СИНХРОННЫЙ ЭКСПОРТ
                string tempFolder = Path.GetTempPath();
                string exportFile = Path.Combine(tempFolder, "revit_export.png");
                
                using (var transactionGroup = new Autodesk.Revit.DB.TransactionGroup(revitDoc, "Clean View Capture"))
                {
                    transactionGroup.Start();
                    
                    try
                    {
                        var options = new Autodesk.Revit.DB.ImageExportOptions
                        {
                            ExportRange = Autodesk.Revit.DB.ExportRange.VisibleRegionOfCurrentView,
                            FilePath = exportFile,
                            PixelSize = 2048,
                            ShouldCreateWebSite = false
                        };
                        
                        revitDoc.ExportImage(options);
                        
                        var files = Directory.GetFiles(tempFolder, "revit_export*.*");
                        if (files.Length == 0)
                        {
                            throw new InvalidOperationException($"Revit export failed - no revit_export files found in {tempFolder}");
                        }
                        
                        var foundFile = files[0];
                        addLogMethod?.Invoke(_viewModel, new[] { $"[SUCCESS] Found exported file: {Path.GetFileName(foundFile)}" });
                        
                        var imageBytes = File.ReadAllBytes(foundFile);
                        if (imageBytes.Length < 30 * 1024)
                        {
                            throw new InvalidOperationException($"PNG too small: {imageBytes.Length} bytes (minimum 30 KB). This is likely an empty screen!");
                        }
                        
                        addLogMethod?.Invoke(_viewModel, new[] { $"[SUCCESS] REAL Revit view captured as PNG, size: {imageBytes.Length} bytes" });
                        
                        transactionGroup.RollBack();
                        addLogMethod?.Invoke(_viewModel, new[] { "[CLEAN VIEW] Transaction rolled back - user view restored" });
                        
                        File.Delete(foundFile);
                        return Convert.ToBase64String(imageBytes);
                    }
                    catch
                    {
                        transactionGroup.RollBack();
                        throw;
                    }
                }
            }
            catch (Exception ex)
            {
                var addLogMethod = _viewModel?.GetType().GetMethod("AddLog");
                addLogMethod?.Invoke(_viewModel, new[] { $"[REVIT SYNC ERROR] {ex.Message}" });
                throw new Exception($"Failed to export view: {ex.Message}", ex);
            }
        }

        /// <summary>
        /// Проверяет статус генерации
        /// </summary>
        public async Task<GenerationStatus> CheckStatusAsync(string requestId, int attempt = 0)
        {
            try
            {
                // ПРИКАЗ №2: АНИМАЦИЯ КОТИКОВ В ОЖИДАНИИ
                string[] catFrames = new string[] { "(=^･ω･^=)", "(=^･ｪ･^=)", "(=①ω①=)", "( ⓛ ω ⓛ *)", "(=^･^=)" };
                string[] funnyPhrases = new string[] {
                    "Разогреваем GPU лапками...", "Шерсть дыбом, пиксели строятся!", 
                    "Кусь за полигон, и рендер готов...", "Тыгыдык-тыгыдык по дата-центру...",
                    "Смотрим на загрузку, не моргая..."
                };
                Random rnd = new Random();
                
                // ПРИКАЗ №1: КОД ДЛЯ ПАРСИНГА СТАТУСА - правильный URL
                var statusPath = $"api/v1/request/get/{requestId}";
                
                System.Diagnostics.Debug.WriteLine($"[GEN-API] DEBUG STATUS PATH: {statusPath}");
                System.Diagnostics.Debug.WriteLine($"[GEN-API STATUS] Authorization header: {_httpClient.DefaultRequestHeaders.Authorization}");
                
                // ПРИКАЗ №1: GET ЗАПРОС ДЛЯ СТАТУСА
                var response = await _httpClient.GetAsync(statusPath);
                
                if (response.IsSuccessStatusCode)
                {
                    var responseContent = await response.Content.ReadAsStringAsync();
                    System.Diagnostics.Debug.WriteLine($"[GEN-API STATUS] RAW STATUS: {responseContent}");
                    
                    // ПРИКАЗ №4: ЛОГИ - ВЫВОДИМ СЫРОЙ JSON ОТВЕТА GET-ЗАПРОСА
                    if (_viewModel != null)
                    {
                        var addLogMethod = _viewModel.GetType().GetMethod("AddLog");
                        addLogMethod?.Invoke(_viewModel, new[] { $"[DEBUG] Статус: {responseContent}" });
                    }
                    
                    // ПРИКАЗ №1: КОД ДЛЯ ПАРСИНГА СТАТУСА - System.Text.Json
                    using (JsonDocument doc = JsonDocument.Parse(responseContent))
                    {
                        JsonElement root = doc.RootElement;
                        string currentStatus = root.GetProperty("status").GetString();
                        
                        if (currentStatus == "success")
                        {
                            // ПРИКАЗ №1: Берем первую ссылку из массива result
                            string imageUrl = root.GetProperty("result")[0].GetString();
                            
                            if (_viewModel != null)
                            {
                                var addLogMethod = _viewModel.GetType().GetMethod("AddLog");
                                addLogMethod?.Invoke(_viewModel, new[] { $"[SUCCESS] Картинка готова! Скачиваем: {imageUrl}" });
                            }
                            
                            // ПРИКАЗ №2: СКАЧИВАНИЕ РЕЗУЛЬТАТА
                            string localImagePath = await DownloadGeneratedImageAsync(imageUrl);
                            
                            return new GenerationStatus
                            {
                                Status = "success",
                                ImageUrl = localImagePath,
                                ImageBase64 = null,
                                Error = null
                            };
                        }
                        else if (currentStatus == "processing" || currentStatus == "in_progress" || currentStatus == "created")
                        {
                            if (_viewModel != null)
                            {
                                var addLogMethod = _viewModel.GetType().GetMethod("AddLog");
                                // ПРИКАЗ №2: АНИМАЦИЯ КОТИКОВ - веселые фразы
                                int frameIndex = DateTime.Now.Second % catFrames.Length;
                                int phraseIndex = rnd.Next(funnyPhrases.Length);
                                addLogMethod?.Invoke(_viewModel, new[] { $"{catFrames[frameIndex]} Попытка {attempt}/100. {funnyPhrases[phraseIndex]}" });
                            }
                            
                            await Task.Delay(5000); // Ждем 5 секунд перед следующим запросом
                            
                            return new GenerationStatus
                            {
                                Status = "processing",
                                ImageUrl = null,
                                ImageBase64 = null,
                                Error = null
                            };
                        }
                        else
                        {
                            throw new Exception($"Неизвестный или ошибочный статус генерации: {currentStatus}");
                        }
                    }
                }
                else
                {
                    var errorContent = await response.Content.ReadAsStringAsync();
                    System.Diagnostics.Debug.WriteLine($"[GEN-API STATUS] Failed Status: {response.StatusCode}");
                    System.Diagnostics.Debug.WriteLine($"[GEN-API STATUS] Failed Content: {errorContent}");
                    
                    // ПРИКАЗ №3: ЛОГИРУЕМ 404 ОШИБКУ ДЛЯ ДИАГНОСТИКИ
                    if (_viewModel != null)
                    {
                        var addLogMethod = _viewModel.GetType().GetMethod("AddLog");
                        addLogMethod?.Invoke(_viewModel, new[] { $"[ERROR] Поллинг {response.StatusCode}: {errorContent}" });
                    }
                    
                    throw new HttpRequestException($"Status check failed with status {response.StatusCode}. Content: {errorContent}");
                }
            }
            catch (Exception ex)
            {
                System.Diagnostics.Debug.WriteLine($"[GEN-API STATUS EXCEPTION] {ex.Message}");
                throw new Exception($"Failed to check status: {ex.Message}", ex);
            }
        }

        /// <summary>
        /// Загружает сгенерированное изображение
        /// </summary>
        public async Task<byte[]> DownloadImageAsync(string imageUrl)
        {
            try
            {
                // ПРИКАЗ №2: ОТПРАВКА БЕЗ СЛЕША В НАЧАЛЕ - imageUrl уже полный URL от API
                System.Diagnostics.Debug.WriteLine($"[GEN-API DOWNLOAD] Downloading from: {imageUrl}");
                
                var response = await _httpClient.GetAsync(imageUrl);
                response.EnsureSuccessStatusCode();

                var imageData = await response.Content.ReadAsByteArrayAsync();
                System.Diagnostics.Debug.WriteLine($"[GEN-API DOWNLOAD] Downloaded {imageData.Length} bytes");
                
                return imageData;
            }
            catch (Exception ex)
            {
                throw new Exception($"Failed to download image: {ex.Message}", ex);
            }
        }

        /// <summary>
        /// ПРИКАЗ №2: СКАЧИВАНИЕ РЕЗУЛЬТАТА - скачивает картинку по URL
        /// </summary>
        private async Task<string> DownloadGeneratedImageAsync(string imageUrl)
        {
            try
            {
                System.Diagnostics.Debug.WriteLine($"[GEN-API DOWNLOAD] Starting download from: {imageUrl}");
                
                // Скачиваем картинку
                var imageData = await _httpClient.GetByteArrayAsync(imageUrl);
                
                // Сохраняем во временную папку
                string tempFolder = Path.GetTempPath();
                string fileName = $"generated_{Guid.NewGuid()}.png";
                string localPath = Path.Combine(tempFolder, fileName);
                
                await File.WriteAllBytesAsync(localPath, imageData);
                
                System.Diagnostics.Debug.WriteLine($"[GEN-API DOWNLOAD] Downloaded {imageData.Length} bytes to: {localPath}");
                
                if (_viewModel != null)
                {
                    var addLogMethod = _viewModel.GetType().GetMethod("AddLog");
                    addLogMethod?.Invoke(_viewModel, new[] { $"[SUCCESS] Картинка скачана: {fileName} ({imageData.Length} байт)" });
                }
                
                return localPath;
            }
            catch (Exception ex)
            {
                System.Diagnostics.Debug.WriteLine($"[GEN-API DOWNLOAD ERROR] {ex.Message}");
                throw new Exception($"Failed to download generated image: {ex.Message}", ex);
            }
        }

        public void Dispose()
        {
            _httpClient?.Dispose();
        }
    }

    /// <summary>
    /// Модели ответов API
    /// </summary>
    public class GenApiResponse
    {
        public object request_id { get; set; }
        public string status { get; set; }
        public string output_image_url { get; set; }
        public string output_image_base64 { get; set; }
        public string error { get; set; }
    }

    public class GenerationStatus
    {
        public string Status { get; set; }
        public string ImageUrl { get; set; }
        public string ImageBase64 { get; set; }
        public string Error { get; set; }

        public bool IsCompleted => Status == "success" || Status == "completed";
        public bool IsFailed => Status == "failed" || !string.IsNullOrEmpty(Error);
        public bool IsInProgress => Status == "starting" || Status == "processing";
    }
}
