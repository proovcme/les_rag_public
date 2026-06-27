using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media.Imaging;
using Microsoft.Win32;
using System.Net.Http;
using MyVeras.Core;
using MyVeras.Settings;
using MyVeras.UI.ViewModels;

namespace MyVeras.UI.Windows
{
    public partial class MainWindow : Window
    {
        private AppSettings _settings;
        private readonly object _document;
        private readonly List<string> _viewNames;
        private GenApiClient _apiClient;
        private readonly MainViewModel _viewModel;
        private byte[] _generatedImageData;
        private CancellationTokenSource _cancellationTokenSource;
        
        // ПРИКАЗ №2: ПОДГОТОВКА ПЕРЕМЕННОЙ - путь к захваченному изображению
        private string _currentCapturedImagePath;

        public MainWindow(object document, List<string> viewNames)
        {
            InitializeComponent();
            
            // ПРИКАЗ №1: ФИКС NULL DOCUMENT - инициализируем сразу
            _document = document ?? throw new ArgumentNullException(nameof(document));
            
            // ПРИКАЗ №2: КЛЮЧ (Anti-Amnesia) - Load() ПЕРВОЙ СТРОКОЙ!
            _settings = SettingsManager.Instance.Load();
            
            // Инициализируем ViewModel
            _viewModel = new MainViewModel(null, document, viewNames);
            DataContext = _viewModel;
            _viewModel.Initialize();
            
            // Проверяем загрузку настроек
            if (_settings == null)
            {
                throw new InvalidOperationException("Failed to load settings");
            }
            
            // Логируем состояние API ключа
            if (!string.IsNullOrEmpty(_settings.ApiKey))
            {
                _viewModel.AddLog($"API key loaded successfully (length: {_settings.ApiKey.Length})");
                _apiClient = new GenApiClient(_settings.ApiKey, _viewModel);
            }
            else
            {
                _viewModel.AddLog("API key is empty");
            }
                
            // Заполняем ComboBox
            if (ViewComboBox != null)
            {
                ViewComboBox.ItemsSource = viewNames;
                if (viewNames.Count > 0 && !viewNames[0].Contains("Нет доступных"))
                {
                    ViewComboBox.SelectedIndex = 0;
                }
            }
                
            // Подписываемся на события ViewModel
            _viewModel.PropertyChanged += ViewModel_PropertyChanged;
            
            // Закрываем при закрытии окна
            Closing += MainWindow_Closing;
        }

        // ПРИКАЗ №3: ЛОГИКА ЗАХВАТА - CaptureButton_Click
        private void CaptureButton_Click(object sender, RoutedEventArgs e)
        {
            try
            {
                _viewModel.AddLog("=== CAPTURE STARTED ===");
                
                // Блокируем кнопку захвата
                CaptureButton.IsEnabled = false;
                CaptureButton.Content = "Capturing...";
                
                // ПРИКАЗ №1: ШАГ 1 - СИНХРОННО вытаскиваем картинку из Ревита
                _currentCapturedImagePath = CaptureRevitViewSync();
                
                // ПРИКАЗ №2: ШАГ 2 - Читаем картинку и морозим её
                BitmapImage bitmap = CreateFrozenBitmap(_currentCapturedImagePath);
                
                // Показываем картинку и скрываем плейсхолдер
                SourcePreviewImage.Source = bitmap;
                SourcePreviewImage.Visibility = Visibility.Visible;
                SourcePlaceholderTextBlock.Visibility = Visibility.Collapsed;
                
                _viewModel.AddLog("Source image captured and displayed successfully");
                
                // Разблокируем кнопку захвата
                CaptureButton.IsEnabled = true;
                CaptureButton.Content = "📸 CAPTURE";
                
                // Активируем кнопку генерации
                GenerateButton.IsEnabled = true;
                GenerateButton.Background = System.Windows.Media.Brushes.LightGreen;
            }
            catch (Exception ex)
            {
                _viewModel.AddLog($"[CAPTURE ERROR] {ex.Message}");
                
                // Разблокируем кнопку при ошибке
                CaptureButton.IsEnabled = true;
                CaptureButton.Content = "📸 CAPTURE";
                
                MessageBox.Show($"Ошибка захвата изображения: {ex.Message}", "Ошибка", MessageBoxButton.OK, MessageBoxImage.Error);
            }
        }

        private async void GenerateButton_Click(object sender, RoutedEventArgs e)
        {
            try 
            {
                // ПРИКАЗ №4: ФИКС СТАТУСА - проверяем захваченное изображение
                if (string.IsNullOrEmpty(_currentCapturedImagePath))
                {
                    _viewModel.AddLog("Сначала захватите вид!");
                    MessageBox.Show("Сначала захватите вид кнопкой '📸 CAPTURE'", "Внимание", MessageBoxButton.OK, MessageBoxImage.Warning);
                    return;
                }
                
                // ПРИКАЗ №2: ЧТЕНИЕ UI ПЕРЕД ОТПРАВКОЙ - считываем все значения в UI потоке
                string promptText = PromptTextBox.Text;
                string negativePromptText = NegativePromptTextBox.Text;
                double controlNetStrength = _viewModel.ControlNetStrength;
                
                // Сохраняем промпты
                _viewModel.UserPrompt = promptText;
                _viewModel.NegativePrompt = negativePromptText;
                _viewModel.SavePrompts();
                
                // Блокируем кнопку
                GenerateButton.IsEnabled = false;
                GenerateButton.Content = "Generating...";
                StopButton.IsEnabled = true;
                _cancellationTokenSource = new CancellationTokenSource();
                
                _viewModel.AddLog("=== GENERATION STARTED ===");
                
                // ПРИКАЗ №2: ШАГ 3 - ОТДАЕМ ПОТОК ИНТЕРФЕЙСУ НА ОТРИСОВКУ
                await Task.Delay(100); 
                
                // ПРИКАЗ №2: ШАГ 4 - АСИНХРОННАЯ ОТПРАВКА
                await Task.Run(async () => 
                {
                    try
                    {
                        // Читаем файл и конвертируем в Base64
                        var imageBytes = File.ReadAllBytes(_currentCapturedImagePath);
                        var base64Image = Convert.ToBase64String(imageBytes);
                        
                        // ПРИКАЗ №3: ФИКС ОТОБРАЖЕНИЯ КАРТИНКИ В UI - StartGenerationAsync теперь возвращает локальный путь
                        string resultPath = await _apiClient.StartGenerationAsync(
                            promptText,
                            negativePromptText,
                            base64Image,
                            _viewModel.ReferenceImagePath,
                            _viewModel.ReferenceInfluence,
                            controlNetStrength
                        );
                        
                        // ПРИКАЗ №3: Выводим картинку в правое окно
                        if (!string.IsNullOrEmpty(resultPath) && File.Exists(resultPath))
                        {
                            Application.Current.Dispatcher.Invoke(() => {
                                BitmapImage resultBitmap = new BitmapImage();
                                resultBitmap.BeginInit();
                                resultBitmap.CacheOption = BitmapCacheOption.OnLoad;
                                resultBitmap.UriSource = new Uri(resultPath, UriKind.Absolute);
                                resultBitmap.EndInit();
                                resultBitmap.Freeze();
                                
                                GeneratedImage.Source = resultBitmap; // Вывод в правое окно
                                GeneratedImage.Visibility = Visibility.Visible;
                                PlaceholderTextBlock.Visibility = Visibility.Collapsed;
                                GeneratedImage.UpdateLayout();
                                
                                _viewModel.AddLog("[SUCCESS] Рендер выведен на экран!");
                                
                                // Активируем кнопку экспорта
                                ExportButton.IsEnabled = true;
                            });
                        }
                        
                        _viewModel.AddLog("=== GENERATION COMPLETED SUCCESSFULLY ===");
                    }
                    catch (OperationCanceledException)
                    {
                        _viewModel.AddLog("=== GENERATION CANCELLED BY USER ===");
                    }
                    catch (HttpRequestException ex)
                    {
                        _viewModel.AddLog($"HTTP ERROR: {ex.Message}");
                        _viewModel.AddLog("=== GENERATION FAILED ===");
                        
                        if (ex.Message.Contains("402") || ex.Message.Contains("Payment Required"))
                        {
                            _viewModel.AddLog("[STOP] Баланс пуст. GPT-4.1 требует пополнения на gen-api.ru.");
                            GenerateButton.IsEnabled = false;
                            GenerateButton.Background = System.Windows.Media.Brushes.Orange;
                            
                            var timer = new System.Windows.Threading.DispatcherTimer();
                            timer.Interval = TimeSpan.FromSeconds(60);
                            timer.Tick += (s, args) =>
                            {
                                GenerateButton.IsEnabled = true;
                                GenerateButton.Background = System.Windows.Media.Brushes.LightGreen;
                                timer.Stop();
                                _viewModel.AddLog("[INFO] Кнопка Generate разблокирована. Попробуй снова.");
                            };
                            timer.Start();
                            
                            MessageBox.Show("Баланс пуст! GPT-4.1 требует пополнения на gen-api.ru.", "БАЛАНС ПУСТ", MessageBoxButton.OK, MessageBoxImage.Warning);
                        }
                        else
                        {
                            MessageBox.Show($"Ошибка HTTP запроса: {ex.Message}", "Ошибка", MessageBoxButton.OK, MessageBoxImage.Error);
                        }
                    }
                    catch (Exception ex)
                    {
                        _viewModel.AddLog($"ERROR: {ex.Message}");
                        _viewModel.AddLog("=== GENERATION FAILED ===");
                        MessageBox.Show($"Ошибка генерации: {ex.Message}", "Ошибка", MessageBoxButton.OK, MessageBoxImage.Error);
                    }
                    finally
                    {
                        Dispatcher.Invoke(() =>
                        {
                            GenerateButton.IsEnabled = true;
                            GenerateButton.Content = "Generate";
                            StopButton.IsEnabled = false;
                        });
                    }
                }, _cancellationTokenSource.Token);
            }
            catch (Exception ex)
            {
                _viewModel.AddLog($"GenerateButton_Click ERROR: {ex.Message}");
                MessageBox.Show($"Ошибка: {ex.Message}", "Ошибка", MessageBoxButton.OK, MessageBoxImage.Error);
            }
        }

        private async void StopButton_Click(object sender, RoutedEventArgs e)
        {
            try
            {
                if (_cancellationTokenSource != null)
                {
                    _viewModel.AddLog("Stopping generation...");
                    _cancellationTokenSource.Cancel();
                    StopButton.IsEnabled = false;
                }
            }
            catch (Exception ex)
            {
                _viewModel.AddLog($"StopButton_Click ERROR: {ex.Message}");
                MessageBox.Show($"Ошибка: {ex.Message}", "Ошибка", MessageBoxButton.OK, MessageBoxImage.Error);
            }
        }

        // ПРИКАЗ №1: СТРОГОЕ РАЗДЕЛЕНИЕ - СИНХРОННЫЙ ЗАХВАТ REVIT
        private string CaptureRevitViewSync()
        {
            try
            {
                _viewModel.AddLog("[REVIT] Starting synchronous capture...");
                
                // ВЫЗЫВАЕМ ЭКСПОРТ ЧЕРЕЗ API CLIENT - ОН УЖЕ СОДЕРЖИТ ВЕСЬ REVIT API КОД
                string base64Image = _apiClient.ExportViewToBase64Sync(_document, "Unknown View");
                
                if (string.IsNullOrEmpty(base64Image))
                {
                    throw new InvalidOperationException("Revit export returned empty result");
                }
                
                // КОНВЕРТИРУЕМ BASE64 ОБРАТНО В ФАЙЛ
                var imageBytes = Convert.FromBase64String(base64Image);
                if (imageBytes.Length < 30 * 1024) // меньше 30 КБ
                {
                    throw new InvalidOperationException($"PNG too small: {imageBytes.Length} bytes (minimum 30 KB). This is likely an empty screen!");
                }
                
                // СОХРАНЯЕМ ВО ВРЕМЕННЫЙ ФАЙЛ
                string tempFolder = Path.GetTempPath();
                string tempFile = Path.Combine(tempFolder, "revit_export.png");
                File.WriteAllBytes(tempFile, imageBytes);
                
                _viewModel.AddLog($"[SUCCESS] REAL Revit view captured as PNG, size: {imageBytes.Length} bytes");
                
                return tempFile;
            }
            catch (Exception ex)
            {
                _viewModel.AddLog($"[CAPTURE ERROR] Failed to capture view: {ex.Message}");
                throw new Exception($"Failed to capture view: {ex.Message}", ex);
            }
        }

        // ПРИКАЗ №2: СОЗДАНИЕ ЗАМОРОЖЕННОГО BITMAP
        private BitmapImage CreateFrozenBitmap(string imagePath)
        {
            var imageBytes = File.ReadAllBytes(imagePath);
            _viewModel.AddLog($"[DEBUG] Image size: {imageBytes.Length} bytes");
            
            var bitmap = new BitmapImage();
            bitmap.BeginInit();
            bitmap.CacheOption = BitmapCacheOption.OnLoad;
            bitmap.StreamSource = new MemoryStream(imageBytes);
            bitmap.EndInit();
            bitmap.Freeze(); // КРИТИЧЕСКИ ВАЖНО ДЛЯ ПОТОКОВ!
            
            return bitmap;
        }

        private async Task WaitForGenerationResult(string requestId, CancellationToken cancellationToken)
        {
            var maxAttempts = 30;
            var attempt = 0;
            
            while (attempt < maxAttempts && !cancellationToken.IsCancellationRequested)
            {
                attempt++;
                // ПРИКАЗ №1: ВЕРНИ КОТИКОВ В ЗАГРУЗКУ - веселый лог
                _viewModel.AddLog($"[😸 Котики рендерят...] Попытка {attempt}/{maxAttempts}. Ждем шедевр...");
                
                try
                {
                    var status = await _apiClient.CheckStatusAsync(requestId);
                    _viewModel.AddLog($"Status response: {status.Status}");
                    
                    if (status.Status == "success")
                    {
                        if (!string.IsNullOrEmpty(status.ImageUrl))
                        {
                            _viewModel.AddLog("ERROR: Success status but no image URL");
                            break;
                        }
                        
                        var imageData = await _apiClient.DownloadImageAsync(status.ImageUrl);
                        _generatedImageData = imageData;
                        _viewModel.AddLog($"[DEBUG] Downloaded image size: {imageData.Length} bytes");
                        
                        // ПРИКАЗ №2: ОКОНЧАТЕЛЬНЫЙ ФИКС ПОТОКОВ - .Freeze() ПЕРЕД Dispatcher
                        var bitmap = new BitmapImage();
                        bitmap.BeginInit();
                        bitmap.CacheOption = BitmapCacheOption.OnLoad;
                        bitmap.StreamSource = new MemoryStream(imageData);
                        bitmap.EndInit();
                        bitmap.Freeze(); // ОБОЯЗАТЕЛЬНО!
                        
                        // ПРИКАЗ №2: ФИКС ПОТОКОВ - используем Dispatcher.Invoke
                        Application.Current.Dispatcher.Invoke(() =>
                        {
                            GeneratedImage.Source = bitmap; // Уже заморожен!
                        });
                        
                        _viewModel.AddLog("Result image loaded successfully");
                        _viewModel.AddLog("🐱 Котик доволен результатом! Мяу!");
                        break;
                    }
                    else if (status.Status == "failed")
                    {
                        _viewModel.AddLog($"ERROR: Generation failed: {status.Error}");
                        break;
                    }
                }
                catch (Exception ex)
                {
                    _viewModel.AddLog($"CheckStatus error: {ex.Message}");
                }
                
                await Task.Delay(10000, cancellationToken);
            }
            
            if (attempt >= maxAttempts)
            {
                _viewModel.AddLog("Timeout: Generation took too long");
            }
        }

        private void SaveButton_Click(object sender, RoutedEventArgs e)
        {
            try
            {
                if (_generatedImageData != null)
                {
                    var saveFileDialog = new SaveFileDialog
                    {
                        Filter = "PNG Files (*.png)|*.png|All files (*.*)|*.*",
                        DefaultExt = "png",
                        FileName = "generated_image.png"
                    };
                    
                    if (saveFileDialog.ShowDialog() == true)
                    {
                        File.WriteAllBytes(saveFileDialog.FileName, _generatedImageData);
                        _viewModel.AddLog($"Image saved to: {saveFileDialog.FileName}");
                        MessageBox.Show("Изображение успешно сохранено!", "Успех", MessageBoxButton.OK, MessageBoxImage.Information);
                    }
                }
                else
                {
                    _viewModel.AddLog("No generated image to save");
                    MessageBox.Show("Нет сгенерированного изображения для сохранения", "Ошибка", MessageBoxButton.OK, MessageBoxImage.Warning);
                }
            }
            catch (Exception ex)
            {
                _viewModel.AddLog($"SaveButton_Click ERROR: {ex.Message}");
                MessageBox.Show($"Ошибка сохранения: {ex.Message}", "Ошибка", MessageBoxButton.OK, MessageBoxImage.Error);
            }
        }

        private void SettingsButton_Click(object sender, RoutedEventArgs e)
        {
            try
            {
                _viewModel.AddLog("Opening settings window...");
                
                var settingsWindow = new SettingsWindow();
                settingsWindow.Owner = this;
                
                if (settingsWindow.ShowDialog() == true)
                {
                    _viewModel.AddLog("Settings saved, refreshing...");
                    RefreshSettings();
                }
                else
                {
                    _viewModel.AddLog("Settings cancelled");
                }
            }
            catch (Exception ex)
            {
                _viewModel.AddLog($"SettingsButton_Click ERROR: {ex.Message}");
                MessageBox.Show($"Ошибка открытия настроек: {ex.Message}", "Ошибка", MessageBoxButton.OK, MessageBoxImage.Error);
            }
        }

        private void ControlNetStrengthSlider_ValueChanged(object sender, RoutedPropertyChangedEventArgs<double> e)
        {
            if (_viewModel != null)
            {
                _viewModel.ControlNetStrength = e.NewValue;
                ControlNetStrengthText.Text = e.NewValue.ToString("F1");
            }
        }

        private void ReferenceInfluenceSlider_ValueChanged(object sender, RoutedPropertyChangedEventArgs<double> e)
        {
            if (_viewModel != null)
            {
                _viewModel.ReferenceInfluence = e.NewValue;
            }
        }

        private void ExportButton_Click(object sender, RoutedEventArgs e)
        {
            try
            {
                if (_generatedImageData != null)
                {
                    var saveFileDialog = new SaveFileDialog
                    {
                        Filter = "PNG Files (*.png)|*.png|All files (*.*)|*.*",
                        DefaultExt = "png",
                        FileName = "exported_image.png"
                    };
                    
                    if (saveFileDialog.ShowDialog() == true)
                    {
                        File.WriteAllBytes(saveFileDialog.FileName, _generatedImageData);
                        _viewModel.AddLog($"Image exported to: {saveFileDialog.FileName}");
                        MessageBox.Show("Изображение успешно экспортировано!", "Успех", MessageBoxButton.OK, MessageBoxImage.Information);
                    }
                }
                else
                {
                    _viewModel.AddLog("No generated image to export");
                    MessageBox.Show("Нет сгенерированного изображения для экспорта", "Ошибка", MessageBoxButton.OK, MessageBoxImage.Warning);
                }
            }
            catch (Exception ex)
            {
                _viewModel.AddLog($"ExportButton_Click ERROR: {ex.Message}");
                MessageBox.Show($"Ошибка экспорта: {ex.Message}", "Ошибка", MessageBoxButton.OK, MessageBoxImage.Error);
            }
        }

        private void LoadReferenceButton_Click(object sender, RoutedEventArgs e)
        {
            try
            {
                var openFileDialog = new OpenFileDialog
                {
                    Filter = "Image Files (*.jpg;*.jpeg;*.png;*.bmp)|*.jpg;*.jpeg;*.png;*.bmp|All files (*.*)|*.*",
                    Title = "Выберите референсное изображение"
                };
                
                if (openFileDialog.ShowDialog() == true)
                {
                    _viewModel.ReferenceImagePath = openFileDialog.FileName;
                    _viewModel.IsReferenceLoaded = true;
                    
                    // ПРИКАЗ №2: ОКОНЧАТЕЛЬНЫЙ ФИКС ПОТОКОВ - .Freeze() ПЕРЕД Dispatcher
                    var bitmap = new BitmapImage();
                    bitmap.BeginInit();
                    bitmap.CacheOption = BitmapCacheOption.OnLoad;
                    bitmap.UriSource = new Uri(openFileDialog.FileName);
                    bitmap.EndInit();
                    bitmap.Freeze(); // ОБОЯЗАТЕЛЬНО!
                    
                    // ПРИКАЗ №2: ФИКС ПОТОКОВ - используем Dispatcher.Invoke
                    Application.Current.Dispatcher.Invoke(() =>
                    {
                        ReferencePreviewImage.Source = bitmap; // Уже заморожен!
                    });
                    
                    _viewModel.AddLog($"Reference image loaded: {openFileDialog.FileName}");
                    MessageBox.Show("Референсное изображение загружено!", "Успех", MessageBoxButton.OK, MessageBoxImage.Information);
                }
            }
            catch (Exception ex)
            {
                _viewModel.AddLog($"LoadReferenceButton_Click ERROR: {ex.Message}");
                MessageBox.Show($"Ошибка загрузки референса: {ex.Message}", "Ошибка", MessageBoxButton.OK, MessageBoxImage.Error);
            }
        }

        private void ClearReferenceButton_Click(object sender, RoutedEventArgs e)
        {
            try
            {
                _viewModel.ReferenceImagePath = string.Empty;
                _viewModel.IsReferenceLoaded = false;
                
                // ПРИКАЗ №2: ФИКС ПОТОКОВ - используем Dispatcher.Invoke
                Application.Current.Dispatcher.Invoke(() =>
                {
                    ReferencePreviewImage.Source = null;
                });
                
                _viewModel.AddLog("Reference image cleared");
                MessageBox.Show("Референсное изображение очищено!", "Успех", MessageBoxButton.OK, MessageBoxImage.Information);
            }
            catch (Exception ex)
            {
                _viewModel.AddLog($"ClearReferenceButton_Click ERROR: {ex.Message}");
                MessageBox.Show($"Ошибка очистки референса: {ex.Message}", "Ошибка", MessageBoxButton.OK, MessageBoxImage.Error);
            }
        }

        private void ViewModel_PropertyChanged(object sender, System.ComponentModel.PropertyChangedEventArgs e)
        {
            if (e.PropertyName == nameof(MainViewModel.IsReferenceLoaded))
            {
                UpdateReferenceUI();
            }
        }

        private void UpdateReferenceUI()
        {
            if (_viewModel != null)
            {
                ReferenceInfluenceSlider.IsEnabled = _viewModel.IsReferenceLoaded;
                ClearReferenceButton.IsEnabled = _viewModel.IsReferenceLoaded;
            }
        }

        public void RefreshSettings()
        {
            try
            {
                if (_viewModel != null)
                {
                    _settings = SettingsManager.Instance.Load();
                    _viewModel.SelectedViewName = _settings.SelectedViewName ?? string.Empty;
                    _viewModel.UserPrompt = _settings.UserPrompt ?? string.Empty;
                    _viewModel.NegativePrompt = _settings.NegativePrompt ?? string.Empty;
                    _viewModel.ReferenceInfluence = 0.75;
                    
                    if (!string.IsNullOrEmpty(_settings.ApiKey))
                    {
                        _apiClient = new GenApiClient(_settings.ApiKey, _viewModel);
                        _viewModel.AddLog("API client updated with new key");
                    }
                    
                    _viewModel.AddLog("Settings refreshed successfully");
                }
            }
            catch (Exception ex)
            {
                _viewModel.AddLog($"RefreshSettings ERROR: {ex.Message}");
                MessageBox.Show($"Ошибка обновления настроек: {ex.Message}", "Ошибка", MessageBoxButton.OK, MessageBoxImage.Error);
            }
        }

        private void MainWindow_Closing(object sender, System.ComponentModel.CancelEventArgs e)
        {
            try
            {
                _cancellationTokenSource?.Cancel();
                _cancellationTokenSource?.Dispose();
                _apiClient?.Dispose();
                _viewModel.AddLog("MainWindow closing - resources cleaned up");
            }
            catch (Exception ex)
            {
                _viewModel.AddLog($"MainWindow_Closing ERROR: {ex.Message}");
            }
        }
    }
}
